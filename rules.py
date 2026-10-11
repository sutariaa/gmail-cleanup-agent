"""
rules.py
--------
Plain-text rule files you edit to teach the cleanup what matters.

  keep_rules.txt   Gmail query fragments for mail that must NEVER be trashed,
                   e.g.  from:amex.com   or   subject:"flight confirmation"
                   Read by the agent (as instructions) and by bulk_trash.py
                   (as -exclusions on every bulk query).

  trash_rules.txt  Gmail query fragments trashed on every run with no AI,
                   e.g.  from:noreply@marketing.example.com

  star_rules.txt   Gmail query fragments that get STARRED every run (never trashed),
                   e.g. confirmations, tickets, receipts.

Lines starting with # and blank lines are ignored.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent


def _read(name: str) -> list[str]:
    path = ROOT / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def keep_rules() -> list[str]:
    return _read("keep_rules.txt")


def trash_rules() -> list[str]:
    return _read("trash_rules.txt")


def star_rules() -> list[str]:
    return _read("star_rules.txt")
