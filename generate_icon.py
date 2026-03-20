"""Generate a barrel icon with BOF text for the BOF Asset Decryptor."""

from PIL import Image, ImageDraw, ImageFont
import math
import os


def draw_barrel(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    s = size
    pad = max(2, s * 0.06)

    # Barrel body colors
    wood_mid   = (180, 110, 45)
    wood_light = (210, 145, 70)
    wood_dark  = (130, 75, 25)
    hoop_color = (55, 38, 18)
    hoop_hi    = (90, 65, 35)

    # --- Body silhouette (rounded rectangle, slightly bulging sides) ---
    # We approximate the barrel bulge by drawing an ellipse for the body
    # plus a clipped rect, so it looks like a cylinder with round top/bottom.

    left   = pad
    right  = s - pad
    top    = pad * 1.2
    bottom = s - pad * 1.2
    cx     = s / 2
    cy     = s / 2
    w      = right - left
    h      = bottom - top

    # Barrel body — mid tone fill
    # Slightly barrel-shaped: draw a polygon with curved sides
    # Approximate with a series of points
    pts = []
    steps = 60
    # Left side (bulges left)
    bulge = w * 0.08
    for i in range(steps + 1):
        t = i / steps
        x = left - bulge * math.sin(t * math.pi)
        y = top + t * h
        pts.append((x, y))
    # Right side (bulges right)
    for i in range(steps + 1):
        t = 1 - i / steps
        x = right + bulge * math.sin(t * math.pi)
        y = top + t * h
        pts.append((x, y))

    d.polygon(pts, fill=wood_mid)

    # Vertical shading: lighter stripe down the centre, darker on edges
    # Draw gradient-like vertical bands using narrow rectangles
    bands = 18
    for i in range(bands):
        t = i / (bands - 1)            # 0 = left edge, 1 = right edge
        dist = abs(t - 0.5) * 2        # 0 at centre, 1 at edges
        # Blend wood_light (centre) -> wood_dark (edges)
        r = int(wood_light[0] * (1 - dist) + wood_dark[0] * dist)
        g = int(wood_light[1] * (1 - dist) + wood_dark[1] * dist)
        b = int(wood_light[2] * (1 - dist) + wood_dark[2] * dist)
        bx = left + t * w
        bw = w / bands + 1
        # Clip to barrel outline using a fresh mask each time is slow;
        # instead just draw and the polygon clips via alpha
        d.rectangle([bx, top, bx + bw, bottom], fill=(r, g, b))

    # Re-draw barrel outline to clean up edge bands
    d.polygon(pts, fill=None, outline=wood_dark)

    # Re-fill barrel shape cleanly over the bands (blend pass)
    # Use a soft inner ellipse to add centre highlight
    hi_w = w * 0.35
    hi_h = h * 0.55
    hi_x = cx - hi_w / 2
    hi_y = cy - hi_h / 2
    # Draw highlight as semi-transparent lighter overlay
    overlay = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse([hi_x, hi_y, hi_x + hi_w, hi_y + hi_h],
               fill=(255, 200, 120, 60))
    img = Image.alpha_composite(img, overlay)
    d = ImageDraw.Draw(img)

    # --- Top and bottom ellipse caps ---
    cap_h = max(4, h * 0.10)
    # Bottom cap (darker, shadow)
    d.ellipse([left, bottom - cap_h, right, bottom + cap_h],
              fill=wood_dark, outline=hoop_color)
    # Top cap (lighter)
    d.ellipse([left, top - cap_h, right, top + cap_h],
              fill=wood_light, outline=hoop_color)

    # --- Metal hoops ---
    hoop_thickness = max(2, int(s * 0.055))
    hoop_h         = max(3, int(s * 0.07))

    def draw_hoop(y_centre):
        # Flat band
        y0 = y_centre - hoop_h // 2
        y1 = y_centre + hoop_h // 2
        d.rectangle([left - 1, y0, right + 1, y1], fill=hoop_color)
        # Highlight on top edge
        d.rectangle([left - 1, y0, right + 1, y0 + max(1, hoop_thickness // 3)],
                    fill=hoop_hi)
        # Ellipse ends
        ew = max(4, w * 0.05)
        d.ellipse([left - ew, y0, left + ew, y1], fill=hoop_color)
        d.ellipse([right - ew, y0, right + ew, y1], fill=hoop_color)

    # Three hoops: top, middle, bottom
    draw_hoop(top + h * 0.17)
    draw_hoop(cy)
    draw_hoop(bottom - h * 0.17)

    # Outline the whole barrel silhouette
    d.polygon(pts, fill=None, outline=hoop_color)

    # --- BOF text ---
    font_size = max(6, int(s * 0.28))
    font = None
    # Try to load a bold font; fall back to default
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    text = "BOF"
    # Measure
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - tw / 2 - bbox[0]
    ty = cy - th / 2 - bbox[1] - max(1, s * 0.01)

    # Shadow
    shadow_off = max(1, int(s * 0.025))
    d.text((tx + shadow_off, ty + shadow_off), text, font=font,
           fill=(40, 20, 5, 200))
    # Main text — cream/ivory colour so it pops on the wood
    d.text((tx, ty), text, font=font, fill=(245, 230, 190, 255))
    # Subtle outline
    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
        d.text((tx + dx, ty + dy), text, font=font, fill=(80, 45, 10, 180))
    d.text((tx, ty), text, font=font, fill=(245, 230, 190, 255))

    return img


def make_ico(output_path):
    sizes = [256, 64, 48, 32, 16]
    images = [draw_barrel(s) for s in sizes]
    # Save as ICO — Pillow needs RGB+A or RGBA
    images[0].save(
        output_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Saved: {output_path}")
    # Also save PNG (used by macOS/Linux builds)
    png_path = output_path.replace(".ico", ".png")
    images[0].save(png_path)
    print(f"PNG: {png_path}")


if __name__ == "__main__":
    import os
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "bof_decryptor", "icon.ico")
    make_ico(out)
