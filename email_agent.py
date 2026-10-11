"""
email_agent.py
--------------
Claude-powered Gmail cleanup agent.

Claude receives four tools:
  1. search_messages       -- search Gmail by query, returns message metadata
  2. get_message_details   -- fetch headers/body for borderline cases
  3. propose_trash         -- accumulate IDs to trash (in-memory; no Gmail call)
  4. finish                -- end the loop with a summary

The agent ONLY proposes deletions. The CLI wrapper (clean_email.py) shows
the proposal to the user, prompts for confirmation, and only then moves
messages to Trash via Gmail's batchModify API. Trash is reversible for 30
days, so this is the safe default.

Model: claude-haiku-5-5 at low effort -- the cheapest option.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import anthropic
import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config
import rules

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

CATEGORIES: dict[str, str] = {
    "spam": "in:spam",
    "promotional": "category:promotions older_than:7d",
    "social": "category:social older_than:7d",
    "old_read": "is:read older_than:6m -is:starred -is:important -in:sent -in:chats",
}


# -- Gmail service -------------------------------------------------------------
def token_path_for(account: str | None) -> Path:
    """Resolve the token file for an optional account name."""
    if account:
        return Path(f"gmail_token_{account}.json")
    return Path(config.GMAIL_TOKEN_PATH)


def get_gmail_service(account: str | None = None):
    """Load the saved OAuth token and build a Gmail service client."""
    token_path = token_path_for(account)
    hint = f"python setup_gmail.py --account {account}" if account else "python setup_gmail.py"
    if not token_path.exists():
        raise RuntimeError(
            f"Gmail token not found at {token_path}. Run `{hint}` first."
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Tokens from an OAuth app in "Testing" status expire after 7 days
            raise RuntimeError(
                f"Gmail token at {token_path} has expired or been revoked. "
                f"Run `{hint}` to sign in again."
            ) from exc
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# -- Gmail helpers -------------------------------------------------------------
def _list_message_ids(service, query: str, max_results: int) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_results:
        page_size = min(100, max_results - len(ids))
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=page_size,
            pageToken=page_token,
        ).execute()
        for m in resp.get("messages", []):
            ids.append(m["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def _get_metadata(service, message_id: str) -> dict[str, Any]:
    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": message_id,
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", "")[:200],
        "labels": msg.get("labelIds", []),
    }


def _get_full(service, message_id: str) -> dict[str, Any]:
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract a plain-text body chunk if available
    body_text = ""
    payload = msg.get("payload", {})
    parts = payload.get("parts") or [payload]
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                break
    if not body_text:
        body_text = msg.get("snippet", "")

    return {
        "id": message_id,
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "date": headers.get("Date", ""),
        "body": body_text[:1500],
        "labels": msg.get("labelIds", []),
    }


# -- Trash execution (called by clean_email.py after confirmation) ------------
def batch_trash(service, message_ids: list[str]) -> int:
    """Move a list of message IDs to Trash. Returns count moved."""
    if not message_ids:
        return 0
    moved = 0
    for i in range(0, len(message_ids), 1000):
        batch = message_ids[i : i + 1000]
        service.users().messages().batchModify(
            userId="me",
            body={"ids": batch, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
        ).execute()
        moved += len(batch)
    return moved


# -- Anthropic tool definitions -----------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_messages",
        "description": (
            "Search the user's Gmail using Gmail's standard query syntax "
            "(e.g. 'in:spam', 'category:promotions older_than:30d', 'from:foo@bar.com'). "
            "Returns up to max_results messages with id, from, subject, date, snippet, and labels."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Max messages to return. Cap is 200.",
                },
            },
            "required": ["query", "max_results"],
        },
    },
    {
        "name": "get_message_details",
        "description": (
            "Fetch full headers and body text for a single message. "
            "Use this when search_messages snippets aren't enough to decide whether to trash."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID."},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "propose_trash",
        "description": (
            "Mark a list of messages for the user to review and trash. "
            "Call this once per category with all IDs that fit. Do NOT call it for "
            "messages you are unsure about. Include a short reason explaining the "
            "category (e.g. 'promotional newsletter from retailer X')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "The category being surveyed (as named in the system prompt). "
                        "Validated at runtime against the categories actually requested."
                    ),
                },
                "message_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Gmail message IDs to propose for trashing.",
                },
                "reason": {
                    "type": "string",
                    "description": "One-line justification for this batch.",
                },
            },
            "required": ["category", "message_ids", "reason"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Call this once you have surveyed every requested category and proposed "
            "all messages you're confident should be trashed. Provide a short summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
]


# -- System prompt -------------------------------------------------------------
def _build_system_prompt(categories: list[str], max_per_category: int) -> str:
    lines = [
        "You are a Gmail cleanup assistant. Your job is to identify emails the user "
        "no longer needs and propose them for trashing. You do NOT delete anything "
        "directly -- a human reviews your proposals before any messages move.",
        "",
        "Today the user wants to survey these categories:",
    ]
    for cat in categories:
        lines.append(f"  - {cat}: starting query `{CATEGORIES[cat]}`")
    lines.extend([
        "",
        f"Cap each search at {max_per_category} messages.",
        "",
        "Rules:",
        "  1. For 'spam': trust Gmail's spam folder. Propose ALL of them.",
        "  2. For 'promotional' and 'social': skim subjects/senders. Propose only",
        "     items that look like routine marketing or notification noise.",
        "     Skip anything that looks like a receipt, order confirmation, or",
        "     account-security notice.",
        "  3. For 'old_read': be conservative. Propose only items that are clearly",
        "     transient (newsletters, automated digests, expired offers). When in",
        "     doubt, skip the message.",
        "  4. Never propose: starred, important, sent mail, chats, drafts, or",
        "     anything from a real person you correspond with.",
        "  5. Use get_message_details only for borderline cases -- don't fetch",
        "     details for items you've already decided about from the search snippet.",
        "",
        "Workflow:",
        "  1. For each requested category, call search_messages with that category's",
        "     starting query.",
        "  2. Group the results into propose_trash calls (one or more per category).",
        "  3. When all categories are surveyed, call finish with a brief summary.",
    ])
    keep = rules.keep_rules()
    if keep:
        lines.extend([
            "",
            "The user has told you these are IMPORTANT. Never propose a message that",
            "matches any of these Gmail query fragments (treat them as hard rules):",
        ])
        lines.extend(f"  - {k}" for k in keep)
    return "\n".join(lines)


# -- Agent loop ----------------------------------------------------------------
MAX_ITERATIONS = 25  # high enough to sweep all four categories with room for borderline lookups

# Cheapest model. Haiku 5.5 bills $0.10/$0.50 per MTok while a prompt stays at
# or under 100K tokens ($0.50/$2.50 above), so keep per-category caps <= 200.
MODEL = "claude-haiku-5-5"
EFFORT = "low"  # raise to "medium" if proposals get sloppy


def run(
    categories: list[str],
    max_per_category: int,
    account: str | None = None,
) -> dict[str, list[str]]:
    """
    Run the cleanup agent. Returns proposals as {category: [message_id, ...]}.
    Does NOT trash anything -- the caller is responsible for confirmation + trashing.
    """
    if not categories:
        raise ValueError("categories must be non-empty")
    for cat in categories:
        if cat not in CATEGORIES:
            raise ValueError(f"Unknown category: {cat}. Choose from {list(CATEGORIES)}")

    service = get_gmail_service(account)
    proposals: dict[str, list[str]] = {cat: [] for cat in categories}
    reasons: dict[str, list[str]] = {cat: [] for cat in categories}

    client = anthropic.Anthropic(api_key=config.get_anthropic_key())
    system_prompt = _build_system_prompt(categories, max_per_category)

    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            f"Please survey these categories and propose what to trash: "
            f"{', '.join(categories)}. Cap searches at {max_per_category} messages each."
        ),
    }]

    finished = False
    tokens = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for iteration in range(MAX_ITERATIONS):
        # Streaming is required by the SDK whenever max_tokens is large enough
        # that the request could exceed the 10-min non-streaming timeout. The
        # final Message returned by stream.get_final_message() has the same
        # shape as client.messages.create()'s response.
        #
        # Retry up to 3 times on transient network errors (connection reset,
        # timeout, remote-protocol errors). These show up mid-stream during
        # long adaptive-thinking steps and aren't recoverable mid-response.
        response = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                with client.messages.stream(
                    model=MODEL,
                    max_tokens=32000,
                    thinking={"type": "adaptive"},
                    output_config={"effort": EFFORT},
                    # Every iteration resends the whole conversation (including
                    # ~200 messages of search results); caching bills the
                    # repeated prefix at 0.1x
                    cache_control={"type": "ephemeral"},
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                ) as stream:
                    for _ in stream:
                        pass
                    response = stream.get_final_message()
                break
            except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError,
                    httpx.TimeoutException, anthropic.APIConnectionError,
                    anthropic.APITimeoutError) as exc:
                last_err = exc
                wait = 2 ** attempt
                print(f"  Network error ({type(exc).__name__}: {exc}); retrying in {wait}s "
                      f"(attempt {attempt + 1}/3)...", flush=True)
                time.sleep(wait)
        if response is None:
            raise RuntimeError(f"Anthropic API failed after 3 attempts: {last_err}")

        usage = response.usage
        tokens["input"] += usage.input_tokens
        tokens["cache_write"] += usage.cache_creation_input_tokens or 0
        tokens["cache_read"] += usage.cache_read_input_tokens or 0
        tokens["output"] += usage.output_tokens

        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"  Agent: {block.text.strip()}")

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            print(f"  Unexpected stop_reason: {response.stop_reason}")
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            name, tool_input = block.name, block.input
            result = _execute_tool(service, proposals, reasons, name, tool_input)
            print(f"  -> {name}({_short(tool_input)}) -> {result[:120]}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
            if name == "finish":
                finished = True

        messages.append({"role": "user", "content": tool_results})

        if finished:
            break

    if not finished:
        print(f"  (agent stopped after {iteration + 1} iterations without calling finish)")
    print(f"  Tokens ({MODEL}): {tokens['input']} input, {tokens['cache_write']} cache write, "
          f"{tokens['cache_read']} cache read, {tokens['output']} output")

    # Attach reasons to result via a side dict on the function (caller can read)
    run.last_reasons = reasons  # type: ignore[attr-defined]
    return proposals


def _short(d: dict[str, Any]) -> str:
    s = json.dumps(d, default=str)
    return s if len(s) < 80 else s[:77] + "..."


def _execute_tool(
    service,
    proposals: dict[str, list[str]],
    reasons: dict[str, list[str]],
    name: str,
    tool_input: dict[str, Any],
) -> str:
    if name == "search_messages":
        query = tool_input.get("query", "")
        cap = min(int(tool_input.get("max_results", 50)), 200)
        ids = _list_message_ids(service, query, cap)
        out = [_get_metadata(service, mid) for mid in ids]
        return json.dumps(out)

    if name == "get_message_details":
        mid = tool_input.get("message_id", "")
        return json.dumps(_get_full(service, mid))

    if name == "propose_trash":
        cat = tool_input.get("category", "")
        ids = tool_input.get("message_ids", []) or []
        reason = tool_input.get("reason", "")
        if cat not in proposals:
            return json.dumps({"error": f"unknown category: {cat}"})
        existing = set(proposals[cat])
        added = [i for i in ids if i not in existing]
        proposals[cat].extend(added)
        if reason:
            reasons[cat].append(f"({len(added)}) {reason}")
        return json.dumps({"category": cat, "added": len(added), "total_proposed_in_category": len(proposals[cat])})

    if name == "finish":
        return json.dumps({"status": "done", "summary": tool_input.get("summary", "")})

    return json.dumps({"error": f"Unknown tool: {name}"})
