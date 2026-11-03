#!/bin/bash
# Generate the matugen color scheme (themes/dynamic.json) for a wallpaper.
#
# Usage: generate-color-scheme.sh [<wallpaper basename without extension>]
#
# Color lookup (per field): wallpapers repo colors.kdl entry for the name
# -> its "_default" -> ~/.config/matugen/default-colors.kdl "_default".
# If the repo has no colors.kdl, the legacy colors.toml is used instead.
# With no name, the default colors are used.
#
# The wallpapers repo location can be changed in
# ~/.config/dotfiles/wallpaper-random.local (e.g. WALLPAPER_REPO="$HOME/pics").
# MATUGEN_CONFIG / DYNAMIC_JSON override the output locations (for tests).
#
# Exit status: 0 ok, 1 no usable colors (nothing written), 2 dynamic.json was
# written but matugen failed (e.g. its post_hooks on a tty without a session).
set -euo pipefail

NAME="${1:-}"

WALLPAPER_REPO="$HOME/.local/share/wallpapers"
WALLPAPER_LOCAL="$HOME/.config/dotfiles/wallpaper-random.local"
# shellcheck source=/dev/null
[[ -f "$WALLPAPER_LOCAL" ]] && source "$WALLPAPER_LOCAL"

MATUGEN_CONFIG="${MATUGEN_CONFIG:-$HOME/.config/matugen}"
DYNAMIC_JSON="${DYNAMIC_JSON:-$MATUGEN_CONFIG/themes/dynamic.json}"
DEFAULT_COLORS_KDL="$MATUGEN_CONFIG/default-colors.kdl"
COLORS_KDL="$WALLPAPER_REPO/colors.kdl"
COLORS_TOML="$WALLPAPER_REPO/colors.toml"

# TOML fallback lookup (kept for compatibility with colors.toml).
lookup_color_toml() {
    local key="$1" section="color.${2}"
    sed -n "/^\[${section}\]/,/^\[/p" "$COLORS_TOML" | grep "^${key} " | grep -oP '"#\K[0-9a-fA-F]{6}' || true
}

# Print primary and secondary (one per line, without '#'), looking up NAME
# then "_default" in each KDL file in order. Empty line if not found.
# A file that cannot be read or parsed is skipped with a warning.
lookup_color_kdl() {
    uv run --no-project --quiet --with ckdl python3 - "$NAME" "$@" <<'PY'
import sys, ckdl
name, paths = sys.argv[1], sys.argv[2:]
tables = []
for path in paths:
    try:
        with open(path) as f:
            doc = ckdl.parse(f.read())
        colors = {}
        for node in doc.nodes:
            if node.name == "color" and node.args:
                colors[str(node.args[0])] = {
                    c.name: str(c.args[0]) for c in node.children if c.args
                }
    except Exception as e:
        print(f"Warning: skipping {path}: {type(e).__name__}: {e}", file=sys.stderr)
        continue
    tables.append(colors)
def pick(field):
    for colors in tables:
        for key in (name, "_default"):
            val = colors.get(key, {}).get(field)
            if val:
                return val.lstrip("#")
    return ""
print(pick("primary"))
print(pick("secondary"))
PY
}

PRIMARY="" SECONDARY=""
kdl_files=()
if [[ -f "$COLORS_KDL" ]]; then
    kdl_files+=("$COLORS_KDL")
elif [[ -f "$COLORS_TOML" ]]; then
    [[ -n "$NAME" ]] && PRIMARY=$(lookup_color_toml primary "$NAME")
    [[ -n "$NAME" ]] && SECONDARY=$(lookup_color_toml secondary "$NAME")
    : "${PRIMARY:=$(lookup_color_toml primary _default)}"
    : "${SECONDARY:=$(lookup_color_toml secondary _default)}"
fi
[[ -f "$DEFAULT_COLORS_KDL" ]] && kdl_files+=("$DEFAULT_COLORS_KDL")

if [[ -z "$PRIMARY" || -z "$SECONDARY" ]] && (( ${#kdl_files[@]} > 0 )); then
    kdl_colors=$(lookup_color_kdl "${kdl_files[@]}") || {
        echo "Error: color lookup with uv/ckdl failed" >&2
        exit 1
    }
    : "${PRIMARY:=$(sed -n 1p <<< "$kdl_colors")}"
    : "${SECONDARY:=$(sed -n 2p <<< "$kdl_colors")}"
fi

for c in "$PRIMARY" "$SECONDARY"; do
    if [[ ! "$c" =~ ^[0-9a-fA-F]{6}$ ]]; then
        echo "Error: no valid color found for '${NAME:-<default>}' (got '$c')" >&2
        exit 1
    fi
done

# Derive dark variant: lightness +5%, saturation +10%
derive_dark() {
    python3 -c "
import colorsys
r,g,b=int('$1'[:2],16)/255,int('$1'[2:4],16)/255,int('$1'[4:],16)/255
h,l,s=colorsys.rgb_to_hls(r,g,b)
r,g,b=colorsys.hls_to_rgb(h,min(l+.05,1),min(s+.1,1))
print(f'{int(r*255+.5):02x}{int(g*255+.5):02x}{int(b*255+.5):02x}')"
}

PRIMARY_DARK=$(derive_dark "$PRIMARY")
SECONDARY_DARK=$(derive_dark "$SECONDARY")

mkdir -p "$(dirname "$DYNAMIC_JSON")"
cat > "$DYNAMIC_JSON" <<EOF
{
  "theme": {
    "dynamic_primary": {
      "light": { "color": "#${PRIMARY}" },
      "dark": { "color": "#${PRIMARY_DARK}" },
      "default": { "color": "#${PRIMARY_DARK}" }
    },
    "dynamic_secondary": {
      "light": { "color": "#${SECONDARY}" },
      "dark": { "color": "#${SECONDARY_DARK}" },
      "default": { "color": "#${SECONDARY_DARK}" }
    }
  }
}
EOF

rc=0
matugen color hex ffffff || rc=$?
if [[ $rc -ne 0 ]]; then
    echo "Warning: matugen exited with status $rc ($DYNAMIC_JSON was written)" >&2
    exit 2
fi
