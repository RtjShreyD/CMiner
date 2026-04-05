#!/usr/bin/env python3
"""AutoAnimator Pipeline Runner – Episodic video generation with state management."""

import argparse
import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.autoAnimator.utils import ensure_session_outputs, get_model
from agents.shared.llm_tracker import LLMTracker


def _first_key(mapping: dict) -> str | None:
    for k in mapping.keys():
        return str(k)
    return None


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


def main():
    parser = argparse.ArgumentParser(description="AutoAnimator Pipeline Runner")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--prompt", help="Override base prompt (otherwise reads prompt.txt)")
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
    parser.add_argument("--vector_upscale", action="store_true", help="Apply upscale stub after image generation")
    parser.add_argument("--enable_music", action="store_true", help="Include background music in final video")
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
    parser.add_argument("--planner_model", help="Override planner model name")
    parser.add_argument("--character_image_model", help="Override character image model name")
    parser.add_argument("--scene_image_model", help="Override scene image model name")
    parser.add_argument(
        "--music_provider",
        choices=["strudel", "lyria"],
        default="strudel",
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
        session_dir = ensure_session_outputs(workspace)
        print(f"New session directory: {session_dir}")

    # ── Load Config ───────────────────────────────────────────
    config_path = Path(__file__).resolve().parent / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)

    models_config = config.get("models", {})
    planner_model = models_config.get("planner_model", "models/gemini-flash-latest")
    char_image_model = models_config.get("character_image_model", "models/gemini-2.5-flash-image")
    scene_image_model = models_config.get("scene_image_model", "models/gemini-2.5-flash-image")
    max_image_requests = models_config.get("max_image_requests", 50)
    max_chars = models_config.get("max_chars_per_episode", 5)
    max_panels = models_config.get("max_panels_per_episode", 15)
    max_duration = models_config.get("max_episode_duration_mins", 5)

    if args.max_image_requests:
        max_image_requests = args.max_image_requests
    if args.max_chars_per_episode:
        max_chars = args.max_chars_per_episode
    if args.max_panels_per_episode:
        max_panels = args.max_panels_per_episode
    if args.max_episode_duration_mins:
        max_duration = args.max_episode_duration_mins
    if args.planner_model:
        planner_model = args.planner_model
    if args.character_image_model:
        char_image_model = args.character_image_model
    if args.scene_image_model:
        scene_image_model = args.scene_image_model
    tts_voices_pool = config.get("tts_voices_pool", {})

    base_prompt = args.prompt or ""
    if not base_prompt:
        prompt_file = Path(__file__).resolve().parent / "prompt.txt"
        if prompt_file.exists():
            base_prompt = prompt_file.read_text().strip()
            print(f"Loaded base prompt from {prompt_file}")
        else:
            base_prompt = "A dramatic manga story."

    # Style/theme presets
    themes = config.get("themes", {})
    art_styles = config.get("art_styles", {})
    output_presets = config.get("output_presets", {})

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
    fps = video_config.get("fps", 8)
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

    # ── State Management ──────────────────────────────────────
    state_path = session_dir / "session_state.json"
    state = _load_state(state_path)

    state.setdefault("settings", {}).update({
        "prompt": base_prompt,
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
        "cloud_style": args.cloud_style or "cloud-none",
        "font_style": args.font_style or "font-geist-sans",
        "subtitle_style": args.subtitle_style or "sub-clean-bottom",
        "narration_mode": args.narration_mode or "hybrid_subtitles_clouds",
        "subtitle_scale": args.subtitle_scale if args.subtitle_scale is not None else 1.0,
        "episode_mode": args.episode_mode == "true",
    })
    _save_state(state_path, state)

    print(f"Session: {session_dir}")
    print(f"Config: fps={fps}, max_image_requests={max_image_requests}, max_chars={max_chars}")
    print(f"Theme selected: {selected_theme_key or 'none'}")
    print(f"Style keys selected: {', '.join(selected_style_keys) if selected_style_keys else 'none'}")
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
            tts_voices_pool=tts_voices_pool,
            max_duration_mins=max_duration,
            max_chars=max_chars,
            max_panels=max_panels,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            theme=resolved_theme,
            episode_mode=(args.episode_mode == "true"),
            target_episode=args.episode,
            tracker=tracker,
        )
        manga_board = planner.run(base_prompt, session_dir)

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
        manga_board = _load_manga_board(session_dir, args.episode)
        if manga_board is None:
            print("Error: No manga-board.json found. Run 'planner' step first.")
            sys.exit(1)

    ep_num = manga_board.get("episode_number", 1)
    ep_dir = session_dir / "episodes" / f"episode{ep_num}"

    # ── Calculate image budget ────────────────────────────────
    num_chars = len(manga_board.get("characters", []))
    num_panels = len(manga_board.get("panels", []))
    char_budget = min(num_chars, max_chars)
    scene_budget = min(num_panels, max_image_requests - char_budget)
    print(f"Image budget: {char_budget} chars + {scene_budget} scenes = {char_budget + scene_budget}/{max_image_requests}")

    # ── 2. Character Generation ───────────────────────────────
    chars_manifest_path = session_dir / "chars" / "chars_manifest.json"
    char_manifest = {}
    if args.step in ["all", "chars"] or (run_generation and not run_specific_step):
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
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["chars_generated"] = True
        _save_state(state_path, state)
    elif chars_manifest_path.exists():
        with open(chars_manifest_path, "r") as f:
            char_manifest = json.load(f)

    # ── 3. Scene Generation ───────────────────────────────────
    scenes_manifest_path = session_dir / "scenes" / "scenes_manifest.json"
    scenes_manifest = {}
    if args.step in ["all", "scenes"] or (run_generation and not run_specific_step):
        from agents.autoAnimator.chains.scene_gen import SceneGen

        scene_gen = SceneGen(
            image_model_name=scene_image_model,
            max_generations=scene_budget,
            resolution=resolution,
            art_style=art_style,
            aesthetic_guidance=aesthetic_guidance,
            tracker=tracker,
        )
        scenes_manifest = scene_gen.run(manga_board, char_manifest, session_dir)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["scenes_generated"] = True
        _save_state(state_path, state)
    elif scenes_manifest_path.exists():
        with open(scenes_manifest_path, "r") as f:
            scenes_manifest = json.load(f)

    # ── 4. TTS Generation ─────────────────────────────────────
    audio_dir = session_dir / "audio"
    audio_files = []
    if args.step in ["all", "audio"] or (run_generation and not run_specific_step):
        from agents.autoAnimator.chains.tts_gen import TTSGen

        tts_gen = TTSGen(voices_pool=tts_voices_pool)
        audio_files = tts_gen.run(manga_board, session_dir)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["audio_generated"] = True
        _save_state(state_path, state)
    else:
        audio_files = sorted(
            [str(p) for p in audio_dir.glob("panel_*.mp3")]
            + [str(p) for p in audio_dir.glob("panel_*.wav")]
        )

    # ── 5. Cloud Generation (OpenCV – no LLM) ────────────────
    if args.step in ["all", "clouds"] or (run_generation and not run_specific_step):
        from agents.autoAnimator.chains.cloud_gen import CloudGen

        settings = state.get("settings", {})
        cloud_gen = CloudGen(
            fps=fps,
            resolution=resolution,
            cloud_style=settings.get("cloud_style", "cloud-none"),
            font_style=settings.get("font_style", "font-geist-sans"),
            subtitle_style=settings.get("subtitle_style", "sub-clean-bottom"),
            narration_mode=settings.get("narration_mode", "hybrid_subtitles_clouds"),
            subtitle_scale=float(settings.get("subtitle_scale", 1.0) or 1.0),
        )
        cloud_gen.run(manga_board, session_dir)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["clouds_generated"] = True
        _save_state(state_path, state)

    # ── 6. Music Generation (optional) ───────────────────────
    if args.step in ["all", "music"] or (run_generation and not run_specific_step):
        if enable_music:
            from agents.autoAnimator.chains.music_gen import MusicGen

            music_gen = MusicGen(
                model_name=planner_model,
                music_provider=args.music_provider,
                lyria_model=args.lyria_model,
                tracker=tracker,
            )
            music_path = music_gen.run(manga_board, session_dir, base_prompt=base_prompt)
            state.setdefault("episodes", {}).setdefault(str(ep_num), {})["music_generated"] = bool(music_path)
            _save_state(state_path, state)
        else:
            print("Music step skipped because music is disabled (--enable_music not set).")
            state.setdefault("episodes", {}).setdefault(str(ep_num), {})["music_generated"] = False
            _save_state(state_path, state)

    # ── 7. Movie Maker ────────────────────────────────────────
    if args.step in ["all", "video"] or (run_generation and not run_specific_step):
        from agents.autoAnimator.chains.moviemaker import MovieMaker

        if not scenes_manifest and scenes_manifest_path.exists():
            with open(scenes_manifest_path, "r") as f:
                scenes_manifest = json.load(f)
        if not audio_files:
            audio_files = sorted(
                [str(p) for p in audio_dir.glob("panel_*.mp3")]
                + [str(p) for p in audio_dir.glob("panel_*.wav")]
            )

        maker = MovieMaker(fps=fps, resolution=resolution, enable_music=enable_music)
        final_video = maker.run(manga_board, scenes_manifest, audio_files, session_dir)
        rendered_videos = [str(final_video)] if final_video else []

        # When YouTube Video is selected, also export a Shorts variant by default.
        if args.format == "youtube_widescreen" and output_presets.get("youtube_shorts"):
            shorts_cfg = output_presets.get("youtube_shorts", {})
            shorts_resolution = tuple(shorts_cfg.get("resolution", [1080, 1920]))
            shorts_fps = int(shorts_cfg.get("fps", fps))
            shorts_maker = MovieMaker(fps=shorts_fps, resolution=shorts_resolution, enable_music=enable_music)
            shorts_video = shorts_maker.run(
                manga_board,
                scenes_manifest,
                audio_files,
                session_dir,
                output_suffix="youtube_shorts",
            )
            if shorts_video:
                rendered_videos.append(str(shorts_video))
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["status"] = "complete"
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["video"] = str(final_video)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["videos"] = rendered_videos
        _save_state(state_path, state)

        if vector_upscale:
            print("Vector upscale requested, stub behavior: upscaling is not yet implemented.")

        print(f"Task Complete. Final Output: {final_video}")
        if len(rendered_videos) > 1:
            print(f"Additional outputs: {rendered_videos[1:]}")
    elif run_specific_step:
        print(f"Step '{args.step}' complete in {session_dir}")

    # ── Save LLM usage report ─────────────────────────────────
    if tracker.calls:
        tracker.save(session_dir)


# ── State helpers ─────────────────────────────────────────────

def _load_state(state_path: Path) -> dict:
    if state_path.exists():
        with open(state_path, "r") as f:
            return json.load(f)
    return {"latest_episode": 0, "episodes": {}}


def _save_state(state_path: Path, state: dict):
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _load_manga_board(session_dir: Path, episode_num: int = None) -> dict | None:
    episodes_dir = session_dir / "episodes"
    if not episodes_dir.exists():
        return None

    if episode_num:
        board_path = episodes_dir / f"episode{episode_num}" / "manga-board.json"
        if board_path.exists():
            with open(board_path, "r") as f:
                return json.load(f)
        return None

    existing = sorted(
        [d for d in episodes_dir.iterdir() if d.is_dir() and d.name.startswith("episode")],
        key=lambda p: p.name,
    )
    if existing:
        board_path = existing[-1] / "manga-board.json"
        if board_path.exists():
            with open(board_path, "r") as f:
                return json.load(f)
    return None


if __name__ == "__main__":
    main()
