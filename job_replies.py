"""
job_replies.py
--------------
Finds recent recruiter / job-opportunity emails from real people and saves a
tailored reply as a Gmail DRAFT in the same thread. Nothing is sent: you
review each draft in Gmail and press Send yourself.

Usage:
  python job_replies.py --account personal              # create drafts
  python job_replies.py --account personal --dry-run    # print drafts only
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import subprocess
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import anthropic

import config
import email_agent

LOG = Path(__file__).parent / "logs" / "job-replies.jsonl"
MODEL = "claude-sonnet-5-5"  # reply quality matters more than the few cents it costs

SEARCH = (
    '(subject:(job OR jobs OR role OR opportunity OR opening OR hiring OR recruiter '
    'OR position OR interview OR candidate OR "reaching out") OR "open to" '
    'OR "job opportunity") newer_than:3d -category:promotions -in:sent'
)

# Senders that are automated, not a person (never reply to these)
AUTOMATED = re.compile(
    r"no-?reply|donotreply|do-not-reply|notifications?@|support@|jobs-noreply|alerts?@|newsletter|theoutput|digest|marketing", re.I
)

STANDARD_REPLY = (
    "I'm not looking at the moment, but I expect to start looking again in Q1 or Q2 of 2027, "
    "so let's reconnect then. Happy to stay connected in the meantime."
)

LINKEDIN_URL = "https://www.linkedin.com/in/sutariaarjun"
LINKEDIN_TEXT = "www.linkedin.com/in/sutariaarjun"


def _email_parts(body: str) -> tuple[str, str]:
    """Plain-text and HTML versions. The LinkedIn link is a real anchor, so Gmail
    never rewrites it into a google.com/url redirect."""
    text = f"{body}\n\nLinkedIn: {LINKEDIN_TEXT}"
    html_body = html.escape(body).replace("\n", "<br>")
    html_part = (
        f'<div dir="auto">{html_body}<br><br>LinkedIn: '
        f'<a href="{LINKEDIN_URL}">{LINKEDIN_TEXT}</a></div>'
    )
    return text, html_part

SYSTEM = f"""You write email replies for Arjun Sutaria (Solutions Engineer) to recruiters and job-opportunity emails.

