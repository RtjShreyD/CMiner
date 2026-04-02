from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import base64
from io import BytesIO
import re
import shutil
from datetime import datetime
import random

from PIL import Image, ImageDraw, ImageFont

from api.services.registry_store import STYLES_DIR

OUTPUTS_DIR = Path("outputs")
PREVIEW_DIR = OUTPUTS_DIR / "overlay_samples"
ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ResolutionSpec:
    key: str
    label: str
    width: int
    height: int


RESOLUTION_SPECS: list[ResolutionSpec] = [
    ResolutionSpec("youtube_shorts", "YouTube Shorts", 1080, 1920),
    ResolutionSpec("youtube_video", "YouTube Video", 1920, 1080),
    ResolutionSpec("insta_reels", "Insta Reels", 1080, 1920),
    ResolutionSpec("insta_posts", "Insta Posts", 1080, 1080),
]

RESOLUTION_MAP = {r.key: r for r in RESOLUTION_SPECS}

# Curated backend-owned font catalog inspired by the shadcn ecosystem naming.
FONT_LIBRARY: list[dict[str, Any]] = [
    {
        "id": "font-geist-sans",
        "name": "Geist Sans",
        "css_family": "'Geist', 'Inter', 'Segoe UI', sans-serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    },
    {
        "id": "font-geist-mono",
        "name": "Geist Mono",
        "css_family": "'Geist Mono', 'JetBrains Mono', 'Fira Code', monospace",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    },
    {
        "id": "font-league-spartan",
        "name": "League Spartan",
        "css_family": "'League Spartan', 'Montserrat', sans-serif",
        "font_path": "/usr/share/fonts/opentype/league-spartan/LeagueSpartan-Bold.otf",
    },
    {
        "id": "font-ubuntu-bold",
        "name": "Ubuntu Bold",
        "css_family": "'Ubuntu', 'Inter', sans-serif",
        "font_path": "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    },
    {
        "id": "font-ubuntu-mono",
        "name": "Ubuntu Mono",
        "css_family": "'Ubuntu Mono', 'JetBrains Mono', monospace",
        "font_path": "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    },
    {
        "id": "font-dejavu-bold",
        "name": "DejaVu Sans Bold",
        "css_family": "'DejaVu Sans', 'Arial', sans-serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    },
    {
        "id": "font-dejavu-condensed",
        "name": "DejaVu Sans Condensed",
        "css_family": "'DejaVu Sans Condensed', 'Arial Narrow', sans-serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    },
    {
        "id": "font-dejavu-serif-bold",
        "name": "DejaVu Serif Bold",
        "css_family": "'DejaVu Serif', 'Times New Roman', serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    },
    {
        "id": "font-liberation-sans",
        "name": "Liberation Sans",
        "css_family": "'Liberation Sans', 'Arial', sans-serif",
        "font_path": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    },
    {
        "id": "font-liberation-serif",
        "name": "Liberation Serif",
        "css_family": "'Liberation Serif', 'Times New Roman', serif",
        "font_path": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    },
    {
        "id": "font-nimbus-sans",
        "name": "Nimbus Sans",
        "css_family": "'Nimbus Sans', 'Helvetica Neue', sans-serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
    },
    {
        "id": "font-nimbus-sans-bold",
        "name": "Nimbus Sans Bold",
        "css_family": "'Nimbus Sans', 'Helvetica Neue', sans-serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
    },
    {
        "id": "font-nimbus-roman",
        "name": "Nimbus Roman",
        "css_family": "'Nimbus Roman', 'Times New Roman', serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/NimbusRoman-Regular.otf",
    },
    {
        "id": "font-urw-gothic",
        "name": "URW Gothic",
        "css_family": "'URW Gothic', 'Arial', sans-serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/URWGothic-Demi.otf",
    },
    {
        "id": "font-bookman",
        "name": "Bookman",
        "css_family": "'Bookman', 'Georgia', serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/URWBookman-Demi.otf",
    },
    {
        "id": "font-p052",
        "name": "P052 Roman",
        "css_family": "'P052', 'Palatino', serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/P052-Roman.otf",
    },
    {
        "id": "font-c059",
        "name": "C059 Roman",
        "css_family": "'C059', 'Century Schoolbook', serif",
        "font_path": "/usr/share/fonts/opentype/urw-base35/C059-Roman.otf",
    },
    {
        "id": "font-nimbus-mono",
        "name": "Nimbus Mono",
        "css_family": "'Nimbus Mono', 'Courier New', monospace",
        "font_path": "/usr/share/fonts/opentype/urw-base35/NimbusMonoPS-Regular.otf",
    },
    {
        "id": "font-manrope",
        "name": "Manrope",
        "css_family": "'Manrope', 'Inter', sans-serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    },
    {
        "id": "font-instrument-serif",
        "name": "Instrument Serif",
        "css_family": "'Instrument Serif', 'Georgia', serif",
        "font_path": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    },
]

SUBTITLE_STYLES: list[dict[str, Any]] = [
    {
        "id": "sub-clean-bottom",
        "name": "Clean Bottom",
        "position": "bottom",
        "fill": [244, 247, 255],
        "stroke": [20, 26, 46],
        "stroke_width": 3,
        "band_fill": [0, 0, 0, 140],
    },
    {
        "id": "sub-neon-pop",
        "name": "Neon Pop",
        "position": "bottom",
        "fill": [255, 236, 150],
        "stroke": [176, 58, 138],
        "stroke_width": 5,
        "band_fill": [18, 6, 34, 168],
    },
    {
        "id": "sub-top-ribbon",
        "name": "Top Ribbon",
        "position": "top",
        "fill": [245, 250, 255],
        "stroke": [22, 28, 40],
        "stroke_width": 2,
        "band_fill": [14, 22, 38, 168],
    },
    {
        "id": "sub-noir-cinema",
        "name": "Noir Cinema",
        "position": "bottom",
        "fill": [238, 238, 230],
        "stroke": [10, 10, 10],
        "stroke_width": 2,
        "band_fill": [6, 6, 8, 188],
    },
    {
        "id": "sub-anime-scream",
        "name": "Anime Scream",
        "position": "top",
        "fill": [255, 247, 232],
        "stroke": [168, 38, 38],
        "stroke_width": 6,
        "band_fill": [34, 8, 8, 180],
    },
]

CLOUD_STYLES: list[dict[str, Any]] = [
    {"id": "cloud-none", "name": "None (No Cloud)", "kind": "none"},
    {"id": "cloud-soft-round", "name": "Soft Round", "kind": "speech_round"},
    {"id": "cloud-thought-dots", "name": "Thought Dots", "kind": "thought"},
    {"id": "cloud-shout-burst", "name": "Shout Burst", "kind": "shout"},
    {"id": "cloud-rectangle-box", "name": "Rectangle Box", "kind": "rectangle"},
    {"id": "cloud-whisper-pill", "name": "Whisper Pill", "kind": "whisper"},
]


def _initials(text: str) -> str:
    letters = re.findall(r"[A-Za-z0-9]+", text)
    if not letters:
        return "item"
    return "".join(part[0].lower() for part in letters[:6])


def _composite_key(session_id: str, file_name: str) -> str:
    stem = Path(file_name).stem
    return f"{session_id}-{_initials(stem)}"


def _decode_composite_key(value: str) -> tuple[str, str] | None:
    if not value or "-" not in value:
        return None
    session_id, initials = value.split("-", 1)
    if not session_id or not initials:
        return None
    return session_id, initials


def _load_font(font_id: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    selected = next((f for f in FONT_LIBRARY if f["id"] == font_id), FONT_LIBRARY[0])
    try:
        return ImageFont.truetype(selected["font_path"], size=size)
    except Exception:
        return ImageFont.load_default()


def cleanup_overlay_samples_dir() -> None:
    if PREVIEW_DIR.exists() and PREVIEW_DIR.is_dir():
        shutil.rmtree(PREVIEW_DIR, ignore_errors=True)


def _discover_scene_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for scene_path in OUTPUTS_DIR.glob("*/*/scenes/*.png"):
        parts = scene_path.parts
        if len(parts) < 4:
            continue
        session_id = parts[1]
        key = _composite_key(session_id, scene_path.name)
        items.append(
            {
                "id": key,
                "name": f"{session_id} / {scene_path.name}",
                "path": scene_path.as_posix(),
            }
        )
    return sorted(items, key=lambda x: x["name"])


def _discover_character_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    # Session character images
    for char_path in OUTPUTS_DIR.glob("*/*/chars/*"):
        if char_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        parts = char_path.parts
        if len(parts) < 4:
            continue
        session_id = parts[1]
        key = _composite_key(session_id, char_path.name)
        items.append(
            {
                "id": key,
                "name": f"{session_id} / {char_path.name}",
                "path": char_path.as_posix(),
            }
        )

    dedup: dict[str, dict[str, str]] = {}
    for item in items:
        dedup[item["id"]] = item
    return sorted(dedup.values(), key=lambda x: x["name"])


def purge_library_characters() -> None:
    library_char_dir = ROOT_DIR / "library" / "characters"
    if library_char_dir.exists():
        shutil.rmtree(library_char_dir, ignore_errors=True)


def _new_session_id() -> str:
    return f"{random.randint(1_000_000, 9_999_999)}"


def _resolve_session_id_for_save(scene_id: str | None, session_path: str | None) -> str:
    if scene_id:
        decoded = _decode_composite_key(scene_id)
        if decoded and decoded[0] and decoded[0] != "library":
            return decoded[0]

    if session_path:
        parts = [p for p in session_path.split("/") if p]
        if parts:
            return parts[0]

    return _new_session_id()


def list_buildpack_options() -> dict[str, Any]:
    cleanup_overlay_samples_dir()
    return {
        "resolutions": [
            {"key": r.key, "label": r.label, "width": r.width, "height": r.height}
            for r in RESOLUTION_SPECS
        ],
        "characters": _discover_character_items(),
        "scenes": _discover_scene_items(),
        "fontstyles": [
            {"id": f["id"], "name": f["name"], "css_family": f["css_family"]}
            for f in FONT_LIBRARY
        ],
        "subtitle_styles": [{"id": s["id"], "name": s["name"]} for s in SUBTITLE_STYLES],
        "cloud_styles": [{"id": s["id"], "name": s["name"]} for s in CLOUD_STYLES],
    }


def _resolve_asset_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate

    if candidate.exists() and candidate.is_file():
        return candidate

    # fallback for outputs-relative strings
    fallback = ROOT_DIR / OUTPUTS_DIR / value
    if fallback.exists() and fallback.is_file():
        return fallback

    return None


def _asset_from_composite(items: list[dict[str, str]], composite_id: str | None) -> Path | None:
    if not composite_id:
        return None

    # Try direct dictionary lookup first.
    for item in items:
        if item.get("id") == composite_id:
            return _resolve_asset_path(item.get("path"))

    # Fallback decoding by session-id + initials.
    decoded = _decode_composite_key(composite_id)
    if not decoded:
        return None
    session_id, initials = decoded

    for item in items:
        item_id = item.get("id", "")
        if item_id.startswith(f"{session_id}-") and item_id.endswith(initials):
            return _resolve_asset_path(item.get("path"))

    return None


def _draw_cloud(draw: ImageDraw.ImageDraw, kind: str, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    if kind == "thought":
        draw.ellipse((x1, y1, x2, y2), fill=(250, 252, 255, 238), outline=(34, 42, 74, 255), width=4)
        draw.ellipse((x2 - 22, y2 + 8, x2 + 24, y2 + 44), fill=(250, 252, 255, 238), outline=(34, 42, 74, 255), width=3)
        draw.ellipse((x2 + 20, y2 + 40, x2 + 56, y2 + 68), fill=(250, 252, 255, 238), outline=(34, 42, 74, 255), width=2)
        return
    if kind == "shout":
        pts = [
            (x1 + 24, y1 + 10), (x1 + 102, y1 + 46), (x1 + 166, y1 + 6), (x1 + 254, y1 + 52),
            (x2 - 36, y1 + 18), (x2 - 14, y1 + 104), (x2 + 30, y1 + 148), (x2 - 52, y2 - 14),
            (x2 - 16, y2 + 38), (x2 - 128, y2 - 2), (x2 - 178, y2 + 38), (x2 - 240, y2 - 6),
            (x1 + 110, y2 + 26), (x1 + 72, y2 - 12), (x1 + 10, y2 + 8), (x1 + 40, y1 + 122),
        ]
        draw.polygon(pts, fill=(255, 249, 238, 242), outline=(48, 34, 30, 255), width=4)
        return

    if kind == "rectangle":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=20, fill=(246, 250, 255, 240), outline=(36, 44, 78, 255), width=4)
        draw.polygon([(x2 - 100, y2), (x2 - 46, y2), (x2 - 78, y2 + 36)], fill=(246, 250, 255, 240), outline=(36, 44, 78, 255))
        return

    if kind == "whisper":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=56, fill=(232, 244, 255, 222), outline=(72, 102, 138, 255), width=3)
        draw.ellipse((x2 - 30, y2 - 4, x2 + 10, y2 + 30), fill=(232, 244, 255, 222), outline=(72, 102, 138, 255), width=2)
        return

    draw.ellipse((x1, y1, x2, y2), fill=(245, 249, 255, 240), outline=(30, 40, 74, 255), width=4)
    draw.ellipse((x2 - 38, y2 - 14, x2 + 16, y2 + 34), fill=(245, 249, 255, 240), outline=(30, 40, 74, 255), width=3)


def _resolve_subtitle_style(style_id: str) -> dict[str, Any]:
    match = next((s for s in SUBTITLE_STYLES if s["id"] == style_id), None)
    return match or SUBTITLE_STYLES[0]


def _resolve_cloud_kind(cloud_style_id: str) -> str:
    from_defs = next((c["kind"] for c in CLOUD_STYLES if c["id"] == cloud_style_id), None)
    if from_defs:
        return from_defs
    if "thought" in cloud_style_id:
        return "thought"
    if "shout" in cloud_style_id:
        return "shout"
    if "rectangle" in cloud_style_id:
        return "rectangle"
    if "whisper" in cloud_style_id:
        return "whisper"
    if "none" in cloud_style_id:
        return "none"
    return "speech_round"


def _fit_image(base: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = base.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = base.resize((int(src_w * scale), int(src_h * scale)))
    left = max((resized.width - target_w) // 2, 0)
    top = max((resized.height - target_h) // 2, 0)
    return resized.crop((left, top, left + target_w, top + target_h))


def generate_overlay_preview(
    resolution_key: str,
    character_id: str | None,
    scene_id: str | None,
    font_style_id: str,
    subtitle_style_id: str,
    cloud_style_id: str,
    sample_text: str,
    sample_size: int,
    subtitle_x: float | None = None,
    subtitle_y: float | None = None,
    subtitle_scale: float = 1.0,
    cloud_x: float | None = None,
    cloud_y: float | None = None,
    cloud_w: float | None = None,
    cloud_h: float | None = None,
) -> dict[str, Any]:
    spec = RESOLUTION_MAP.get(resolution_key, RESOLUTION_MAP["youtube_shorts"])
    options = list_buildpack_options()

    scene_src = _asset_from_composite(options["scenes"], scene_id)
    if scene_src:
        base = Image.open(scene_src).convert("RGB")
        canvas = _fit_image(base, spec.width, spec.height).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (spec.width, spec.height), (19, 26, 52, 255))
        gradient = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gradient)
        gd.rectangle((0, 0, spec.width, spec.height), fill=(40, 52, 96, 110))
        canvas = Image.alpha_composite(canvas, gradient)

    # Place character cutout if provided.
    char_src = _asset_from_composite(options["characters"], character_id)
    if char_src:
        try:
            char_img = Image.open(char_src).convert("RGBA")
            target_h = int(spec.height * 0.56)
            ratio = target_h / max(char_img.height, 1)
            target_w = max(1, int(char_img.width * ratio))
            char_img = char_img.resize((target_w, target_h))
            paste_x = int(spec.width * 0.06)
            paste_y = spec.height - target_h - int(spec.height * 0.06)
            canvas.alpha_composite(char_img, (paste_x, paste_y))
        except Exception:
            pass

    overlay = Image.new("RGBA", (spec.width, spec.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    sub_style = _resolve_subtitle_style(subtitle_style_id)
    cloud_kind = _resolve_cloud_kind(cloud_style_id)

    # Subtitle band
    band_h = int(spec.height * 0.16)
    if sub_style["position"] == "top":
        band_y1, band_y2 = 0, band_h
    else:
        band_y1, band_y2 = spec.height - band_h, spec.height
    draw.rectangle((0, band_y1, spec.width, band_y2), fill=tuple(sub_style.get("band_fill", [0, 0, 0, 140])))

    # Cloud bubble (optional)
    cloud_w_px = int(spec.width * max(0.12, min(cloud_w if cloud_w is not None else 0.55, 0.9)))
    cloud_h_px = int(spec.height * max(0.08, min(cloud_h if cloud_h is not None else 0.18, 0.75)))
    cloud_x1 = int(spec.width * max(0.0, min(cloud_x if cloud_x is not None else 0.38, 0.95)))
    cloud_y1 = int(spec.height * max(0.0, min(cloud_y if cloud_y is not None else 0.18, 0.95)))
    has_cloud = cloud_kind != "none"
    if has_cloud:
        _draw_cloud(draw, cloud_kind, (cloud_x1, cloud_y1, cloud_x1 + cloud_w_px, cloud_y1 + cloud_h_px))

    # Text layers
    scaled_size = int(sample_size * max(0.5, min(subtitle_scale, 2.2)))
    font_size = max(16, min(scaled_size, 140))
    font = _load_font(font_style_id, font_size)
    sub_font = _load_font(font_style_id, int(font_size * 0.88))

    text = (sample_text or "Overlay preview sample text").strip()[:180]

    subtitle_x_px = int(spec.width * max(0.0, min(subtitle_x if subtitle_x is not None else 0.06, 0.95)))
    subtitle_y_default = band_y1 + int((band_h - font_size) * 0.35)
    subtitle_y_px = int(spec.height * max(0.0, min(subtitle_y if subtitle_y is not None else subtitle_y_default / max(spec.height, 1), 0.95)))
    draw.text(
        (subtitle_x_px, subtitle_y_px),
        text,
        font=sub_font,
        fill=tuple(sub_style["fill"]),
        stroke_width=int(sub_style["stroke_width"]),
        stroke_fill=tuple(sub_style["stroke"]),
    )

    if has_cloud:
        bubble_text = text[:90]
        draw.text(
            (cloud_x1 + int(cloud_w_px * 0.08), cloud_y1 + int(cloud_h_px * 0.32)),
            bubble_text,
            font=font,
            fill=(26, 36, 62, 255),
        )

    composed = Image.alpha_composite(canvas, overlay).convert("RGB")

    buffer = BytesIO()
    composed.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    meta = {
        "resolution": {"key": spec.key, "label": spec.label, "width": spec.width, "height": spec.height},
        "character_id": character_id,
        "scene_id": scene_id,
        "font_style_id": font_style_id,
        "subtitle_style_id": subtitle_style_id,
        "cloud_style_id": cloud_style_id,
        "sample_text": text,
        "layout": {
            "subtitle_x": subtitle_x_px / max(spec.width, 1),
            "subtitle_y": subtitle_y_px / max(spec.height, 1),
            "subtitle_scale": max(0.5, min(subtitle_scale, 2.2)),
            "cloud_x": cloud_x1 / max(spec.width, 1),
            "cloud_y": cloud_y1 / max(spec.height, 1),
            "cloud_w": cloud_w_px / max(spec.width, 1),
            "cloud_h": cloud_h_px / max(spec.height, 1),
        },
    }
    return {
        "preview_path": None,
        "preview_mime": "image/png",
        "preview_blob": image_b64,
        "metadata": meta,
    }


def save_overlay_preview_to_session(
    *,
    session_path: str | None,
    scene_id: str | None,
    resolution_key: str,
    character_id: str | None,
    font_style_id: str,
    subtitle_style_id: str,
    cloud_style_id: str,
    sample_text: str,
    sample_size: int,
    subtitle_x: float | None,
    subtitle_y: float | None,
    subtitle_scale: float,
    cloud_x: float | None,
    cloud_y: float | None,
    cloud_w: float | None,
    cloud_h: float | None,
) -> dict[str, Any]:
    session_id = _resolve_session_id_for_save(scene_id=scene_id, session_path=session_path)
    target_dir = OUTPUTS_DIR / session_id / "autoAnimator" / "buildpacks"
    target_dir.mkdir(parents=True, exist_ok=True)

    preview = generate_overlay_preview(
        resolution_key=resolution_key,
        character_id=character_id,
        scene_id=scene_id,
        font_style_id=font_style_id,
        subtitle_style_id=subtitle_style_id,
        cloud_style_id=cloud_style_id,
        sample_text=sample_text,
        sample_size=sample_size,
        subtitle_x=subtitle_x,
        subtitle_y=subtitle_y,
        subtitle_scale=subtitle_scale,
        cloud_x=cloud_x,
        cloud_y=cloud_y,
        cloud_w=cloud_w,
        cloud_h=cloud_h,
    )

    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    image_name = f"buildpack_overlay_{stamp}.png"
    target_path = target_dir / image_name
    target_path.write_bytes(base64.b64decode(preview["preview_blob"]))

    return {
        "session_id": session_id,
        "saved_path": str(target_path.relative_to(OUTPUTS_DIR)),
        "metadata": preview.get("metadata", {}),
    }
