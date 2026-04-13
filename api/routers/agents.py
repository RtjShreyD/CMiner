import asyncio
import json
import hashlib
import os
import random
import shutil
import io
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from contextlib import redirect_stdout, redirect_stderr
from queue import Empty, Queue
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from pydantic import BaseModel, Field
from agents.shared.gemini_compat import make_gemini_client
from agents.shared.llm_tracker import LLMTracker, tracked_generate
from agents.autoAnimator.utils import ensure_session_outputs
from agents.autoAnimator.utils import get_model

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT_DIR / "outputs"
NARRATIVE_RUNNER = ROOT_DIR / "agents" / "autoAnimator" / "run.py"
NARRATIVE_JOBS: dict[str, dict[str, Any]] = {}
NARRATIVE_JOBS_LOCK = threading.Lock()
STEP_HISTORY_STEPS = ("planner", "chars", "scenes", "audio", "texts", "music", "video")
HASH_HISTORY_FILE = "workflow_hash_history.json"
HASH_HISTORY_DIR = ".workflow_hash_snapshots"


def _load_autoanimator_config() -> dict[str, Any]:
    config_path = ROOT_DIR / "agents" / "autoAnimator" / "config.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
    markers = ["Active session directory:", "New session directory:"]
    for line in stdout.splitlines():
        for marker in markers:
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
    preset_prompt: str | None = None,
    session_path: str | None,
    episodes: str = "new",
    develop: bool = False,
    episode: int | None = None,
    theme: str | None = None,
    preset: str | None = None,
    fmt: str | None = None,
    youtube_shorts_export: bool | None = None,
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
    tts_provider: str | None = None,
    gemini_tts_model: str | None = None,
    music_provider: str | None = None,
    lyria_model: str | None = None,
    project_name: str | None = None,
    niche: str | None = None,
    start_frame_path: str | None = None,
    end_frame_path: str | None = None,
    create_banner: bool = False,
    intro_only: bool = False,
    planner_skill_ids: list[str] | None = None,
    planner_skill_prompt: str | None = None,
) -> list[str]:
    cmd = [
        _python_bin(),
        "-u",
        str(NARRATIVE_RUNNER),
        "--workspace",
        str(ROOT_DIR),
        "--step",
        step,
    ]
    if prompt:
        cmd.extend(["--prompt", prompt])
    if preset_prompt:
        cmd.extend(["--preset_prompt", preset_prompt])
    if project_name:
        cmd.extend(["--project_name", project_name])
    if niche:
        cmd.extend(["--niche", niche])
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
    if youtube_shorts_export is False:
        cmd.extend(["--youtube_shorts_export", "off"])
    elif youtube_shorts_export is True:
        cmd.extend(["--youtube_shorts_export", "on"])
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
    if tts_provider:
        cmd.extend(["--tts_provider", tts_provider])
    if gemini_tts_model:
        cmd.extend(["--gemini_tts_model", gemini_tts_model])
    if music_provider:
        cmd.extend(["--music_provider", music_provider])
    if lyria_model:
        cmd.extend(["--lyria_model", lyria_model])
    if start_frame_path:
        cmd.extend(["--start_frame_path", start_frame_path])
    if end_frame_path:
        cmd.extend(["--end_frame_path", end_frame_path])
    if create_banner:
        cmd.append("--create_banner")
    if intro_only:
        cmd.append("--intro_only")
    if planner_skill_ids:
        cleaned_ids = [str(s).strip() for s in planner_skill_ids if str(s).strip()]
        if cleaned_ids:
            cmd.extend(["--planner_skill_ids", ",".join(cleaned_ids)])
    if planner_skill_prompt and str(planner_skill_prompt).strip():
        cmd.extend(["--planner_skill_prompt", str(planner_skill_prompt).strip()])
    return cmd


def _run_narrative_step(
    *,
    step: str,
    prompt: str | None,
    preset_prompt: str | None = None,
    project_name: str | None = None,
    niche: str | None = None,
    session_path: str | None,
    episodes: str = "new",
    develop: bool = False,
    episode: int | None = None,
    theme: str | None = None,
    preset: str | None = None,
    fmt: str | None = None,
    youtube_shorts_export: bool | None = None,
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
    tts_provider: str | None = None,
    gemini_tts_model: str | None = None,
    music_provider: str | None = None,
    lyria_model: str | None = None,
    start_frame_path: str | None = None,
    end_frame_path: str | None = None,
    create_banner: bool = False,
    intro_only: bool = False,
    planner_skill_ids: list[str] | None = None,
    planner_skill_prompt: str | None = None,
) -> dict[str, Any]:
    cmd = _build_narrative_cmd(
        step=step,
        prompt=prompt,
        preset_prompt=preset_prompt,
        project_name=project_name,
        niche=niche,
        session_path=session_path,
        episodes=episodes,
        develop=develop,
        episode=episode,
        theme=theme,
        preset=preset,
        fmt=fmt,
        youtube_shorts_export=youtube_shorts_export,
        enable_music=enable_music,
        max_image_requests=max_image_requests,
        max_chars_per_episode=max_chars_per_episode,
        max_panels_per_episode=max_panels_per_episode,
        max_episode_duration_mins=max_episode_duration_mins,
        resolution_w=resolution_w,
        resolution_h=resolution_h,
        cloud_style=cloud_style,
        font_style=font_style,
        subtitle_style=subtitle_style,
        narration_mode=narration_mode,
        subtitle_scale=subtitle_scale,
        episode_mode=episode_mode,
        planner_model=planner_model,
        chars_model=chars_model,
        scenes_model=scenes_model,
        tts_provider=tts_provider,
        gemini_tts_model=gemini_tts_model,
        music_provider=music_provider,
        lyria_model=lyria_model,
        start_frame_path=start_frame_path,
        end_frame_path=end_frame_path,
        create_banner=create_banner,
        intro_only=intro_only,
        planner_skill_ids=planner_skill_ids,
        planner_skill_prompt=planner_skill_prompt,
    )

    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True, check=False)
    detected_session_path = _extract_session_path_from_stdout(proc.stdout)
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "session_path": detected_session_path or session_path,
    }


