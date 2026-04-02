import asyncio
import json
import hashlib
import random
import shutil
import io
import subprocess
import sys
import threading
import uuid
from contextlib import redirect_stdout, redirect_stderr
from queue import Empty, Queue
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from agents.shared.gemini_compat import make_gemini_client
from agents.shared.llm_tracker import LLMTracker

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT_DIR / "outputs"
NARRATIVE_RUNNER = ROOT_DIR / "agents" / "narrativeManga" / "run.py"
NARRATIVE_JOBS: dict[str, dict[str, Any]] = {}
NARRATIVE_JOBS_LOCK = threading.Lock()


def _python_bin() -> str:
    return sys.executable


def _resolve_session_dir(session_path: str) -> Path:
    candidate = (OUTPUTS_DIR / session_path).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if not str(candidate).startswith(str(outputs_root)):
        raise HTTPException(status_code=403, detail="Invalid session path")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Session path not found")
    return candidate


def _to_rel_session_path(session_dir: Path) -> str:
    try:
        return str(session_dir.relative_to(OUTPUTS_DIR.resolve()))
    except Exception:
        return str(session_dir)


def _extract_session_path_from_stdout(stdout: str) -> str | None:
    for line in stdout.splitlines():
        marker = "New session directory:"
        if marker in line:
            abs_path = line.split(marker, 1)[1].strip()
            p = Path(abs_path)
            if p.exists():
                try:
                    return str(p.resolve().relative_to(OUTPUTS_DIR.resolve()))
                except Exception:
                    return None
    return None


def _build_narrative_cmd(
    *,
    step: str,
    prompt: str | None,
    session_path: str | None,
    episodes: str = "new",
    develop: bool = False,
    episode: int | None = None,
    theme: str | None = None,
    preset: str | None = None,
    fmt: str | None = None,
    enable_music: bool = False,
    max_image_requests: int | None = None,
    max_chars_per_episode: int | None = None,
    max_panels_per_episode: int | None = None,
    max_episode_duration_mins: int | None = None,
    resolution_w: int | None = None,
    resolution_h: int | None = None,
    cloud_style: str | None = None,
    font_style: str | None = None,
    subtitle_style: str | None = None,
    narration_mode: str | None = None,
    subtitle_scale: float | None = None,
    episode_mode: bool = True,
    planner_model: str | None = None,
    chars_model: str | None = None,
    scenes_model: str | None = None,
    music_provider: str | None = None,
    lyria_model: str | None = None,
) -> list[str]:
    cmd = [
        _python_bin(),
        str(NARRATIVE_RUNNER),
        "--workspace",
        str(ROOT_DIR),
        "--step",
        step,
    ]
    if prompt:
        cmd.extend(["--prompt", prompt])
    if session_path:
        cmd.extend(["--session", str(OUTPUTS_DIR / session_path)])
    if episodes == "continue":
        cmd.extend(["--episodes", "continue"])
    if develop:
        cmd.append("--develop")
    if episode is not None:
        cmd.extend(["--episode", str(episode)])
    if theme:
        cmd.extend(["--theme", theme])
    if preset:
        cmd.extend(["--preset", preset])
    if fmt:
        cmd.extend(["--format", fmt])
    if enable_music:
        cmd.append("--enable_music")
    if max_image_requests is not None:
        cmd.extend(["--max_image_requests", str(max_image_requests)])
    if max_chars_per_episode is not None:
        cmd.extend(["--max_chars_per_episode", str(max_chars_per_episode)])
    if max_panels_per_episode is not None:
        cmd.extend(["--max_panels_per_episode", str(max_panels_per_episode)])
    if max_episode_duration_mins is not None:
        cmd.extend(["--max_episode_duration_mins", str(max_episode_duration_mins)])
    if resolution_w is not None and resolution_h is not None:
        cmd.extend(["--resolution_w", str(resolution_w), "--resolution_h", str(resolution_h)])
    if cloud_style:
        cmd.extend(["--cloud_style", cloud_style])
    if font_style:
        cmd.extend(["--font_style", font_style])
    if subtitle_style:
        cmd.extend(["--subtitle_style", subtitle_style])
    if narration_mode:
        cmd.extend(["--narration_mode", narration_mode])
    if subtitle_scale is not None:
        cmd.extend(["--subtitle_scale", str(subtitle_scale)])
    cmd.extend(["--episode_mode", "true" if episode_mode else "false"])
    if planner_model:
        cmd.extend(["--planner_model", planner_model])
    if chars_model:
        cmd.extend(["--character_image_model", chars_model])
    if scenes_model:
        cmd.extend(["--scene_image_model", scenes_model])
    if music_provider:
        cmd.extend(["--music_provider", music_provider])
    if lyria_model:
        cmd.extend(["--lyria_model", lyria_model])
    return cmd