Arjun's position: he is NOT looking right now. He expects to look again in Q1 or Q2 of 2027 and would like to reconnect then.
Always convey this clearly and politely, in one short paragraph, in your own words (don't reuse the same sentence across replies).
Close with a brief line saying he's happy to stay connected, then his LinkedIn on its own line, exactly as written: www.linkedin.com/in/sutariaarjun (no trailing punctuation, no other URL or text attached to it)

Rules:
- Address the sender by first name. Thank them specifically for what they wrote (the company, role or context). Warm and professional, not salesy.
- Keep it under 75 words. Plain text, no markdown, no bullet points, no subject line.
- Sign off as "Arjun".
- NEVER answer questions about work authorization, visa or sponsorship, salary or compensation, location or relocation, availability beyond Q1/Q2 2027, references, or personal details. Don't invent facts.
- If the email asks direct questions beyond "are you interested", start your output with a line "NEEDS_REVIEW:" followed by one sentence naming the questions Arjun must answer himself, then the draft.
- If the email is NOT personal outreach to Arjun (newsletter, marketing blast, automated alert, or no real person asking him something), output exactly: SKIP: <few words why>
- Output only the reply text, the NEEDS_REVIEW line followed by the reply, or a SKIP line. No preamble, no explanation.

Standard message for reference: "{STANDARD_REPLY}"
"""


def _headers(msg: dict) -> dict:
    return {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}


def _body(msg: dict) -> str:
    payload = msg.get("payload", {})
    parts = payload.get("parts") or [payload]
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
    return msg.get("snippet", "")


def find_candidates(service) -> list[dict]:
    resp = service.users().threads().list(userId="me", q=SEARCH, maxResults=25).execute()
    out = []
    for t in resp.get("threads", []):
        thread = service.users().threads().get(userId="me", id=t["id"], format="full").execute()
        msgs = thread.get("messages", [])
        last = msgs[-1]
        # Already answered (we sent the last message)? Skip. A new inbound message after our reply still gets a draft.
        if "SENT" in last.get("labelIds", []):
            continue
        h = _headers(last)
        if AUTOMATED.search(h.get("From", "")):
            continue
        out.append({"thread_id": t["id"], "headers": h, "body": _body(last)})
    return out


def draft_reply(client: anthropic.Anthropic, item: dict) -> str:
    h = item["headers"]
    prompt = (
        f"From: {h.get('From', '')}\nSubject: {h.get('Subject', '')}\n\n"
        f"Email body:\n{item['body'][:4000]}"
    )
    with client.messages.stream(
        model=MODEL,
        max_tokens=1000,
        output_config={"effort": "medium"},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _reply_message(item: dict, body: str) -> dict:
    h = item["headers"]
    msg = EmailMessage()
    msg["To"] = h.get("From", "")
    subject = h.get("Subject", "")
    msg["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    msg["In-Reply-To"] = h.get("Message-ID", "")
    msg["References"] = h.get("Message-ID", "")
    text, html_part = _email_parts(body)
    msg.set_content(text)
    msg.add_alternative(html_part, subtype="html")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw, "threadId": item["thread_id"]}


def create_draft(service, item: dict, body: str) -> str:
    draft = service.users().drafts().create(
        userId="me", body={"message": _reply_message(item, body)}
    ).execute()
    return draft["id"]


def send_reply(service, item: dict, body: str) -> str:
    sent = service.users().messages().send(userId="me", body=_reply_message(item, body)).execute()
    return sent["id"]


def notify(text: str) -> None:
    """macOS notification so held emails don't sit unnoticed."""
    subprocess.run(
        ["osascript", "-e", f'display notification "{text}" with title "Recruiter reply"'],
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send", action="store_true",
                        help="Send clean replies instead of saving drafts. Questions are never sent.")
    args = parser.parse_args()

    service = email_agent.get_gmail_service(args.account)
    client = anthropic.Anthropic(api_key=config.get_anthropic_key())
    items = find_candidates(service)
    print(f"Found {len(items)} recruiter/opportunity thread(s) needing a reply.\n")

    LOG.parent.mkdir(exist_ok=True)
    for item in items:
        h = item["headers"]
        body = draft_reply(client, item)
        if re.search(r"https?://|www\.|linkedin\.com", body, re.I):
            body = re.sub(r"https?://\S+|www\.\S+|\S*linkedin\.com\S*", "", body, flags=re.I)
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body.startswith("SKIP:"):
            print(f"Skipped {h.get('From', '')}: {body[5:].strip()}")
            continue
        # Hold for your review if the model flags it, or the email asks anything
        # (a question mark or a numbered list of questions).
        asks = bool(re.search(r"\?|^\s*\d+[.)]\s", item["body"], re.M))
        review = body.startswith("NEEDS_REVIEW:") or asks
        print("=" * 70)
        print(f"From:    {h.get('From', '')}\nSubject: {h.get('Subject', '')}")
        print(f"Status:  {'NEEDS YOUR ANSWER -- not drafted' if review else 'draft ready'}\n")
        print(body)

        row = {"time": datetime.now().isoformat(timespec="seconds"), "account": args.account,
               "thread": item["thread_id"], "from": h.get("From", ""),
               "subject": h.get("Subject", ""), "needs_review": review}
        if review:
            notify(f"Recruiter email needs your answer: {h.get('Subject', '')[:60]}")
        elif not args.dry_run:
            if args.send:
                row["sent_id"] = send_reply(service, item, body)
            else:
                row["draft_id"] = create_draft(service, item, body)
        with LOG.open("a") as f:
            f.write(json.dumps(row) + "\n")

    print("\nDone. " + ("Clean replies were sent; questions were held for you."
                       if args.send else "Drafts are in Gmail's Drafts folder. Nothing was sent."))


if __name__ == "__main__":
    main()
