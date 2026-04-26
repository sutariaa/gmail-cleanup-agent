"""
setup_gmail.py
--------------
One-time OAuth setup for the Gmail cleanup agent.

Before running:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or use an existing one)
  3. Enable the Gmail API
  4. Create OAuth client ID credentials (type: Desktop app)
  5. Download the JSON and save as `gmail_credentials.json` in this directory

Then run:  python setup_gmail.py

The script opens a browser, you sign in to your Google account, and grant
the agent permission to read/modify (but NOT permanently delete) Gmail.
A refreshable token is saved to `gmail_token.json`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def token_path_for(account: str | None) -> Path:
    """Path for an account-specific token, or the default token if None."""
    if account:
        return Path(f"gmail_token_{account}.json")
    return Path(config.GMAIL_TOKEN_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="One-time OAuth setup for the Gmail cleanup agent.")
    parser.add_argument(
        "--account",
        help="Optional account name to support multiple Gmail accounts. "
             "Token is saved to gmail_token_<name>.json (e.g. --account personal).",
    )
    args = parser.parse_args()

    print()
    print("=" * 60)
    label = "Gmail Cleanup Agent -- OAuth Setup"
    if args.account:
        label += f" ({args.account})"
    print(f"  {label}")
    print("=" * 60)

    creds_path = Path(config.GMAIL_CREDENTIALS_PATH)
    token_path = token_path_for(args.account)

    if not creds_path.exists():
        print(f"\nCould not find OAuth credentials at: {creds_path}")
        print("\nDownload them from Google Cloud Console:")
        print("  1. https://console.cloud.google.com/apis/credentials")
        print("  2. Create OAuth client ID (type: Desktop app)")
        print(f"  3. Download JSON and save as: {creds_path}")
        sys.exit(1)

    print(f"\nUsing credentials: {creds_path}")
    print("A browser window will open. Sign in and grant access.\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json())
    print(f"\nToken saved to: {token_path}")

    # Smoke test: list one message to confirm scope works
    print("Verifying access...")
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"\nConnected as: {profile.get('emailAddress')}")
    print(f"Total messages: {profile.get('messagesTotal')}")
    if args.account:
        print(f"\nSetup complete. Run:  python clean_email.py --account {args.account}")
    else:
        print("\nSetup complete. You can now run:  python clean_email.py")


if __name__ == "__main__":
    main()