def _run_narrative_step(
    *,
    step: str,
    prompt: str | None,
    session_path: str | None,
    episodes: str = "new",
    develop: bool = False,
    episode: int | None = None,
    theme: str | None = None,
    preset: str | None = None,
    fmt: str | None = None,
    enable_music: bool = False,
    max_image_requests: int | None = None,
    max_chars_per_episode: int | None = None,
    max_panels_per_episode: int | None = None,
    max_episode_duration_mins: int | None = None,
    resolution_w: int | None = None,
    resolution_h: int | None = None,
    cloud_style: str | None = None,
    font_style: str | None = None,
    subtitle_style: str | None = None,
    narration_mode: str | None = None,
    subtitle_scale: float | None = None,
    episode_mode: bool = True,
    planner_model: str | None = None,
    chars_model: str | None = None,
    scenes_model: str | None = None,
    music_provider: str | None = None,
    lyria_model: str | None = None,
) -> dict[str, Any]:
    cmd = _build_narrative_cmd(
        step=step,
        prompt=prompt,
        session_path=session_path,
        episodes=episodes,
        develop=develop,
        episode=episode,
        theme=theme,
        preset=preset,
        fmt=fmt,
        enable_music=enable_music,
        max_image_requests=max_image_requests,
        max_chars_per_episode=max_chars_per_episode,
        max_panels_per_episode=max_panels_per_episode,
        max_episode_duration_mins=max_episode_duration_mins,
        resolution_w=resolution_w,
        resolution_h=resolution_h,
        font_style=font_style,
        subtitle_style=subtitle_style,
        narration_mode=narration_mode,
        subtitle_scale=subtitle_scale,
        episode_mode=episode_mode,
        planner_model=planner_model,
        chars_model=chars_model,
        scenes_model=scenes_model,
        music_provider=music_provider,
        lyria_model=lyria_model,
    )

    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True, check=False)
    detected_session_path = _extract_session_path_from_stdout(proc.stdout)
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "session_path": session_path or detected_session_path,
    }


def _step_reset_paths(session_dir: Path, step: str) -> list[Path]:
    mapping: dict[str, list[Path]] = {
        "planner": [session_dir / "episodes", session_dir / "session_state.json"],
        "chars": [session_dir / "chars"],
        "scenes": [session_dir / "scenes"],
        "audio": [session_dir / "audio"],
        "texts": [session_dir / "overlays"],
        "clouds": [session_dir / "overlays"],
        "music": [session_dir / "music"],
        "video": [session_dir / "frames", session_dir / "concat.txt", session_dir / "thumbnail.jpg"],
        "all": [
            session_dir / "episodes",
            session_dir / "chars",
            session_dir / "scenes",
            session_dir / "audio",
            session_dir / "overlays",
            session_dir / "music",
            session_dir / "frames",
            session_dir / "concat.txt",
            session_dir / "thumbnail.jpg",
        ],
    }
    return mapping.get(step, [])


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _collect_step_files(session_dir: Path, step: str) -> list[Path]:
    if step == "planner":
        return sorted(list((session_dir / "episodes").glob("episode*/manga-board.json")))
    if step == "chars":
        return sorted(list((session_dir / "chars").glob("*.png")) + list((session_dir / "chars").glob("*.json")))
    if step == "scenes":
        return sorted(list((session_dir / "scenes").glob("*.png")) + list((session_dir / "scenes").glob("*.json")))
    if step == "audio":
        return sorted(list((session_dir / "audio").glob("panel_*.*")))
    if step == "texts":
        return sorted(list((session_dir / "overlays").glob("**/*.png")))
    if step == "music":
        return sorted(
            list((session_dir / "music").glob("*.mp3"))
            + list((session_dir / "music").glob("*.wav"))
            + list((session_dir / "music").glob("*.aac"))
            + list((session_dir / "music").glob("*.txt"))
            + list((session_dir / "music").glob("*.json"))
        )
    if step == "video":
        return sorted(
            list(session_dir.glob("*.mp4"))
            + list(session_dir.glob("seg_*.mp4"))
            + list(session_dir.glob("thumbnail.jpg"))
            + list(session_dir.glob("metadata.json"))
        )
    return []


def _step_hash(session_dir: Path, step: str) -> str | None:
    files = _collect_step_files(session_dir, step)
    if not files:
        return None
    hasher = hashlib.sha256()
    for f in files:
        stat = f.stat()
        hasher.update(str(f.relative_to(session_dir)).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("utf-8"))
        hasher.update(str(int(stat.st_mtime)).encode("utf-8"))
    return hasher.hexdigest()[:16]


