from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
STYLES_DIR = OUTPUTS / "library" / "styles"
PROFILES_DIR = STYLES_DIR / "profiles"
PREVIEWS_DIR = STYLES_DIR / "previews" / "generated"


def _ensure_dirs() -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def _draw_cloud(draw: ImageDraw.ImageDraw, kind: str, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    if kind == "speech_round":
        draw.ellipse((x1, y1, x2, y2), fill=(245, 247, 255), outline=(32, 36, 64), width=4)
        draw.ellipse((x2 - 40, y2 - 20, x2 + 20, y2 + 36), fill=(245, 247, 255), outline=(32, 36, 64), width=3)
    elif kind == "thought":
        draw.ellipse((x1, y1, x2, y2), fill=(250, 252, 255), outline=(36, 44, 78), width=4)
        draw.ellipse((x2 - 20, y2 + 8, x2 + 28, y2 + 46), fill=(250, 252, 255), outline=(36, 44, 78), width=3)
        draw.ellipse((x2 + 28, y2 + 36, x2 + 58, y2 + 62), fill=(250, 252, 255), outline=(36, 44, 78), width=2)
    elif kind == "shout":
        pts = [
            (x1 + 40, y1), (x1 + 90, y1 + 40), (x1 + 150, y1 + 14), (x1 + 210, y1 + 48),
            (x1 + 280, y1 + 10), (x1 + 338, y1 + 46), (x2, y1 + 30), (x2 - 34, y1 + 94),
            (x2 + 24, y1 + 146), (x2 - 42, y2 - 12), (x2 - 6, y2 + 52), (x2 - 102, y2),
            (x2 - 150, y2 + 48), (x2 - 220, y2 - 2), (x2 - 290, y2 + 32), (x1 + 120, y2 - 10),
            (x1 + 76, y2 + 40), (x1 + 66, y2 - 18), (x1, y2 - 26), (x1 + 24, y1 + 146),
            (x1 - 34, y1 + 102), (x1 + 20, y1 + 84),
        ]
        draw.polygon(pts, fill=(255, 248, 235), outline=(46, 32, 28), width=4)
    elif kind == "rectangle":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=(247, 250, 255), outline=(34, 40, 70), width=4)
        draw.polygon([(x2 - 120, y2), (x2 - 60, y2), (x2 - 92, y2 + 46)], fill=(247, 250, 255), outline=(34, 40, 70))
    else:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=22, fill=(245, 249, 255), outline=(45, 58, 92), width=4)


def _render_sample(file_path: Path, cloud_kind: str, font_name: str, font_path: str, text_style: dict[str, Any], sample_text: str) -> None:
    image = Image.new("RGB", (1280, 720), color=(16, 20, 44))
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 1240, 680), fill=(27, 35, 67), outline=(76, 96, 158), width=3)
    _draw_cloud(draw, cloud_kind, (180, 180, 1060, 520))

    fill = tuple(text_style.get("fill", [242, 246, 255]))
    stroke_fill = tuple(text_style.get("stroke_fill", [40, 52, 94]))
    stroke_width = int(text_style.get("stroke_width", 2))
    shadow = tuple(text_style.get("shadow", [0, 0, 0, 80]))

    font_main = _font(font_path, text_style.get("font_size", 56))
    label_font = _font(font_path, 28)

    # soft shadow
    draw.text((276 + 4, 294 + 4), sample_text, font=font_main, fill=(shadow[0], shadow[1], shadow[2]))
    draw.text((276, 294), sample_text, font=font_main, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)

    draw.text((76, 78), f"{font_name} + {cloud_kind}", font=label_font, fill=(129, 236, 255))
    draw.text((76, 114), text_style.get("label", "style"), font=label_font, fill=(184, 198, 240))

    image.save(file_path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate cloud+text style sample assets")
    parser.add_argument("--limit", type=int, default=12, help="Max number of style combinations")
    args = parser.parse_args()

    _ensure_dirs()

    fonts = [
        ("font-dejavu-sans", "DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("font-dejavu-serif", "DejaVu Serif", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        ("font-dejavu-mono", "DejaVu Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ]
    cloud_kinds = ["speech_round", "thought", "shout", "rectangle", "whisper"]
    text_styles = [
        {"id": "neon-pop", "label": "Neon Pop", "fill": [255, 234, 120], "stroke_fill": [214, 68, 170], "stroke_width": 3, "font_size": 56},
        {"id": "clean-editorial", "label": "Clean Editorial", "fill": [240, 246, 255], "stroke_fill": [52, 66, 111], "stroke_width": 2, "font_size": 52},
        {"id": "comic-bold", "label": "Comic Bold", "fill": [255, 244, 230], "stroke_fill": [26, 26, 38], "stroke_width": 4, "font_size": 60},
    ]

    sample_text = "The city whispered: run now."
    generated = 0

    for font_id, font_name, font_path in fonts:
        for cloud_kind in cloud_kinds:
            for text_style in text_styles:
                if generated >= args.limit:
                    break

                style_id = f"{font_id}-{cloud_kind}-{text_style['id']}"
                image_name = f"{style_id}.png"
                image_path = PREVIEWS_DIR / image_name

                _render_sample(image_path, cloud_kind, font_name, font_path, text_style, sample_text)

                profile_payload = {
                    "id": style_id,
                    "name": f"{font_name} {cloud_kind.replace('_', ' ').title()} {text_style['label']}",
                    "category": "subtitle",
                    "version": "v1",
                    "tags": ["generated", "cloud-text", cloud_kind, text_style["id"]],
                    "status": "active",
                    "preview_assets": {
                        "thumbnail": f"library/styles/previews/generated/{image_name}",
                        "sample_text": sample_text,
                    },
                    "config_json": {
                        "font_family": font_name,
                        "font_file": font_path,
                        "cloud_kind": cloud_kind,
                        "text_style": text_style["id"],
                        "stroke_width": text_style["stroke_width"],
                        "font_size": text_style["font_size"],
                    },
                }
                _write_json(PROFILES_DIR / f"{style_id}.json", profile_payload)

                generated += 1
            if generated >= args.limit:
                break
        if generated >= args.limit:
            break

    print(f"Generated {generated} cloud+text style samples into {PREVIEWS_DIR}")


if __name__ == "__main__":
    main()
