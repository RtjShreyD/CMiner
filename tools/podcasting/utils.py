import os
import random
from pathlib import Path
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment.")

genai.configure(api_key=GEMINI_API_KEY)

def _new_session_id() -> str:
    rng = random.SystemRandom()
    return str(rng.randint(1_000_000, 9_999_999))

def ensure_session_outputs(base_dir: Path) -> Path:
    outputs_dir = base_dir / "outputs"
    session_id = _new_session_id()
    session_dir = outputs_dir / session_id / "podCasting"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "chars").mkdir(parents=True, exist_ok=True)
    (session_dir / "audio").mkdir(parents=True, exist_ok=True)
    (session_dir / "frames").mkdir(parents=True, exist_ok=True)
    return session_dir

def get_model(model_name: str):
    return genai.GenerativeModel(model_name)
