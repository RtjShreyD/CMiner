#!/usr/bin/env python3
"""AutoAnimator Pipeline Runner – Episodic video generation with state management."""

import argparse
import sys
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.autoAnimator.utils import (
    ensure_session_outputs,
    get_model,
    autoanimator_session_folder_name,
)
from agents.shared.llm_tracker import LLMTracker

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_STATE_WRITE_LOCK = threading.Lock()
_GENERIC_PROJECT_NAMES = {
    "",
    "autoanimator",
    "autoanimator project",
    "project",
    "untitled",
    "untitled project",
}


def _first_key(mapping: dict) -> str | None:
    for k in mapping.keys():
        return str(k)
    return None


def _normalize_tts_voices_pool(raw_pool: dict) -> dict:
    """Return a compatibility-safe voice pool with both legacy and generic keys.

    Legacy keys: narrator, hero, villain, support
    Generic keys: voice_a, voice_b, voice_c, voice_d
    """
    pool = dict(raw_pool) if isinstance(raw_pool, dict) else {}
    normalized: dict[str, list[str]] = {}

    for key, value in pool.items():
        if isinstance(value, list):
            cleaned = [str(v).strip() for v in value if str(v).strip()]
            if cleaned:
                normalized[str(key)] = cleaned

    alias_pairs = {
        "voice_a": "narrator",
        "voice_b": "hero",
        "voice_c": "villain",
        "voice_d": "support",
    }

    for generic_key, legacy_key in alias_pairs.items():
        if generic_key in normalized and legacy_key not in normalized:
            normalized[legacy_key] = list(normalized[generic_key])
        elif legacy_key in normalized and generic_key not in normalized:
            normalized[generic_key] = list(normalized[legacy_key])

    return normalized


def _parse_json_object(raw: str) -> dict:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _is_unspecified_project_name(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in _GENERIC_PROJECT_NAMES


def _ensure_project_named_session_dir(session_dir: Path, project_name: str) -> Path:
    desired_name = autoanimator_session_folder_name(project_name)
    if session_dir.name == desired_name:
        return session_dir

    target = session_dir.parent / desired_name
    if target.exists() and target != session_dir:
        print(
            f"Warning: desired session folder '{desired_name}' already exists under {session_dir.parent}. "
            f"Continuing with existing folder name '{session_dir.name}'."
        )
        return session_dir

    session_dir.rename(target)
    return target


def _fallback_project_name(seed_prompt: str, niche_key: str | None) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(seed_prompt or ""))
    title_words = [w.capitalize() for w in words if w]
    if title_words:
        if len(title_words) >= 3:
            return " ".join(title_words[:3])
        return " ".join(title_words)
    if niche_key:
        return f"{str(niche_key).replace('_', ' ').title()} Series"
    return "AutoAnimator Series"


def _auto_assign_project_name(
    *,
    model_name: str,
    seed_prompt: str,
    niche_key: str | None,
    tracker: LLMTracker,
) -> str:
    fallback = _fallback_project_name(seed_prompt, niche_key)
    seed = str(seed_prompt or "").strip()
    if not seed:
        return fallback

    model = get_model(model_name)
    prompt = (
        "You are naming an episodic animation project from a story prompt.\n"
        "Return ONLY strict JSON: {\"project_name\": \"...\"}.\n"
        "Rules:\n"
        "- 2 to 4 words.\n"
        "- <= 42 characters.\n"
        "- Distinctive, brandable, and suitable for recurring episodes.\n"
        "- Do not use generic names like 'AutoAnimator Project'.\n"
        "- Use title case.\n"
        "- No punctuation except apostrophe if needed.\n\n"
        f"NICHE: {niche_key or 'general'}\n"
        f"STORY_PROMPT:\n{seed}\n"
    )

    try:
        from agents.shared.llm_tracker import tracked_generate

        response = tracked_generate(tracker, model, prompt, purpose="project_name_selector")
        obj = _parse_json_object(getattr(response, "text", "") or "")
        candidate = str(obj.get("project_name", "")).strip() if isinstance(obj.get("project_name"), str) else ""
        if not candidate:
            return fallback
        candidate = " ".join(candidate.split())
        if len(candidate) > 42:
            candidate = candidate[:42].rstrip()
        if _is_unspecified_project_name(candidate):
            return fallback
        return candidate
    except Exception:
        return fallback


def _auto_select_theme_and_styles(
    *,
    model_name: str,
    base_prompt: str,
    themes: dict[str, str],
    art_styles: dict[str, str],
    tracker: LLMTracker,
) -> tuple[str | None, list[str]]:
    if not themes and not art_styles:
        return None, []

    model = get_model(model_name)
    prompt = (
        "You are selecting generation aesthetics for an episodic visual story pipeline.\n"
        "Choose exactly ONE theme key and ONE OR TWO art_style keys from the provided options.\n"
        "Rules:\n"
        "- Return ONLY strict JSON.\n"
        "- theme_key must be one key from theme_options.\n"
        "- style_keys must contain one or two keys from art_style_options.\n"
        "- Prefer one style unless combining two gives a clearly better fit for the prompt.\n\n"
        f"USER_PROMPT:\n{base_prompt}\n\n"
        f"theme_options: {json.dumps(themes, ensure_ascii=True)}\n"
        f"art_style_options: {json.dumps(art_styles, ensure_ascii=True)}\n\n"
        "Return JSON in this shape:\n"
        "{\n"
        "  \"theme_key\": \"one_theme_key\",\n"
        "  \"style_keys\": [\"style_key_1\", \"style_key_2_optional\"]\n"
        "}"
    )

    try:
        from agents.shared.llm_tracker import tracked_generate

        response = tracked_generate(tracker, model, prompt, purpose="style_theme_selector")
        obj = _parse_json_object(getattr(response, "text", "") or "")
    except Exception:
        obj = {}

    chosen_theme = str(obj.get("theme_key", "")).strip() if isinstance(obj.get("theme_key"), str) else ""
    raw_styles = obj.get("style_keys") if isinstance(obj.get("style_keys"), list) else []

    style_keys: list[str] = []
    for item in raw_styles:
        key = str(item).strip()
        if key in art_styles and key not in style_keys:
            style_keys.append(key)
        if len(style_keys) >= 2:
            break

    if chosen_theme not in themes:
        chosen_theme = _first_key(themes) or ""

    if not style_keys:
        default_style = _first_key(art_styles)
        style_keys = [default_style] if default_style else []

    return (chosen_theme or None), style_keys


def _resolve_art_style_text(style_keys: list[str], art_styles: dict[str, str]) -> str:
    resolved = [art_styles[k] for k in style_keys if k in art_styles]
    if not resolved:
        fallback_key = _first_key(art_styles)
        if fallback_key:
            return str(art_styles[fallback_key])
        return "cinematic anime"
    # Auto mode may combine up to two styles.
    return " + ".join(resolved)


