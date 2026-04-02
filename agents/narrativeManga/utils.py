import os
import random
from pathlib import Path
from agents.shared.gemini_compat import get_model as _get_model

# Keep env read for backwards compatibility with existing modules.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _new_session_id() -> str:
    rng = random.SystemRandom()
    return str(rng.randint(1_000_000, 9_999_999))


def ensure_session_outputs(base_dir: Path) -> Path:
    """Create a new session directory with all required subdirectories."""
    outputs_dir = base_dir / "outputs"
    session_id = _new_session_id()
    session_dir = outputs_dir / session_id / "narrativeManga"
    session_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ["episodes", "chars", "scenes", "audio", "overlays", "frames"]:
        (session_dir / subdir).mkdir(parents=True, exist_ok=True)

    return session_dir


def get_model(model_name: str):
    """Return a Gemini model adapter backed by google.genai."""
    return _get_model(model_name, required_key=False)
