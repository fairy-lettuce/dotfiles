#!/bin/bash
# Change wallpaper to a random picture in WALLPAPER_DIR excluding current wallpaper
WALLPAPER_DIR="$HOME/.local/share/wallpapers/16x9"
COLORS_TOML="$HOME/.local/share/wallpapers/colors.toml"
DYNAMIC_JSON="$HOME/.config/matugen/themes/dynamic.json"

# Restart daemon if not running
# Temporary fix for awww-daemon crashing after rebooting from systemctl suspend
if ! pgrep -x awww-daemon > /dev/null; then
    awww-daemon &
    sleep 1
fi

CURRENT=$(awww query | grep -oP 'image: \K.*' | head -1)
IMAGE=$(find "$WALLPAPER_DIR" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.jpeg' -o -name '*.webp' \) | grep -vF "$CURRENT" | shuf -n 1)
[ -n "$IMAGE" ] && awww img "$IMAGE" --transition-fps 165 -t wipe --transition-angle 15

# Update dynamic colors based on wallpaper
BASENAME=$(basename "$IMAGE" | sed 's/\.[^.]*$//')

lookup_color() {
    local key="$1" section="color.${2}"
    sed -n "/^\[${section}\]/,/^\[/p" "$COLORS_TOML" | grep "^${key} " | grep -oP '"#\K[0-9a-fA-F]{6}'
}

PRIMARY=$(lookup_color primary "$BASENAME")
SECONDARY=$(lookup_color secondary "$BASENAME")
: "${PRIMARY:=$(lookup_color primary _default)}"
: "${SECONDARY:=$(lookup_color secondary _default)}"

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
