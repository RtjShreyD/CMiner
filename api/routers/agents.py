import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()

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

@router.post("/run")
async def start_agent_run(req: RunAgentRequest):
    """Placeholder to spawn a background Celery/APScheduler job.
    Returns the Job ID for WebSocket tracking."""
    # TODO: Implement actual subprocess launching
    return {"status": "queued", "job_id": "test-job-123", "agent": req.agent_name}

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
