"""CMiner API Server.

Serves as the backend for the Web Studio UI, exposing agent execution,
workspace session exploration, and real-time streaming sockets.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import sessions, agents, styles, characters, overlay_samples
from api.models import create_db_and_tables
from api.services.registry_store import ensure_library_dirs, ensure_subdirs, seed_default_styles

# Configuration
OUTPUTS_DIR = Path("outputs")
LIBRARY_DIR = Path("library")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure outputs exists
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    ensure_library_dirs()
    ensure_subdirs()
    seed_default_styles()
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

# Mount outputs and library for direct media streaming in the browser
# e.g., <video src="http://localhost:8000/media/something.mp4">
# e.g., <img src="http://localhost:8000/library-media/characters/...png">
app.mount("/media", StaticFiles(directory=OUTPUTS_DIR), name="media")
app.mount("/library-media", StaticFiles(directory=LIBRARY_DIR), name="library-media")

# Routers
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(styles.router, prefix="/api/styles", tags=["styles"])
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(overlay_samples.router, prefix="/api/overlay-samples", tags=["overlay-samples"])

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "CMiner Studio API"}
