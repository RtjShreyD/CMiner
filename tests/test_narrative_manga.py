import json
import tempfile
import sys
import types
from pathlib import Path
from unittest import mock

# Stub the google.generativeai module used by narrativeManga.utils
google = types.ModuleType("google")
generativeai = types.ModuleType("google.generativeai")

def configure(api_key=None):
    return None

class GenerativeModel:
    def __init__(self, model_name):
        self.model_name = model_name

    def generate_content(self, contents):
        return None

setattr(generativeai, "configure", configure)
setattr(generativeai, "GenerativeModel", GenerativeModel)
setattr(google, "generativeai", generativeai)

# Stub dotenv
dotenv = types.ModuleType("dotenv")
def load_dotenv():
    return None
setattr(dotenv, "load_dotenv", load_dotenv)

sys.modules["google"] = google
sys.modules["google.generativeai"] = generativeai
sys.modules["dotenv"] = dotenv

from agents.narrativeManga.chains.episode_planner import EpisodePlanner


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
            with mock.patch("agents.narrativeManga.chains.episode_planner.get_model", return_value=FakeModel()):
                with mock.patch("agents.narrativeManga.chains.episode_planner.tracked_generate", side_effect=lambda tracker, model, prompt, purpose=None: FakeModel().generate_content(None)):
                    board = planner.run("", tmp_path)

            self.assertEqual(board["episode_number"], 1)
            self.assertEqual(board["episode_title"], "Test Episode")
            self.assertEqual(board["characters"][0]["name"], "Alex")

            ep_dir = tmp_path / "episodes" / "episode1"
            self.assertTrue(ep_dir.exists())
            self.assertTrue((ep_dir / "manga-board.json").exists())
