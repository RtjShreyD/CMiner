from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw


def _slug(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-") or "character"


def _default_names(count: int) -> list[str]:
    seeds = [
        "Arin Vale",
        "Kaelen Thorne",
        "Mira Sol",
        "Ivo Rook",
        "Nyra Flux",
        "Talan Grey",
        "Sera Kline",
    ]
    random.shuffle(seeds)
    names = seeds[:count]
    while len(names) < count:
        names.append(f"Character {len(names) + 1}")
    return names


def _create_character_art(path: Path, display_name: str, style: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (512, 512), color=(22, 30, 58))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 482, 482), outline=(122, 154, 255), width=3)
    draw.ellipse((170, 90, 342, 262), fill=(84, 112, 186), outline=(186, 208, 255), width=3)
    draw.rectangle((200, 252, 312, 400), fill=(56, 74, 136), outline=(150, 182, 250), width=3)
    draw.text((56, 430), display_name[:28], fill=(220, 228, 255))
    draw.text((56, 458), style[:28], fill=(156, 175, 220))
    image.save(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate reusable character packs")
    parser.add_argument("--prompt", default="A cinematic manga ensemble cast", help="Character generation brief")
    parser.add_argument("--count", type=int, default=3, help="Number of characters")
    parser.add_argument("--style", default="cinematic_anime", help="Style profile id or style tag")
    parser.add_argument("--pack-id", help="Optional fixed pack id")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    workspace = Path(args.workspace).resolve()
    library_root = workspace / "library"
    library_packs_dir = library_root / "characters" / "packs"
    library_packs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    pack_id = args.pack_id or f"pack-{_slug(args.style)}-{timestamp}"
    previews_dir = library_root / "characters" / "previews" / pack_id
    previews_dir.mkdir(parents=True, exist_ok=True)

    names = _default_names(max(1, args.count))
    characters = []
    for idx, name in enumerate(names, start=1):
        char_id = _slug(name)
        preview_path = previews_dir / f"{char_id}.png"
        _create_character_art(preview_path, name, args.style)
        preview_rel = f"library/{preview_path.relative_to(library_root).as_posix()}"
        characters.append(
            {
                "character_id": char_id,
                "display_name": name,
                "archetype": "hero" if idx == 1 else "support",
                "visual_prompt": f"{name}, styled as {args.style}, generated from brief: {args.prompt}",
                "tags": [args.style, "charGen"],
                "anchor_images": [preview_rel],
                "metadata": {
                    "style": args.style,
                    "prompt": args.prompt,
                    "quality_score": 0.5,
                },
            }
        )

    record = {
        "id": pack_id,
        "name": f"{args.style} cast",
        "style_profile_id": args.style,
        "source_agent": "charGen",
        "tags": [args.style, "generated"],
        "preview_assets": {
            "thumbnail": characters[0]["anchor_images"][0] if characters else None,
        },
        "characters": characters,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    out_path = library_packs_dir / f"{pack_id}.json"
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"charGen pack created: {pack_id}")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
