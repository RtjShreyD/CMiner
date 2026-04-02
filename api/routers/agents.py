import asyncio
import json
import hashlib
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter()
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = ROOT_DIR / "outputs"
NARRATIVE_RUNNER = ROOT_DIR / "agents" / "narrativeManga" / "run.py"
VENV_PYTHON = ROOT_DIR / ".venv" / "bin" / "python3"


def _python_bin() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


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
) -> dict[str, Any]:
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
        "video": [session_dir / "frames", session_dir / "concat.txt", session_dir / "thumbnail.jpg"],
        "all": [
            session_dir / "episodes",
            session_dir / "chars",
            session_dir / "scenes",
            session_dir / "audio",
            session_dir / "overlays",
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
        "video": _step_hash(session_dir, "video"),
    }

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
    step: str = Field(default="all", pattern="^(all|planner|chars|scenes|audio|texts|video)$")
    reset: bool = False
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


class CopyCharacterRequest(BaseModel):
    source_path: str
    target_session_path: str | None = None


class SessionLocksRequest(BaseModel):
    session_path: str
    locks: dict[str, bool]


def _locks_file(session_path: str) -> Path:
    return _resolve_session_dir(session_path) / "workflow_locks.json"


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
        "video": "video",
        "all": "all",
    }
    step = step_map.get(req.step, req.step)

    if req.step == "texts" and req.narration_mode in {"subtitles_only", "none"}:
        return {
            "status": "skipped",
            "reason": "Narration mode does not require cloud/text overlay generation.",
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

@router.websocket("/stream/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """Streams live console output back to the Web UI 'Terminal' pane."""
    await websocket.accept()
    try:
        # Placeholder mock streaming logic
        await websocket.send_text(json.dumps({"type": "info", "msg": f"Connected to log stream for Job {job_id}"}))
        await asyncio.sleep(1)
        
        for i in range(10):
            await websocket.send_text(json.dumps({"type": "log", "msg": f"Agent processing step {i + 1}/10..."}))
            await asyncio.sleep(0.5)
            
        await websocket.send_text(json.dumps({"type": "success", "msg": "Agent execution completed successfully."}))
        
    except WebSocketDisconnect:
        print(f"Client disconnected from job {job_id}")
    finally:
        pass # Handle cleanup
