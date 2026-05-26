"""
trash_with_filter.py
--------------------
One-off: run the cleanup agent on an account, filter out any messages from
senders in EXCLUDED_SENDERS (substring match, case-insensitive), then trash
the remainder. Used to honor the user's "never delete Credit Karma" rule.

Usage:  python trash_with_filter.py --account personal
"""

from __future__ import annotations

import argparse
import sys

import email_agent
import notifier

EXCLUDED_SENDERS = ["credit karma"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--max", type=int, default=50)
    args = parser.parse_args()

    cats = list(email_agent.CATEGORIES.keys())
    print(f"\n=== Running agent on '{args.account}' (cap {args.max}/category) ===\n")
    proposals = email_agent.run(cats, args.max, account=args.account)

    print(f"\n=== Filtering out senders: {EXCLUDED_SENDERS} ===\n")
    service = email_agent.get_gmail_service(args.account)
    filtered: dict[str, list[str]] = {}
    excluded: list[tuple[str, str, str]] = []  # (category, from, subject)

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
                excluded.append((cat, sender, headers.get("Subject", "")[:70]))
            else:
                keep.append(mid)
        filtered[cat] = keep

    if excluded:
        print(f"KEPT (matched exclusion list):")
        for cat, sender, subject in excluded:
            print(f"  [{cat}] {sender} | {subject}")
        print()
    else:
        print("(nothing matched the exclusion list)\n")

    total = sum(len(ids) for ids in filtered.values())
    if total == 0:
        print("Nothing to trash after filtering.")
        return

    print(f"=== Trashing {total} messages ===\n")
    moved_total = 0
    for cat, ids in filtered.items():
        if not ids:
            print(f"  [{cat}] 0")
            continue
        moved = email_agent.batch_trash(service, ids)
        moved_total += moved
        print(f"  [{cat}] trashed {moved}")

    final = f"\nGmail cleanup ({args.account}): trashed {moved_total}, kept {len(excluded)} from exclusion list. Reversible 30 days."
    print(final)
    notifier.send_sms(final)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
