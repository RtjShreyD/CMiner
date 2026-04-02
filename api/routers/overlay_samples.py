from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.services.buildpacks import (
    FONT_LIBRARY,
    generate_overlay_preview,
    list_buildpack_options,
    purge_library_characters,
    save_overlay_preview_to_session,
)

router = APIRouter()


class OverlaySampleRequest(BaseModel):
    session_mode: str = Field(default="new", description="new|existing")
    session_path: str | None = None

    resolution: str = Field(default="youtube_video")
    character_id: str | None = None
    scene_id: str | None = None
    fontstyle: str = Field(default="font-ubuntu-mono")
    subtitle_style: str = Field(default="sub-neon-pop")
    cloud_style: str = Field(default="cloud-none")

    sample_text: str = Field(default="The city whispered: move now.")
    sample_size: int = Field(default=48, ge=14, le=120)

    subtitle_x: float | None = Field(default=0.03958333333333333)
    subtitle_y: float | None = Field(default=0.8787037037037037)
    subtitle_scale: float = Field(default=1.25, ge=0.5, le=2.2)
    cloud_x: float | None = Field(default=0.3796875)
    cloud_y: float | None = Field(default=0.17962962962962964)
    cloud_w: float | None = Field(default=0.55)
    cloud_h: float | None = Field(default=0.17962962962962964)


@router.get("/buildpacks/options")
async def get_buildpack_options() -> dict[str, Any]:
    return list_buildpack_options()


@router.post("/purge-library-characters")
async def purge_library_chars() -> dict[str, Any]:
    purge_library_characters()
    return {"ok": True, "message": "Library characters removed."}


@router.post("/")
async def create_overlay_sample(payload: OverlaySampleRequest) -> dict[str, Any]:
    # Requested behavior: when existing session mode is selected, do not run BuildPack preview pipeline.
    if payload.session_mode == "existing":
        return {
            "skipped": True,
            "reason": "BuildPack preview is enabled only in new-session mode.",
            "preview_path": None,
        }

    data = generate_overlay_preview(
        resolution_key=payload.resolution,
        character_id=payload.character_id,
        scene_id=payload.scene_id,
        font_style_id=payload.fontstyle,
        subtitle_style_id=payload.subtitle_style,
        cloud_style_id=payload.cloud_style,
        sample_text=payload.sample_text,
        sample_size=payload.sample_size,
        subtitle_x=payload.subtitle_x,
        subtitle_y=payload.subtitle_y,
        subtitle_scale=payload.subtitle_scale,
        cloud_x=payload.cloud_x,
        cloud_y=payload.cloud_y,
        cloud_w=payload.cloud_w,
        cloud_h=payload.cloud_h,
    )

    data["skipped"] = False
    return data


@router.post("/save")
async def save_overlay_sample(payload: OverlaySampleRequest) -> dict[str, Any]:
    result = save_overlay_preview_to_session(
        session_path=payload.session_path,
        scene_id=payload.scene_id,
        resolution_key=payload.resolution,
        character_id=payload.character_id,
        font_style_id=payload.fontstyle,
        subtitle_style_id=payload.subtitle_style,
        cloud_style_id=payload.cloud_style,
        sample_text=payload.sample_text,
        sample_size=payload.sample_size,
        subtitle_x=payload.subtitle_x,
        subtitle_y=payload.subtitle_y,
        subtitle_scale=payload.subtitle_scale,
        cloud_x=payload.cloud_x,
        cloud_y=payload.cloud_y,
        cloud_w=payload.cloud_w,
        cloud_h=payload.cloud_h,
    )
    return {"ok": True, **result}
