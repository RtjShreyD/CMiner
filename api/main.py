"""CMiner API Server.

Serves as the backend for the Web Studio UI, exposing agent execution,
workspace session exploration, and real-time streaming sockets.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import sessions, agents
from api.models import create_db_and_tables

# Configuration
OUTPUTS_DIR = Path("outputs")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure outputs exists
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    # Database init
    create_db_and_tables()
    yield
    # Cleanup here

app = FastAPI(
    title="CMiner Studio API",
    description="Backend API for the CMiner Web Studio.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In development, allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount outputs for direct native media streaming in the browser
# e.g., <video src="http://localhost:8000/media/something.mp4">
app.mount("/media", StaticFiles(directory=OUTPUTS_DIR), name="media")

# Routers
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "CMiner Studio API"}