def _workflow_hashes(session_dir: Path) -> dict[str, str | None]:
    return {
        "planner": _step_hash(session_dir, "planner"),
        "chars": _step_hash(session_dir, "chars"),
        "scenes": _step_hash(session_dir, "scenes"),
        "audio": _step_hash(session_dir, "audio"),
        "texts": _step_hash(session_dir, "texts"),
        "music": _step_hash(session_dir, "music"),
        "video": _step_hash(session_dir, "video"),
    }


def _job_state(job_id: str) -> dict[str, Any] | None:
    with NARRATIVE_JOBS_LOCK:
        return NARRATIVE_JOBS.get(job_id)


def _create_job(job_id: str) -> dict[str, Any]:
    state = {"queue": Queue(), "done": False, "result": None}
    with NARRATIVE_JOBS_LOCK:
        NARRATIVE_JOBS[job_id] = state
    return state


def _run_narrative_step_worker(job_id: str, req: Any, step: str, res: tuple[int, int] | None):
    state = _job_state(job_id)
    if not state:
        return

    q: Queue = state["queue"]
    q.put({"type": "info", "msg": f"Starting step '{req.step}'..."})

    cmd = _build_narrative_cmd(
        step=step,
        prompt=req.prompt,
        session_path=req.session_path if req.session_mode == "existing" else req.session_path,
        episodes=req.episodes,
        develop=req.develop,
        episode=req.episode,
        theme=req.theme,
        preset=req.preset,
        fmt=req.format,
        enable_music=req.enable_music,
        max_image_requests=req.max_image_requests,
        max_chars_per_episode=req.max_chars_per_episode,
        max_panels_per_episode=req.max_panels_per_episode,
        max_episode_duration_mins=req.max_episode_duration_mins,
        resolution_w=res[0] if res else None,
        resolution_h=res[1] if res else None,
        cloud_style=req.cloud_style,
        font_style=req.font_style,
        subtitle_style=req.subtitle_style,
        narration_mode=req.narration_mode,
        subtitle_scale=req.subtitle_scale,
        episode_mode=req.episode_mode,
        planner_model=req.planner_model,
        chars_model=req.chars_model,
        scenes_model=req.scenes_model,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
    )

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    detected_session_path = req.session_path

    def _drain_stdout():
        nonlocal detected_session_path
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            stdout_lines.append(line)
            q.put({"type": "log", "msg": line})
            maybe = _extract_session_path_from_stdout(line)
            if maybe:
                detected_session_path = maybe

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip("\n")
            if not line:
                continue
            stderr_lines.append(line)
            q.put({"type": "error", "msg": line})

    t_out = threading.Thread(target=_drain_stdout, daemon=True)
    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out.start()
    t_err.start()
    exit_code = proc.wait()
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    hashes = None
    if detected_session_path:
        try:
            hashes = _workflow_hashes(_resolve_session_dir(detected_session_path))
        except Exception:
            hashes = None

    result = {
        "status": "success" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "step": req.step,
        "session_path": detected_session_path,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "hashes": hashes,
    }
    state["result"] = result
    state["done"] = True
    q.put({"type": "success" if exit_code == 0 else "error", "msg": f"Step '{req.step}' finished with status {result['status']}."})

class RunAgentRequest(BaseModel):
    agent_name: str
    cmd_args: str | None = None
    prompt: str | None = None
    theme: str | None = None
    preset: str | None = None
    format: str | None = None
    cloud_style: str | None = None
    font_style: str | None = None
    session_mode: str = "new"
    session_path: str | None = None
    enable_music: bool = False
    music_provider: str = "strudel"
    lyria_model: str = "lyria-3-clip-preview"
    narration_mode: str | None = None
    character_pack_id: str | None = None
    reuse_session_chars: bool = False
    session_chars_path: str | None = None
    selected_session_character: str | None = None
    max_image_requests: int | None = None
    max_chars_per_episode: int | None = None
    max_panels_per_episode: int | None = None
    max_episode_duration_mins: int | None = None


class RunNarrativeStepRequest(BaseModel):
    session_mode: str = "new"
    session_path: str | None = None
    step: str = Field(default="all", pattern="^(all|planner|chars|scenes|audio|texts|music|video)$")
    reset: bool = False
    redo: bool = False
    prompt: str | None = None
    episodes: str = "new"
    develop: bool = False
    episode: int | None = None
    theme: str | None = None
    preset: str | None = None
    format: str | None = None
    enable_music: bool = False
    narration_mode: str | None = None
    max_image_requests: int | None = None
    max_chars_per_episode: int | None = None
    max_panels_per_episode: int | None = None
    max_episode_duration_mins: int | None = None
    buildpack_resolution: str | None = None
    cloud_style: str | None = None
    font_style: str | None = None
    subtitle_style: str | None = None
    subtitle_scale: float | None = None
    episode_mode: bool = True
    planner_model: str | None = None
    chars_model: str | None = None
    scenes_model: str | None = None
    music_provider: str | None = None
    lyria_model: str | None = None
    chars_visual_overrides: dict[str, str] | None = None