def _step_reset_paths(session_dir: Path, step: str) -> list[Path]:
    episode_dirs = sorted((session_dir / "episodes").glob("episode*")) if (session_dir / "episodes").exists() else []
    episode_scenes = [d / "scenes" for d in episode_dirs]
    episode_audio = [d / "audio" for d in episode_dirs]
    episode_music = [d / "music" for d in episode_dirs]
    episode_intro = [d / "intro" for d in episode_dirs]
    episode_generic = [d / "generic" for d in episode_dirs]

    mapping: dict[str, list[Path]] = {
        "planner": [session_dir / "episodes", session_dir / "session_state.json"],
        "chars": [session_dir / "chars"],
        "scenes": [session_dir / "scenes", *episode_scenes],
        "audio": [session_dir / "audio", *episode_audio],
        "texts": [session_dir / "overlays", session_dir / "overlays_youtube_shorts", *episode_intro, *episode_generic],
        "clouds": [session_dir / "overlays", session_dir / "overlays_youtube_shorts", *episode_intro, *episode_generic],
        "music": [session_dir / "music", *episode_music],
        "video": [
            session_dir / "frames",
            session_dir / "fullvideo",
            session_dir / "shorts",
            session_dir / "concat.txt",
            session_dir / "thumbnail.jpg",
            *episode_intro,
            *episode_generic,
        ],
        "all": [
            session_dir / "episodes",
            session_dir / "chars",
            session_dir / "scenes",
            session_dir / "audio",
            session_dir / "overlays",
            session_dir / "overlays_youtube_shorts",
            session_dir / "music",
            session_dir / "frames",
            session_dir / "fullvideo",
            session_dir / "shorts",
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
    episode_dirs = sorted((session_dir / "episodes").glob("episode*")) if (session_dir / "episodes").exists() else []

    if step == "planner":
        board_files = sorted(
            list((session_dir / "episodes").glob("episode*/storyboard.json"))
        )
        return board_files
    if step == "chars":
        return sorted(list((session_dir / "chars").glob("*.png")) + list((session_dir / "chars").glob("*.json")))
    if step == "scenes":
        files = list((session_dir / "scenes").glob("*.png")) + list((session_dir / "scenes").glob("*.json"))
        for ep in episode_dirs:
            files += list((ep / "scenes").glob("*.png")) + list((ep / "scenes").glob("*.json"))
        return sorted(files)
    if step == "audio":
        files = list((session_dir / "audio").glob("panel_*.*"))
        for ep in episode_dirs:
            files += list((ep / "audio").glob("panel_*.*"))
        return sorted(files)
    if step == "texts":
        files = (
            list((session_dir / "overlays").glob("**/*.png"))
            + list((session_dir / "overlays_youtube_shorts").glob("**/*.png"))
        )
        for ep in episode_dirs:
            files += list((ep / "intro").glob("**/*.png"))
            files += list((ep / "generic").glob("**/*.png"))
        return sorted(files)
    if step == "music":
        files = (
            list((session_dir / "music").glob("*.mp3"))
            + list((session_dir / "music").glob("*.wav"))
            + list((session_dir / "music").glob("*.aac"))
            + list((session_dir / "music").glob("*.txt"))
            + list((session_dir / "music").glob("*.json"))
        )
        for ep in episode_dirs:
            files += list((ep / "music").glob("*.mp3"))
            files += list((ep / "music").glob("*.wav"))
            files += list((ep / "music").glob("*.aac"))
            files += list((ep / "music").glob("*.txt"))
            files += list((ep / "music").glob("*.json"))
        return sorted(files)
    if step == "video":
        files = (
            list(session_dir.glob("*.mp4"))
            + list(session_dir.glob("seg_*.mp4"))
            + list(session_dir.glob("thumbnail.jpg"))
            + list(session_dir.glob("metadata.json"))
            + list((session_dir / "fullvideo").glob("**/*.mp4"))
            + list((session_dir / "fullvideo").glob("**/*.jpg"))
            + list((session_dir / "fullvideo").glob("**/*.json"))
            + list((session_dir / "shorts").glob("**/*.mp4"))
            + list((session_dir / "shorts").glob("**/*.jpg"))
            + list((session_dir / "shorts").glob("**/*.json"))
        )
        for ep in episode_dirs:
            files += list((ep / "intro").glob("**/*.mp4"))
            files += list((ep / "intro").glob("**/*.jpg"))
            files += list((ep / "intro").glob("**/*.json"))
            files += list((ep / "generic").glob("**/*.mp4"))
            files += list((ep / "generic").glob("**/*.jpg"))
            files += list((ep / "generic").glob("**/*.json"))
        return sorted(files)
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


def _hash_history_file(session_dir: Path) -> Path:
    return session_dir / HASH_HISTORY_FILE


def _hash_snapshot_root(session_dir: Path) -> Path:
    return session_dir / HASH_HISTORY_DIR


def _load_hash_history(session_dir: Path) -> dict[str, list[dict[str, Any]]]:
    path = _hash_history_file(session_dir)
    if not path.exists():
        return {k: [] for k in STEP_HISTORY_STEPS}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {k: [] for k in STEP_HISTORY_STEPS}
        out: dict[str, list[dict[str, Any]]] = {}
        for step in STEP_HISTORY_STEPS:
            rows = data.get(step, [])
            out[step] = rows if isinstance(rows, list) else []
        return out
    except Exception:
        return {k: [] for k in STEP_HISTORY_STEPS}


def _save_hash_history(session_dir: Path, history: dict[str, list[dict[str, Any]]]) -> None:
    path = _hash_history_file(session_dir)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def _snapshot_step_files(session_dir: Path, step: str, step_hash: str) -> Path | None:
    files = _collect_step_files(session_dir, step)
    if not files:
        return None

    snapshot_dir = _hash_snapshot_root(session_dir) / step / step_hash
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for src in files:
        rel = src.relative_to(session_dir)
        dest = snapshot_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return snapshot_dir


def _record_step_hash_history(session_dir: Path, step: str) -> dict[str, Any] | None:
    if step not in STEP_HISTORY_STEPS:
        return None

    step_hash = _step_hash(session_dir, step)
    if not step_hash:
        return None

    history = _load_hash_history(session_dir)
    rows = history.get(step, [])
    if rows and str(rows[0].get("hash")) == step_hash:
        return rows[0]

    snapshot_dir = _snapshot_step_files(session_dir, step, step_hash)
    if snapshot_dir is None:
        return None

    entry = {
        "hash": step_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "snapshot": str(snapshot_dir.relative_to(session_dir)),
    }
    rows.insert(0, entry)
    history[step] = rows[:20]
    _save_hash_history(session_dir, history)
    return entry


def _record_hash_history_for_run(session_dir: Path, step: str) -> dict[str, list[dict[str, Any]]]:
    if step == "all":
        for s in STEP_HISTORY_STEPS:
            _record_step_hash_history(session_dir, s)
    elif step in STEP_HISTORY_STEPS:
        _record_step_hash_history(session_dir, step)
    elif step == "clouds":
        _record_step_hash_history(session_dir, "texts")
    return _load_hash_history(session_dir)


def _history_payload(session_dir: Path) -> dict[str, list[dict[str, Any]]]:
    history = _load_hash_history(session_dir)
    out: dict[str, list[dict[str, Any]]] = {}
    for step in STEP_HISTORY_STEPS:
        entries = history.get(step, [])
        out[step] = [
            {
                "hash": str(e.get("hash", "")),
                "timestamp": str(e.get("timestamp", "")),
            }
            for e in entries
            if e.get("hash")
        ]
    return out


def _restore_step_from_hash(session_dir: Path, step: str, hash_value: str) -> None:
    history = _load_hash_history(session_dir)
    rows = history.get(step, [])
    entry = next((r for r in rows if str(r.get("hash")) == hash_value), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Hash '{hash_value}' not found for step '{step}'")

    snapshot_rel = str(entry.get("snapshot", "")).strip()
    if not snapshot_rel:
        raise HTTPException(status_code=500, detail="History entry is missing snapshot path")

    snapshot_dir = (session_dir / snapshot_rel).resolve()
    if not str(snapshot_dir).startswith(str(session_dir.resolve())) or not snapshot_dir.exists():
        raise HTTPException(status_code=404, detail="Snapshot data not found for selected hash")

    cleanup_paths = _step_reset_paths(session_dir, step)
    if step == "planner":
        cleanup_paths = [session_dir / "episodes"]
    for p in cleanup_paths:
        _delete_path(p)

    for src in snapshot_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(snapshot_dir)
        dest = session_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _job_state(job_id: str) -> dict[str, Any] | None:
    with NARRATIVE_JOBS_LOCK:
        return NARRATIVE_JOBS.get(job_id)


def _create_job(job_id: str) -> dict[str, Any]:
    state = {
        "queue": Queue(),
        "done": False,
        "result": None,
        "proc": None,
        "aborted": False,
        "session_path": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with NARRATIVE_JOBS_LOCK:
        NARRATIVE_JOBS[job_id] = state
    return state


def _run_narrative_step_worker(job_id: str, req: Any, step: str, res: tuple[int, int] | None):
    state = _job_state(job_id)
    if not state:
        return

    q: Queue = state["queue"]
    pipeline_started_at = datetime.now(timezone.utc).isoformat()
    state["session_path"] = req.session_path
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    q.put({"type": "info", "msg": f"Starting step '{req.step}'..."})

    effective_fmt = "youtube_widescreen" if req.format == "youtube_video_only" else req.format
    effective_shorts_export = False if req.format == "youtube_video_only" else req.youtube_shorts_export

    cmd = _build_narrative_cmd(
        step=step,
        prompt=req.prompt,
        preset_prompt=req.preset_prompt,
        project_name=req.project_name,
        niche=req.niche,
        session_path=req.session_path if req.session_mode == "existing" else req.session_path,
        episodes=req.episodes,
        develop=req.develop,
        episode=req.episode,
        theme=req.theme,
        preset=req.preset,
        fmt=effective_fmt,
        youtube_shorts_export=effective_shorts_export,
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
        tts_provider=req.tts_provider,
        gemini_tts_model=req.gemini_tts_model,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
        start_frame_path=req.start_frame_path,
        end_frame_path=req.end_frame_path,
        create_banner=req.create_banner,
        intro_only=req.intro_only,
        planner_skill_ids=req.planner_skill_ids,
        planner_skill_prompt=req.planner_skill_prompt,
    )

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    state["proc"] = proc

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
            print(f"[autoAnimator:{job_id}:stdout] {line}", flush=True)
            maybe = _extract_session_path_from_stdout(line)
            if maybe:
                detected_session_path = maybe
                state["session_path"] = maybe
                state["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _drain_stderr():
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip("\n")
            if not line:
                continue
            stderr_lines.append(line)
            q.put({"type": "error", "msg": line})
            print(f"[autoAnimator:{job_id}:stderr] {line}", flush=True)

    t_out = threading.Thread(target=_drain_stdout, daemon=True)
    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out.start()
    t_err.start()
    exit_code = proc.wait()
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    hashes = None
    history = None
    if detected_session_path:
        try:
            session_dir = _resolve_session_dir(detected_session_path)
            hashes = _workflow_hashes(session_dir)
            if exit_code == 0:
                history = _record_hash_history_for_run(session_dir, step)
            else:
                history = _history_payload(session_dir)
        except Exception:
            hashes = None
            history = None

    result = {
        "status": "aborted" if state.get("aborted") else ("success" if exit_code == 0 else "error"),
        "exit_code": exit_code,
        "step": req.step,
        "session_path": detected_session_path,
        "pipeline_started_at": pipeline_started_at,
        "pipeline_finished_at": datetime.now(timezone.utc).isoformat(),
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "hashes": hashes,
        "history": history,
    }
    _persist_pipeline_run_timing(
        session_path=detected_session_path,
        started_at=result["pipeline_started_at"],
        finished_at=result["pipeline_finished_at"],
        status=result["status"],
        step=str(req.step),
        job_id=job_id,
    )
    state["proc"] = None
    state["result"] = result
    state["done"] = True
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    msg_type = "success" if result["status"] == "success" else "error"
    q.put({"type": msg_type, "msg": f"Step '{req.step}' finished with status {result['status']}."})

class RunAgentRequest(BaseModel):
    agent_name: str
    cmd_args: str | None = None
    prompt: str | None = None
    preset_prompt: str | None = None
    theme: str | None = None
    preset: str | None = None
    format: str | None = None
    youtube_shorts_export: bool | None = None
    cloud_style: str | None = None
    font_style: str | None = None
    session_mode: str = "new"
    session_path: str | None = None
    enable_music: bool = False
    create_banner: bool = False
    intro_only: bool = False
    music_provider: str = "lyria"
    lyria_model: str = "lyria-3-clip-preview"
    tts_provider: str = "edge"
    gemini_tts_model: str = "models/gemini-2.5-flash-tts"
    narration_mode: str | None = None
    character_pack_id: str | None = None
    reuse_session_chars: bool = False
    session_chars_path: str | None = None
    selected_session_character: str | None = None
    max_image_requests: int | None = None
    max_chars_per_episode: int | None = None
    max_panels_per_episode: int | None = None
    max_episode_duration_mins: int | None = None
    project_name: str | None = None
    niche: str | None = None
    start_frame_path: str | None = None
    end_frame_path: str | None = None
    planner_skill_ids: list[str] = Field(default_factory=list)
    planner_skill_prompt: str | None = None


class RunNarrativeStepRequest(BaseModel):
    session_mode: str = "new"
    session_path: str | None = None
    step: str = Field(default="all", pattern="^(all|planner|chars|scenes|audio|texts|music|video)$")
    reset: bool = False
    redo: bool = False
    prompt: str | None = None
    preset_prompt: str | None = None
    episodes: str = "new"
    develop: bool = False
    episode: int | None = None
    theme: str | None = None
    preset: str | None = None
    format: str | None = None
    youtube_shorts_export: bool | None = None
    enable_music: bool = False
    create_banner: bool = False
    intro_only: bool = False
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
    tts_provider: str | None = None
    gemini_tts_model: str | None = None
    music_provider: str | None = None
    lyria_model: str | None = None
    chars_visual_overrides: dict[str, str] | None = None
    project_name: str | None = None
    niche: str | None = None
    start_frame_path: str | None = None
    end_frame_path: str | None = None
    planner_skill_ids: list[str] = Field(default_factory=list)
    planner_skill_prompt: str | None = None


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


class BootstrapSessionRequest(BaseModel):
    project_name: str | None = None


class RedoSingleCharRequest(BaseModel):
    session_path: str
    char_name: str
    episode: int | None = None
    visual_prompt: str | None = None
    chars_model: str | None = None


class RestoreHashRequest(BaseModel):
    session_path: str
    step: str = Field(pattern="^(planner|chars|scenes|audio|texts|music|video)$")
    hash: str


class MaterializePresetPromptRequest(BaseModel):
    session_path: str
    base_prompt: str | None = None
    project_name: str | None = None
    niche: str | None = None


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


def _parse_json_object(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _persist_pipeline_run_timing(
    *,
    session_path: str | None,
    started_at: str,
    finished_at: str,
    status: str,
    step: str,
    job_id: str,
) -> None:
    if not session_path:
        return
    try:
        session_dir = _resolve_session_dir(session_path)
    except Exception:
        return

    state_path = session_dir / "session_state.json"
    current: dict[str, Any] = {}
    if state_path.exists():
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}

    settings = current.get("settings") if isinstance(current.get("settings"), dict) else {}
    runtime = current.get("runtime") if isinstance(current.get("runtime"), dict) else {}
    runs = runtime.get("pipeline_runs") if isinstance(runtime.get("pipeline_runs"), list) else []

    run_row = {
        "job_id": job_id,
        "step": step,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
    }
    runs.append(run_row)
    if len(runs) > 50:
        runs = runs[-50:]

    runtime["last_pipeline_run"] = run_row
    runtime["pipeline_runs"] = runs
    settings["pipeline_started_at"] = started_at
    settings["pipeline_finished_at"] = finished_at
    current["runtime"] = runtime
    current["settings"] = settings

    state_path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def _fallback_series_preset_prompt(seed_prompt: str, project_name: str, niche_key: str | None) -> str:
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


def _compute_series_preset_prompt(
    *,
    planner_model: str,
    seed_prompt: str,
    project_name: str,
    niche_key: str | None,
) -> str:
    fallback = _fallback_series_preset_prompt(seed_prompt, project_name, niche_key)
    if not seed_prompt.strip():
        return fallback

    try:
        model = get_model(planner_model)
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
        tracker = LLMTracker()
        response = tracked_generate(tracker, model, prompt, purpose="series_preset_builder_api")
        obj = _parse_json_object(getattr(response, "text", "") or "")
        preset = str(obj.get("preset_prompt", "")).strip() if isinstance(obj.get("preset_prompt"), str) else ""
        return preset or fallback
    except Exception:
        return fallback


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
    """Return the storyboard path for the target episode.
    Uses storyboard.json only.
    """
    _BOARD_NAMES = ("storyboard.json",)
    episodes_dir = session_dir / "episodes"
    if not episodes_dir.exists():
        return None

    if episode is not None:
        ep_dir = episodes_dir / f"episode{int(episode)}"
        for name in _BOARD_NAMES:
            p = ep_dir / name
            if p.exists():
                return p
        return None

    ep_num = _latest_episode_num(session_dir)
    if ep_num is not None:
        ep_dir = episodes_dir / f"episode{ep_num}"
        for name in _BOARD_NAMES:
            p = ep_dir / name
            if p.exists():
                return p

    for name in _BOARD_NAMES:
        boards = sorted(episodes_dir.glob(f"episode*/{name}"))
        if boards:
            return boards[-1]
    return None


def _resolve_art_style_and_resolution(session_dir: Path) -> tuple[str, tuple[int, int], str]:
    config = _load_autoanimator_config()

    state_path = session_dir / "session_state.json"
    settings: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            settings = state.get("settings", {}) if isinstance(state.get("settings", {}), dict) else {}
        except Exception:
            settings = {}

    art_styles = config.get("art_styles", {}) if isinstance(config.get("art_styles", {}), dict) else {}
    style_keys = settings.get("style_keys") if isinstance(settings.get("style_keys"), list) else []
    if style_keys:
        resolved = [str(art_styles.get(str(k), "")).strip() for k in style_keys if str(art_styles.get(str(k), "")).strip()]
        art_style = " + ".join(resolved) if resolved else ""
    else:
        preset = str(settings.get("preset", "") or "")
        art_style = str(art_styles.get(preset, "")).strip()
    if not art_style:
        first_style = next(iter(art_styles.values()), "cinematic anime")
        art_style = str(first_style)

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


@router.get("/autoanimator/google-models")
async def narrative_google_models() -> dict[str, Any]:
    config_path = ROOT_DIR / "agents" / "autoAnimator" / "config.json"
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


@router.get("/autoanimator/planner-options")
async def autoanimator_planner_options() -> dict[str, Any]:
    cfg = _load_autoanimator_config()
    themes = cfg.get("themes", {}) if isinstance(cfg.get("themes", {}), dict) else {}
    art_styles = cfg.get("art_styles", {}) if isinstance(cfg.get("art_styles", {}), dict) else {}
    niches = cfg.get("niche_bundles", {}) if isinstance(cfg.get("niche_bundles", {}), dict) else {}
    planner_skills = cfg.get("planner_skills", {}) if isinstance(cfg.get("planner_skills", {}), dict) else {}
    models_cfg = cfg.get("models", {}) if isinstance(cfg.get("models", {}), dict) else {}
    tts_provider_default = str(models_cfg.get("tts_provider", "edge") or "edge")
    gemini_tts_default = str(models_cfg.get("gemini_tts_model", "models/gemini-2.5-flash-tts") or "models/gemini-2.5-flash-tts")
    max_image_requests_default = int(models_cfg.get("max_image_requests", 50) or 50)
    max_chars_default = int(models_cfg.get("max_chars_per_episode", 3) or 3)
    max_panels_default = int(models_cfg.get("max_panels_per_episode", 50) or 50)
    max_duration_default = int(models_cfg.get("max_episode_duration_mins", 1) or 1)
    return {
        "themes": themes,
        "art_styles": art_styles,
        "niches": niches,
        "planner_skills": planner_skills,
        "tts": {
            "providers": ["edge", "gemini"],
            "gemini_models": ["models/gemini-2.5-flash-tts", "models/gemini-2.5-pro-tts"],
        },
        "defaults": {
            "theme": "auto-select",
            "preset": "auto-select",
            "niche": "auto-select",
            "tts_provider": tts_provider_default,
            "gemini_tts_model": gemini_tts_default,
            "max_image_requests": max_image_requests_default,
            "max_chars_per_episode": max_chars_default,
            "max_panels_per_episode": max_panels_default,
            "max_episode_duration_mins": max_duration_default,
            "planner_skill_ids": [],
        },
    }


@router.get("/autoanimator/char-prompts")
async def narrative_char_prompts(session_path: str, episode: int | None = None) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    board_path = _episode_board_path(session_dir, episode)
    if not board_path:
        return {"session_path": session_path, "episode": episode, "char_prompts": [], "object_prompts": []}

    board = json.loads(board_path.read_text(encoding="utf-8"))
    chars = board.get("characters", []) if isinstance(board, dict) else []
    char_out: list[dict[str, str]] = []
    for char in chars:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name", "") or "").strip()
        if not name:
            continue
        visual_prompt = str(char.get("visual_prompt") or char.get("description") or "").strip()
        char_out.append({"name": name, "visual_prompt": visual_prompt, "entity_type": "character"})

    objects = board.get("objects", []) if isinstance(board, dict) else []
    obj_out: list[dict[str, str]] = []
    for obj in (objects if isinstance(objects, list) else []):
        if not isinstance(obj, dict):
            continue
        name = str(obj.get("name", "") or "").strip()
        if not name:
            continue
        visual_prompt = str(obj.get("visual_prompt") or obj.get("description") or "").strip()
        obj_out.append({
            "name": name,
            "visual_prompt": visual_prompt,
            "object_type": str(obj.get("object_type", "prop") or "prop"),
            "entity_type": "object",
        })

    episode_num = int(board.get("episode_number", 0) or 0) if isinstance(board, dict) else 0
    return {
        "session_path": session_path,
        "episode": episode_num if episode_num > 0 else episode,
        "char_prompts": char_out,
        "object_prompts": obj_out,
    }


@router.get("/autoanimator/review-board")
async def narrative_review_board(session_path: str, episode: int | None = None) -> dict[str, Any]:
    """Return characters, objects, and storyboard panels for UI review."""
    session_dir = _resolve_session_dir(session_path)
    board_path = _episode_board_path(session_dir, episode)
    if not board_path:
        return {"session_path": session_path, "episode": episode, "characters": [], "objects": [], "panels": []}

    board = json.loads(board_path.read_text(encoding="utf-8"))
    episode_num = int(board.get("episode_number", 0) or 0) if isinstance(board, dict) else 0

    # Characters with portrait image URL
    chars_dir = session_dir / "chars"
    chars = board.get("characters", []) if isinstance(board, dict) else []
    char_rows: list[dict[str, Any]] = []
    for char in (chars if isinstance(chars, list) else []):
        if not isinstance(char, dict):
            continue
        name = str(char.get("name", "") or "").strip()
        if not name:
            continue
        safe_name = name.replace(" ", "_").lower()
        img_rel: str | None = None
        candidate = chars_dir / f"char_{safe_name}.png"
        if candidate.exists():
            try:
                img_rel = str(candidate.relative_to(OUTPUTS_DIR))
            except ValueError:
                img_rel = None
        char_rows.append({
            "name": name,
            "description": str(char.get("description", "") or ""),
            "visual_prompt": str(char.get("visual_prompt") or char.get("description") or ""),
            "bubble_style": str(char.get("bubble_style", "") or ""),
            "image_path": img_rel,
            "entity_type": "character",
        })

    # Objects with reference image URL
    objects = board.get("objects", []) if isinstance(board, dict) else []
    obj_rows: list[dict[str, Any]] = []
    for obj in (objects if isinstance(objects, list) else []):
        if not isinstance(obj, dict):
            continue
        name = str(obj.get("name", "") or "").strip()
        if not name:
            continue
        safe_name = name.replace(" ", "_").lower()
        img_rel = None
        candidate = chars_dir / f"obj_{safe_name}.png"
        if candidate.exists():
            try:
                img_rel = str(candidate.relative_to(OUTPUTS_DIR))
            except ValueError:
                img_rel = None
        obj_rows.append({
            "name": name,
            "description": str(obj.get("description", "") or ""),
            "visual_prompt": str(obj.get("visual_prompt") or obj.get("description") or ""),
            "object_type": str(obj.get("object_type", "prop") or "prop"),
            "role_in_story": str(obj.get("role_in_story", "") or ""),
            "image_path": img_rel,
            "entity_type": "object",
        })

    # Storyboard panels (summary)
    panels = board.get("panels", []) if isinstance(board, dict) else []
    panel_rows: list[dict[str, Any]] = []
    for panel in (panels if isinstance(panels, list) else []):
        if not isinstance(panel, dict):
            continue
        pnum = int(panel.get("panel_number", 0) or 0)
        panel_key = f"panel_{(pnum - 1):02d}" if pnum > 0 else None
        img_rel = None
        if panel_key:
            candidate = session_dir / "scenes" / f"{panel_key}.png"
            if candidate.exists():
                try:
                    img_rel = str(candidate.relative_to(OUTPUTS_DIR))
                except ValueError:
                    img_rel = None
        panel_rows.append({
            "panel_number": pnum,
            "scene_description": str(panel.get("scene_description", "") or ""),
            "characters_present": panel.get("characters_present", []),
            "objects_present": panel.get("objects_present", []),
            "camera_angle": str(panel.get("camera_angle", "") or ""),
            "mood": str(panel.get("mood", "") or ""),
            "image_path": img_rel,
        })

    return {
        "session_path": session_path,
        "episode": episode_num if episode_num > 0 else episode,
        "characters": char_rows,
        "objects": obj_rows,
        "panels": panel_rows,
    }


@router.get("/autoanimator/locks")
async def narrative_get_locks(session_path: str) -> dict[str, Any]:
    path = _locks_file(session_path)
    if not path.exists():
        return {"session_path": session_path, "locks": {}}
    return {"session_path": session_path, "locks": json.loads(path.read_text(encoding="utf-8"))}


@router.post("/autoanimator/locks")
async def narrative_set_locks(req: SessionLocksRequest) -> dict[str, Any]:
    path = _locks_file(req.session_path)
    path.write_text(json.dumps(req.locks, indent=2), encoding="utf-8")
    return {"ok": True, "session_path": req.session_path, "locks": req.locks}


@router.post("/autoanimator/session-sync")
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

    incoming_settings = dict(req.settings or {})

    # Preserve previously stored values when frontend sends blank placeholders.
    # This prevents accidental prompt loss during mode/session transitions.
    for key in ("prompt", "preset_prompt", "project_name"):
        if key in incoming_settings:
            val = incoming_settings.get(key)
            if val is None:
                incoming_settings.pop(key, None)
            elif isinstance(val, str) and not val.strip():
                incoming_settings.pop(key, None)

    # Preset prompt policy:
    # 1) First narrative prompt becomes persistent preset prompt as-is.
    # 2) Once preset exists, keep it immutable across future syncs.
    existing_preset = str(existing_settings.get("preset_prompt", "") or "").strip()
    incoming_prompt = str(incoming_settings.get("prompt", "") or "").strip()
    incoming_preset = str(incoming_settings.get("preset_prompt", "") or "").strip()
    if existing_preset:
        incoming_settings["preset_prompt"] = existing_preset
    elif not incoming_preset and incoming_prompt:
        incoming_settings["preset_prompt"] = incoming_prompt

    next_settings = {**existing_settings, **incoming_settings}
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


@router.post("/autoanimator/materialize-preset-prompt")
async def narrative_materialize_preset_prompt(req: MaterializePresetPromptRequest) -> dict[str, Any]:
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

    settings = current.get("settings") if isinstance(current.get("settings"), dict) else {}
    existing_preset = str(settings.get("preset_prompt", "") or "").strip()
    if existing_preset:
        return {
            "ok": True,
            "session_path": req.session_path,
            "preset_prompt": existing_preset,
            "materialized": False,
        }

    seed_prompt = str(req.base_prompt or settings.get("prompt", "") or "").strip()
    if not seed_prompt:
        prompt_file = ROOT_DIR / "agents" / "autoAnimator" / "prompt.txt"
        if prompt_file.exists():
            try:
                seed_prompt = prompt_file.read_text(encoding="utf-8").strip()
            except Exception:
                seed_prompt = "A dramatic manga story."
        else:
            seed_prompt = "A dramatic manga story."

    # Requested behavior: preserve first narrative prompt exactly as preset prompt.
    preset_prompt = seed_prompt

    settings["preset_prompt"] = preset_prompt
    settings["episode_mode"] = True
    current["settings"] = settings
    state_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "session_path": req.session_path,
        "preset_prompt": preset_prompt,
        "materialized": True,
    }


@router.post("/autoanimator/bootstrap-session")
async def narrative_bootstrap_session(req: BootstrapSessionRequest | None = None) -> dict[str, Any]:
    session_dir = ensure_session_outputs(ROOT_DIR, project_name=(req.project_name if req else None))
    rel = _to_rel_session_path(session_dir)
    sid = rel.split("/")[0] if rel else ""
    return {
        "ok": True,
        "session_path": rel,
        "session_id": sid,
    }


@router.post("/autoanimator/upload-reference-frame")
async def narrative_upload_reference_frame(
    session_path: str = Form(...),
    role: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    role_norm = str(role or "").strip().lower()
    if role_norm not in {"start", "end"}:
        raise HTTPException(status_code=400, detail="role must be 'start' or 'end'")

    session_dir = _resolve_session_dir(session_path)
    refs_dir = session_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "frame.png").suffix.lower() or ".png"
    safe_suffix = suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    name = f"{role_norm}_frame{safe_suffix}"
    out_path = refs_dir / name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    out_path.write_bytes(content)

    rel_frame = str(out_path.relative_to(session_dir))
    return {
        "ok": True,
        "session_path": session_path,
        "role": role_norm,
        "frame_path": rel_frame,
    }

@router.post("/run")
async def start_agent_run(req: RunAgentRequest):
    deprecation_warning = None
    if req.agent_name == "narrativeManga":
        deprecation_warning = "'narrativeManga' is deprecated; use 'AutoAnimator'."
        req.agent_name = "AutoAnimator"

    if req.agent_name != "AutoAnimator":
        return {"status": "queued", "job_id": "test-job-123", "agent": req.agent_name}

    effective_fmt = "youtube_widescreen" if req.format == "youtube_video_only" else req.format
    effective_shorts_export = False if req.format == "youtube_video_only" else req.youtube_shorts_export

    run = _run_narrative_step(
        step="all",
        prompt=req.prompt,
        preset_prompt=req.preset_prompt,
        project_name=req.project_name,
        niche=req.niche,
        session_path=req.session_path if req.session_mode == "existing" else None,
        episodes="new",
        develop=False,
        theme=req.theme,
        preset=req.preset,
        fmt=effective_fmt,
        youtube_shorts_export=effective_shorts_export,
        enable_music=req.enable_music,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
        tts_provider=req.tts_provider,
        gemini_tts_model=req.gemini_tts_model,
        max_image_requests=req.max_image_requests,
        max_chars_per_episode=req.max_chars_per_episode,
        max_panels_per_episode=req.max_panels_per_episode,
        max_episode_duration_mins=req.max_episode_duration_mins,
        start_frame_path=req.start_frame_path,
        end_frame_path=req.end_frame_path,
        create_banner=req.create_banner,
        intro_only=req.intro_only,
        planner_skill_ids=req.planner_skill_ids,
        planner_skill_prompt=req.planner_skill_prompt,
    )

    return {
        "status": "success" if run["exit_code"] == 0 else "error",
        "job_id": "autoanimator-sync-run",
        "agent": req.agent_name,
        "deprecation_warning": deprecation_warning,
        "exit_code": run["exit_code"],
        "session_path": run["session_path"],
        "stdout": run["stdout"],
        "stderr": run["stderr"],
    }


@router.get("/autoanimator/checkpoints")
async def narrative_checkpoints(session_path: str) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    return {
        "session_path": session_path,
        "hashes": _workflow_hashes(session_dir),
        "history": _history_payload(session_dir),
    }


@router.get("/autoanimator/hash-history")
async def narrative_hash_history(session_path: str) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    return {
        "session_path": session_path,
        "history": _history_payload(session_dir),
    }


@router.post("/autoanimator/revert-hash")
async def narrative_revert_hash(req: RestoreHashRequest) -> dict[str, Any]:
    session_dir = _resolve_session_dir(req.session_path)

    # Persist the current step state before rollback so users can move forward/backward.
    _record_step_hash_history(session_dir, req.step)

    _restore_step_from_hash(session_dir, req.step, req.hash)
    # Promote restored state as the latest current entry in history.
    _record_step_hash_history(session_dir, req.step)

    hashes = _workflow_hashes(session_dir)
    history = _history_payload(session_dir)
    return {
        "ok": True,
        "session_path": req.session_path,
        "step": req.step,
        "hash": req.hash,
        "hashes": hashes,
        "history": history,
    }


@router.post("/autoanimator/run-step")
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

    effective_fmt = "youtube_widescreen" if req.format == "youtube_video_only" else req.format
    effective_shorts_export = False if req.format == "youtube_video_only" else req.youtube_shorts_export

    run = _run_narrative_step(
        step=step,
        prompt=req.prompt,
        preset_prompt=req.preset_prompt,
        project_name=req.project_name,
        niche=req.niche,
        session_path=req.session_path if req.session_mode == "existing" else req.session_path,
        episodes=req.episodes,
        develop=req.develop,
        episode=req.episode,
        theme=req.theme,
        preset=req.preset,
        fmt=effective_fmt,
        youtube_shorts_export=effective_shorts_export,
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
        tts_provider=req.tts_provider,
        gemini_tts_model=req.gemini_tts_model,
        music_provider=req.music_provider,
        lyria_model=req.lyria_model,
        start_frame_path=req.start_frame_path,
        end_frame_path=req.end_frame_path,
        create_banner=req.create_banner,
        intro_only=req.intro_only,
        planner_skill_ids=req.planner_skill_ids,
        planner_skill_prompt=req.planner_skill_prompt,
    )

    hashes = None
    history = None
    if run.get("session_path"):
        try:
            session_dir = _resolve_session_dir(run["session_path"])
            hashes = _workflow_hashes(session_dir)
            if run["exit_code"] == 0:
                history = _record_hash_history_for_run(session_dir, step)
            else:
                history = _history_payload(session_dir)
        except Exception:
            hashes = None
            history = None

    return {
        "status": "success" if run["exit_code"] == 0 else "error",
        "exit_code": run["exit_code"],
        "step": req.step,
        "session_path": run.get("session_path"),
        "stdout": run["stdout"],
        "stderr": run["stderr"],
        "hashes": hashes,
        "history": history,
    }


@router.post("/autoanimator/run-step-live")
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

    if req.session_mode != "existing" and not req.session_path:
        session_dir = ensure_session_outputs(ROOT_DIR)
        req.session_path = _to_rel_session_path(session_dir)

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

    job_id = f"autoanimator-step-{uuid.uuid4().hex[:12]}"
    _create_job(job_id)
    worker = threading.Thread(target=_run_narrative_step_worker, args=(job_id, req, step, res), daemon=True)
    worker.start()

    session_id = str(req.session_path).split("/")[0] if req.session_path else None
    return {"done": False, "job_id": job_id, "session_path": req.session_path, "session_id": session_id}


@router.get("/autoanimator/job/{job_id}")
async def narrative_job_status(job_id: str) -> dict[str, Any]:
    state = _job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"done": state["done"], "result": state["result"]}


@router.get("/autoanimator/session-active-job")
async def narrative_session_active_job(session_path: str) -> dict[str, Any]:
    target = str(session_path or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="session_path is required")

    candidate: tuple[str, dict[str, Any]] | None = None
    with NARRATIVE_JOBS_LOCK:
        for jid, st in NARRATIVE_JOBS.items():
            if st.get("done"):
                continue
            if str(st.get("session_path") or "") != target:
                continue
            if candidate is None or str(st.get("updated_at") or "") > str(candidate[1].get("updated_at") or ""):
                candidate = (jid, st)

    if not candidate:
        return {"found": False}

    jid, st = candidate
    return {
        "found": True,
        "job_id": jid,
        "session_path": st.get("session_path") or target,
    }


@router.post("/autoanimator/job/{job_id}/abort")
async def narrative_abort_job(job_id: str) -> dict[str, Any]:
    state = _job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    proc = state.get("proc")
    if state.get("done"):
        return {"ok": True, "job_id": job_id, "aborted": False, "status": "already-finished"}
    if proc is None:
        return {"ok": True, "job_id": job_id, "aborted": False, "status": "no-process"}

    try:
        state["aborted"] = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        state["queue"].put({"type": "error", "msg": "Abort requested by user. Stopping pipeline..."})
        return {"ok": True, "job_id": job_id, "aborted": True, "status": "terminating"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to abort job: {e}")


@router.post("/autoanimator/copy-character")
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
        target_session_dir = OUTPUTS_DIR / f"{new_sid}" / "AutoAnimator"
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


@router.post("/autoanimator/redo-char")
async def narrative_redo_single_char(req: RedoSingleCharRequest) -> dict[str, Any]:
    session_dir = _resolve_session_dir(req.session_path)
    board_path = _episode_board_path(session_dir, req.episode)
    if not board_path:
        raise HTTPException(status_code=404, detail="No storyboard.json found for session")

    board = json.loads(board_path.read_text(encoding="utf-8"))
    chars = board.get("characters", []) if isinstance(board, dict) else []
    if not isinstance(chars, list):
        raise HTTPException(status_code=400, detail="Invalid storyboard characters format")

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

    from agents.autoAnimator.chains.char_gen import CharGen

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

    try:
        history = _record_hash_history_for_run(session_dir, "chars")
    except Exception:
        history = _history_payload(session_dir)

    if tracker is not None and tracker.calls:
        tracker.save(session_dir)

    return {
        "ok": True,
        "session_path": req.session_path,
        "char_name": req.char_name,
        "image_path": out,
        "hashes": hashes,
        "history": history,
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "llm_calls_recorded": len(tracker.calls) if tracker is not None else 0,
    }

# ─────────────────────────────────────────────────────────────────────────────
# OVA Agent endpoints
# ─────────────────────────────────────────────────────────────────────────────

OVA_RUNNER = ROOT_DIR / "agents" / "ova" / "run.py"


def _load_ova_config() -> dict[str, Any]:
    config_path = ROOT_DIR / "agents" / "ova" / "config.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_ova_cmd(
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
    font_style: str | None = None,
    subtitle_style: str | None = None,
    episode_mode: bool = False,
    planner_model: str | None = None,
    chars_model: str | None = None,
    scenes_model: str | None = None,
    tts_provider: str | None = None,
    gemini_tts_model: str | None = None,
    music_provider: str | None = None,
    lyria_model: str | None = None,
) -> list[str]:
    cmd = [
        _python_bin(), "-u", str(OVA_RUNNER),
        "--workspace", str(ROOT_DIR),
        "--step", step,
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
    if font_style:
        cmd.extend(["--font_style", font_style])
    if subtitle_style:
        cmd.extend(["--subtitle_style", subtitle_style])
    cmd.extend(["--episode_mode", "true" if episode_mode else "false"])
    if planner_model:
        cmd.extend(["--planner_model", planner_model])
    if chars_model:
        cmd.extend(["--character_image_model", chars_model])
    if scenes_model:
        cmd.extend(["--scene_image_model", scenes_model])
    if tts_provider:
        cmd.extend(["--tts_provider", tts_provider])
    if gemini_tts_model:
        cmd.extend(["--gemini_tts_model", gemini_tts_model])
    if music_provider:
        cmd.extend(["--music_provider", music_provider])
    if lyria_model:
        cmd.extend(["--lyria_model", lyria_model])
    return cmd


class OvaRunStepRequest(BaseModel):
    session_mode: str = "new"
    session_path: str | None = None
    step: str = Field(default="all", pattern="^(all|planner|chars|scenes|audio|music|video)$")
    reset: bool = False
    prompt: str | None = None
    episodes: str = "new"
    develop: bool = False
    episode: int | None = None
    theme: str | None = None
    preset: str | None = None
    format: str | None = None
    enable_music: bool = False
    max_image_requests: int | None = None
    max_chars_per_episode: int | None = None
    max_panels_per_episode: int | None = None
    max_episode_duration_mins: int | None = None
    buildpack_resolution: str | None = None
    font_style: str | None = None
    subtitle_style: str | None = None
    episode_mode: bool = False
    planner_model: str | None = None
    chars_model: str | None = None
    scenes_model: str | None = None
    tts_provider: str | None = None
    gemini_tts_model: str | None = None
    music_provider: str | None = None
    lyria_model: str | None = None


class OvaBootstrapRequest(BaseModel):
    pass


class OvaSessionSyncRequest(BaseModel):
    session_path: str
    settings: dict[str, Any] = Field(default_factory=dict)


def _run_ova_step_worker(job_id: str, req: OvaRunStepRequest, step: str, res: tuple[int, int] | None):
    state = _job_state(job_id)
    if not state:
        return

    q: Queue = state["queue"]
    q.put({"type": "info", "msg": f"OVA: Starting step '{req.step}'..."})

    cmd = _build_ova_cmd(
        step=step,
        prompt=req.prompt,
        session_path=req.session_path,
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
        font_style=req.font_style,
        subtitle_style=req.subtitle_style,
        episode_mode=req.episode_mode,
        planner_model=req.planner_model,
        chars_model=req.chars_model,
        scenes_model=req.scenes_model,
        tts_provider=req.tts_provider,
        gemini_tts_model=req.gemini_tts_model,
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
        start_new_session=True,
    )
    state["proc"] = proc

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
            print(f"[ova:{job_id}:stdout] {line}", flush=True)
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
            print(f"[ova:{job_id}:stderr] {line}", flush=True)

    t_out = threading.Thread(target=_drain_stdout, daemon=True)
    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_out.start()
    t_err.start()
    exit_code = proc.wait()
    t_out.join(timeout=2)
    t_err.join(timeout=2)

    hashes = None
    history = None
    if detected_session_path:
        try:
            session_dir = _resolve_session_dir(detected_session_path)
            hashes = _workflow_hashes(session_dir)
            if exit_code == 0:
                history = _record_hash_history_for_run(session_dir, step)
            else:
                history = _history_payload(session_dir)
        except Exception:
            hashes = None
            history = None

    result = {
        "status": "aborted" if state.get("aborted") else ("success" if exit_code == 0 else "error"),
        "exit_code": exit_code,
        "step": req.step,
        "session_path": detected_session_path,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "hashes": hashes,
        "history": history,
    }
    state["proc"] = None
    state["result"] = result
    state["done"] = True
    msg_type = "success" if result["status"] == "success" else "error"
    q.put({"type": msg_type, "msg": f"OVA step '{req.step}' finished with status {result['status']}."})


@router.get("/ova/planner-options")
async def ova_planner_options() -> dict[str, Any]:
    config = _load_ova_config()
    return {
        "themes": config.get("themes", {}),
        "art_styles": config.get("art_styles", {}),
        "output_presets": config.get("output_presets", {}),
        "voice_profiles": config.get("tts_voices_pool", {}),
        "models": config.get("models", {}),
        "defaults": config.get("defaults", {}),
        "video": config.get("video", {}),
    }


@router.post("/ova/bootstrap-session")
async def ova_bootstrap_session() -> dict[str, Any]:
    from agents.ova.utils import ensure_session_outputs as ova_ensure
    session_dir = ova_ensure(ROOT_DIR)
    rel = _to_rel_session_path(session_dir)
    sid = rel.split("/")[0] if rel else ""
    return {"ok": True, "session_path": rel, "session_id": sid}


@router.post("/ova/session-sync")
async def ova_session_sync(req: OvaSessionSyncRequest) -> dict[str, Any]:
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
    incoming_settings = {k: v for k, v in (req.settings or {}).items()
                         if v is not None and (not isinstance(v, str) or v.strip())}
    current["settings"] = {**existing_settings, **incoming_settings}
    state_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return {"ok": True, "session_path": req.session_path, "settings": current["settings"]}


@router.get("/ova/checkpoints")
async def ova_checkpoints(session_path: str) -> dict[str, Any]:
    session_dir = _resolve_session_dir(session_path)
    return {
        "session_path": session_path,
        "hashes": _workflow_hashes(session_dir),
        "history": _history_payload(session_dir),
    }


@router.post("/ova/run-step-live")
async def ova_run_step_live(req: OvaRunStepRequest) -> dict[str, Any]:
    step = req.step

    if req.session_mode != "existing" and not req.session_path:
        from agents.ova.utils import ensure_session_outputs as ova_ensure
        session_dir = ova_ensure(ROOT_DIR)
        req.session_path = _to_rel_session_path(session_dir)

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

    job_id = f"ova-step-{uuid.uuid4().hex[:12]}"
    _create_job(job_id)
    worker = threading.Thread(target=_run_ova_step_worker, args=(job_id, req, step, res), daemon=True)
    worker.start()

    session_id = str(req.session_path).split("/")[0] if req.session_path else None
    return {"done": False, "job_id": job_id, "session_path": req.session_path, "session_id": session_id}


@router.get("/ova/job/{job_id}")
async def ova_job_status(job_id: str) -> dict[str, Any]:
    state = _job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"done": state["done"], "result": state["result"]}


@router.post("/ova/job/{job_id}/abort")
async def ova_abort_job(job_id: str) -> dict[str, Any]:
    state = _job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    proc = state.get("proc")
    if proc and proc.poll() is None:
        state["aborted"] = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
    return {"ok": True, "job_id": job_id}


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
