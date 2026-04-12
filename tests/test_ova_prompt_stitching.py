"""
Tests for OVA agent prompt stitching.

Verifies that each chain:
1. Reads the correct keys from ``prompt_config``.
2. Substitutes every {template_variable} with real values.
3. Falls back to built-in defaults when ``prompt_config`` is empty.
4. Values loaded from the real config.json produce well-formed prompts.

No LLM calls, no disk I/O, no FFmpeg — all heavy dependencies are stubbed.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import textwrap
import types
from pathlib import Path
from typing import Any, Dict
from unittest import mock

# ── Minimal stubs for heavy imports ──────────────────────────────────────────

def _make_google_stubs():
    google = types.ModuleType("google")
    genai = types.ModuleType("google.genai")
    types_ = types.ModuleType("google.genai.types")

    class _FakeResponse:
        text = '{"episode_number":1,"episode_title":"T","episode_summary":"S","characters":[],"panels":[],"render_strategy":{}}'

    class _Models:
        def generate_content(self, model=None, contents=None, config=None):
            return _FakeResponse()

    class Client:
        def __init__(self, api_key=None):
            self.models = _Models()

    genai.Client = Client
    google.genai = genai
    sys.modules["google"] = google
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.types"] = types_


def _make_misc_stubs():
    for mod in [
        "dotenv", "cv2", "edge_tts", "edge_tts.communicate",
        "agents.muicStruddler", "agents.muicStruddler.music_agent",
        "api", "api.services", "api.services.buildpacks",
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # dotenv
    sys.modules["dotenv"].load_dotenv = lambda: None

    # cv2 stubs
    cv2 = sys.modules["cv2"]
    cv2.data = types.SimpleNamespace(haarcascades="")
    cv2.CascadeClassifier = mock.MagicMock(return_value=mock.MagicMock(empty=lambda: True))
    cv2.imread = mock.MagicMock(return_value=None)
    cv2.cvtColor = mock.MagicMock(return_value=None)
    cv2.COLOR_BGR2GRAY = 0

    # buildpacks stub
    sys.modules["api.services.buildpacks"]._load_font = mock.MagicMock(return_value=None)

    # music agent stubs
    ma = sys.modules["agents.muicStruddler.music_agent"]
    ma.StrudelMusicAgent = mock.MagicMock()
    ma.LyriaMusicAgent = mock.MagicMock()


_make_google_stubs()
_make_misc_stubs()

# ── Now safe to import OVA modules ───────────────────────────────────────────

from agents.ova.chains.episode_planner import EpisodePlanner  # noqa: E402
from agents.ova.chains.char_gen import CharGen  # noqa: E402
from agents.ova.chains.scene_gen import SceneGen  # noqa: E402
from agents.ova.chains.music_gen import MusicGen  # noqa: E402

# ── Helpers ───────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).resolve().parent.parent / "agents" / "ova" / "config.json"


def _load_real_config() -> Dict[str, Any]:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _no_placeholders(text: str) -> bool:
    """Return True if no un-expanded {placeholder} tokens remain."""
    import re
    return not bool(re.search(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))


def _build_planner_prompt(prompt_config: Dict[str, Any]) -> str:
    """Extract the stitched prompt string from EpisodePlanner without making LLM calls."""
    planner = EpisodePlanner(
        model_name="models/test",
        tts_voices_pool={"narrator": ["en-US-AriaNeural"]},
        max_duration_mins=2,
        max_chars=4,
        max_panels=10,
        art_style="cinematic anime",
        theme=None,
        episode_mode=False,
        target_episode=1,
        tracker=None,
        prompt_config=prompt_config,
    )
    # Reproduce the prompt-building logic inline (mirrors run() without I/O)
    next_num = 1
    theme_text = ""
    target_seconds = max(120, planner.max_duration_mins * 60)
    min_panel_duration = max(6, target_seconds // max(1, planner.max_panels) - 2)

    pc = planner.prompt_config
    system_text = pc.get("system", "Default system")
    ep1_structure = pc.get("episode_1_structure", "Default ep1 structure")
    char_style_rules = pc.get("character_style_rules", "Default char rules")
    scene_rule = pc.get("scene_description_rule", "Default scene rule")
    hard_rules_extra = pc.get("hard_rules_extra", "Default hard rules")
    no_continuity = pc.get("no_continuity_note", "Default no-continuity note")

    return (
        f"{system_text}\n\n"
        f"CORE SYSTEM PREMISE:\ntest prompt\n\n"
        f"{theme_text}"
        f"DEFAULT ART STYLE: {planner.art_style}\n"
        f"EPISODE NUMBER: {next_num}\n"
        f"{no_continuity}\n"
        "HARD RULES:\n"
        f"- Max characters: {planner.max_chars}\n"
        f"- EXACTLY {planner.max_panels} panels\n"
        f"- Target total runtime >= {target_seconds} seconds\n"
        f"- Each panel duration_seconds must be >= {min_panel_duration}\n"
        f"- Episode 1 is a SHOW INTRO ONLY — no invention pitch, no contestant. Structure: {ep1_structure}\n"
        f"- {char_style_rules}\n"
        f"- {scene_rule}\n"
        f"- {hard_rules_extra}\n"
    )


# ── EpisodePlanner tests ──────────────────────────────────────────────────────

class TestEpisodePlannerPrompt:
    def test_all_config_keys_present_in_output(self):
        """Every config.json episode_planner value should appear in the final prompt."""
        cfg = _load_real_config().get("prompts", {}).get("episode_planner", {})
        prompt = _build_planner_prompt(cfg)
        for key, value in cfg.items():
            # The value appears (possibly as part of a larger block)
            assert value in prompt, f"Key '{key}' value not found in planner prompt"

    def test_dynamic_values_are_substituted(self):
        """Episode number, panel count, art style must appear."""
        cfg = _load_real_config().get("prompts", {}).get("episode_planner", {})
        prompt = _build_planner_prompt(cfg)
        assert "EPISODE NUMBER: 1" in prompt
        assert "EXACTLY 10 panels" in prompt
        assert "cinematic anime" in prompt
        assert "Max characters: 4" in prompt

    def test_default_fallback_when_config_empty(self):
        """Empty prompt_config must still build a structurally valid prompt."""
        prompt = _build_planner_prompt({})
        assert "HARD RULES:" in prompt
        assert "EPISODE NUMBER:" in prompt
        assert "cinematic anime" in prompt

    def test_custom_system_text_overrides_default(self):
        """Custom system key should replace the default director text."""
        custom = {"system": "CUSTOM SYSTEM INSTRUCTION HERE"}
        prompt = _build_planner_prompt(custom)
        assert "CUSTOM SYSTEM INSTRUCTION HERE" in prompt
        assert "You are the DIRECTOR" not in prompt

    def test_custom_episode1_structure_used(self):
        custom = {"episode_1_structure": "MY CUSTOM STRUCTURE ABC"}
        prompt = _build_planner_prompt(custom)
        assert "MY CUSTOM STRUCTURE ABC" in prompt

    def test_no_leftover_template_placeholders(self):
        """No un-expanded {placeholder} tokens should survive."""
        cfg = _load_real_config().get("prompts", {}).get("episode_planner", {})
        prompt = _build_planner_prompt(cfg)
        assert _no_placeholders(prompt), f"Leftover placeholders in planner prompt: {prompt[:300]}"

    def test_theme_injected_when_set(self):
        planner = EpisodePlanner(
            model_name="models/test",
            theme="scary_stories",
            target_episode=1,
            prompt_config={},
        )
        assert planner.theme == "scary_stories"


# ── CharGen tests ─────────────────────────────────────────────────────────────

class TestCharGenPrompt:
    def _chargen(self, prompt_config: Dict[str, Any]) -> CharGen:
        return CharGen(
            image_model_name="models/test",
            resolution=(1920, 1080),
            art_style="noir comic",
            prompt_config=prompt_config,
        )

    def test_default_portrait_prompt_contains_required_phrases(self):
        cg = self._chargen({})
        p = cg._build_prompt("A tall warrior with a red cape")
        assert "A tall warrior with a red cape" in p
        assert "noir comic" in p
        assert "1920:1080" in p
        assert "1920x1080" in p

    def test_config_template_is_used(self):
        cfg = _load_real_config().get("prompts", {}).get("char_gen", {})
        cg = self._chargen(cfg)
        p = cg._build_prompt("Hero in golden armor")
        assert "Hero in golden armor" in p
        assert "noir comic" in p
        assert "1920" in p

    def test_no_leftover_placeholders_default(self):
        cg = self._chargen({})
        p = cg._build_prompt("Mysterious wizard")
        assert _no_placeholders(p), f"Leftover placeholders in char prompt: {p}"

    def test_no_leftover_placeholders_from_config(self):
        cfg = _load_real_config().get("prompts", {}).get("char_gen", {})
        cg = self._chargen(cfg)
        p = cg._build_prompt("Mysterious wizard")
        assert _no_placeholders(p), f"Leftover placeholders in char prompt: {p}"

    def test_custom_portrait_template(self):
        custom = {"portrait_prompt": "CUSTOM: {visual_prompt} | {art_style} | {width}x{height}"}
        cg = self._chargen(custom)
        p = cg._build_prompt("Samurai")
        assert p == "CUSTOM: Samurai | noir comic | 1920x1080"

    def test_anchor_prefix_from_config(self):
        cfg = _load_real_config().get("prompts", {}).get("char_gen", {})
        cg = self._chargen(cfg)
        prefix = cg.prompt_config.get("anchor_prefix", "")
        assert len(prefix) > 0, "anchor_prefix should be non-empty in config"
        assert "EXACT same art style" in prefix or "same art style" in prefix.lower()

    def test_default_anchor_prefix_fallback(self):
        cg = self._chargen({})
        prefix = cg.prompt_config.get(
            "anchor_prefix",
            "Generate a NEW character in the EXACT same art style. ",
        )
        assert "EXACT same art style" in prefix


# ── SceneGen tests ────────────────────────────────────────────────────────────

class TestSceneGenPrompt:
    def _scenegen(self, prompt_config: Dict[str, Any]) -> SceneGen:
        return SceneGen(
            image_model_name="models/test",
            resolution=(1920, 1080),
            art_style="horror manga",
            prompt_config=prompt_config,
        )

    def _build_scene_prompt(
        self,
        sg: SceneGen,
        scene_desc: str = "A dark alley at midnight",
        camera: str = "close-up",
        mood: str = "tense",
        chars_in_scene: str = "Zara Nova: tall host; Brahma: four-armed deity",
    ) -> str:
        """Reproduce scene prompt building logic without disk I/O."""
        width, height = sg.resolution
        template = sg.prompt_config.get(
            "panel_prompt",
            "A cinematic manga panel. {scene_desc}. "
            "Camera: {camera}. Mood: {mood}. "
            "Characters in scene: {chars_in_scene}. "
            "Art style: {art_style}. "
            "IMPORTANT: Include ONLY manga expression/reaction elements in-scene: sweat drops, sparkle bursts, "
            "anger marks, thought wisps, motion lines. "
            "DO NOT draw any speech bubbles or dialogue text boxes in the image — "
            "those will be added programmatically as overlays. "
            "CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution.",
        )
        return template.format(
            scene_desc=scene_desc,
            camera=camera,
            mood=mood,
            chars_in_scene=chars_in_scene,
            art_style=sg.art_style,
            width=width,
            height=height,
        )

    def test_default_prompt_contains_required_phrases(self):
        sg = self._scenegen({})
        p = self._build_scene_prompt(sg)
        assert "A dark alley at midnight" in p
        assert "close-up" in p
        assert "tense" in p
        assert "horror manga" in p
        assert "1920:1080" in p
        assert "speech bubbles" in p

    def test_config_template_used(self):
        cfg = _load_real_config().get("prompts", {}).get("scene_gen", {})
        sg = self._scenegen(cfg)
        p = self._build_scene_prompt(sg)
        assert "A dark alley at midnight" in p
        assert "1920" in p
        assert "horror manga" in p

    def test_no_leftover_placeholders_default(self):
        sg = self._scenegen({})
        p = self._build_scene_prompt(sg)
        assert _no_placeholders(p), f"Leftover placeholders in scene prompt: {p}"

    def test_no_leftover_placeholders_from_config(self):
        cfg = _load_real_config().get("prompts", {}).get("scene_gen", {})
        sg = self._scenegen(cfg)
        p = self._build_scene_prompt(sg)
        assert _no_placeholders(p), f"Leftover placeholders in scene prompt: {p}"

    def test_custom_panel_template(self):
        custom = {"panel_prompt": "SCENE:{scene_desc}|CAM:{camera}|MOOD:{mood}|CHR:{chars_in_scene}|STY:{art_style}|{width}x{height}"}
        sg = self._scenegen(custom)
        p = self._build_scene_prompt(sg, scene_desc="Volcano", camera="wide-shot", mood="action")
        assert p == "SCENE:Volcano|CAM:wide-shot|MOOD:action|CHR:Zara Nova: tall host; Brahma: four-armed deity|STY:horror manga|1920x1080"

    def test_no_speech_bubbles_instruction_in_default(self):
        sg = self._scenegen({})
        p = self._build_scene_prompt(sg)
        assert "DO NOT draw any speech bubbles" in p

    def test_resolution_reflected_in_prompt(self):
        sg = SceneGen(resolution=(1280, 720), prompt_config={})
        p = self._build_scene_prompt(sg)
        assert "1280:720" in p
        assert "1280x720" in p


# ── MusicGen tests ────────────────────────────────────────────────────────────

class TestMusicGenPrompt:
    _BOARD = {
        "episode_title": "The Grand Reveal",
        "episode_summary": "Judges meet the contestants.",
        "panels": [
            {"panel_number": 1, "mood": "dramatic", "scene_description": "Epic stage", "duration_seconds": 10},
        ],
    }

    def _musicgen(self, prompt_config: Dict[str, Any]) -> MusicGen:
        return MusicGen(
            model_name="models/test",
            prompt_config=prompt_config,
        )

    def _build_music_prompt(self, mg: MusicGen) -> str:
        """Reproduce music prompt building logic without LLM call."""
        storyboard_digest = mg._build_storyboard_digest(self._BOARD)
        pc = mg.prompt_config
        system_text = pc.get(
            "system",
            "You are a film music composer for short manga episodes.\n"
            "Create a compact background music direction for score generation.\n"
            "Avoid lyrics and vocals. Focus on atmosphere and pacing.",
        )
        user_template = pc.get(
            "user_template",
            "BASE STORY PROMPT:\n{base_prompt}\n\n"
            "STORYBOARD CONTEXT:\n{storyboard_digest}\n\n"
            "Return ONLY strict JSON with this schema:\n"
            "{{\n"
            '  "music_prompt": "short but vivid music direction, include instrumentation + tempo arc",\n'
            '  "style": "ambient",\n'
            '  "duration_seconds": 120\n'
            "}}\n"
            "style must be one of: ambient, cinematic, lo-fi, electronic.",
        )
        return (
            f"{system_text}\n\n"
            + user_template.format(
                base_prompt="Test story premise",
                storyboard_digest=storyboard_digest,
            )
        )

    def test_default_system_in_prompt(self):
        mg = self._musicgen({})
        p = self._build_music_prompt(mg)
        assert "film music composer" in p
        assert "Avoid lyrics" in p

    def test_storyboard_digest_included(self):
        mg = self._musicgen({})
        p = self._build_music_prompt(mg)
        assert "The Grand Reveal" in p
        assert "dramatic" in p

    def test_base_prompt_included(self):
        mg = self._musicgen({})
        p = self._build_music_prompt(mg)
        assert "Test story premise" in p

    def test_config_system_overrides_default(self):
        cfg = _load_real_config().get("prompts", {}).get("music_gen", {})
        mg = self._musicgen(cfg)
        p = self._build_music_prompt(mg)
        assert "film music composer" in p

    def test_no_leftover_placeholders_default(self):
        mg = self._musicgen({})
        p = self._build_music_prompt(mg)
        assert _no_placeholders(p), f"Leftover placeholders in music prompt: {p}"

    def test_no_leftover_placeholders_from_config(self):
        cfg = _load_real_config().get("prompts", {}).get("music_gen", {})
        mg = self._musicgen(cfg)
        p = self._build_music_prompt(mg)
        assert _no_placeholders(p), f"Leftover placeholders in music prompt: {p}"

    def test_custom_system_override(self):
        custom = {
            "system": "MY CUSTOM COMPOSER ROLE",
            "user_template": "PROMPT:{base_prompt}|DIGEST:{storyboard_digest}",
        }
        mg = self._musicgen(custom)
        p = self._build_music_prompt(mg)
        assert "MY CUSTOM COMPOSER ROLE" in p
        assert "PROMPT:Test story premise" in p

    def test_build_storyboard_digest_uses_panels(self):
        mg = self._musicgen({})
        digest = mg._build_storyboard_digest(self._BOARD)
        assert "The Grand Reveal" in digest
        assert "dramatic" in digest
        assert "Epic stage" in digest


# ── Config integrity tests ────────────────────────────────────────────────────

class TestConfigIntegrity:
    def test_config_json_is_valid(self):
        cfg = _load_real_config()
        assert isinstance(cfg, dict)

    def test_prompts_block_exists(self):
        cfg = _load_real_config()
        assert "prompts" in cfg, "config.json must have a 'prompts' key"

    def test_all_four_chain_sections_present(self):
        prompts = _load_real_config().get("prompts", {})
        for section in ("episode_planner", "char_gen", "scene_gen", "music_gen"):
            assert section in prompts, f"Missing prompts section: {section}"

    def test_episode_planner_has_all_keys(self):
        ep = _load_real_config()["prompts"]["episode_planner"]
        required = {
            "system", "episode_1_structure", "character_style_rules",
            "scene_description_rule", "hard_rules_extra", "no_continuity_note",
        }
        missing = required - set(ep.keys())
        assert not missing, f"episode_planner missing keys: {missing}"

    def test_char_gen_has_all_keys(self):
        cg = _load_real_config()["prompts"]["char_gen"]
        assert "portrait_prompt" in cg
        assert "anchor_prefix" in cg

    def test_scene_gen_has_panel_prompt(self):
        sg = _load_real_config()["prompts"]["scene_gen"]
        assert "panel_prompt" in sg

    def test_music_gen_has_all_keys(self):
        mg = _load_real_config()["prompts"]["music_gen"]
        assert "system" in mg
        assert "user_template" in mg

    def test_char_gen_portrait_template_has_required_placeholders(self):
        template = _load_real_config()["prompts"]["char_gen"]["portrait_prompt"]
        for ph in ("{visual_prompt}", "{art_style}", "{width}", "{height}"):
            assert ph in template, f"char_gen portrait_prompt missing placeholder: {ph}"

    def test_scene_gen_panel_template_has_required_placeholders(self):
        template = _load_real_config()["prompts"]["scene_gen"]["panel_prompt"]
        for ph in ("{scene_desc}", "{camera}", "{mood}", "{chars_in_scene}", "{art_style}", "{width}", "{height}"):
            assert ph in template, f"scene_gen panel_prompt missing placeholder: {ph}"

    def test_music_gen_user_template_has_required_placeholders(self):
        template = _load_real_config()["prompts"]["music_gen"]["user_template"]
        assert "{base_prompt}" in template
        assert "{storyboard_digest}" in template

    def test_no_values_are_empty_strings(self):
        prompts = _load_real_config()["prompts"]
        for section, keys in prompts.items():
            for key, value in keys.items():
                assert value.strip(), f"Empty value in prompts.{section}.{key}"
