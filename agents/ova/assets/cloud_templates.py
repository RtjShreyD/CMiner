"""Static speech bubble template renderer for OVA agent.

Generates RGBA PIL images for different cloud/bubble styles.
Each template has a transparent background, white fill, and dark outline.
Scaled to the requested (width, height) bounding box.

Styles:
  speech  – classic oval with down-left pointer tail (default)
  shout   – spiky starburst shout bubble
  thought – lumpy thought cloud with dot trail
  caption – rounded-rect narration caption box
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

STYLES = ("speech", "shout", "thought", "caption")


def render_template(style: str, width: int, height: int) -> Image.Image:
    """Return an RGBA PIL image of the requested cloud template at (width, height)."""
    width = max(60, width)
    height = max(40, height)
    if style == "shout":
        return _render_shout(width, height)
    if style == "thought":
        return _render_thought(width, height)
    if style == "caption":
        return _render_caption(width, height)
    return _render_speech(width, height)


# ── Individual renderers ──────────────────────────────────────────────────────

def _render_speech(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tw = max(2, w // 55)
    margin = max(tw + 1, 8)
    tail_h = max(8, h // 8)

    # Body ellipse
    body = [margin, margin, w - margin, h - margin - tail_h]
    draw.ellipse(body, fill=(255, 255, 255, 245), outline=(18, 18, 18, 255), width=tw)

    # Tail polygon pointing lower-left
    mid_x = (body[0] + body[2]) // 2
    bot_y = body[3]
    half = max(7, w // 18)
    tip_x = max(tw + margin, margin + w // 8)
    tip_y = h - tw
    tail_pts = [(mid_x - half, bot_y), (tip_x, tip_y), (mid_x + half, bot_y)]
    draw.polygon(tail_pts, fill=(255, 255, 255, 245))
    draw.line([tail_pts[0], tail_pts[1]], fill=(18, 18, 18, 255), width=tw)
    draw.line([tail_pts[1], tail_pts[2]], fill=(18, 18, 18, 255), width=tw)
    return img


def _render_shout(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tw = max(2, w // 55)
    cx, cy = w / 2, h / 2
    rx, ry = cx - tw - 2, cy - tw - 2
    n_spikes = 16
    pts: list[tuple[float, float]] = []
    for i in range(n_spikes * 2):
        angle = math.pi * 2 * i / (n_spikes * 2) - math.pi / 2
        r = (rx if i % 2 == 0 else rx * 0.68, ry if i % 2 == 0 else ry * 0.68)
        pts.append((cx + r[0] * math.cos(angle), cy + r[1] * math.sin(angle)))
    draw.polygon(pts, fill=(255, 252, 200, 248), outline=(18, 18, 18, 255), width=tw)
    return img


def _render_thought(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tw = max(2, w // 55)
    margin = max(tw + 1, 6)
    dot_zone = max(10, h // 7)
    body_h = h - margin - dot_zone

    # Lumpy body: big centre ellipse + surrounding lobes
    bx1, by1, bx2, by2 = margin, margin, w - margin, body_h
    cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
    rx, ry = (bx2 - bx1) / 2, (by2 - by1) / 2
    lobe_r = max(6, int(min(rx, ry) * 0.3))

    # Draw fill lobes first
    draw.ellipse([bx1, by1, bx2, by2], fill=(255, 255, 255, 240))
    for deg in range(0, 360, 32):
        a = math.radians(deg)
        lx = cx + (rx - lobe_r * 0.4) * math.cos(a)
        ly = cy + (ry - lobe_r * 0.4) * math.sin(a)
        draw.ellipse([lx - lobe_r, ly - lobe_r, lx + lobe_r, ly + lobe_r],
                     fill=(255, 255, 255, 240))

    # Outline
    draw.ellipse([bx1, by1, bx2, by2], outline=(18, 18, 18, 255), width=tw)
    for deg in range(0, 360, 32):
        a = math.radians(deg)
        lx = cx + (rx - lobe_r * 0.4) * math.cos(a)
        ly = cy + (ry - lobe_r * 0.4) * math.sin(a)
        draw.ellipse([lx - lobe_r, ly - lobe_r, lx + lobe_r, ly + lobe_r],
                     outline=(18, 18, 18, 255), width=tw)

    # Dot trail (lower-left)
    dx, dy = margin * 3, body_h + margin // 2
    for r in [max(4, tw * 3), max(3, tw * 2), max(2, tw)]:
        draw.ellipse([dx - r, dy - r, dx + r, dy + r],
                     fill=(255, 255, 255, 230), outline=(18, 18, 18, 255), width=max(1, tw - 1))
        dx += r * 3
        dy += r
    return img


def _render_caption(w: int, h: int) -> Image.Image:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tw = max(2, w // 60)
    margin = max(tw + 1, 4)
    radius = max(6, min(w, h) // 10)
    draw.rounded_rectangle(
        [margin, margin, w - margin, h - margin],
        radius=radius,
        fill=(255, 248, 210, 238),
        outline=(38, 20, 10, 255),
        width=tw,
    )
    return img
