#!/bin/bash
# Change wallpaper to a random picture in WALLPAPER_DIR excluding current wallpaper
WALLPAPER_DIR="$HOME/.local/share/wallpapers/16x9"
COLORS_KDL="$HOME/.local/share/wallpapers/colors.kdl"
COLORS_TOML="$HOME/.local/share/wallpapers/colors.toml"
DYNAMIC_JSON="$HOME/.config/matugen/themes/dynamic.json"

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

# Update dynamic colors based on wallpaper
BASENAME=$(basename "$IMAGE" | sed 's/\.[^.]*$//')

# TOML fallback lookup (kept for compatibility with colors.toml).
lookup_color_toml() {
    local key="$1" section="color.${2}"
    sed -n "/^\[${section}\]/,/^\[/p" "$COLORS_TOML" | grep "^${key} " | grep -oP '"#\K[0-9a-fA-F]{6}'
}

if [ -f "$COLORS_KDL" ]; then
    # Resolve primary/secondary from KDL via the ckdl parser, with _default fallback.
    { read -r PRIMARY; read -r SECONDARY; } < <(
        uv run --quiet --with ckdl python3 - "$COLORS_KDL" "$BASENAME" <<'PY'
import sys, ckdl
path, name = sys.argv[1], sys.argv[2]
with open(path) as f:
    doc = ckdl.parse(f.read())
colors = {}
for node in doc.nodes:
    if node.name == "color" and node.args:
        colors[str(node.args[0])] = {
            c.name: str(c.args[0]) for c in node.children if c.args
        }
def pick(field):
    val = colors.get(name, {}).get(field) or colors.get("_default", {}).get(field) or ""
    return val.lstrip("#")
print(pick("primary"))
print(pick("secondary"))
PY
    )
else
    PRIMARY=$(lookup_color_toml primary "$BASENAME")
    SECONDARY=$(lookup_color_toml secondary "$BASENAME")
    : "${PRIMARY:=$(lookup_color_toml primary _default)}"
    : "${SECONDARY:=$(lookup_color_toml secondary _default)}"
fi

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

matugen color hex ffffff
