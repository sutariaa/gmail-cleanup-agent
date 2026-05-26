"""
deep_clean.py
-------------
Second-pass cleanup using the Claude agent on judgment-heavy categories:
old read mail, sign-up/welcome confirmations, and stale automated updates.

The agent decides per-message what to trash; Credit Karma is filtered out
in Python before any trashing happens.

Usage:
  python deep_clean.py --account work
  python deep_clean.py --account work --max 200
"""

from __future__ import annotations

import argparse
import sys

import email_agent
import notifier

EXCLUDED_SENDERS = ["credit karma"]

# Extend the agent's category map with deeper-cleanup queries
EXTRA_CATEGORIES: dict[str, str] = {
    "signup_confirmations": (
        '(subject:welcome OR subject:"verify your email" OR subject:"confirm your email" '
        'OR subject:"thanks for signing up" OR subject:"account created" OR subject:"you\'re in") '
        'is:read -is:starred -is:important'
    ),
    "stale_updates": "category:updates older_than:60d is:read -is:starred -is:important",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--max", type=int, default=200)
    args = parser.parse_args()

    # Register the extra categories so email_agent.run() understands them
    for k, v in EXTRA_CATEGORIES.items():
        email_agent.CATEGORIES[k] = v

    targets = ["old_read", "signup_confirmations", "stale_updates"]
    print(f"\n=== Deep clean: {args.account} | categories={targets} | max={args.max} ===\n")
    proposals = email_agent.run(targets, args.max, account=args.account)

    print(f"\n=== Filtering out senders: {EXCLUDED_SENDERS} ===\n")
    service = email_agent.get_gmail_service(args.account)
    filtered: dict[str, list[str]] = {}
    kept_excluded: list[tuple[str, str, str]] = []

    for cat, ids in proposals.items():
        keep: list[str] = []
        for mid in ids:
            meta = service.users().messages().get(
                userId="me",
                id=mid,
                format="metadata",
                metadataHeaders=["From", "Subject"],
            ).execute()
            headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
            sender = headers.get("From", "")
            if any(ex in sender.lower() for ex in EXCLUDED_SENDERS):
                kept_excluded.append((cat, sender, headers.get("Subject", "")[:70]))
            else:
                keep.append(mid)
        filtered[cat] = keep

    if kept_excluded:
        print(f"KEPT (Credit Karma) — {len(kept_excluded)} items:")
        for cat, sender, subject in kept_excluded[:8]:
            print(f"  [{cat}] {sender} | {subject}")
        print()

    total = sum(len(ids) for ids in filtered.values())
    if total == 0:
        print("Nothing to trash after filtering.")
        return

    print(f"=== Trashing {total} messages ===")
    moved_total = 0
    for cat, ids in filtered.items():
        if not ids:
            print(f"  [{cat}] 0")
            continue
        moved = email_agent.batch_trash(service, ids)
        moved_total += moved
        print(f"  [{cat}] trashed {moved}")

    msg = f"Deep clean ({args.account}): trashed {moved_total}, kept {len(kept_excluded)} Credit Karma. Reversible 30 days."
    print(f"\n{msg}")
    notifier.send_sms(msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
