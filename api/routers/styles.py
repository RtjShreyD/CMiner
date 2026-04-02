from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.registry_store import (
    ensure_library_dirs,
    ensure_subdirs,
    list_json_records,
    read_json,
    style_profile_path,
    write_json,
    STYLES_DIR,
)

router = APIRouter()


class StyleProfileCreate(BaseModel):
    id: str
    name: str
    category: str = Field(description="font|cloud|subtitle|render|character_style")
    version: str = "v1"
    tags: list[str] = Field(default_factory=list)
    preview_assets: dict[str, Any] = Field(default_factory=dict)
    config_json: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"


@router.get("/profiles")
async def list_profiles(category: Optional[str] = None, tag: Optional[str] = None) -> list[dict[str, Any]]:
    ensure_library_dirs()
    ensure_subdirs()
    records = list_json_records(STYLES_DIR / "profiles")

    if category:
        records = [r for r in records if str(r.get("category", "")).lower() == category.lower()]
    if tag:
        records = [r for r in records if tag.lower() in [str(t).lower() for t in r.get("tags", [])]]

    return records


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str) -> dict[str, Any]:
    ensure_library_dirs()
    ensure_subdirs()
    path = style_profile_path(profile_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Style profile not found")
    return read_json(path)


@router.post("/profiles")
async def create_profile(payload: StyleProfileCreate) -> dict[str, Any]:
    ensure_library_dirs()
    ensure_subdirs()
    path = style_profile_path(payload.id)
    if path.exists():
        raise HTTPException(status_code=409, detail="Style profile already exists")

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": payload.id,
        "name": payload.name,
        "category": payload.category,
        "version": payload.version,
        "tags": payload.tags,
        "status": payload.status,
        "preview_assets": payload.preview_assets,
        "config_json": payload.config_json,
        "created_at": now,
        "updated_at": now,
    }
    write_json(path, record)
    return record