class CopyCharacterRequest(BaseModel):
    source_path: str
    target_session_path: str | None = None


class SessionLocksRequest(BaseModel):
    session_path: str
    locks: dict[str, bool]


class SessionStateSyncRequest(BaseModel):
    session_path: str
    settings: dict[str, Any] = Field(default_factory=dict)
    locks: dict[str, bool] = Field(default_factory=dict)


class RedoSingleCharRequest(BaseModel):
    session_path: str
    char_name: str
    episode: int | None = None
    visual_prompt: str | None = None
    chars_model: str | None = None


def _latest_episode_num(session_dir: Path) -> int | None:
    state_path = session_dir / "session_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            latest = int(state.get("latest_episode", 0) or 0)
            if latest > 0:
                return latest
        except Exception:
            pass
    episodes_dir = session_dir / "episodes"
    if not episodes_dir.exists():
        return None
    nums: list[int] = []
    for d in episodes_dir.iterdir():
        if d.is_dir() and d.name.startswith("episode"):
            try:
                nums.append(int(d.name.replace("episode", "") or 0))
            except Exception:
                continue
    return max(nums) if nums else None


def _apply_redo_behavior(req: RunNarrativeStepRequest) -> None:
    if not req.redo or not req.session_path:
        return
    if req.step != "planner":
        req.reset = True
        return

    session_dir = _resolve_session_dir(req.session_path)
    ep_num = req.episode or _latest_episode_num(session_dir) or 1
    req.episode = int(ep_num)

    # Planner redo should only overwrite the targeted episode board.
    _delete_path(session_dir / "episodes" / f"episode{ep_num}")

    # Keep state coherent by dropping the targeted planned-episode metadata.
    state_path = session_dir / "session_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state.get("episodes"), dict):
                state["episodes"].pop(str(ep_num), None)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass


def _episode_board_path(session_dir: Path, episode: int | None = None) -> Path | None:
    episodes_dir = session_dir / "episodes"
    if not episodes_dir.exists():
        return None

    if episode is not None:
        board = episodes_dir / f"episode{int(episode)}" / "manga-board.json"
        return board if board.exists() else None

    ep_num = _latest_episode_num(session_dir)
    if ep_num is not None:
        board = episodes_dir / f"episode{ep_num}" / "manga-board.json"
        if board.exists():
            return board

    boards = sorted(episodes_dir.glob("episode*/manga-board.json"))
    return boards[-1] if boards else None


def _resolve_art_style_and_resolution(session_dir: Path) -> tuple[str, tuple[int, int], str]:
    config_path = ROOT_DIR / "agents" / "narrativeManga" / "config.json"
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}

    state_path = session_dir / "session_state.json"
    settings: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            settings = state.get("settings", {}) if isinstance(state.get("settings", {}), dict) else {}
        except Exception:
            settings = {}

    art_styles = config.get("art_styles", {}) if isinstance(config.get("art_styles", {}), dict) else {}
    default_art_style = str(config.get("art_style", "cinematic anime"))
    preset = settings.get("preset")
    art_style = str(art_styles.get(preset, default_art_style))

    video_cfg = config.get("video", {}) if isinstance(config.get("video", {}), dict) else {}
    default_resolution = tuple(video_cfg.get("resolution", [1280, 720]))
    resolution_raw = settings.get("resolution")
    if isinstance(resolution_raw, list) and len(resolution_raw) == 2:
        try:
            resolution = (int(resolution_raw[0]), int(resolution_raw[1]))
        except Exception:
            resolution = default_resolution
    else:
        resolution = default_resolution

    char_model = str(settings.get("character_image_model") or "models/gemini-2.5-flash-image")
    return art_style, resolution, char_model


def _apply_char_prompt_overrides(req: RunNarrativeStepRequest) -> None:
    overrides = req.chars_visual_overrides or {}
    if not overrides or not req.session_path:
        return

    session_dir = _resolve_session_dir(req.session_path)
    board_path = _episode_board_path(session_dir, req.episode)
    if not board_path or not board_path.exists():
        return

    board = json.loads(board_path.read_text(encoding="utf-8"))
    characters = board.get("characters", [])
    if not isinstance(characters, list):
        return

    changed = False
    for char in characters:
        name = str(char.get("name", "") or "")
        if not name or name not in overrides:
            continue
        value = str(overrides[name] or "").strip()
        if not value:
            continue
        char["visual_prompt"] = value
        changed = True

    if changed:
        board_path.write_text(json.dumps(board, indent=2), encoding="utf-8")


