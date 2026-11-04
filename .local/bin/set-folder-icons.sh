#!/bin/bash
# Assign custom Colloid folder icons (by name) to well-known folders under $HOME.
set -euo pipefail

declare -A NAME_ICON=(
	[Projects]=folder-projects
	[Works]=folder-projects
	[Games]=folder-games
	[src]=folder-code
	[source]=folder-code
	[.config]=folder-notes
	[.local]=folder-bookmark
	[.steam]=folder-steam
)

for name in "${!NAME_ICON[@]}"; do
	path="$HOME/$name"
	if [ -d "$path" ]; then
		gio set "$path" metadata::custom-icon-name "${NAME_ICON[$name]}"
	fi
done

# .steam is a real directory that contains a `steam` symlink to the actual
# install location; icon both the symlink and its target explicitly.
if [ -L "$HOME/.steam/steam" ]; then
	gio set -n "$HOME/.steam/steam" metadata::custom-icon-name folder-steam
fi
if [ -d "$HOME/.local/share/Steam" ]; then
	gio set "$HOME/.local/share/Steam" metadata::custom-icon-name folder-steam
fi
