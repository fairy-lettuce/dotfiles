#!/bin/bash
# Recolor Colloid folder icons (notint source) with the current secondary accent
# and install them into the Colloid-shakimofu icon theme override.
set -euo pipefail

SRC_DIR="$HOME/src/Colloid-icon-theme/notint"
DEST_DIR="$HOME/.local/share/icons/Colloid-shakimofu/places/scalable"
HEX_FILE="$HOME/.config/matugen/generated/folder-color.hex"

HEX=$(tr -d '[:space:]' < "$HEX_FILE")

mkdir -p "$DEST_DIR"
cp "$SRC_DIR"/*.svg "$DEST_DIR"/
sed -i "s/#60c0f0/${HEX}/gI" "$DEST_DIR"/*.svg

# Colloid uses aliases for some standard XDG user-dir icon names;
# notint only ships the base names, so recreate the aliases here.
declare -A ALIASES=(
	[folder-pictures.svg]=folder-images.svg
	[folder-publicshare.svg]=folder-public.svg
	[folder-downloads.svg]=folder-download.svg
	[folder-video.svg]=folder-videos.svg
	[desktop.svg]=user-desktop.svg
	[folder-desktop.svg]=desktop.svg
)
for alias in "${!ALIASES[@]}"; do
	ln -sf "${ALIASES[$alias]}" "$DEST_DIR/$alias"
done

gtk-update-icon-cache "$HOME/.local/share/icons/Colloid-shakimofu" 2>/dev/null || true
