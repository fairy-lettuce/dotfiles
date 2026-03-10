#!/bin/bash
# Change wallpaper to a random picture in WALLPAPER_DIR excluding current wallpaper
WALLPAPER_DIR="$HOME/Pictures/Wallpaper"
CURRENT=$(swww query | grep -oP 'image: \K.*' | head -1)
IMAGE=$(find "$WALLPAPER_DIR" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \) | grep -vF "$CURRENT" | shuf -n 1)
[ -n "$IMAGE" ] && swww img "$IMAGE" --transition-fps 165 -t wipe --transition-angle 15