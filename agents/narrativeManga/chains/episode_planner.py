"""
Episode Planner – Plans sequential manga episodes with continuity.

Produces: episodes/episodeN/manga-board.json
Does NOT generate images. Enforces character limits and art style.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from agents.narrativeManga.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class EpisodePlanner:
    def __init__(
        self,
        model_name: str = "models/gemini-flash-latest",
        tts_voices_pool: Dict[str, str] = None,
        max_duration_mins: int = 5,
        max_chars: int = 5,
        max_panels: int = 15,
        art_style: str = "cinematic anime",
        theme: str = None,
        episode_mode: bool = True,
        tracker: Optional[LLMTracker] = None,
    ):
        self.model_name = model_name
        self.tts_voices_pool = tts_voices_pool or {}
        self.max_duration_mins = max_duration_mins
        self.max_chars = max_chars
        self.max_panels = max_panels
        self.art_style = art_style
        self.theme = theme
        self.episode_mode = episode_mode
        self.tracker = tracker

    def run(self, base_prompt: str, session_dir: Path) -> Dict[str, Any]:
        print("--- Pipeline: Episode Planner ---")
        episodes_dir = session_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)

        # Determine next episode number
        existing = sorted(
            [d for d in episodes_dir.iterdir() if d.is_dir() and d.name.startswith("episode")],
            key=lambda p: p.name,
        )
        next_num = len(existing) + 1 if self.episode_mode else 1
        is_first = next_num == 1

        # Gather prior episode context for continuity
        prior_context = ""
        established_chars = []
        if existing and self.episode_mode:
            last_ep_dir = existing[-1]
            last_board = last_ep_dir / "manga-board.json"
            if last_board.exists():
                with open(last_board, "r") as f:
                    prev = json.load(f)
                established_chars = prev.get("characters", [])
                prior_context = (
                    f"\n\nPREVIOUS EPISODE CONTEXT (Episode {prev.get('episode_number', '?')}: "
                    f"\"{prev.get('episode_title', 'Unknown')}\"):\n"
                    f"Episode summary: {prev.get('episode_summary', 'N/A')}\n"
                    f"Established characters (MUST reuse with IDENTICAL visual_prompt for consistency):\n"
                )
                for c in established_chars:
                    prior_context += (
                        f"  - {c['name']}: {c.get('visual_prompt', c.get('description', ''))}\n"
                        f"    Voice: {c.get('assigned_voice', 'N/A')}\n"
                    )

                panels = prev.get("panels", [])
                prior_context += f"\nThe episode ended with:\n"
                for p in panels[-3:]:
                    prior_context += f"  Panel {p.get('panel_number')}: {p.get('scene_description', '')}\n"
                    for dl in p.get("dialogue", []):
                        prior_context += f"    {dl.get('character', '?')}: \"{dl.get('line', '')}\"\n"
                prior_context += "\nContinue the story DIRECTLY from this point.\n"

        max_words = self.max_duration_mins * 150

        # Episode type instructions
        if is_first:
            episode_type = (
                "This is the PILOT EPISODE (Episode 1). Focus on:\n"
                "- Establishing the world and setting\n"
                "- Introducing the main characters with rich backstory hints\n"
                "- Setting up the central mystery/conflict\n"
                "- Ending with a compelling hook that makes viewers want Episode 2\n"
                "- The tone should draw viewers in slowly, building atmosphere\n"
            )
        else:
            episode_type = (
                f"This is Episode {next_num}. Focus on:\n"
                "- Continuing directly from where the previous episode ended\n"
                "- Deepening character relationships and conflicts\n"
                "- Advancing the central mystery with new revelations\n"
                "- Maintaining tension and pacing\n"
                "- Ending with a cliffhanger or significant story beat\n"
            )

        theme_text = f"THEME: {self.theme}\n" if self.theme else ""

        prompt = (
            f"You are a master manga storyboard artist and narrative designer.\n\n"
            f"BASE STORY PREMISE:\n{base_prompt}\n"
            f"{theme_text}"
            f"DEFAULT ART STYLE: {self.art_style}\n"
            f"{prior_context}\n"
            f"EPISODE TYPE:\n{episode_type}\n"
            f"INSTRUCTIONS:\n"
            f"Create Episode {next_num}. Target ~{self.max_duration_mins} minutes "
            f"of narrated video (~{max_words} words total dialogue).\n\n"
            f"HARD LIMITS:\n"
            f"- Maximum {self.max_chars} characters (reuse established characters when possible)\n"
            f"- Target EXACTLY {self.max_panels} panels for high-quality pacing and dynamic movement\n"
            f"- Each character's visual_prompt MUST be identical across episodes for image generation consistency\n\n"
            f"Return ONLY strict JSON:\n"
            f"{{\n"
            f'  "episode_number": {next_num},\n'
            f'  "episode_title": "string",\n'
            f'  "episode_summary": "2-3 sentence summary of this episode including key events and cliffhanger",\n'
            f'  "characters": [\n'
            f'    {{\n'
            f'      "name": "Name",\n'
            f'      "description": "Role and personality",\n'
            f'      "visual_prompt": "EXACT detailed visual description for consistent image generation across episodes (hair color/style, eye color, outfit details, body type, distinguishing marks). Art style: {self.art_style}.",\n'
            f'      "voice_profile": "Voice tone description",\n'
            f'      "assigned_voice": "EXACT key from voice pool"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "panels": [\n'
            f'    {{\n'
            f'      "panel_number": 1,\n'
            f'      "characters_present": ["Name1"],\n'
            f'      "dialogue": [\n'
            f'        {{"character": "Name1", "line": "Dialogue text"}}\n'
            f'      ],\n'
            f'      "scene_description": "Detailed scene for image generation with art style: {self.art_style}",\n'
            f'      "camera_angle": "close-up | medium-shot | wide-shot | birds-eye | low-angle",\n'
            f'      "mood": "tense | calm | dramatic | humorous | melancholic | action",\n'
            f'      "duration_seconds": 15\n'
            f'    }}\n'
            f'  ],\n'
            f'  "render_strategy": {{\n'
            f'    "transition_type": "cut | crossfade | fade-to-black",\n'
            f'    "panel_layout": "fullscreen",\n'
            f'    "art_style_notes": "{self.art_style}"\n'
            f'  }}\n'
            f"}}\n\n"
            f"VOICE POOL (assign EXACT keys, max {self.max_chars} chars): {json.dumps(self.tts_voices_pool)}\n\n"
            f"Return ONLY valid JSON, no markdown fences.\n"
        )

        model = get_model(self.model_name)
        response = tracked_generate(self.tracker, model, prompt, purpose="episode_planner")

        text = response.text
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON found in planner response: {text[:200]}")

        manga_board = json.loads(text[start : end + 1])

        # Enforce character limit
        chars = manga_board.get("characters", [])
        if len(chars) > self.max_chars:
            print(f"Warning: LLM returned {len(chars)} characters, trimming to {self.max_chars}")
            manga_board["characters"] = chars[:self.max_chars]

        # Save
        ep_dir = episodes_dir / f"episode{next_num}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        board_path = ep_dir / "manga-board.json"
        with open(board_path, "w") as f:
            json.dump(manga_board, f, indent=2)

        print(f"Episode {next_num} planned: \"{manga_board.get('episode_title', 'Untitled')}\"")
        print(f"  Characters: {len(manga_board.get('characters', []))}/{self.max_chars}")
        print(f"  Panels: {len(manga_board.get('panels', []))}")
        print(f"  Saved to: {board_path}")
        return manga_board
