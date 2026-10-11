"""
decisions.py
------------
Append-only log of every keep/trash decision the agent made, so you can
review them and add mistakes to keep_rules.txt or trash_rules.txt.
One JSON object per line in logs/decisions.jsonl.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).parent / "logs" / "decisions.jsonl"


def record(account: str, category: str, action: str, sender: str, subject: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    row = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "account": account,
        "category": category,
        "action": action,  # "trashed" | "kept"
        "from": sender,
        "subject": subject,
    }
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
