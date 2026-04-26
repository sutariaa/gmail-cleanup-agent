"""
config.py
---------
Lazy environment-variable loading. Required keys raise only when first used,
so utilities (e.g. setup scripts) can run without the full .env in place.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise ValueError(
            f"Missing required environment variable: {key}\n"
            f"  -> Copy .env.example to .env and fill in your credentials."
        )
    return val


# Anthropic (validated lazily)
def get_anthropic_key() -> str:
    return _require("ANTHROPIC_API_KEY")


ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Telegram (optional -- notifier.py prints a warning if missing)
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Gmail OAuth (run `python setup_gmail.py` once to generate the token file)
GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json")
GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "gmail_token.json")
