"""OVA Episode Planner – director-first storyboard generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from agents.ova.utils import get_model
from agents.ova.usage_tracker import OVALLMTracker, llm_call


class EpisodePlanner:
    def __init__(
        self,
        model_name: str = "models/gemini-flash-latest",
        tts_voices_pool: Dict[str, list[str]] | None = None,
        max_duration_mins: int = 3,
        max_chars: int = 6,
        max_panels: int = 18,
        art_style: str = "cinematic anime",
        theme: str | None = None,
        episode_mode: bool = True,
        target_episode: int | None = None,
        tracker: Optional[OVALLMTracker] = None,
    ):
        self.model_name = model_name
        self.tts_voices_pool = tts_voices_pool or {}
        self.max_duration_mins = max_duration_mins
        self.max_chars = max_chars
        self.max_panels = max_panels
        self.art_style = art_style
        self.theme = theme
        self.episode_mode = episode_mode
        self.target_episode = target_episode
        self.tracker = tracker

    def run(self, base_prompt: str, session_dir: Path) -> Dict[str, Any]:
        print("--- Pipeline: OVA Director Planner ---")
        episodes_dir = session_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)

        if self.target_episode is not None:
            next_num = max(1, int(self.target_episode))
        else:
            # OVA is intentionally single-episode isolated unless user explicitly targets another number.
            next_num = 1

        theme_text = f"THEME: {self.theme}\n" if self.theme else ""
        target_seconds = max(120, self.max_duration_mins * 60)
        min_panel_duration = max(6, target_seconds // max(1, self.max_panels) - 2)

        prompt = (
            "You are the DIRECTOR for an anime-comic automated animation pipeline.\n"
            "Your output is consumed by downstream generators and MUST be strictly machine-usable.\n\n"
            f"CORE SYSTEM PREMISE:\n{base_prompt}\n\n"
            f"{theme_text}"
            f"DEFAULT ART STYLE: {self.art_style}\n"
            f"EPISODE NUMBER: {next_num}\n"
            "NO CONTINUITY MODE: Do not reuse prior episode names, events, or carry-forward context.\n"
            "HARD RULES:\n"
            f"- Max characters: {self.max_chars}\n"
            f"- EXACTLY {self.max_panels} panels\n"
            f"- Target total runtime >= {target_seconds} seconds\n"
            f"- Each panel duration_seconds must be >= {min_panel_duration}\n"
            "- Episode 1 must include show intro first, then judges introduction (Brahma, Vishnu, Mahadev), then invention pitch\n"
            "- Brahma, Vishnu, Mahesh must be visually recognizable through canonical symbols while styled modern-futuristic:\n"
            "  Brahma: serene elder with four-headed motif symbolism, Vedic scholar aura, modern ceremonial tech robe.\n"
            "  Vishnu: calm protector presence with shankha/chakra symbolism, royal blue-gold futuristic attire.\n"
            "  Mahesh (Shiva): ash-toned ascetic energy, trishul/rudraksha motifs, modern cosmic streetwear armor blend.\n"
            "- In scene_description, ALWAYS include explicit instruction for manga/comic speech and expression clouds to be visible\n"
            "- Keep characters and objects visually consistent in all frames\n"
            "- Dialogue must be coherent and meaningful in one language (English)\n"
            "- assigned_voice must be a valid voice key from VOICE POOL\n\n"
            "Return ONLY strict JSON with this schema:\n"
            "{\n"
            f"  \"episode_number\": {next_num},\n"
            "  \"episode_title\": \"string\",\n"
            "  \"episode_summary\": \"string\",\n"
            "  \"characters\": [\n"
            "    {\n"
            "      \"name\": \"Name\",\n"
            "      \"description\": \"role/personality\",\n"
            f"      \"visual_prompt\": \"highly specific reusable character visual prompt, art style: {self.art_style}. For gods include recognizable canonical traits + modern futuristic styling.\",\n"
            "      \"voice_profile\": \"narrator|hero|villain|support\",\n"
            "      \"assigned_voice\": \"exact voice id from pool\"\n"
            "    }\n"
            "  ],\n"
            "  \"panels\": [\n"
            "    {\n"
            "      \"panel_number\": 1,\n"
            "      \"characters_present\": [\"Name\"],\n"
            "      \"dialogue\": [{\"character\": \"Name\", \"line\": \"line\"}],\n"
            "      \"scene_description\": \"detailed composition + include visible manga speech/expression clouds\",\n"
            "      \"camera_angle\": \"close-up|medium-shot|wide-shot|birds-eye|low-angle\",\n"
            "      \"mood\": \"tense|calm|dramatic|humorous|melancholic|action\",\n"
            f"      \"duration_seconds\": {min_panel_duration}\n"
            "    }\n"
            "  ],\n"
            "  \"render_strategy\": {\n"
            "    \"transition_type\": \"cut|crossfade|fade-to-black\",\n"
            "    \"panel_layout\": \"fullscreen\",\n"
            f"    \"art_style_notes\": \"{self.art_style}\"\n"
            "  }\n"
            "}\n\n"
            f"VOICE POOL: {json.dumps(self.tts_voices_pool)}\n"
            "Return only valid JSON."
        )

        model = get_model(self.model_name)
        response = llm_call(self.tracker, model, prompt, purpose="ova_director_planner")
        text = response.text or ""

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON found in planner response: {text[:200]}")

        board = json.loads(text[start : end + 1])
        chars = board.get("characters", [])
        if len(chars) > self.max_chars:
            board["characters"] = chars[: self.max_chars]

        panel_total = sum(int(p.get("duration_seconds", 0) or 0) for p in board.get("panels", []))
        if panel_total < 120 and board.get("panels"):
            deficit = 120 - panel_total
            extra_per = max(1, deficit // len(board["panels"]))
            for panel in board["panels"]:
                panel["duration_seconds"] = int(panel.get("duration_seconds", 8) or 8) + extra_per

        ep_dir = episodes_dir / f"episode{next_num}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        out = ep_dir / "manga-board.json"
        out.write_text(json.dumps(board, indent=2))

        print(f"Episode {next_num} planned: {board.get('episode_title', 'Untitled')}")
        print(f"Panels: {len(board.get('panels', []))}")
        print(f"Saved: {out}")
        return board