def _auto_select_niche(
    *,
    model_name: str,
    base_prompt: str,
    niche_bundles: dict[str, dict],
    tracker: LLMTracker,
) -> str | None:
    if not niche_bundles:
        return None

    model = get_model(model_name)
    prompt = (
        "You classify a story prompt into exactly one production niche key.\n"
        "Rules:\n"
        "- Return ONLY strict JSON.\n"
        "- niche_key must be one key from niche_options.\n"
        "- Choose the best single fit for tone, pacing, and structure.\n\n"
        f"USER_PROMPT:\n{base_prompt}\n\n"
        f"niche_options: {json.dumps(niche_bundles, ensure_ascii=True)}\n\n"
        "Return JSON in this shape:\n"
        "{\n"
        "  \"niche_key\": \"one_niche_key\"\n"
        "}"
    )

    try:
        from agents.shared.llm_tracker import tracked_generate

        response = tracked_generate(tracker, model, prompt, purpose="niche_selector")
        obj = _parse_json_object(getattr(response, "text", "") or "")
    except Exception:
        obj = {}

    chosen_niche = str(obj.get("niche_key", "")).strip() if isinstance(obj.get("niche_key"), str) else ""
    if chosen_niche in niche_bundles:
        return chosen_niche
    return None


def _construct_series_preset_prompt(
    *,
    seed_prompt: str,
    project_name: str,
    niche_key: str | None,
) -> str:
    niche_label = niche_key or "general_series"
    return (
        "SERIES SOURCE OF TRUTH (PERSISTENT PRESET)\n"
        f"PROJECT: {project_name}\n"
        f"NICHE: {niche_label}\n"
        "MODE: episodic show/series continuity\n\n"
        "BASELINE SETUP (authoritative foundation):\n"
        f"{seed_prompt}\n\n"
        "SERIES RULES:\n"
        "- Keep continuity of world setup, recurring cast logic, and tone across episodes.\n"
        "- Preserve baseline constraints unless the user explicitly requests a change.\n"
        "- New episode prompts are additive directions, not baseline replacement.\n"
        "- Reuse established characters and visual identity unless add/remove is requested.\n"
    )


def _llm_compute_series_preset_prompt(
    *,
    model_name: str,
    seed_prompt: str,
    project_name: str,
    niche_key: str | None,
    tracker: LLMTracker,
) -> str:
    fallback = _construct_series_preset_prompt(
        seed_prompt=seed_prompt,
        project_name=project_name,
        niche_key=niche_key,
    )

    if not seed_prompt.strip():
        return fallback

    model = get_model(model_name)
    niche_label = niche_key or "general_series"
    prompt = (
        "You are creating a persistent SERIES PRESET PROMPT for episodic continuity.\n"
        "This preset is computed once from the first narrative prompt and reused across future episodes.\n"
        "Return ONLY strict JSON with key: preset_prompt.\n"
        "Rules:\n"
        "- Keep it concise, practical, and production-ready (120-220 words).\n"
        "- Extract immutable series foundations: world, recurring cast intent, tone, stakes.\n"
        "- Include continuity rules for future add-on prompts.\n"
        "- Do NOT copy the user prompt verbatim. Distill and normalize it.\n"
        "- Do NOT include markdown fences.\n\n"
        f"PROJECT_NAME: {project_name}\n"
        f"NICHE: {niche_label}\n"
        f"FIRST_USER_NARRATIVE_PROMPT:\n{seed_prompt}\n\n"
        "JSON shape:\n"
        "{\"preset_prompt\": \"...\"}"
    )

    try:
        from agents.shared.llm_tracker import tracked_generate

        response = tracked_generate(tracker, model, prompt, purpose="series_preset_builder")
        obj = _parse_json_object(getattr(response, "text", "") or "")
        preset = str(obj.get("preset_prompt", "")).strip() if isinstance(obj.get("preset_prompt"), str) else ""
        return preset or fallback
    except Exception:
        return fallback


def _build_aesthetic_guidance(
    *,
    model_name: str,
    base_prompt: str,
    resolved_theme: str | None,
    selected_style_keys: list[str],
    art_styles: dict[str, str],
    tracker: LLMTracker,
    auto_mode: bool,
) -> str:
    style_text = "; ".join([art_styles.get(k, k) for k in selected_style_keys if k])
    fallback = (
        f"Theme mood: {resolved_theme or 'none'}. "
        f"Style blend: {style_text or 'cinematic anime'}. "
        "Keep cinematic composition, coherent lighting, texture continuity, and character identity consistency across panels."
    )

    if not auto_mode:
        return fallback

    model = get_model(model_name)
    prompt = (
        "You are a visual direction lead for episodic animation frames.\n"
        "Create a concise AESTHETIC_GUIDANCE string for image generation prompts.\n"
        "Rules:\n"
        "- You MAY remix and blend the selected styles; do not just repeat key names.\n"
        "- Keep it under 80 words.\n"
        "- Include: palette, lighting, composition rhythm, texture detail, and mood continuity.\n"
        "- Output JSON only: {\"aesthetic_guidance\": \"...\"}.\n\n"
        f"STORY_PROMPT:\n{base_prompt}\n\n"
        f"THEME_TEXT:\n{resolved_theme or 'none'}\n\n"
        f"SELECTED_STYLE_KEYS:\n{json.dumps(selected_style_keys, ensure_ascii=True)}\n"
        f"SELECTED_STYLE_TEXT:\n{style_text}\n"
    )

    try:
        from agents.shared.llm_tracker import tracked_generate

        response = tracked_generate(tracker, model, prompt, purpose="aesthetic_guidance")
        obj = _parse_json_object(getattr(response, "text", "") or "")
        guidance = str(obj.get("aesthetic_guidance", "")).strip()
        return guidance or fallback
    except Exception:
        return fallback


def _apply_dynamic_fps_policy(
    manga_board: dict,
    *,
    max_duration_mins: int,
    default_output_fps: int,
) -> tuple[int, int, int]:
    """Assign per-panel FPS from director policy and scene intensity within budget constraints.

    Returns (min_fps, max_fps, avg_fps_rounded).
    """
    panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
    if not panels:
        return default_output_fps, default_output_fps, default_output_fps

    rs = manga_board.get("render_strategy", {}) if isinstance(manga_board.get("render_strategy", {}), dict) else {}
    fps_policy = rs.get("fps_policy", {}) if isinstance(rs.get("fps_policy", {}), dict) else {}

    base_fps = int(fps_policy.get("base_fps", max(12, default_output_fps - 6)) or max(12, default_output_fps - 6))
    max_fps = int(fps_policy.get("max_fps", default_output_fps) or default_output_fps)
    min_fps = int(fps_policy.get("min_fps", 12) or 12)

    # Budget-aware clamps.
    if max_duration_mins <= 1:
        max_fps = min(max_fps, 24)
    else:
        max_fps = min(max_fps, 30)
    base_fps = max(min_fps, min(base_fps, max_fps))

    action_keywords = [
        "fight", "battle", "impact", "punch", "kick", "blast", "dash", "combo", "chase",
        "duel", "clash", "strike", "attack", "explosion", "counter",
    ]
    high_motion_moods = {"action", "tense", "dramatic"}
    high_motion_cameras = {"low-angle", "birds-eye", "wide-shot"}

    assigned: list[int] = []
    for p in panels:
        score = 0
        scene_text = str(p.get("scene_description", "") or "").lower()
        mood = str(p.get("mood", "") or "").lower()
        camera = str(p.get("camera_angle", "") or "").lower()

        if any(k in scene_text for k in action_keywords):
            score += 2
        if mood in high_motion_moods:
            score += 1
        if camera in high_motion_cameras:
            score += 1

        # Dialogue emotion can hint intensity.
        for d in (p.get("dialogue", []) if isinstance(p.get("dialogue", []), list) else []):
            em = str((d or {}).get("emotion", "") or "").lower()
            if em in {"angry", "tense", "overwhelmed"}:
                score += 1

        panel_fps = base_fps + (score * 2)
        panel_fps = max(min_fps, min(max_fps, panel_fps))
        p["fps"] = int(panel_fps)
        assigned.append(int(panel_fps))

    rs["fps_policy"] = {
        "mode": "dynamic",
        "base_fps": int(base_fps),
        "min_fps": int(min_fps),
        "max_fps": int(max_fps),
        "output_fps": int(default_output_fps),
    }
    manga_board["render_strategy"] = rs

    return min(assigned), max(assigned), int(round(sum(assigned) / len(assigned)))


