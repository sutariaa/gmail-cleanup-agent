#!/bin/bash
# install_schedule.sh
# -------------------
# Installs a launchd agent that runs weekly_cleanup.sh every Sunday at 6 PM.
# If the Mac is asleep at that time, launchd runs the job as soon as it wakes.
# (A Mac that is fully shut down skips that week.)
#
# Usage:  ./install_schedule.sh              # install or reinstall
#         ./install_schedule.sh --uninstall  # remove the schedule

WEEKDAY=0   # 0 = Sunday
HOUR=18
MINUTE=0

LABEL="com.sutariaa.gmail-cleanup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")" && pwd)"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null

if [ "$1" = "--uninstall" ]; then
    rm -f "$PLIST"
    echo "Removed $LABEL"
    exit 0
fi

mkdir -p "$REPO/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-i</string>
        <string>/bin/bash</string>
        <string>$REPO/weekly_cleanup.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>$WEEKDAY</integer>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$REPO/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/logs/launchd.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "$DOMAIN" "$PLIST" \
    && echo "Installed $LABEL: weekday $WEEKDAY at $(printf '%02d:%02d' $HOUR $MINUTE), runs $REPO/weekly_cleanup.sh"
