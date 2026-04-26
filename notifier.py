"""
notifier.py
-----------
Sends a Telegram message alert via the Telegram Bot API.
No third-party SDK needed — uses Python's built-in urllib.

Setup: run `python setup_telegram.py` to get your credentials.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime

import config


def send_sms(message: str) -> None:
    """Send a Telegram message to the configured chat and print to terminal."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{timestamp}] ALERT: {message}\n")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print(f"[{timestamp}] Telegram not configured — run `python setup_telegram.py`")
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": config.TELEGRAM_CHAT_ID, "text": message}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"[{timestamp}] Telegram message sent.")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        print(f"[{timestamp}] Telegram send failed ({exc.code}): {body}")
    except Exception as exc:
        print(f"[{timestamp}] Telegram send failed: {exc}")


# ── Quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    send_sms("Test alert from reservation agent! If you got this, Telegram is working.")