def main():
    parser = argparse.ArgumentParser(description="AutoAnimator Pipeline Runner")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--prompt", help="Override base prompt (otherwise reads prompt.txt)")
    parser.add_argument("--preset_prompt", help="Persistent source-of-truth prompt for episode-mode series")
    parser.add_argument("--project_name", help="Project or brand name for this session")
    parser.add_argument("--niche", help="Optional niche bundle key for planner/director guidance")
    parser.add_argument("--start_frame_path", help="Session-relative path for planner start frame reference")
    parser.add_argument("--end_frame_path", help="Session-relative path for planner end frame reference")
    parser.add_argument(
        "--step",
        choices=["all", "planner", "chars", "scenes", "audio", "clouds", "music", "video"],
        default="all",
        help="Execute a specific pipeline step",
    )
    parser.add_argument("--session", help="Continue in an existing session directory")
    parser.add_argument(
        "--episodes",
        choices=["new", "continue"],
        default="new",
        help="'new' starts a fresh series. 'continue' plans the next episode from prior context.",
    )
    parser.add_argument("--theme", help="Theme key from config themes")
    parser.add_argument("--preset", help="Style preset key from config art_styles")
    parser.add_argument("--format", choices=["tiktok","instagram_reels","youtube_shorts","youtube_widescreen"], help="Output format preset")
    parser.add_argument(
        "--youtube_shorts_export",
        choices=["auto", "on", "off"],
        default="auto",
        help="Control whether Shorts variant is exported when format is youtube_widescreen",
    )
    parser.add_argument("--vector_upscale", action="store_true", help="Apply upscale stub after image generation")
    parser.add_argument("--enable_music", action="store_true", help="Include background music in final video")
    parser.add_argument("--create_banner", action="store_true", help="Generate wide panoramic show banner after character generation and use it as the series first-frame anchor")
    parser.add_argument("--intro_only", action="store_true", help="Generate an intro-only episode flow from the base premise")
    parser.add_argument("--max_image_requests", type=int, help="Maximum total image requests")
    parser.add_argument("--max_chars_per_episode", type=int, help="Maximum characters in one episode")
    parser.add_argument("--max_panels_per_episode", type=int, help="Maximum panel count in one episode")
    parser.add_argument("--max_episode_duration_mins", type=int, help="Maximum episode duration minutes")
    parser.add_argument("--resolution_w", type=int, help="Override output resolution width")
    parser.add_argument("--resolution_h", type=int, help="Override output resolution height")
    parser.add_argument("--cloud_style", help="Cloud style id from buildpack")
    parser.add_argument("--font_style", help="Font style id from buildpack")
    parser.add_argument("--subtitle_style", help="Subtitle style id from buildpack")
    parser.add_argument("--narration_mode", help="Narration mode from buildpack")
    parser.add_argument("--subtitle_scale", type=float, help="Subtitle scale from buildpack")
    parser.add_argument("--tts_max_parallel_panels", type=int, help="Maximum concurrent panel TTS jobs")
    parser.add_argument("--segment_workers", type=int, help="Maximum concurrent segment ffmpeg jobs")
    parser.add_argument("--scene_concurrency", type=int, help="Maximum concurrent scene image API requests")
    parser.add_argument("--cloud_workers", type=int, help="Maximum concurrent panels in cloud overlay generation")
    parser.add_argument(
        "--tts_provider",
        choices=["edge", "gemini"],
        help="TTS provider for audio step",
    )
    parser.add_argument(
        "--gemini_tts_model",
        help="Gemini TTS model when --tts_provider=gemini",
    )
    parser.add_argument("--planner_model", help="Override planner model name")
    parser.add_argument("--director_model", help="Override director model name")
    parser.add_argument("--director_fallback_model", help="Override director fallback model name")
    parser.add_argument("--character_image_model", help="Override character image model name")
    parser.add_argument("--scene_image_model", help="Override scene image model name")
    parser.add_argument("--planner_skill_ids", help="Comma-separated planner skill IDs from config planner_skills")
    parser.add_argument("--planner_skill_prompt", help="Optional custom planner skill prompt text")
    parser.add_argument(
        "--music_provider",
        choices=["strudel", "lyria"],
        default="lyria",
        help="Music generation provider for Step 6",
    )
    parser.add_argument(
        "--lyria_model",
        default="lyria-3-clip-preview",
        help="Lyria model id when --music_provider=lyria",
    )
    parser.add_argument(
        "--episode_mode",
        choices=["true", "false"],
        default="true",
        help="true allows multi-episode continuity, false forces single-video mode",
    )
    parser.add_argument(
        "--develop",
        action="store_true",
        help="When used with --episodes continue, also runs generation chains (chars/scenes/audio/clouds/video)",
    )
    parser.add_argument("--episode", type=int, help="Target a specific episode number (for re-runs)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    tracker = LLMTracker()

    # ── Session Handling ──────────────────────────────────────
    if args.session:
        session_dir = Path(args.session).resolve()
        if not session_dir.exists():
            print(f"Error: Session directory {args.session} not found.")
            sys.exit(1)
        print(f"Continuing in session: {session_dir}")
    else:
        session_dir = ensure_session_outputs(workspace, project_name=(args.project_name or ""))

    # ── Load Config ───────────────────────────────────────────
    config_path = Path(__file__).resolve().parent / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)

    models_config = config.get("models", {})
    planner_model = models_config.get("planner_model", "models/gemini-flash-latest")
    director_model = models_config.get("director_model", "models/gemini-2.5-flash")
    director_fallback_model = models_config.get("director_fallback_model", "models/gemini-2.0-flash-lite")
    char_image_model = models_config.get("character_image_model", "models/gemini-2.5-flash-image")
    scene_image_model = models_config.get("scene_image_model", "models/gemini-2.5-flash-image")
    max_image_requests = models_config.get("max_image_requests", 50)
    max_chars = models_config.get("max_chars_per_episode", 3)
    max_panels = models_config.get("max_panels_per_episode", 50)
    max_duration = models_config.get("max_episode_duration_mins", 1)
    tts_max_parallel_panels = models_config.get("tts_max_parallel_panels", 4)
    segment_workers = models_config.get("segment_workers", 4)
    scene_concurrency = models_config.get("scene_concurrency", 4)
    cloud_workers = models_config.get("cloud_workers", 4)
    tts_provider = models_config.get("tts_provider", "edge")
    gemini_tts_model = models_config.get("gemini_tts_model", "models/gemini-2.5-flash-tts")

    if args.max_image_requests:
        max_image_requests = args.max_image_requests
    if args.max_chars_per_episode:
        max_chars = args.max_chars_per_episode
    if args.max_panels_per_episode:
        max_panels = args.max_panels_per_episode
    if args.max_episode_duration_mins:
        max_duration = args.max_episode_duration_mins
    if args.tts_max_parallel_panels:
        tts_max_parallel_panels = max(1, args.tts_max_parallel_panels)
    if args.segment_workers:
        segment_workers = max(1, args.segment_workers)
    if args.scene_concurrency:
        scene_concurrency = max(1, args.scene_concurrency)
    if args.cloud_workers:
        cloud_workers = max(1, args.cloud_workers)
    if args.tts_provider:
        tts_provider = args.tts_provider
    if args.gemini_tts_model:
        gemini_tts_model = args.gemini_tts_model
    if args.planner_model:
        planner_model = args.planner_model
    if args.director_model:
        director_model = args.director_model
    if args.director_fallback_model:
        director_fallback_model = args.director_fallback_model
    if args.character_image_model:
        char_image_model = args.character_image_model
    if args.scene_image_model:
        scene_image_model = args.scene_image_model
    tts_voices_pool = _normalize_tts_voices_pool(config.get("tts_voices_pool", {}))

    # ── State Management (early) ─────────────────────────────
    state_path = session_dir / "session_state.json"
    state = _load_state(state_path)

    input_narrative_prompt = (args.prompt or "").strip()
    input_preset_prompt = (args.preset_prompt or "").strip()
    saved_prompt = str(state.get("settings", {}).get("prompt", "") or "").strip()
    saved_preset_prompt = str(state.get("settings", {}).get("preset_prompt", "") or "").strip()

    # Fallback default for first runs when no prompt is provided.
    fallback_prompt = "A dramatic manga story."
    prompt_file = Path(__file__).resolve().parent / "prompt.txt"
    if prompt_file.exists():
        try:
            fallback_prompt = prompt_file.read_text().strip() or fallback_prompt
        except Exception:
            fallback_prompt = "A dramatic manga story."

    requested_project_name = (args.project_name or "").strip()
    prior_project_name = str(state.get("settings", {}).get("project_name", "") or "").strip()

    raw_requested_niche = (args.niche or "").strip()
    requested_niche_is_auto = raw_requested_niche == "auto-select"
    requested_niche = raw_requested_niche
    if requested_niche_is_auto:
        requested_niche = ""

    # Style/theme presets
    themes = config.get("themes", {})
    art_styles = config.get("art_styles", {})
    niche_bundles = config.get("niche_bundles", {}) if isinstance(config.get("niche_bundles", {}), dict) else {}
    planner_skills_catalog = config.get("planner_skills", {}) if isinstance(config.get("planner_skills", {}), dict) else {}
    output_presets = config.get("output_presets", {})

    niche_key = requested_niche if requested_niche in niche_bundles else None
    prompt_for_niche_select = input_narrative_prompt or saved_preset_prompt or saved_prompt or fallback_prompt
    if requested_niche_is_auto:
        auto_niche = _auto_select_niche(
            model_name=planner_model,
            base_prompt=prompt_for_niche_select,
            niche_bundles=niche_bundles,
            tracker=tracker,
        )
        niche_key = auto_niche if auto_niche else None
    niche_bundle = niche_bundles.get(niche_key, {}) if niche_key else {}
    niche_context = str(niche_bundle.get("director_context", "") or "").strip()

    # Planner should always assign a suitable project name when user input is unspecified.
    if requested_project_name and not _is_unspecified_project_name(requested_project_name):
        project_name = requested_project_name
    elif prior_project_name and not _is_unspecified_project_name(prior_project_name):
        project_name = prior_project_name
    else:
        project_seed = input_narrative_prompt or input_preset_prompt or saved_preset_prompt or saved_prompt or fallback_prompt
        project_name = _auto_assign_project_name(
            model_name=planner_model,
            seed_prompt=project_seed,
            niche_key=niche_key,
            tracker=tracker,
        )

    # Normalize session folder naming to outputs/<session id>/<project-name>_autoAnimator.
    session_dir = _ensure_project_named_session_dir(session_dir, project_name)
    state_path = session_dir / "session_state.json"
    print(f"Active session directory: {session_dir}")

    # Final prompt composition.
    episode_mode_enabled = args.episode_mode == "true"
    preset_prompt = input_preset_prompt or (saved_preset_prompt if episode_mode_enabled else "")
    narrative_prompt = input_narrative_prompt

    if episode_mode_enabled and not preset_prompt:
        baseline_seed = narrative_prompt or saved_prompt or fallback_prompt
        preset_prompt = _llm_compute_series_preset_prompt(
            model_name=planner_model,
            seed_prompt=baseline_seed,
            project_name=project_name,
            niche_key=niche_key,
            tracker=tracker,
        )

    if not episode_mode_enabled and not narrative_prompt:
        narrative_prompt = saved_prompt or fallback_prompt

    if episode_mode_enabled:
        if narrative_prompt:
            base_prompt = f"{preset_prompt}\n\nEPISODE ADD-ON REQUEST:\n{narrative_prompt}"
        else:
            base_prompt = preset_prompt
    else:
        base_prompt = narrative_prompt

    requested_theme = (args.theme or "").strip()
    requested_preset = (args.preset or "").strip()
    auto_theme = requested_theme in {"", "auto-select"}
    auto_preset = requested_preset in {"", "auto-select"}

    if auto_theme or auto_preset:
        selected_theme_key, selected_style_keys = _auto_select_theme_and_styles(
            model_name=planner_model,
            base_prompt=base_prompt,
            themes=themes if isinstance(themes, dict) else {},
            art_styles=art_styles if isinstance(art_styles, dict) else {},
            tracker=tracker,
        )
    else:
        selected_theme_key = requested_theme if requested_theme in themes else None
        selected_style_keys = [requested_preset] if requested_preset in art_styles else []

    if not selected_theme_key:
        selected_theme_key = _first_key(themes)
    if not selected_style_keys:
        default_style_key = _first_key(art_styles)
        selected_style_keys = [default_style_key] if default_style_key else []

    # Stage-show default steering: prefer the dedicated stage-show theme/style unless explicitly overridden.
    stage_show_theme_key = "stage_show_portal_satire"
    stage_show_style_key = "rick_morty_stage_show"
    if niche_key == "stage_show":
        if auto_theme and stage_show_theme_key in themes:
            selected_theme_key = stage_show_theme_key
        if auto_preset and stage_show_style_key in art_styles:
            selected_style_keys = [
                stage_show_style_key,
                *[k for k in selected_style_keys if k != stage_show_style_key],
            ][:2]

    resolved_theme = themes.get(selected_theme_key) if selected_theme_key else None
    art_style = _resolve_art_style_text(selected_style_keys, art_styles if isinstance(art_styles, dict) else {})
    aesthetic_guidance = _build_aesthetic_guidance(
        model_name=planner_model,
        base_prompt=base_prompt,
        resolved_theme=resolved_theme,
        selected_style_keys=selected_style_keys,
        art_styles=art_styles if isinstance(art_styles, dict) else {},
        tracker=tracker,
        auto_mode=(auto_theme or auto_preset),
    )

    video_config = config.get("video", {})
    resolution = tuple(video_config.get("resolution", [1280, 720]))
    fps = 24
    target_duration = video_config.get("target_duration_mins", 5)

    if args.format and args.format in output_presets:
        preset_cfg = output_presets[args.format]
        resolution = tuple(preset_cfg.get("resolution", list(resolution)))
        fps = preset_cfg.get("fps", fps)
        target_duration = preset_cfg.get("duration_mins", target_duration)
    if args.resolution_w and args.resolution_h:
        resolution = (args.resolution_w, args.resolution_h)

    enable_music = args.enable_music
    vector_upscale = args.vector_upscale

    if not requested_niche and not requested_niche_is_auto:
        saved_niche = str(state.get("settings", {}).get("niche", "") or "").strip()
        if saved_niche and saved_niche in niche_bundles:
            niche_key = saved_niche
            niche_bundle = niche_bundles.get(niche_key, {})
            niche_context = str(niche_bundle.get("director_context", "") or "").strip()

    start_frame_path = (args.start_frame_path or "").strip()
    end_frame_path = (args.end_frame_path or "").strip()
    if not start_frame_path:
        start_frame_path = str(state.get("settings", {}).get("start_frame_path", "") or "").strip()
    if not end_frame_path:
        end_frame_path = str(state.get("settings", {}).get("end_frame_path", "") or "").strip()
    start_frame_path = start_frame_path or None
    end_frame_path = end_frame_path or None

    create_banner = args.create_banner or bool(state.get("settings", {}).get("create_banner", False))
    intro_only = args.intro_only or bool(state.get("settings", {}).get("intro_only", False))

    # Optional planner-skill augmentation (predefined skill ids + custom user skill prompt).
    raw_skill_ids = str(args.planner_skill_ids or "").strip()
    if raw_skill_ids:
        planner_skill_ids = [s.strip() for s in raw_skill_ids.split(",") if s.strip()]
    else:
        saved_skill_ids = state.get("settings", {}).get("planner_skill_ids", [])
        planner_skill_ids = [str(s).strip() for s in saved_skill_ids if str(s).strip()] if isinstance(saved_skill_ids, list) else []
    valid_skill_ids = [sid for sid in planner_skill_ids if sid in planner_skills_catalog]

    planner_skill_prompt = str(args.planner_skill_prompt or "").strip()
    if not planner_skill_prompt:
        planner_skill_prompt = str(state.get("settings", {}).get("planner_skill_prompt", "") or "").strip()

    resolved_skill_blocks = []
    for sid in valid_skill_ids:
        cfg = planner_skills_catalog.get(sid, {})
        if not isinstance(cfg, dict):
            continue
        resolved_skill_blocks.append(
            {
                "id": sid,
                "label": str(cfg.get("label", sid) or sid),
                "description": str(cfg.get("description", "") or "").strip(),
                "prompt": str(cfg.get("prompt", "") or "").strip(),
            }
        )

    # Auto-apply existing show banner as start frame when no explicit start_frame set.
    _banner_auto = session_dir / "banner" / "show_banner.png"
    if _banner_auto.exists() and not start_frame_path:
        start_frame_path = str(_banner_auto.relative_to(session_dir))
        print(f"Auto-applying show banner as start frame: {start_frame_path}")
        logger.info("Auto-applied show banner as start_frame_path: %s", start_frame_path)

    persisted_narrative_prompt = narrative_prompt or saved_prompt

    state.setdefault("settings", {}).update({
        "prompt": persisted_narrative_prompt,
        "effective_prompt": base_prompt,
        "preset_prompt": preset_prompt if episode_mode_enabled else None,
        "project_name": project_name,
        "niche": niche_key,
        "niche_context": niche_context or None,
        "start_frame_path": start_frame_path,
        "end_frame_path": end_frame_path,
        "episodes_mode": args.episodes,
        "episode": args.episode,
        "theme": selected_theme_key,
        "preset": selected_style_keys[0] if selected_style_keys else None,
        "style_keys": selected_style_keys,
        "theme_selection_mode": "auto" if auto_theme else "manual",
        "style_selection_mode": "auto" if auto_preset else "manual",
        "aesthetic_guidance": aesthetic_guidance,
        "format": args.format,
        "planner_model": planner_model,
        "director_model": director_model,
        "director_fallback_model": director_fallback_model,
        "character_image_model": char_image_model,
        "scene_image_model": scene_image_model,
        "resolution": list(resolution),
        "fps": fps,
        "enable_music": enable_music,
        "music_provider": args.music_provider,
        "lyria_model": args.lyria_model,
        "vector_upscale": vector_upscale,
        "max_image_requests": max_image_requests,
        "max_chars_per_episode": max_chars,
        "max_panels_per_episode": max_panels,
        "max_episode_duration_mins": max_duration,
        "tts_max_parallel_panels": tts_max_parallel_panels,
        "segment_workers": segment_workers,
        "scene_concurrency": scene_concurrency,
        "cloud_workers": cloud_workers,
        "tts_provider": tts_provider,
        "gemini_tts_model": gemini_tts_model,
        "cloud_style": args.cloud_style or "cloud-none",
        "font_style": args.font_style or "font-geist-sans",
        "subtitle_style": args.subtitle_style or "sub-clean-bottom",
        "narration_mode": args.narration_mode or "hybrid_subtitles_clouds",
        "subtitle_scale": args.subtitle_scale if args.subtitle_scale is not None else 1.0,
        "episode_mode": args.episode_mode == "true",
        "create_banner": create_banner,
        "intro_only": intro_only,
        "planner_skill_ids": valid_skill_ids,
        "planner_skill_prompt": planner_skill_prompt or None,
        "planner_skills_resolved": resolved_skill_blocks,
    })
    _save_state(state_path, state)

    print(f"Session: {session_dir}")
    print(f"Config: fps={fps}, max_image_requests={max_image_requests}, max_chars={max_chars}")
    print(f"Theme selected: {selected_theme_key or 'none'}")
    print(f"Style keys selected: {', '.join(selected_style_keys) if selected_style_keys else 'none'}")
    print(f"Niche selected: {niche_key or 'general/none'}")
    if episode_mode_enabled:
        print(f"Series preset prompt active: {'yes' if preset_prompt else 'no'}")
        print(f"Narrative add-on provided: {'yes' if bool(narrative_prompt) else 'no'}")
    print(f"Aesthetic guidance: {aesthetic_guidance}")

    # ── Determine what to run ─────────────────────────────────
    # --episodes continue: plan-only by default
    # --episodes continue --develop: plan + all generation
    # --step X: run a specific step
    run_planner = args.step in ["all", "planner"] or args.episodes == "continue"
    run_generation = args.develop or (args.step in ["all"] and args.episodes != "continue")
    run_specific_step = args.step not in ["all", "planner"]

    # ── 1. Episode Planner ────────────────────────────────────
    manga_board = None
    if run_planner and not run_specific_step:
        from agents.autoAnimator.chains.episode_planner import EpisodePlanner

        planner = EpisodePlanner(
            model_name=planner_model,
            director_model_name=director_model,
            director_fallback_model_name=director_fallback_model,
            project_name=project_name,
            preset_prompt=preset_prompt,
            niche_name=niche_key,
            niche_context=niche_context,
            start_frame_path=start_frame_path,
            end_frame_path=end_frame_path,
            tts_voices_pool=tts_voices_pool,
            max_duration_mins=max_duration,
            max_chars=max_chars,
            max_panels=max_panels,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            theme=resolved_theme,
            model_stack={
                "character_image_model": char_image_model,
                "scene_image_model": scene_image_model,
                "tts_engine": "edge-tts",
                "music_provider": args.music_provider,
                "lyria_model": args.lyria_model,
            },
            episode_mode=(args.episode_mode == "true"),
            intro_only=intro_only,
            target_episode=args.episode,
            tracker=tracker,
            planner_skill_ids=valid_skill_ids,
            planner_skill_prompt=planner_skill_prompt,
            planner_skills_catalog=planner_skills_catalog,
        )
        manga_board = planner.run(base_prompt, session_dir)
        min_fps, max_fps_assigned, avg_fps = _apply_dynamic_fps_policy(
            manga_board,
            max_duration_mins=max_duration,
            default_output_fps=fps,
        )
        print(f"Dynamic FPS assigned per panel: min={min_fps}, max={max_fps_assigned}, avg={avg_fps}")

        # Update state
        ep_num = manga_board.get("episode_number", 1)
        state["latest_episode"] = ep_num
        state.setdefault("episodes", {})[str(ep_num)] = {
            "status": "planned",
            "title": manga_board.get("episode_title", ""),
            "panels": len(manga_board.get("panels", [])),
            "characters": [c["name"] for c in manga_board.get("characters", [])],
        }
        _save_state(state_path, state)

        if args.episodes == "continue" and not args.develop:
            print(f"\nEpisode {ep_num} planned. Use --develop to generate assets.")
            if tracker.calls:
                tracker.save(session_dir)
            return
    else:
        manga_board = _load_storyboard(session_dir, args.episode)
        if manga_board is None:
            print("Error: No storyboard.json found. Run 'planner' step first.")
            sys.exit(1)
        min_fps, max_fps_assigned, avg_fps = _apply_dynamic_fps_policy(
            manga_board,
            max_duration_mins=max_duration,
            default_output_fps=fps,
        )
        print(f"Dynamic FPS assigned per panel: min={min_fps}, max={max_fps_assigned}, avg={avg_fps}")

    ep_num = manga_board.get("episode_number", 1)
    ep_dir = session_dir / "episodes" / f"episode{ep_num}"
    mode_scope = "intro" if intro_only else "generic"

    def _episode_path(rel_path: str) -> Path:
        return ep_dir / rel_path

    def _mode_rel_path(*parts: str) -> str:
        return "/".join([f"episodes/episode{ep_num}", mode_scope, *parts])

    # ── Calculate image budget ────────────────────────────────
    num_chars = len(manga_board.get("characters", []))
    num_panels = len(manga_board.get("panels", []))
    char_budget = min(num_chars, max_chars)
    scene_budget = min(num_panels, max_image_requests - char_budget)
    print(f"Image budget: {char_budget} chars + {scene_budget} scenes = {char_budget + scene_budget}/{max_image_requests}")
    if scene_budget < num_panels:
        print(
            f"Warning: scene budget ({scene_budget}) is lower than planned panels ({num_panels}). "
            "Remaining panels will use local static fallback frames unless budget is increased."
        )

    run_chars_step = args.step in ["all", "chars"] or (run_generation and not run_specific_step)
    run_scenes_step = args.step in ["all", "scenes"] or (run_generation and not run_specific_step)
    run_audio_step = args.step in ["all", "audio"] or (run_generation and not run_specific_step)
    run_clouds_step = args.step in ["all", "clouds"] or (run_generation and not run_specific_step)
    run_music_step = args.step in ["all", "music"] or (run_generation and not run_specific_step)
    run_video_step = args.step in ["all", "video"] or (run_generation and not run_specific_step)

    # In full generation mode, overlap independent steps (audio/music)
    # while image generation is running.
    can_parallelize = bool(args.step == "all" and run_generation and not run_specific_step)
    executor = None
    audio_future = None
    music_future = None

    def _run_audio_task():
        from agents.autoAnimator.chains.tts_gen import TTSGen

        tts_gen = TTSGen(
            voices_pool=tts_voices_pool,
            max_parallel_panels=tts_max_parallel_panels,
            tts_provider=tts_provider,
            gemini_tts_model=gemini_tts_model,
            tracker=tracker,
        )
        return tts_gen.run(manga_board, session_dir)

    def _run_music_task():
        from agents.autoAnimator.chains.music_gen import MusicGen

        music_gen = MusicGen(
            model_name=planner_model,
            music_provider=args.music_provider,
            lyria_model=args.lyria_model,
            tracker=tracker,
        )
        return music_gen.run(manga_board, session_dir, base_prompt=base_prompt)

    if can_parallelize:
        executor = ThreadPoolExecutor(max_workers=2)
        if run_audio_step:
            print("[parallel] Scheduled TTS generation.")
            audio_future = executor.submit(_run_audio_task)
        if run_music_step and enable_music:
            print("[parallel] Scheduled music generation.")
            music_future = executor.submit(_run_music_task)

    # ── 2. Character Generation ───────────────────────────────
    chars_manifest_path = session_dir / "chars" / "chars_manifest.json"
    char_manifest = {}
    if run_chars_step:
        print("[step:chars] Starting character generation.")
        from agents.autoAnimator.chains.char_gen import CharGen

        char_gen = CharGen(
            image_model_name=char_image_model,
            max_generations=char_budget,
            resolution=resolution,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            tracker=tracker,
        )
        char_manifest = char_gen.run(manga_board, session_dir)
        print("[step:chars] Character generation complete.")
        logger.info("[step:chars] complete | session=%s", session_dir)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["chars_generated"] = True
        _save_state(state_path, state)

        # ── Banner generation (first episode / user-requested) ─────
        _banner_path = session_dir / "banner" / "show_banner.png"
        if create_banner and not _banner_path.exists():
            logger.info("[step:banner] Generating show banner …")
            _banner_result = char_gen.generate_banner(
                project_name, session_dir,
                manga_board.get("characters", []), char_manifest,
            )
            if _banner_result:
                logger.info("[step:banner] Show banner saved: %s", _banner_result)
                print(f"[step:banner] Show banner saved: {_banner_result}")
                if not start_frame_path:
                    start_frame_path = str(_banner_result.relative_to(session_dir))
                    print(f"[step:banner] Auto-set start_frame_path = {start_frame_path}")
                    state.setdefault("settings", {})["start_frame_path"] = start_frame_path
                    _save_state(state_path, state)
    elif chars_manifest_path.exists():
        with open(chars_manifest_path, "r") as f:
            char_manifest = json.load(f)

    # ── 3. Scene Generation ───────────────────────────────────
    scenes_manifest_path = _episode_path("scenes/scenes_manifest.json")
    scenes_manifest = {}
    if run_scenes_step:
        print("[step:scenes] Starting scene generation.")
        from agents.autoAnimator.chains.episode_planner import EpisodePlanner
        from agents.autoAnimator.chains.scene_gen import SceneGen

        planner_preflight = EpisodePlanner(
            model_name=planner_model,
            director_model_name=director_model,
            director_fallback_model_name=director_fallback_model,
            project_name=project_name,
            preset_prompt=preset_prompt,
            niche_name=niche_key,
            niche_context=niche_context,
            start_frame_path=start_frame_path,
            end_frame_path=end_frame_path,
            tts_voices_pool=tts_voices_pool,
            max_duration_mins=max_duration,
            max_chars=max_chars,
            max_panels=max_panels,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            theme=resolved_theme,
            model_stack={
                "character_image_model": char_image_model,
                "scene_image_model": scene_image_model,
                "tts_engine": "edge-tts",
                "music_provider": args.music_provider,
                "lyria_model": args.lyria_model,
            },
            episode_mode=(args.episode_mode == "true"),
            intro_only=intro_only,
            target_episode=args.episode,
            tracker=tracker,
            planner_skill_ids=valid_skill_ids,
            planner_skill_prompt=planner_skill_prompt,
            planner_skills_catalog=planner_skills_catalog,
        )
        manga_board = planner_preflight.prepare_for_scene_generation(manga_board, session_dir)
        ep_num = manga_board.get("episode_number", ep_num)
        ep_dir = session_dir / "episodes" / f"episode{ep_num}"
        mode_scope = "intro" if intro_only else "generic"

        scene_gen = SceneGen(
            image_model_name=scene_image_model,
            max_generations=scene_budget,
            resolution=resolution,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            project_name=project_name,
            tracker=tracker,
            scene_concurrency=scene_concurrency,
        )
        scenes_manifest = scene_gen.run(manga_board, char_manifest, session_dir)
        print("[step:scenes] Scene generation complete.")
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["scenes_generated"] = True
        _save_state(state_path, state)
    elif scenes_manifest_path.exists():
        with open(scenes_manifest_path, "r") as f:
            scenes_manifest = json.load(f)
    else:
        legacy_manifest_path = session_dir / "scenes" / "scenes_manifest.json"
        if legacy_manifest_path.exists():
            with open(legacy_manifest_path, "r") as f:
                scenes_manifest = json.load(f)

    # ── 4. TTS Generation ─────────────────────────────────────
    audio_dir = _episode_path("audio")
    audio_files = []
    if run_audio_step:
        print("[step:audio] Starting TTS generation.")
        if audio_future is not None:
            audio_files = audio_future.result()
            print("[step:audio] TTS generation complete (parallel result).")
        else:
            from agents.autoAnimator.chains.tts_gen import TTSGen

            tts_gen = TTSGen(
                voices_pool=tts_voices_pool,
                max_parallel_panels=tts_max_parallel_panels,
                tts_provider=tts_provider,
                gemini_tts_model=gemini_tts_model,
                tracker=tracker,
            )
            audio_files = tts_gen.run(manga_board, session_dir)
            print("[step:audio] TTS generation complete.")
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["audio_generated"] = True
        _save_state(state_path, state)
    else:
        if not audio_dir.exists():
            audio_dir = session_dir / "audio"
        audio_files = sorted(
            [str(p) for p in audio_dir.glob("panel_*.mp3")]
            + [str(p) for p in audio_dir.glob("panel_*.wav")]
        )

    # ── 5. Cloud Generation (OpenCV – no LLM) ────────────────
    if run_clouds_step:
        from agents.autoAnimator.chains.cloud_gen import CloudGen

        settings = state.get("settings", {})
        print("[step:clouds] Starting overlay generation.")
        primary_variant = "shorts" if args.format == "youtube_shorts" else "youtube_full"
        primary_cloud_tag = "shorts" if primary_variant == "shorts" else "youtube_full"

        def _run_cloud_primary():
            print(f"[clouds:{primary_cloud_tag}] Generating primary overlays.")
            primary_overlay_dir = _mode_rel_path(primary_variant, "overlays")
            cloud_gen = CloudGen(
                fps=fps,
                resolution=resolution,
                project_name=project_name,
                episode_number=ep_num,
                overlay_dir_name=primary_overlay_dir,
                scenes_dir_name=f"episodes/episode{ep_num}/scenes",
                audio_dir_name=f"episodes/episode{ep_num}/audio",
                log_prefix=f"[clouds:{primary_cloud_tag}]",
                use_panel_fps=(primary_variant != "shorts"),
                cloud_style=settings.get("cloud_style", "cloud-none"),
                font_style=settings.get("font_style", "font-geist-sans"),
                subtitle_style=settings.get("subtitle_style", "sub-clean-bottom"),
                narration_mode=settings.get("narration_mode", "hybrid_subtitles_clouds"),
                subtitle_scale=float(settings.get("subtitle_scale", 1.0) or 1.0),
                subtitle_x=settings.get("subtitle_x"),
                subtitle_y=settings.get("subtitle_y"),
                cloud_x=settings.get("cloud_x"),
                cloud_y=settings.get("cloud_y"),
                cloud_w=settings.get("cloud_w"),
                cloud_h=settings.get("cloud_h"),
                cloud_workers=cloud_workers,
            )
            cloud_gen.run(manga_board, session_dir)
            print(f"[clouds:{primary_cloud_tag}] Primary overlays ready.")

        def _run_cloud_shorts():
            shorts_cfg = output_presets.get("youtube_shorts", {})
            shorts_resolution = tuple(shorts_cfg.get("resolution", [1080, 1920]))
            shorts_fps = int(shorts_cfg.get("fps", fps))
            print("[clouds:shorts] Generating shorts overlays.")
            shorts_cloud_gen = CloudGen(
                fps=shorts_fps,
                resolution=shorts_resolution,
                project_name=project_name,
                episode_number=ep_num,
                overlay_dir_name=_mode_rel_path("shorts", "overlays"),
                scenes_dir_name=f"episodes/episode{ep_num}/scenes",
                audio_dir_name=f"episodes/episode{ep_num}/audio",
                log_prefix="[clouds:shorts]",
                use_panel_fps=False,
                cloud_style=settings.get("cloud_style", "cloud-none"),
                font_style=settings.get("font_style", "font-geist-sans"),
                subtitle_style=settings.get("subtitle_style", "sub-clean-bottom"),
                narration_mode=settings.get("narration_mode", "hybrid_subtitles_clouds"),
                subtitle_scale=float(settings.get("subtitle_scale", 1.0) or 1.0),
                subtitle_x=settings.get("subtitle_x"),
                subtitle_y=settings.get("subtitle_y"),
                cloud_x=settings.get("cloud_x"),
                cloud_y=settings.get("cloud_y"),
                cloud_w=settings.get("cloud_w"),
                cloud_h=settings.get("cloud_h"),
                cloud_workers=cloud_workers,
            )
            shorts_cloud_gen.run(manga_board, session_dir)
            print("[clouds:shorts] Shorts overlays ready.")

        shorts_enabled = (
            args.youtube_shorts_export == "on"
            or (args.youtube_shorts_export == "auto" and args.format == "youtube_widescreen")
        )
        should_generate_shorts_clouds = bool(shorts_enabled and output_presets.get("youtube_shorts"))
        if should_generate_shorts_clouds:
            with ThreadPoolExecutor(max_workers=2) as clouds_pool:
                futures = [
                    clouds_pool.submit(_run_cloud_primary),
                    clouds_pool.submit(_run_cloud_shorts),
                ]
                for f in futures:
                    f.result()
        else:
            _run_cloud_primary()

        print("[step:clouds] Overlay generation complete.")
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["clouds_generated"] = True
        _save_state(state_path, state)

    # ── 6. Music Generation (optional) ───────────────────────
    if run_music_step:
        print("[step:music] Starting music generation.")
        if enable_music:
            music_path = None
            if music_future is not None:
                try:
                    music_path = music_future.result()
                    print("[step:music] Music generation complete (parallel result).")
                except Exception as exc:
                    print(f"[step:music] Warning: music generation failed in parallel task: {exc}")
                    music_path = None
            else:
                from agents.autoAnimator.chains.music_gen import MusicGen

                music_gen = MusicGen(
                    model_name=planner_model,
                    music_provider=args.music_provider,
                    lyria_model=args.lyria_model,
                    tracker=tracker,
                )
                try:
                    music_path = music_gen.run(manga_board, session_dir, base_prompt=base_prompt)
                    print("[step:music] Music generation complete.")
                except Exception as exc:
                    print(f"[step:music] Warning: music generation failed: {exc}")
                    music_path = None
            state.setdefault("episodes", {}).setdefault(str(ep_num), {})["music_generated"] = bool(music_path)
            _save_state(state_path, state)
        else:
            print("Music step skipped because music is disabled (--enable_music not set).")
            state.setdefault("episodes", {}).setdefault(str(ep_num), {})["music_generated"] = False
            _save_state(state_path, state)

    # ── 7. Movie Maker ────────────────────────────────────────
    if run_video_step:
        print("[step:video] Starting video assembly.")
        from agents.autoAnimator.chains.moviemaker import MovieMaker

        if not scenes_manifest and scenes_manifest_path.exists():
            with open(scenes_manifest_path, "r") as f:
                scenes_manifest = json.load(f)
        if not scenes_manifest:
            legacy_manifest_path = session_dir / "scenes" / "scenes_manifest.json"
            if legacy_manifest_path.exists():
                with open(legacy_manifest_path, "r") as f:
                    scenes_manifest = json.load(f)
        if not audio_files:
            if not audio_dir.exists():
                audio_dir = session_dir / "audio"
            audio_files = sorted(
                [str(p) for p in audio_dir.glob("panel_*.mp3")]
                + [str(p) for p in audio_dir.glob("panel_*.wav")]
            )

        primary_variant = "shorts" if args.format == "youtube_shorts" else "youtube_full"

        def _render_primary() -> Path:
            output_suffix = (args.format or "youtube_widescreen")
            maker = MovieMaker(
                fps=fps,
                resolution=resolution,
                enable_music=enable_music,
                segment_workers=segment_workers,
                use_panel_fps=(primary_variant != "shorts"),
            )
            return maker.run(
                manga_board,
                scenes_manifest,
                audio_files,
                session_dir,
                project_name=project_name,
                output_suffix=output_suffix,
                overlay_dir_name=_mode_rel_path(primary_variant, "overlays"),
                output_dir_name=_mode_rel_path(primary_variant),
                max_duration_seconds=float(max_duration * 60),
            )

        rendered_videos = []
        final_video = Path("")

        # When YouTube full video is selected, also export a Shorts variant by default.
        if shorts_enabled and output_presets.get("youtube_shorts"):
            shorts_cfg = output_presets.get("youtube_shorts", {})
            shorts_resolution = tuple(shorts_cfg.get("resolution", [1080, 1920]))
            shorts_fps = int(shorts_cfg.get("fps", fps))

            def _render_shorts() -> Path:
                from agents.autoAnimator.chains.cloud_gen import CloudGen

                # Ensure shorts overlays exist; generate only if missing (e.g. video-only rerun).
                shorts_overlay_root = session_dir / _mode_rel_path("shorts", "overlays")
                if not shorts_overlay_root.exists() or not any(shorts_overlay_root.iterdir()):
                    settings = state.get("settings", {})
                    print("[video:shorts] Shorts overlays missing; generating before render.")
                    shorts_cloud_gen = CloudGen(
                        fps=shorts_fps,
                        resolution=shorts_resolution,
                        project_name=project_name,
                        episode_number=ep_num,
                        overlay_dir_name=_mode_rel_path("shorts", "overlays"),
                        scenes_dir_name=f"episodes/episode{ep_num}/scenes",
                        audio_dir_name=f"episodes/episode{ep_num}/audio",
                        log_prefix="[video:shorts:clouds]",
                        use_panel_fps=False,
                        cloud_style=settings.get("cloud_style", "cloud-none"),
                        font_style=settings.get("font_style", "font-geist-sans"),
                        subtitle_style=settings.get("subtitle_style", "sub-clean-bottom"),
                        narration_mode=settings.get("narration_mode", "hybrid_subtitles_clouds"),
                        subtitle_scale=float(settings.get("subtitle_scale", 1.0) or 1.0),
                        subtitle_x=settings.get("subtitle_x"),
                        subtitle_y=settings.get("subtitle_y"),
                        cloud_x=settings.get("cloud_x"),
                        cloud_y=settings.get("cloud_y"),
                        cloud_w=settings.get("cloud_w"),
                        cloud_h=settings.get("cloud_h"),
                        cloud_workers=cloud_workers,
                    )
                    shorts_cloud_gen.run(manga_board, session_dir)
                else:
                    print("[video:shorts] Reusing pre-generated shorts overlays.")

                shorts_maker = MovieMaker(
                    fps=shorts_fps,
                    resolution=shorts_resolution,
                    enable_music=enable_music,
                    segment_workers=segment_workers,
                    use_panel_fps=False,
                )
                return shorts_maker.run(
                    manga_board,
                    scenes_manifest,
                    audio_files,
                    session_dir,
                    project_name=project_name,
                    output_suffix="youtube_shorts",
                    overlay_dir_name=_mode_rel_path("shorts", "overlays"),
                    output_dir_name=_mode_rel_path("shorts"),
                    max_duration_seconds=float(max_duration * 60),
                )

            with ThreadPoolExecutor(max_workers=2) as render_pool:
                print("[step:video] Rendering fullvideo and shorts in parallel.")
                wide_future = render_pool.submit(_render_primary)
                shorts_future = render_pool.submit(_render_shorts)
                final_video = wide_future.result()
                shorts_video = shorts_future.result()

            if final_video:
                rendered_videos.append(str(final_video))
            if shorts_video:
                rendered_videos.append(str(shorts_video))
        else:
            final_video = _render_primary()
            if final_video:
                rendered_videos.append(str(final_video))
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["status"] = "complete"
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["video"] = str(final_video)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["videos"] = rendered_videos
        _save_state(state_path, state)

        if vector_upscale:
            print("Vector upscale requested, stub behavior: upscaling is not yet implemented.")

        print(f"Task Complete. Final Output: {final_video}")
        if len(rendered_videos) > 1:
            print(f"Additional outputs: {rendered_videos[1:]}")
        print("[step:video] Video assembly complete.")
    elif run_specific_step:
        print(f"Step '{args.step}' complete in {session_dir}")

    # ── Save LLM usage report ─────────────────────────────────
    if executor is not None:
        executor.shutdown(wait=False)

    if tracker.calls:
        tracker.save(session_dir)


# ── State helpers ─────────────────────────────────────────────

def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path, "r") as f:
            return json.load(f)
    return {"latest_episode": 0, "episodes": {}}


def _save_state(state_path: Path, state: dict):
    with _STATE_WRITE_LOCK:
        tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, state_path)


def _load_storyboard(session_dir: Path, episode_num: int = None) -> dict | None:
    """Load storyboard JSON for the target episode."""
    _BOARD_NAMES = ("storyboard.json",)
    episodes_dir = session_dir / "episodes"
    if not episodes_dir.exists():
        return None

    if episode_num:
        ep_dir = episodes_dir / f"episode{episode_num}"
        for name in _BOARD_NAMES:
            board_path = ep_dir / name
            if board_path.exists():
                with open(board_path, "r") as f:
                    return json.load(f)
        return None

    existing = sorted(
        [d for d in episodes_dir.iterdir() if d.is_dir() and d.name.startswith("episode")],
        key=lambda p: p.name,
    )
    if existing:
        for name in _BOARD_NAMES:
            board_path = existing[-1] / name
            if board_path.exists():
                with open(board_path, "r") as f:
                    return json.load(f)
    return None


if __name__ == "__main__":
    main()
