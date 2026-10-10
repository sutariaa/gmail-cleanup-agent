#!/bin/bash
# weekly_cleanup.sh
# -----------------
# Run by launchd every Sunday (see install_schedule.sh). For each account:
# bulk-trash the obvious junk, then deep-clean with the agent. Output goes to
# logs/cleanup-YYYY-MM-DD.log and a macOS notification reports the result.
#
# Usage:  ./weekly_cleanup.sh            # real run
#         ./weekly_cleanup.sh --dry-run  # bulk_trash --dry-run only; trashes nothing

REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO" || exit 1
PY="$REPO/venv/bin/python"
ACCOUNTS=(personal work)

DRY_RUN=0
[ "$1" = "--dry-run" ] && DRY_RUN=1

mkdir -p "$REPO/logs"
LOG="$REPO/logs/cleanup-$(date +%Y-%m-%d).log"
START_LINE=1
[ -f "$LOG" ] && START_LINE=$(( $(wc -l < "$LOG") + 1 ))
exec >>"$LOG" 2>&1

echo "=== weekly cleanup started $(date) (dry_run=$DRY_RUN) ==="

failures=""
for acct in "${ACCOUNTS[@]}"; do
    if [ "$DRY_RUN" -eq 1 ]; then
        "$PY" -u bulk_trash.py --account "$acct" --dry-run || failures="$failures $acct-bulk"
        continue
    fi
    "$PY" -u bulk_trash.py --account "$acct" || failures="$failures $acct-bulk"
    "$PY" -u deep_clean.py --account "$acct" || failures="$failures $acct-deep"
done

# Sum the "trashed N" totals printed by bulk_trash.py and deep_clean.py during this run
trashed=$(tail -n +"$START_LINE" "$LOG" \
    | grep -E '^(Grand total|Deep clean \()' \
    | grep -Eo 'trashed [0-9]+' \
    | awk '{s += $2} END {print s + 0}')

expired=$(tail -n +"$START_LINE" "$LOG" \
    | grep -Eo 'Run `python setup_gmail.py --account [a-z]+`' \
    | grep -Eo '[a-z]+`$' | tr -d '`' | sort -u | tr '\n' ' ')

if [ -n "$expired" ]; then
    note="Gmail sign-in expired for: ${expired% }. Run setup_gmail.py --account <name>."
elif [ -n "$failures" ]; then
    note="Trashed $trashed emails. Errors:$failures. See logs/$(basename "$LOG")"
elif [ "$DRY_RUN" -eq 1 ]; then
    note="Dry run OK. See logs/$(basename "$LOG")"
else
    note="Trashed $trashed emails (${ACCOUNTS[*]})."
fi

echo "=== weekly cleanup finished $(date): $note ==="
osascript -e "display notification \"$note\" with title \"Gmail cleanup\"" || true

[ -z "$failures" ]
