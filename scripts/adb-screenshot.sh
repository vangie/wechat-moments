#!/bin/bash
#
# Take a screenshot from connected Android device
#
# Usage:
#   ./scripts/adb-screenshot.sh [output_path]
#
# Default: screenshots/<timestamp>.png

set -e

# Default output with timestamp
if [ -n "$1" ]; then
    OUTPUT="$1"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    SCREENSHOTS_DIR="$PROJECT_ROOT/screenshots"
    mkdir -p "$SCREENSHOTS_DIR"
    OUTPUT="$SCREENSHOTS_DIR/$(date +%Y%m%d_%H%M%S).png"
fi

# Get display ID for multi-display devices (e.g., Huawei/EMUI)
DISPLAY_ID=$(adb shell dumpsys SurfaceFlinger --display-id 2>/dev/null | awk '/^Display/{print $2; exit}')

# Capture screenshot
if [ -n "$DISPLAY_ID" ]; then
    adb shell screencap -d "$DISPLAY_ID" /data/local/tmp/_wmp_screen.png
else
    adb shell screencap /data/local/tmp/_wmp_screen.png
fi

# Transfer via base64 (more reliable than adb pull on some devices)
adb shell base64 /data/local/tmp/_wmp_screen.png | base64 --decode > "$OUTPUT"

echo "Saved to $OUTPUT"

# Open on macOS
if [ "$(uname)" = "Darwin" ]; then
    open "$OUTPUT"
fi