def _locks_file(session_path: str) -> Path:
    return _resolve_session_dir(session_path) / "workflow_locks.json"


def _google_price_catalog() -> dict[str, dict[str, Any]]:
    # Source: https://ai.google.dev/gemini-api/docs/pricing (April 2026 snapshot).
    # Prices are estimated from public docs and used only for UI ordering.
    return {
        "models/gemini-2.5-flash-lite": {
            "text_input_price": 0.10,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-2.5-flash": {
            "text_input_price": 0.30,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-flash-latest": {
            "text_input_price": 0.30,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-2.5-pro": {
            "text_input_price": 1.25,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-3-flash-preview": {
            "text_input_price": 0.50,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-3.1-flash-lite-preview": {
            "text_input_price": 0.25,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-3.1-pro-preview": {
            "text_input_price": 2.00,
            "image_output_price": None,
            "supports_planner": True,
            "supports_image_generation": False,
        },
        "models/gemini-2.5-flash-image": {
            "text_input_price": 0.30,
            "image_output_price": 0.039,
            "supports_planner": False,
            "supports_image_generation": True,
        },
        "models/gemini-3.1-flash-image-preview": {
            "text_input_price": 0.50,
            "image_output_price": 0.045,
            "supports_planner": False,
            "supports_image_generation": True,
        },
        "models/gemini-3-pro-image-preview": {
            "text_input_price": 2.00,
            "image_output_price": 0.134,
            "supports_planner": False,
            "supports_image_generation": True,
        },
    }


