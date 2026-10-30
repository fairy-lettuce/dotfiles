#!/bin/bash
# Keep GNOME's color-scheme gsetting in sync with matugen's resolved gtk4
# light/dark output (which already accounts for flip_mode.gtk4). Without this,
# libadwaita apps (e.g. nautilus) can load the wrong base stylesheet and show
# unreadable text when flip_mode inverts gtk4 relative to is_dark_mode.
set -euo pipefail

MODE_FILE="$HOME/.config/matugen/generated/gtk-mode.txt"
MODE=$(tr -d '[:space:]' < "$MODE_FILE")

case "$MODE" in
light) gsettings set org.gnome.desktop.interface color-scheme 'prefer-light' ;;
dark)  gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' ;;
esac
