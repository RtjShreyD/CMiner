#!/usr/bin/env python3
"""NarrativeManga Pipeline Runner – Episodic video generation with state management."""

import argparse
import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from agents.narrativeManga.utils import ensure_session_outputs, get_model
from agents.shared.llm_tracker import LLMTracker


def main():
    parser = argparse.ArgumentParser(description="NarrativeManga Pipeline Runner")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--prompt", help="Override base prompt (otherwise reads prompt.txt)")
    parser.add_argument(
        "--step",
        choices=["all", "planner", "chars", "scenes", "audio", "clouds", "video"],
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
    tts_voices_pool = config.get("tts_voices_pool", {})

    # Style/theme presets
    themes = config.get("themes", {})
    art_styles = config.get("art_styles", {})
    output_presets = config.get("output_presets", {})

    base_prompt = args.prompt or ""
    if args.theme and args.theme in themes and not base_prompt:
        base_prompt = themes[args.theme]

    if args.preset and args.preset in art_styles:
        art_style = art_styles[args.preset]
    else:
        art_style = config.get("art_style", "cinematic anime")

    video_config = config.get("video", {})
    resolution = tuple(video_config.get("resolution", [1280, 720]))
    fps = video_config.get("fps", 8)
    target_duration = video_config.get("target_duration_mins", 5)

    if args.format and args.format in output_presets:
        preset_cfg = output_presets[args.format]
        resolution = tuple(preset_cfg.get("resolution", list(resolution)))
        fps = preset_cfg.get("fps", fps)
        target_duration = preset_cfg.get("duration_mins", target_duration)

    enable_music = args.enable_music
    vector_upscale = args.vector_upscale

    if not base_prompt:
        prompt_file = Path(__file__).resolve().parent / "prompt.txt"
        if prompt_file.exists():
            base_prompt = prompt_file.read_text().strip()
            print(f"Loaded base prompt from {prompt_file}")
        else:
            base_prompt = "A dramatic manga story."

    # ── State Management ──────────────────────────────────────
    state_path = session_dir / "session_state.json"
    state = _load_state(state_path)

    state.setdefault("settings", {}).update({
        "theme": args.theme,
        "preset": args.preset,
        "format": args.format,
        "resolution": list(resolution),
        "fps": fps,
        "enable_music": enable_music,
        "vector_upscale": vector_upscale,
        "max_image_requests": max_image_requests,
        "max_chars_per_episode": max_chars,
        "max_panels_per_episode": max_panels,
        "max_episode_duration_mins": max_duration,
    })
    _save_state(state_path, state)

    print(f"Session: {session_dir}")
    print(f"Config: fps={fps}, max_image_requests={max_image_requests}, max_chars={max_chars}")

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
        from agents.narrativeManga.chains.episode_planner import EpisodePlanner

        planner = EpisodePlanner(
            model_name=planner_model,
            tts_voices_pool=tts_voices_pool,
            max_duration_mins=max_duration,
            max_chars=max_chars,
            max_panels=max_panels,
            art_style=art_style,
            theme=args.theme,
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
        from agents.narrativeManga.chains.char_gen import CharGen

        char_gen = CharGen(
            image_model_name=char_image_model,
            max_generations=char_budget,
            resolution=resolution,
            art_style=art_style,
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
        from agents.narrativeManga.chains.scene_gen import SceneGen

        scene_gen = SceneGen(
            image_model_name=scene_image_model,
            max_generations=scene_budget,
            resolution=resolution,
            art_style=art_style,
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
        from agents.narrativeManga.chains.tts_gen import TTSGen

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
        from agents.narrativeManga.chains.cloud_gen import CloudGen

        cloud_gen = CloudGen(fps=fps, resolution=resolution)
        cloud_gen.run(manga_board, session_dir)
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["clouds_generated"] = True
        _save_state(state_path, state)

    # ── 6. Movie Maker ────────────────────────────────────────
    if args.step in ["all", "video"] or (run_generation and not run_specific_step):
        from agents.narrativeManga.chains.moviemaker import MovieMaker

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
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["status"] = "complete"
        state.setdefault("episodes", {}).setdefault(str(ep_num), {})["video"] = str(final_video)
        _save_state(state_path, state)

        if vector_upscale:
            print("Vector upscale requested, stub behavior: upscaling is not yet implemented.")

        print(f"Task Complete. Final Output: {final_video}")
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