def _annotate_model_for_tasks(model: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    name = str(model.get("name", ""))
    lower = name.lower()
    known = catalog.get(name, {})

    is_image_by_name = ("-image" in lower) or lower.startswith("models/imagen")
    supports_image_generation = bool(known.get("supports_image_generation", is_image_by_name))
    supports_planner = bool(known.get("supports_planner", not supports_image_generation))

    text_input_price = known.get("text_input_price")
    image_output_price = known.get("image_output_price")

    enriched = dict(model)
    enriched.update(
        {
            "supports_planner": supports_planner,
            "supports_image_generation": supports_image_generation,
            "text_input_price": text_input_price,
            "image_output_price": image_output_price,
        }
    )
    return enriched


def _sort_models_for_planner(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        models,
        key=lambda m: (
            float(m.get("text_input_price")) if isinstance(m.get("text_input_price"), (int, float)) else 9_999.0,
            -int(m.get("input_token_limit", 0) or 0),
        ),
    )


def _sort_models_for_image(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        models,
        key=lambda m: (
            float(m.get("image_output_price")) if isinstance(m.get("image_output_price"), (int, float)) else 9_999.0,
            float(m.get("text_input_price")) if isinstance(m.get("text_input_price"), (int, float)) else 9_999.0,
        ),
    )


@router.get("/narrative/google-models")
async def narrative_google_models() -> dict[str, Any]:
    config_path = ROOT_DIR / "agents" / "narrativeManga" / "config.json"
    defaults = {
        "planner_model": "models/gemini-flash-latest",
        "character_image_model": "models/gemini-2.5-flash-image",
        "scene_image_model": "models/gemini-2.5-flash-image",
    }
    try:
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            defaults.update(cfg.get("models", {}))
    except Exception:
        pass

    fallback = [
        {"name": "models/gemini-2.5-pro", "input_token_limit": 2_000_000, "output_token_limit": 8192},
        {"name": "models/gemini-2.5-flash-lite", "input_token_limit": 1_000_000, "output_token_limit": 8192},
        {"name": "models/gemini-2.5-flash", "input_token_limit": 1_000_000, "output_token_limit": 8192},
        {"name": "models/gemini-2.5-flash-image", "input_token_limit": 1_000_000, "output_token_limit": 8192},
        {"name": "models/gemini-flash-latest", "input_token_limit": 1_000_000, "output_token_limit": 8192},
    ]
    price_catalog = _google_price_catalog()

    def _build_payload(raw_models: list[dict[str, Any]], source: str) -> dict[str, Any]:
        enriched = [_annotate_model_for_tasks(m, price_catalog) for m in raw_models]
        planner_models = _sort_models_for_planner([m for m in enriched if m.get("supports_planner")])
        image_models = _sort_models_for_image([m for m in enriched if m.get("supports_image_generation")])

        effective_defaults = dict(defaults)
        if planner_models:
            effective_defaults["planner_model"] = planner_models[0]["name"]
        if image_models:
            effective_defaults["character_image_model"] = image_models[0]["name"]
            effective_defaults["scene_image_model"] = image_models[0]["name"]

        # Keep stable ordering for any consumers that still use a flat list.
        all_models = sorted(
            enriched,
            key=lambda m: (
                float(m.get("text_input_price")) if isinstance(m.get("text_input_price"), (int, float)) else 9_999.0,
                float(m.get("image_output_price")) if isinstance(m.get("image_output_price"), (int, float)) else 9_999.0,
            ),
        )
        return {
            "models": all_models,
            "defaults": effective_defaults,
            "source": source,
            "by_task": {
                "planner": planner_models,
                "chars": image_models,
                "scenes": image_models,
            },
        }

    client = make_gemini_client(required=False)
    if client is None:
        return _build_payload(fallback, "fallback")

    models: list[dict[str, Any]] = []
    try:
        for model in client.models.list():
            name = getattr(model, "name", "") or ""
            if not name.startswith("models/gemini"):
                continue
            actions = [str(a).lower() for a in (getattr(model, "supported_actions", []) or [])]
            if actions and not any("generatecontent" in a for a in actions):
                continue
            models.append(
                {
                    "name": name,
                    "input_token_limit": int(getattr(model, "input_token_limit", 0) or 0),
                    "output_token_limit": int(getattr(model, "output_token_limit", 0) or 0),
                }
            )
    except Exception:
        return _build_payload(fallback, "fallback")

    models = sorted(models, key=lambda x: (x["input_token_limit"], x["output_token_limit"]), reverse=True)
    if not models:
        models = fallback
    return _build_payload(models, "google")


@router.get("/narrative/char-prompts")
async def narrative_char_prompts(session_path: str, episode: int | None = None) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    board_path = _episode_board_path(session_dir, episode)
    if not board_path:
        return {"session_path": session_path, "episode": episode, "char_prompts": []}

    board = json.loads(board_path.read_text(encoding="utf-8"))
    chars = board.get("characters", []) if isinstance(board, dict) else []
    out: list[dict[str, str]] = []
    for char in chars:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name", "") or "").strip()
        if not name:
            continue
        visual_prompt = str(char.get("visual_prompt") or char.get("description") or "").strip()
        out.append({"name": name, "visual_prompt": visual_prompt})

    episode_num = int(board.get("episode_number", 0) or 0) if isinstance(board, dict) else 0
    return {
        "session_path": session_path,
        "episode": episode_num if episode_num > 0 else episode,
        "char_prompts": out,
    }


@router.get("/narrative/locks")
async def narrative_get_locks(session_path: str) -> dict[str, Any]:
    path = _locks_file(session_path)
    if not path.exists():
        return {"session_path": session_path, "locks": {}}
    return {"session_path": session_path, "locks": json.loads(path.read_text(encoding="utf-8"))}


@router.post("/narrative/locks")
async def narrative_set_locks(req: SessionLocksRequest) -> dict[str, Any]:
    path = _locks_file(req.session_path)
    path.write_text(json.dumps(req.locks, indent=2), encoding="utf-8")
    return {"ok": True, "session_path": req.session_path, "locks": req.locks}


@router.post("/narrative/session-sync")
async def narrative_sync_session_state(req: SessionStateSyncRequest) -> dict[str, Any]:
    session_dir = _resolve_session_dir(req.session_path)
    state_path = session_dir / "session_state.json"

    current: dict[str, Any] = {}
    if state_path.exists():
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}

    existing_settings = current.get("settings") if isinstance(current.get("settings"), dict) else {}
    existing_locks = current.get("locks") if isinstance(current.get("locks"), dict) else {}

    next_settings = {**existing_settings, **(req.settings or {})}
    next_locks = {**existing_locks, **(req.locks or {})}

    current["settings"] = next_settings
    current["locks"] = next_locks
    state_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    locks_path = _locks_file(req.session_path)
    locks_path.write_text(json.dumps(next_locks, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "session_path": req.session_path,
        "settings": next_settings,
        "locks": next_locks,
    }

@router.post("/run")
async def start_agent_run(req: RunAgentRequest):
    if req.agent_name != "narrativeManga":
        return {"status": "queued", "job_id": "test-job-123", "agent": req.agent_name}

    run = _run_narrative_step(
        step="all",
        prompt=req.prompt,
        session_path=req.session_path if req.session_mode == "existing" else None,
        episodes="new",
        develop=False,
        theme=req.theme,
        preset=req.preset,
        fmt=req.format,
        enable_music=req.enable_music,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
        max_image_requests=req.max_image_requests,
        max_chars_per_episode=req.max_chars_per_episode,
        max_panels_per_episode=req.max_panels_per_episode,
        max_episode_duration_mins=req.max_episode_duration_mins,
    )

    return {
        "status": "success" if run["exit_code"] == 0 else "error",
        "job_id": "narrative-sync-run",
        "agent": req.agent_name,
        "exit_code": run["exit_code"],
        "session_path": run["session_path"],
        "stdout": run["stdout"],
        "stderr": run["stderr"],
    }


@router.get("/narrative/checkpoints")
async def narrative_checkpoints(session_path: str) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    return {
        "session_path": session_path,
        "hashes": _workflow_hashes(session_dir),
    }


@router.post("/narrative/run-step")
async def narrative_run_step(req: RunNarrativeStepRequest) -> dict[str, Any]:
    step_map = {
        "texts": "clouds",
        "planner": "planner",
        "chars": "chars",
        "scenes": "scenes",
        "audio": "audio",
        "music": "music",
        "video": "video",
        "all": "all",
    }
    step = step_map.get(req.step, req.step)

    _apply_redo_behavior(req)
    if req.step in {"chars", "all"}:
        _apply_char_prompt_overrides(req)

    if req.step == "texts" and req.narration_mode == "none":
        return {
            "status": "skipped",
            "reason": "Narration mode 'none' skips cloud/text overlay generation.",
            "session_path": req.session_path,
        }

    if req.reset and req.session_path:
        session_dir = _resolve_session_dir(req.session_path)
        for path in _step_reset_paths(session_dir, req.step):
            _delete_path(path)

    resolution_map = {
        "youtube_shorts": (1080, 1920),
        "youtube_video": (1920, 1080),
        "insta_reels": (1080, 1920),
        "insta_posts": (1080, 1080),
    }
    res = resolution_map.get(req.buildpack_resolution or "", None)

    run = _run_narrative_step(
        step=step,
        prompt=req.prompt,
        session_path=req.session_path if req.session_mode == "existing" else req.session_path,
        episodes=req.episodes,
        develop=req.develop,
        episode=req.episode,
        theme=req.theme,
        preset=req.preset,
        fmt=req.format,
        enable_music=req.enable_music,
        max_image_requests=req.max_image_requests,
        max_chars_per_episode=req.max_chars_per_episode,
        max_panels_per_episode=req.max_panels_per_episode,
        max_episode_duration_mins=req.max_episode_duration_mins,
        resolution_w=res[0] if res else None,
        resolution_h=res[1] if res else None,
        cloud_style=req.cloud_style,
        font_style=req.font_style,
        subtitle_style=req.subtitle_style,
        narration_mode=req.narration_mode,
        subtitle_scale=req.subtitle_scale,
        episode_mode=req.episode_mode,
        planner_model=req.planner_model,
        chars_model=req.chars_model,
        scenes_model=req.scenes_model,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
    )

    hashes = None
    if run.get("session_path"):
        try:
            hashes = _workflow_hashes(_resolve_session_dir(run["session_path"]))
        except Exception:
            hashes = None

    return {
        "status": "success" if run["exit_code"] == 0 else "error",
        "exit_code": run["exit_code"],
        "step": req.step,
        "session_path": run.get("session_path"),
        "stdout": run["stdout"],
        "stderr": run["stderr"],
        "hashes": hashes,
    }


@router.post("/narrative/run-step-live")
async def narrative_run_step_live(req: RunNarrativeStepRequest) -> dict[str, Any]:
    step_map = {
        "texts": "clouds",
        "planner": "planner",
        "chars": "chars",
        "scenes": "scenes",
        "audio": "audio",
        "music": "music",
        "video": "video",
        "all": "all",
    }
    step = step_map.get(req.step, req.step)

    _apply_redo_behavior(req)
    if req.step in {"chars", "all"}:
        _apply_char_prompt_overrides(req)

    if req.step == "texts" and req.narration_mode == "none":
        return {
            "done": True,
            "result": {
                "status": "skipped",
                "reason": "Narration mode 'none' skips cloud/text overlay generation.",
                "session_path": req.session_path,
            },
        }

    if req.reset and req.session_path:
        session_dir = _resolve_session_dir(req.session_path)
        for path in _step_reset_paths(session_dir, req.step):
            _delete_path(path)

    resolution_map = {
        "youtube_shorts": (1080, 1920),
        "youtube_video": (1920, 1080),
        "insta_reels": (1080, 1920),
        "insta_posts": (1080, 1080),
    }
    res = resolution_map.get(req.buildpack_resolution or "", None)

    job_id = f"narrative-step-{uuid.uuid4().hex[:12]}"
    _create_job(job_id)
    worker = threading.Thread(target=_run_narrative_step_worker, args=(job_id, req, step, res), daemon=True)
    worker.start()

    return {"done": False, "job_id": job_id}


@router.get("/narrative/job/{job_id}")
async def narrative_job_status(job_id: str) -> dict[str, Any]:
    state = _job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"done": state["done"], "result": state["result"]}


