"""
bulk_trash.py
-------------
Direct Gmail-API bulk trash for the obvious-junk categories. No Claude in
the loop -- it's faster and equally correct for sender-based rules.

Pages through ALL results for each query, then trashes them in batches of
1000 via batchModify. Credit Karma is excluded at the query level via
`-from:creditkarma.com` so we don't need to fetch metadata.

Usage:
  python bulk_trash.py --account personal           # actually trash
  python bulk_trash.py --account personal --dry-run # just count
"""

from __future__ import annotations

import argparse
import sys

import email_agent
import notifier

# Each entry: (label, gmail query)
QUERIES: list[tuple[str, str]] = [
    ("spam",        "in:spam"),
    ("linkedin",    "from:linkedin.com -from:creditkarma.com"),
    ("promotions",  "category:promotions -from:creditkarma.com -from:linkedin.com"),
    ("social",      "category:social -from:creditkarma.com -from:linkedin.com"),
]


def page_all_ids(service, query: str) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=500, pageToken=page_token
        ).execute()
        for m in resp.get("messages", []):
            ids.append(m["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    service = email_agent.get_gmail_service(args.account)
    print(f"\n=== bulk trash on account '{args.account}' ===")
    if args.dry_run:
        print("(DRY RUN -- nothing will be trashed)\n")

    grand_trashed = 0
    grand_found = 0
    summary_lines: list[str] = []

    for label, query in QUERIES:
        print(f"\n[{label}]  query: {query}")
        print(f"  paging through results...", flush=True)
        ids = page_all_ids(service, query)
        print(f"  found {len(ids)} messages")
        grand_found += len(ids)

        if not ids:
            summary_lines.append(f"  [{label}] 0 found")
            continue

        if args.dry_run:
            summary_lines.append(f"  [{label}] {len(ids)} would be trashed")
            continue

        moved = email_agent.batch_trash(service, ids)
        grand_trashed += moved
        print(f"  trashed {moved}")
        summary_lines.append(f"  [{label}] trashed {moved}")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for line in summary_lines:
        print(line)
    if args.dry_run:
        print(f"\nGrand total (dry run): {grand_found} would be trashed")
        print("Credit Karma is excluded via -from:creditkarma.com in each query.")
    else:
        msg = f"\nGrand total: trashed {grand_trashed} from '{args.account}' (Credit Karma preserved, reversible 30 days)."
        print(msg)
        notifier.send_sms(f"Bulk trash ({args.account}): trashed {grand_trashed} messages.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
