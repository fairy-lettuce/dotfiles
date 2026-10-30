#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Generate a rounded-corner 9-patch panel.png for an fcitx5 classicui theme.

fcitx5's BackgroundImageConfig has no numeric corner-radius option; a solid
background is drawn as a sharp cairo_rectangle. Rounded corners require
supplying a nine-patch Image instead, sliced by the Margin config. This
reads the Color/BorderColor already written into theme.conf (by matugen)
and bakes them into panel.png so the two always stay in sync.
"""

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RADIUS = 3
BORDER = 2
CAP = 8  # must match [.../Background/Margin] in theme.conf
SIZE = CAP * 2 + 4
SUPERSAMPLE = 4


def read_colors(theme_conf: Path) -> tuple[str, str]:
    text = theme_conf.read_text()
    section = text.split("[InputPanel/Background]", 1)[1].split("\n[", 1)[0]
    fill = re.search(r"^Color=(#[0-9a-fA-F]{6,8})", section, re.M).group(1)
    border = re.search(r"^BorderColor=(#[0-9a-fA-F]{6,8})", section, re.M).group(1)
    return fill, border


def draw_panel(fill: str, border: str) -> Image.Image:
    # Two nested filled shapes rather than fill+stroke: a centered stroke's
    # inner/outer radii don't line up with the outer fill's radius, which
    # left a sliver of the fill color visible through the corner arc.
    # Filling border-then-inset-fill instead makes the ring exactly
    # BORDER px wide everywhere, corners included.
    big = SIZE * SUPERSAMPLE
    r = RADIUS * SUPERSAMPLE
    b = BORDER * SUPERSAMPLE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=r, fill=border)
    draw.rounded_rectangle(
        [b, b, big - 1 - b, big - 1 - b], radius=max(r - b, 0), fill=fill
    )
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    theme_dir = Path(sys.argv[1]).expanduser()
    fill, border = read_colors(theme_dir / "theme.conf")
    draw_panel(fill, border).save(theme_dir / "panel.png")


if __name__ == "__main__":
    main()
