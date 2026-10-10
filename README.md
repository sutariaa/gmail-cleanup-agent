# Gmail Cleanup Agent

A Claude-powered toolkit for surveying your Gmail and trashing what you don't need. Messages are moved to **Trash** (not permanently deleted), so anything is recoverable for 30 days.

Four cleanup modes are included, from "let the agent decide" to "delete by query, no model needed." Pick the one that matches the volume and risk level of what you're cleaning.

---

## Cleanup modes

| Script | When to use | How it picks |
| --- | --- | --- |
| `clean_email.py` | First-time use; you want to see the agent's reasoning and confirm before any deletion | Claude reads ~50 messages per category and proposes trash; you approve `y/N` |
| `trash_with_filter.py` | Same as above, but auto-trashes (no prompt) and excludes anything from senders in `EXCLUDED_SENDERS` (default: Credit Karma) | Claude proposes → Python filters → trashes |
| `bulk_trash.py` | Big sweep of obvious junk (LinkedIn notifications, all promotions, all spam). Trashes thousands in seconds — no model in the loop | Direct Gmail query (`from:linkedin.com`, `category:promotions`, etc.) |
| `deep_clean.py` | Second-pass after `bulk_trash`. Catches sign-up confirmations, "welcome" emails, stale automated updates, and old read newsletters that need judgment | Claude on extended categories (`signup_confirmations`, `stale_updates`, `old_read`) with sender filter |

All four scripts respect the same `EXCLUDED_SENDERS` list — Credit Karma mail (any kind) is preserved by default.

---

## Setup

1. **Install deps**
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure secrets** — copy `.env.example` to `.env`, fill in `ANTHROPIC_API_KEY` (and optionally `TELEGRAM_*` for summaries).

3. **Get Gmail OAuth credentials** (one-time, ~3 min):
   - [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
   - Enable the Gmail API for your project
   - Configure the OAuth consent screen (External, add your Gmail addresses as Test users)
   - Create an **OAuth client ID → Desktop app** and download the JSON
   - Save as `gmail_credentials.json` in the repo root
   - Under **Audience**, click **Publish app** so the status is *In production*. While an app is in *Testing*, Google expires sign-ins after 7 days, which breaks the weekly schedule. (Leaving it unverified is fine for personal use.)

4. **Authenticate** (browser opens; sign in and grant access):
   ```
   python setup_gmail.py --account personal     # → gmail_token_personal.json
   python setup_gmail.py --account work         # → gmail_token_work.json
   ```
   Omit `--account` to fall back to the default `gmail_token.json`.

---

## Usage

### `clean_email.py` — agent with confirmation

```
python clean_email.py                       # all categories, dry run + y/N prompt
python clean_email.py --list-only           # show proposals, never trash
python clean_email.py --category spam       # restrict to one category
python clean_email.py --max 50              # cap messages per category (max 200)
python clean_email.py --yes                 # skip the confirm prompt
python clean_email.py --account personal    # use a specific Gmail account
```

Categories: `spam`, `promotional`, `social`, `old_read`.

### `trash_with_filter.py` — agent, auto-trash, sender filter

```
python trash_with_filter.py --account personal           # default --max 50
python trash_with_filter.py --account work --max 100
```

Runs the agent across all 4 categories, removes any proposed messages from senders in `EXCLUDED_SENDERS` (default `["credit karma"]`), and trashes the rest without prompting.

### `bulk_trash.py` — direct Gmail query, no agent

```
python bulk_trash.py --account work --dry-run   # count only
python bulk_trash.py --account work             # actually trash
```

Pages through *every* match for these queries and trashes in batches of 1000:

| Query | What it catches |
| --- | --- |
| `in:spam` | All spam |
| `from:linkedin.com -from:creditkarma.com` | All LinkedIn mail (Job Alerts, notifications, InMail, etc.) |
| `category:promotions -from:creditkarma.com -from:linkedin.com` | All promotional mail |
| `category:social -from:creditkarma.com -from:linkedin.com` | All social-category mail (non-LinkedIn) |

Designed for the first sweep on a heavily backlogged mailbox — can clean 10k+ messages in ~30 seconds.

### `deep_clean.py` — second-pass judgment cleanup

```
python deep_clean.py --account work
python deep_clean.py --account work --max 200
```

After `bulk_trash` has cleared the obvious junk, this runs the agent on three judgment-heavy categories with Credit Karma filtered out:

| Category | Query |
| --- | --- |
| `old_read` | `is:read older_than:6m -is:starred -is:important -in:sent -in:chats` |
| `signup_confirmations` | Subjects matching "welcome", "verify your email", "confirm your email", "thanks for signing up", "account created", "you're in" — read mail only |
| `stale_updates` | `category:updates older_than:60d is:read -is:starred -is:important` |

The agent uses its judgment to skip receipts, security notices, interview invites, and similar items worth keeping.

---

## Weekly schedule

`weekly_cleanup.sh` runs `bulk_trash.py` then `deep_clean.py` on every account (`personal`, `work`). `install_schedule.sh` registers it with macOS `launchd` to run **every Sunday at 6 PM**.

```
./install_schedule.sh                # install (or reinstall after editing the time)
./install_schedule.sh --uninstall    # remove
./weekly_cleanup.sh --dry-run        # test the job without trashing anything
```

- If the Mac is asleep at 6 PM, the job runs as soon as it wakes. A Mac that's shut down skips that week.
- The run is wrapped in `caffeinate`, so the Mac won't sleep partway through.
- Each run writes `logs/cleanup-YYYY-MM-DD.log` and shows a macOS notification with the total trashed, or with what went wrong (for example, an expired Gmail sign-in).
- To change the day or time, edit `WEEKDAY`/`HOUR`/`MINUTE` at the top of `install_schedule.sh` and re-run it.

---

## What's always preserved

The agent's system prompt and all script-level filters protect:

- **Starred** and **important** messages
- **Sent** mail, chats, and drafts
- Anything from senders in `EXCLUDED_SENDERS` (default: `["credit karma"]`)
- Real correspondence, receipts, order confirmations, account-security notices, interview invites — Claude's system prompt is explicit about skipping these

To exclude more senders permanently, edit `EXCLUDED_SENDERS` at the top of `trash_with_filter.py` and `deep_clean.py`.

## Safety

- **Trash, never permanent delete.** OAuth scope is `gmail.modify` only — the app cannot bypass Trash. Recoverable for 30 days in Gmail.
- **Dry-run modes** available on `clean_email.py --list-only` and `bulk_trash.py --dry-run`.
- **Telegram summary** (optional). Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` and every script posts its results.

## Architecture

- `email_agent.py` — Claude tool-use loop with four tools (`search_messages`, `get_message_details`, `propose_trash`, `finish`). The agent never calls Gmail's trash API directly; it only returns proposed IDs.
- `clean_email.py`, `trash_with_filter.py`, `deep_clean.py` — drivers that invoke the agent, optionally filter, then call `email_agent.batch_trash` (the only function that actually moves messages).
- `bulk_trash.py` — bypasses the agent entirely for high-confidence sender/category rules.
- `notifier.py` — Telegram bot wrapper (optional).
- `setup_gmail.py` — one-time OAuth flow per account.
- `config.py` — lazy env-var loading.
