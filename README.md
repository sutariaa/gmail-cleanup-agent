# Gmail Cleanup Agent

A Claude-powered agent that surveys your Gmail and proposes unneeded messages for trashing across four categories: spam, promotional, social notifications, and old read mail.

The agent only **proposes** deletions via tool calls; a CLI wrapper shows the proposal (and optionally pings Telegram), then prompts for confirmation before moving anything to Trash. Trash is reversible for 30 days, so this is the safe default.

## How it works

- `email_agent.py` runs an Anthropic tool-use loop with four tools: `search_messages`, `get_message_details`, `propose_trash`, `finish`. The agent never calls Gmail's trash API directly — it only accumulates proposed message IDs.
- `clean_email.py` is the CLI entrypoint. It runs the agent, prints the proposal grouped by category, sends a Telegram summary (if configured), and prompts `y/N` before calling Gmail's `batchModify` to move messages to Trash.
- OAuth scope is `gmail.modify` only — no permanent-delete capability is granted.

## Setup

1. Create a venv and install deps:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and add your `ANTHROPIC_API_KEY` (and optionally Telegram).

3. Get Gmail OAuth credentials:
   - Go to https://console.cloud.google.com/apis/credentials
   - Create OAuth client ID (type: **Desktop app**)
   - Enable the Gmail API for the project
   - Download the JSON, save as `gmail_credentials.json` in the repo root

4. Run the one-time auth flow:
   ```
   python setup_gmail.py
   ```
   A browser opens; sign in and grant access. A refreshable token is written to `gmail_token.json`.

## Usage

```
python clean_email.py                       # all categories, dry-run + confirm
python clean_email.py --list-only           # show proposals, never trash
python clean_email.py --category spam       # restrict to one category
python clean_email.py --max 50              # cap messages per category
python clean_email.py --yes                 # skip the confirm prompt
```

Categories: `spam`, `promotional`, `social`, `old_read`.

## Categories

| Category      | Gmail query (starting point) |
| ------------- | ---------------------------- |
| `spam`        | `in:spam` |
| `promotional` | `category:promotions older_than:7d` |
| `social`      | `category:social older_than:7d` |
| `old_read`    | `is:read older_than:6m -is:starred -is:important -in:sent -in:chats` |

The agent uses these as starting points and decides per-message what to propose. Starred, important, sent mail, chats, and drafts are always excluded.

## Safety

- **Trash, not delete.** Messages are moved to Trash and remain recoverable in Gmail for 30 days.
- **Two-step.** The agent proposes; you approve. Use `--list-only` for a true dry run.
- **Conservative on `old_read`.** The system prompt instructs Claude to skip when in doubt.
- **Telegram summary** (optional). If `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set, the proposal is also sent to your phone before the prompt.
