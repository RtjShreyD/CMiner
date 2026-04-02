from __future__ import annotations

from datetime import datetime, timezone
import random
from typing import Any, Optional
from pathlib import Path
import copy

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from PIL import Image

from agents.narrativeManga.utils import get_model

from api.services.registry_store import (
    CHARACTERS_DIR,
    LIBRARY_DIR,
    character_pack_path,
    ensure_library_dirs,
    ensure_subdirs,
    read_json,
    write_json,
)

router = APIRouter()
OUTPUTS_DIR = Path("outputs")


class CharacterCreate(BaseModel):
    character_id: str
    display_name: str
    archetype: Optional[str] = None
    visual_prompt: str = ""
    tags: list[str] = Field(default_factory=list)
    anchor_images: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CharacterPackCreate(BaseModel):
    id: str
    name: str
    style_profile_id: Optional[str] = None
    source_agent: str = "charGen"
    tags: list[str] = Field(default_factory=list)
    preview_assets: dict[str, Any] = Field(default_factory=dict)
    characters: list[CharacterCreate] = Field(default_factory=list)


class CharacterGenerateRequest(BaseModel):
    prompt: str
    style: str = "cinematic anime"
    name: str = "Generated Character"
    model_preset: str = "gemini-2.5-flash-image"
    aspect_ratio: str = "1:1"
    save_as_pack: bool = False
    pack_id: Optional[str] = None


def _create_placeholder_image(path: Path, name: str, style: str) -> None:
    color = (random.randint(60, 200), random.randint(60, 200), random.randint(60, 200))
    image = Image.new("RGB", (1024, 1024), color=color)
    image.save(path)


