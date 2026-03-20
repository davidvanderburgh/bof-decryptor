#!/usr/bin/env python3
"""Generate DMG background image with drag-to-install arrow.

Creates a TIFF with transparency so the native Finder background
(dark or light mode) shows through, with only the arrow visible.
"""

from PIL import Image, ImageDraw
import sys

# Retina (2x) resolution for crisp rendering
WIDTH, HEIGHT = 1200, 800
ARROW_COLOR = (160, 160, 160, 200)

img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Arrow between app icon (x=300@2x) and Applications (x=900@2x), at y ~390@2x
arrow_y = 390
arrow_x_start = 460
arrow_x_end = 740
shaft_thickness = 6
head_size = 28

# Arrow shaft
draw.rectangle(
    [arrow_x_start, arrow_y - shaft_thickness // 2,
     arrow_x_end - head_size, arrow_y + shaft_thickness // 2],
    fill=ARROW_COLOR,
)

# Arrowhead (triangle)
draw.polygon(
    [
        (arrow_x_end, arrow_y),
        (arrow_x_end - head_size, arrow_y - head_size),
        (arrow_x_end - head_size, arrow_y + head_size),
    ],
    fill=ARROW_COLOR,
)

out = sys.argv[1] if len(sys.argv) > 1 else "installer/build/dmg_background.tiff"
img.save(out)
print(f"DMG background saved to {out}")
