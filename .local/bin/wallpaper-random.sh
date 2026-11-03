#!/bin/bash
# Change wallpaper to a random picture in WALLPAPER_DIR excluding current wallpaper,
# then regenerate the color scheme for it (generate-color-scheme.sh).
# The wallpapers repo location can be changed in ~/.config/dotfiles/wallpaper-random.local.
WALLPAPER_REPO="$HOME/.local/share/wallpapers"
WALLPAPER_LOCAL="$HOME/.config/dotfiles/wallpaper-random.local"
# shellcheck source=/dev/null
[ -f "$WALLPAPER_LOCAL" ] && . "$WALLPAPER_LOCAL"
WALLPAPER_DIR="$WALLPAPER_REPO/16x9"

# Temporary fix for awww-daemon crasing is no longer needed because it is now executed as a systemd user unit.
# if ! pgrep -x awww-daemon > /dev/null; then
#     awww-daemon &
#     sleep 1
# fi

CURRENT=$(awww query | grep -oP 'image: \K.*' | head -1)
CANDIDATES=$(find "$WALLPAPER_DIR" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \))
[ -n "$CURRENT" ] && CANDIDATES=$(echo "$CANDIDATES" | grep -vF "$CURRENT")
IMAGE=$(echo "$CANDIDATES" | shuf -n 1)
if [ -n "$IMAGE" ]; then
    if [ -n "$CURRENT" ]; then
        awww img "$IMAGE" --transition-fps 165 -t wipe --transition-angle 15
    else
        awww img "$IMAGE" -t none
    fi
fi

# Update dynamic colors based on wallpaper (no image -> default colors)
BASENAME=""
[ -n "$IMAGE" ] && BASENAME=$(basename "$IMAGE" | sed 's/\.[^.]*$//')
exec "$(dirname "$(readlink -f "$0")")/generate-color-scheme.sh" ${BASENAME:+"$BASENAME"}