def _safe_name(value: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in raw:
        raw = raw.replace("--", "-")
    return raw.strip("-") or "character"


def _is_valid_preview_image(rel_path: str) -> bool:
    try:
        trimmed = (rel_path or "").strip()
        if not trimmed:
            return False

        outputs_root = OUTPUTS_DIR.resolve()
        library_root = LIBRARY_DIR.resolve()

        if trimmed.startswith("library/"):
            rel = Path(trimmed[len("library/"):])
            img_path = (library_root / rel).resolve()
            allowed_root = library_root
        else:
            img_path = (outputs_root / trimmed).resolve()
            allowed_root = outputs_root

        if not img_path.exists() or not img_path.is_file() or not img_path.is_relative_to(allowed_root):
            return False
        if img_path.stat().st_size < 1024:
            return False

        with Image.open(img_path) as img:
            img = img.convert("RGB")
            extrema = img.getextrema()  # [(min,max), (min,max), (min,max)]
            # Treat near-solid images as blank placeholders.
            if all((channel_max - channel_min) < 8 for channel_min, channel_max in extrema):
                return False
        return True
    except Exception:
        return False


def _prepare_pack_preview_view(record: dict[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(record)
    valid_chars = []

    for character in view.get("characters", []):
        anchors = character.get("anchor_images") or []
        valid_anchor = next((anchor for anchor in anchors if _is_valid_preview_image(anchor)), None)
        character["has_preview"] = bool(valid_anchor)
        character["preview_path"] = valid_anchor
        if valid_anchor:
            character["anchor_images"] = [valid_anchor]
            valid_chars.append(character)

    view["characters"] = valid_chars
    view.setdefault("preview_assets", {})
    if valid_chars:
        view["preview_assets"]["thumbnail"] = valid_chars[0].get("preview_path")
    else:
        view["preview_assets"]["thumbnail"] = None
    return view


@router.get("/packs")
async def list_character_packs(tag: Optional[str] = None) -> list[dict[str, Any]]:
    ensure_library_dirs()
    ensure_subdirs()
    records = []
    seen_preview_keys: set[tuple[str, str]] = set()
    for pack_path in sorted((CHARACTERS_DIR / "packs").glob("*.json")):
        try:
            record = read_json(pack_path)
            prepared = _prepare_pack_preview_view(record)
            if prepared.get("characters"):
                thumb = (prepared.get("preview_assets") or {}).get("thumbnail") or ""
                dedupe_key = (str(prepared.get("name", "")).strip().lower(), thumb.strip().lower())
                if dedupe_key in seen_preview_keys:
                    continue
                seen_preview_keys.add(dedupe_key)
                records.append(prepared)
        except Exception:
            continue
    if tag:
        records = [r for r in records if tag.lower() in [str(t).lower() for t in r.get("tags", [])]]
    return records


@router.get("/packs/{pack_id}")
async def get_character_pack(pack_id: str) -> dict[str, Any]:
    ensure_library_dirs()
    ensure_subdirs()
    path = character_pack_path(pack_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Character pack not found")
    return _prepare_pack_preview_view(read_json(path))


@router.post("/packs")
async def create_character_pack(payload: CharacterPackCreate) -> dict[str, Any]:
    ensure_library_dirs()
    ensure_subdirs()
    path = character_pack_path(payload.id)
    if path.exists():
        raise HTTPException(status_code=409, detail="Character pack already exists")

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": payload.id,
        "name": payload.name,
        "style_profile_id": payload.style_profile_id,
        "source_agent": payload.source_agent,
        "tags": payload.tags,
        "preview_assets": payload.preview_assets,
        "characters": [c.model_dump() for c in payload.characters],
        "created_at": now,
        "updated_at": now,
    }
    write_json(path, record)
    return _prepare_pack_preview_view(record)


@router.get("/session-images")
async def list_session_character_images(session_path: str) -> list[dict[str, str]]:
    try:
        chars_dir = (OUTPUTS_DIR / session_path / "chars").resolve()
        outputs_resolved = OUTPUTS_DIR.resolve()
        if not chars_dir.is_relative_to(outputs_resolved):
            raise HTTPException(status_code=403, detail="Access denied")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session path")

    if not chars_dir.exists() or not chars_dir.is_dir():
        return []

    images = []
    for entry in sorted(chars_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            rel = str(entry.relative_to(OUTPUTS_DIR.resolve()))
            if not _is_valid_preview_image(rel):
                continue
            images.append(
                {
                    "name": entry.name,
                    "path": rel,
                }
            )
    return images


@router.get("/generated")
async def list_generated_character_previews(limit: int = 40) -> list[dict[str, str]]:
    ensure_library_dirs()
    generated_dir = CHARACTERS_DIR / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, str]] = []
    for entry in sorted(generated_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        rel = f"library/{entry.resolve().relative_to(LIBRARY_DIR.resolve()).as_posix()}"
        items.append({"name": entry.name, "path": rel})
        if len(items) >= max(1, min(limit, 200)):
            break
    return items


@router.post("/generate-preview")
async def generate_character_preview(payload: CharacterGenerateRequest) -> dict[str, Any]:
    ensure_library_dirs()
    ensure_subdirs()

    file_id = f"{_safe_name(payload.name)}-{int(datetime.now(timezone.utc).timestamp())}"
    generated_dir = CHARACTERS_DIR / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    image_path = generated_dir / f"{file_id}.png"

    prompt = (
        f"Generate a full-body character portrait. "
        f"Character name: {payload.name}. "
        f"Style: {payload.style}. "
        f"Aspect ratio target: {payload.aspect_ratio}. "
        f"Creative brief: {payload.prompt}. "
        f"Clean background, high detail."
    )

    generation_error = None
    try:
        model_name = "models/gemini-2.5-flash-image"
        if payload.model_preset == "gemini-default":
            model_name = "models/gemini-1.5-flash"
        model = get_model(model_name)
        response = model.generate_content(prompt)

        image_data = None
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None):
                image_data = part.inline_data.data
                break

        if image_data:
            image_path.write_bytes(image_data)
        else:
            raise ValueError("No image data in Gemini response")
    except Exception as exc:
        generation_error = str(exc)
        _create_placeholder_image(image_path, payload.name, payload.style)

    relative_image_path = f"library/{image_path.resolve().relative_to(LIBRARY_DIR.resolve()).as_posix()}"
    result: dict[str, Any] = {
        "name": payload.name,
        "style": payload.style,
        "model_preset": payload.model_preset,
        "aspect_ratio": payload.aspect_ratio,
        "prompt": payload.prompt,
        "image_path": relative_image_path,
        "fallback_used": generation_error is not None,
    }

    if generation_error:
        result["error"] = generation_error

    if payload.save_as_pack:
        pack_id = payload.pack_id or f"pack-{file_id}"
        pack_path = character_pack_path(pack_id)
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": pack_id,
            "name": f"{payload.name} pack",
            "style_profile_id": payload.style,
            "source_agent": "charGen",
            "tags": ["generated", "gemini"],
            "preview_assets": {"thumbnail": relative_image_path},
            "characters": [
                {
                    "character_id": _safe_name(payload.name),
                    "display_name": payload.name,
                    "archetype": "custom",
                    "visual_prompt": payload.prompt,
                    "tags": [payload.style],
                    "anchor_images": [relative_image_path],
                    "metadata": {"generated_by": "generate-preview"},
                }
            ],
            "created_at": now,
            "updated_at": now,
        }
        write_json(pack_path, record)
        result["pack_id"] = pack_id

    return result
