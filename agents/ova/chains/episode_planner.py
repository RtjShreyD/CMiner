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
        prompt_config: Dict[str, Any] | None = None,
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
        self.prompt_config = prompt_config or {}

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

        # Load prior episode storyboard for continuity when next_num > 1
        prior_ep_context = ""
        prior_characters = []
        if next_num > 1:
            prior_ep_dir = episodes_dir / f"episode{next_num - 1}"
            for fname in ("storyboard.json", "manga-board.json"):
                prior_path = prior_ep_dir / fname
                if prior_path.exists():
                    try:
                        prior_board = json.loads(prior_path.read_text())
                        prior_title = prior_board.get("episode_title", f"Episode {next_num - 1}")
                        prior_summary = prior_board.get("episode_summary", "")
                        prior_characters = prior_board.get("characters", [])
                        prior_ep_context = (
                            f"\nPRIOR EPISODE ({next_num - 1}): \"{prior_title}\"\n"
                            f"SUMMARY: {prior_summary}\n"
                            "ESTABLISHED CHARACTERS (REUSE THESE EXACTLY — same names, visual_prompts, voice assignments):\n"
                            + json.dumps(prior_characters, indent=2)
                            + "\n"
                        )
                    except Exception:
                        pass
                    break

        pc = self.prompt_config
        system_text = pc.get(
            "system",
            "You are the DIRECTOR for an anime-comic automated animation pipeline.\n"
            "Your output is consumed by downstream generators and MUST be strictly machine-usable.",
        )
        ep1_structure = pc.get(
            "episode_1_structure",
            "Epic stage reveal → host Zara Nova intro → show concept explained → "
            "Brahma entrance → Vishnu entrance → Mahesh/Shiva entrance → "
            "dramatic 'TO BE CONTINUED...' closing frame.",
        )
        char_style_rules = pc.get(
            "character_style_rules",
            "Brahma: serene elder with four-headed motif symbolism, Vedic scholar aura, modern ceremonial tech robe.\n"
            "Vishnu: calm protector presence with shankha/chakra symbolism, royal blue-gold futuristic attire.\n"
            "Mahesh (Shiva): ash-toned ascetic energy, trishul/rudraksha motifs, modern cosmic streetwear armor blend.",
        )
        scene_rule = pc.get(
            "scene_description_rule",
            "In scene_description, generate ONLY expression/reaction clouds (sweat drops, anger marks, sparkles, "
            "thought wisps). DO NOT include any speech bubbles in scene images — speech bubbles will be added "
            "programmatically later.",
        )
        hard_rules_extra = pc.get(
            "hard_rules_extra",
            "Keep characters and objects visually consistent in all frames.\n"
            "Dialogue must be coherent and meaningful in one language (English).\n"
            "assigned_voice must be a valid voice key from VOICE POOL.",
        )
        no_continuity = pc.get(
            "no_continuity_note",
            "NO CONTINUITY MODE: Do not reuse prior episode names, events, or carry-forward context.",
        )

        # Build continuity/intro note based on episode number
        if prior_ep_context:
            continuity_note = (
                "CONTINUATION MODE: This is a SEQUEL episode of an ongoing series.\n"
                + prior_ep_context
                + "RULES for continuation:\n"
                "- REUSE the EXACT same characters (same names, same visual_prompts, same assigned_voice values) as listed above.\n"
                "- DO NOT invent new characters unless the story clearly requires a new guest/contestant.\n"
                "- Develop the story forward — reference the prior episode's events and cliffhanger.\n"
                "- Give the episode a new plot hook: a new inventor arrives to pitch their invention to the Trimurti judges.\n"
            )
        else:
            continuity_note = no_continuity

        prompt = (
            f"{system_text}\n\n"
            f"CORE SYSTEM PREMISE:\n{base_prompt}\n\n"
            f"{theme_text}"
            f"DEFAULT ART STYLE: {self.art_style}\n"
            f"EPISODE NUMBER: {next_num}\n"
            f"{continuity_note}\n"
            "HARD RULES:\n"
            f"- Max characters: {self.max_chars}\n"
            f"- EXACTLY {self.max_panels} panels\n"
            f"- Target total runtime >= {target_seconds} seconds\n"
            f"- Each panel duration_seconds must be >= {min_panel_duration}\n"
            f"- Episode 1 is a SHOW INTRO ONLY — no invention pitch, no contestant. Structure: {ep1_structure}\n"
            f"- {char_style_rules}\n"
            f"- {scene_rule}\n"
            f"- {hard_rules_extra}\n"
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
            "      \"scene_description\": \"detailed composition — expression reaction elements only (sweat drops, sparkles, anger marks), absolutely NO speech bubbles or text\",\n"
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
        # Always enforce the intended episode number (LLMs may override it)
        board["episode_number"] = next_num
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
        out = ep_dir / "storyboard.json"
        out.write_text(json.dumps(board, indent=2))

        print(f"Episode {next_num} planned: {board.get('episode_title', 'Untitled')}")
        print(f"Panels: {len(board.get('panels', []))}")
        print(f"Saved: {out}")
        return board
