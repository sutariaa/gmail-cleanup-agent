"""
clean_email.py
--------------
CLI entrypoint for the Gmail cleanup agent.

Usage:
  python clean_email.py                       # all categories, dry run + confirm
  python clean_email.py --category spam       # only one category
  python clean_email.py --max 50              # cap messages per category (default 100)
  python clean_email.py --yes                 # skip the confirmation prompt
  python clean_email.py --list-only           # show proposals, never trash

Categories: spam, promotional, social, old_read
"""

from __future__ import annotations

import argparse
import sys

import email_agent
import notifier


def _format_summary(proposals: dict[str, list[str]], reasons: dict[str, list[str]]) -> str:
    lines = []
    total = 0
    for cat, ids in proposals.items():
        if not ids:
            lines.append(f"  [{cat}] 0 messages")
            continue
        total += len(ids)
        lines.append(f"  [{cat}] {len(ids)} messages")
        for r in reasons.get(cat, [])[:3]:
            lines.append(f"      - {r}")
        if len(reasons.get(cat, [])) > 3:
            lines.append(f"      - ... +{len(reasons[cat]) - 3} more reason(s)")
    lines.append(f"  TOTAL: {total} messages proposed")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail cleanup agent")
    parser.add_argument(
        "--category",
        choices=list(email_agent.CATEGORIES.keys()),
        action="append",
        help="Restrict to one category. Repeat to pick multiple. Default: all.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=100,
        help="Max messages the agent surveys per category (default 100, cap 200).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt and trash immediately.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Show proposals and exit. Never trash anything.",
    )
    args = parser.parse_args()

    categories = args.category or list(email_agent.CATEGORIES.keys())
    max_per_category = max(1, min(args.max, 200))

    print(f"\nRunning Gmail cleanup agent on: {', '.join(categories)}")
    print(f"(cap {max_per_category} messages per category)\n")

    proposals = email_agent.run(categories, max_per_category)
    reasons = getattr(email_agent.run, "last_reasons", {})

    summary = _format_summary(proposals, reasons)
    print("\n" + "=" * 60)
    print("PROPOSED FOR TRASH")
    print("=" * 60)
    print(summary)
    print("=" * 60 + "\n")

    total = sum(len(ids) for ids in proposals.values())
    if total == 0:
        print("Nothing to trash. Done.")
        notifier.send_sms("Gmail cleanup: nothing to trash.")
        return

    notifier.send_sms(f"Gmail cleanup proposal:\n{summary}")

    if args.list_only:
        print("--list-only set; not trashing. Done.")
        return

    if not args.yes:
        answer = input(f"Trash {total} emails? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted. Nothing trashed.")
            notifier.send_sms("Gmail cleanup aborted -- nothing trashed.")
            return

    service = email_agent.get_gmail_service()
    moved_total = 0
    for cat, ids in proposals.items():
        if not ids:
            continue
        moved = email_agent.batch_trash(service, ids)
        moved_total += moved
        print(f"  Trashed {moved} from [{cat}]")

    final_msg = f"Gmail cleanup: moved {moved_total} messages to Trash (recoverable for 30 days)."
    print(f"\n{final_msg}")
    notifier.send_sms(final_msg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Nothing trashed.")
        sys.exit(130)
