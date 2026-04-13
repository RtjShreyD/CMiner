import os
import random
import re
from pathlib import Path
from agents.shared.gemini_compat import get_model as _get_model

# Keep env read for backwards compatibility with existing modules.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _new_session_id() -> str:
    rng = random.SystemRandom()
    return str(rng.randint(1_000_000, 9_999_999))


def sanitize_project_name_for_session(project_name: str | None) -> str:
    raw = str(project_name or "").strip()
    if not raw:
        return "untitled"
    token = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
    token = re.sub(r"_+", "_", token)
    return token or "untitled"


def autoanimator_session_folder_name(project_name: str | None) -> str:
    return f"{sanitize_project_name_for_session(project_name)}_autoAnimator"


def ensure_session_outputs(base_dir: Path, project_name: str | None = None) -> Path:
    """Create a new session directory with all required subdirectories."""
    outputs_dir = base_dir / "outputs"
    session_id = _new_session_id()
    session_dir = outputs_dir / session_id / autoanimator_session_folder_name(project_name)
    session_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ["episodes", "chars", "scenes", "audio", "overlays", "frames"]:
        (session_dir / subdir).mkdir(parents=True, exist_ok=True)

    return session_dir


def get_model(model_name: str):
    """Return a Gemini model adapter backed by google.genai."""
    return _get_model(model_name, required_key=False)
