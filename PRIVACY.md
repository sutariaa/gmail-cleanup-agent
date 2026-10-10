# Privacy

Gmail Cleanup Agent is a personal tool. It runs only on its owner's computer and is used only with the owner's own Gmail accounts.

## What it accesses

- **Gmail** (`gmail.modify` scope): message metadata (sender, subject, date, labels, snippet) and, for a few borderline messages, a short excerpt of the body. It can move messages to Trash. It never sends email and never permanently deletes anything.

## Where data goes

- **Anthropic's Claude API.** `clean_email.py`, `trash_with_filter.py`, and `deep_clean.py` send message metadata and snippets to Claude so it can decide what to trash. `bulk_trash.py` sends nothing to Anthropic.
- **Telegram** (optional, off by default). If configured, short cleanup summaries go to the owner's own Telegram chat.
- Nowhere else. No analytics, no third-party sharing, no server.

## What's stored

- OAuth tokens (`gmail_token_*.json`) and credentials stay on the local machine and are excluded from git.
- Run logs (`logs/`) stay on the local machine and can include sender names and subject lines.

## Revoking access

Remove the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), or delete the local `gmail_token_*.json` files.
