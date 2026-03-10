#!/bin/bash
# Change wallpaper to a random picture in WALLPAPER_DIR excluding current wallpaper
WALLPAPER_DIR="$HOME/.local/share/wallpapers/16x9"

# Restart daemon if not running
# Temporary fix for awww-daemon crashing after rebooting from systemctl suspend
if ! pgrep -x awww-daemon > /dev/null; then
    awww-daemon &
    sleep 1
fi

CURRENT=$(awww query | grep -oP 'image: \K.*' | head -1)
IMAGE=$(find "$WALLPAPER_DIR" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \) | grep -vF "$CURRENT" | shuf -n 1)
[ -n "$IMAGE" ] && awww img "$IMAGE" --transition-fps 165 -t wipe --transition-angle 15