@router.post("/narrative/copy-character")
async def narrative_copy_character(req: CopyCharacterRequest) -> dict[str, Any]:
    source_rel = req.source_path.lstrip("/")
    if source_rel.startswith("outputs/"):
        source_rel = source_rel[len("outputs/"):]
    source = (OUTPUTS_DIR / source_rel).resolve()
    if not str(source).startswith(str(OUTPUTS_DIR.resolve())) or not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="Source character not found")

    if req.target_session_path:
        target_session_dir = _resolve_session_dir(req.target_session_path)
    else:
        new_sid = str(random.randint(1_000_000, 9_999_999))
        target_session_dir = OUTPUTS_DIR / f"{new_sid}" / "narrativeManga"
        target_session_dir.mkdir(parents=True, exist_ok=True)

    target_chars = target_session_dir / "chars"
    target_chars.mkdir(parents=True, exist_ok=True)
    target = target_chars / source.name
    shutil.copy2(source, target)

    return {
        "ok": True,
        "copied_to": str(target.relative_to(OUTPUTS_DIR)),
        "target_session_path": _to_rel_session_path(target_session_dir),
    }


@router.post("/narrative/redo-char")
async def narrative_redo_single_char(req: RedoSingleCharRequest) -> dict[str, Any]:
    session_dir = _resolve_session_dir(req.session_path)
    board_path = _episode_board_path(session_dir, req.episode)
    if not board_path:
        raise HTTPException(status_code=404, detail="No manga-board.json found for session")

    board = json.loads(board_path.read_text(encoding="utf-8"))
    chars = board.get("characters", []) if isinstance(board, dict) else []
    if not isinstance(chars, list):
        raise HTTPException(status_code=400, detail="Invalid manga-board characters format")

    target_char = None
    for c in chars:
        if isinstance(c, dict) and str(c.get("name", "")) == req.char_name:
            target_char = c
            break
    if target_char is None:
        raise HTTPException(status_code=404, detail=f"Character '{req.char_name}' not found in planner output")

    if isinstance(req.visual_prompt, str) and req.visual_prompt.strip():
        target_char["visual_prompt"] = req.visual_prompt.strip()
        board_path.write_text(json.dumps(board, indent=2), encoding="utf-8")

    art_style, resolution, model_name = _resolve_art_style_and_resolution(session_dir)
    if req.chars_model and req.chars_model.strip():
        model_name = req.chars_model.strip()

    char_safe = req.char_name.replace(" ", "_").lower()
    char_path = session_dir / "chars" / f"char_{char_safe}.png"
    char_path.unlink(missing_ok=True)

    from agents.narrativeManga.chains.char_gen import CharGen

    gen = CharGen(
        image_model_name=model_name,
        max_generations=1,
        resolution=resolution,
        art_style=art_style,
        tracker=LLMTracker(),
    )
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    tracker = gen.tracker
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            manifest = gen.run({"characters": [target_char]}, session_dir, force_names={req.char_name})
    except Exception as e:
        if tracker is not None and tracker.calls:
            tracker.save(session_dir)
        return {
            "ok": False,
            "session_path": req.session_path,
            "char_name": req.char_name,
            "error": str(e),
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
            "llm_calls_recorded": len(tracker.calls) if tracker is not None else 0,
        }

    out = manifest.get(req.char_name)
    if not out:
        raise HTTPException(status_code=500, detail="Character generation completed but output manifest missing target")

    try:
        hashes = _workflow_hashes(session_dir)
    except Exception:
        hashes = None

    if tracker is not None and tracker.calls:
        tracker.save(session_dir)

    return {
        "ok": True,
        "session_path": req.session_path,
        "char_name": req.char_name,
        "image_path": out,
        "hashes": hashes,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "llm_calls_recorded": len(tracker.calls) if tracker is not None else 0,
    }

@router.websocket("/stream/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Streams live console output back to the Web UI 'Terminal' pane."""
    await websocket.accept()
    try:
        state = _job_state(job_id)
        if not state:
            await websocket.send_text(json.dumps({"type": "error", "msg": f"No active log stream for Job {job_id}"}))
            return

        q: Queue = state["queue"]
        await websocket.send_text(json.dumps({"type": "info", "msg": f"Connected to log stream for Job {job_id}"}))

        while True:
            sent_any = False
            while True:
                try:
                    item = q.get_nowait()
                except Empty:
                    break
                await websocket.send_text(json.dumps(item))
                sent_any = True

            if state["done"] and q.empty():
                break

            if not sent_any:
                await asyncio.sleep(0.2)

    except WebSocketDisconnect:
        print(f"Client disconnected from job {job_id}")
    finally:
        pass
