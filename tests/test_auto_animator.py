import json
import tempfile
import sys
import types
from pathlib import Path
from unittest import mock

# Stub the google.genai module used by AutoAnimator.utils
google = types.ModuleType("google")
genai = types.ModuleType("google.genai")
genai_types = types.ModuleType("google.genai.types")


class _Part:
    @staticmethod
    def from_bytes(data=None, mime_type=None):
        return {"data": data, "mime_type": mime_type}

class _Models:
    def generate_content(self, model=None, contents=None):
        return None

class Client:
    def __init__(self, api_key=None):
        self.models = _Models()

setattr(genai, "Client", Client)
setattr(genai_types, "Part", _Part)
setattr(genai, "types", genai_types)
setattr(google, "genai", genai)

# Stub dotenv
dotenv = types.ModuleType("dotenv")
def load_dotenv():
    return None
setattr(dotenv, "load_dotenv", load_dotenv)

sys.modules["google"] = google
sys.modules["google.genai"] = genai
sys.modules["google.genai.types"] = genai_types
sys.modules["dotenv"] = dotenv

from agents.autoAnimator.chains.episode_planner import EpisodePlanner
from agents.autoAnimator import run as auto_run


class FakeModel:
    def __init__(self, model_name="fake-model"):
        self.model_name = model_name

    def generate_content(self, contents):
        fake_output = {
            "episode_number": 1,
            "episode_title": "Test Episode",
            "episode_summary": "A short test story.",
            "characters": [
                {
                    "name": "Alex",
                    "description": "Protagonist",
                    "visual_prompt": "Young hero with red jacket",
                    "voice_profile": "hero",
                    "assigned_voice": "en-US-ChristopherNeural"
                }
            ],
            "panels": [
                {
                    "panel_number": 1,
                    "characters_present": ["Alex"],
                    "dialogue": [{"character": "Alex", "line": "This is a test."}],
                    "scene_description": "Alex stands in a neon city.",
                    "camera_angle": "medium-shot",
                    "mood": "dramatic",
                    "duration_seconds": 5
                }
            ],
            "render_strategy": {
                "transition_type": "cut",
                "panel_layout": "fullscreen",
                "art_style": "cinematic anime"
            }
        }
        return mock.Mock(text=json.dumps(fake_output))


import unittest


class EpisodePlannerTests(unittest.TestCase):
    def test_episode_planner_theme_injection(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            planner = EpisodePlanner(theme="mystery_adventure", art_style="cinematic anime")

            # patch get_model and tracked_generate to avoid external API
            with mock.patch("agents.autoAnimator.chains.episode_planner.get_model", return_value=FakeModel()):
                with mock.patch("agents.autoAnimator.chains.episode_planner.tracked_generate", side_effect=lambda tracker, model, prompt, purpose=None: FakeModel().generate_content(None)):
                    board = planner.run("", tmp_path)

            self.assertEqual(board["episode_number"], 1)
            self.assertEqual(board["episode_title"], "Test Episode")
            self.assertEqual(board["characters"][0]["name"], "Alex")

            ep_dir = tmp_path / "episodes" / "episode1"
            self.assertTrue(ep_dir.exists())
            self.assertTrue((ep_dir / "storyboard.json").exists())

    def test_episode_planner_expands_panels_to_target_budget(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            planner = EpisodePlanner(
                theme="mystery_adventure",
                art_style="cinematic anime",
                max_duration_mins=1,
                max_panels=20,
            )

            with mock.patch("agents.autoAnimator.chains.episode_planner.get_model", return_value=FakeModel()):
                with mock.patch("agents.autoAnimator.chains.episode_planner.tracked_generate", side_effect=lambda tracker, model, prompt, purpose=None: FakeModel().generate_content(None)):
                    board = planner.run("short baseline", tmp_path)

            self.assertEqual(len(board.get("panels", [])), 20)


class ProjectNameSelectionTests(unittest.TestCase):
    def test_unspecified_project_name_detection(self):
        self.assertTrue(auto_run._is_unspecified_project_name("AutoAnimator Project"))
        self.assertTrue(auto_run._is_unspecified_project_name("untitled"))
        self.assertFalse(auto_run._is_unspecified_project_name("Prompt Tank Prime"))

    def test_auto_assign_project_name_fallback_without_prompt(self):
        name = auto_run._auto_assign_project_name(
            model_name="models/gemini-flash-latest",
            seed_prompt="",
            niche_key="stage_show",
            tracker=auto_run.LLMTracker(),
        )
        self.assertTrue(isinstance(name, str) and len(name.strip()) > 0)
