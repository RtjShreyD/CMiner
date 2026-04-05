"""
MusicGen – Creates provider-oriented background music plan from storyboard context.

Produces:
- music/music_prompt.txt
- music/music_plan.json
- music/generated_music.mp3 (when provider is available)
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from agents.muicStruddler.music_agent import StrudelMusicAgent, LyriaMusicAgent
from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class MusicGen:
    def __init__(
        self,
        model_name: str = "models/gemini-flash-latest",
        music_provider: str = "lyria",
        lyria_model: str = "lyria-3-clip-preview",
        tracker: Optional[LLMTracker] = None,
    ):
        self.model_name = model_name
        self.music_provider = (music_provider or "strudel").strip().lower()
        self.lyria_model = lyria_model
        self.tracker = tracker

    def _build_storyboard_digest(self, manga_board: Dict[str, Any]) -> str:
        title = manga_board.get("episode_title", "Untitled episode")
        summary = manga_board.get("episode_summary", "")
        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        panel_lines = []
        for panel in panels[:12]:
            pnum = panel.get("panel_number", "?")
            mood = panel.get("mood", "neutral")
            scene = str(panel.get("scene_description", "")).strip()
            scene_short = scene[:220].replace("\n", " ")
            panel_lines.append(f"Panel {pnum} | mood={mood} | scene={scene_short}")
        digest = "\n".join(panel_lines)
        return (
            f"Episode title: {title}\n"
            f"Episode summary: {summary}\n"
            f"Panel digest:\n{digest if digest else 'No panels found.'}"
        )

    def _generate_music_prompt(self, base_prompt: str, manga_board: Dict[str, Any]) -> Dict[str, Any]:
        total_duration = 0
        for panel in manga_board.get("panels", []) or []:
            try:
                total_duration += int(panel.get("duration_seconds", 0) or 0)
            except Exception:
                continue
        if total_duration <= 0:
            total_duration = 60
        total_duration = max(30, min(600, total_duration))

        storyboard_digest = self._build_storyboard_digest(manga_board)

        llm_prompt = (
            "You are a film music composer for short manga episodes.\n"
            "Create a compact background music direction for score generation.\n"
            "Avoid lyrics and vocals. Focus on atmosphere and pacing.\n\n"
            f"BASE STORY PROMPT:\n{base_prompt}\n\n"
            f"STORYBOARD CONTEXT:\n{storyboard_digest}\n\n"
            "Return ONLY strict JSON with this schema:\n"
            "{\n"
            "  \"music_prompt\": \"short but vivid music direction, include instrumentation + tempo arc\",\n"
            "  \"style\": \"ambient\",\n"
            "  \"duration_seconds\": 120\n"
            "}\n"
            "style must be one of: ambient, cinematic, lo-fi, electronic.\n"
        )

        text = ""
        try:
            model = get_model(self.model_name)
            response = tracked_generate(self.tracker, model, llm_prompt, purpose="music_prompt_planner")
            text = (response.text or "").strip()
        except Exception as exc:
            print(f"Music prompt LLM generation unavailable, using fallback plan: {exc}")

        out = {
            "music_prompt": "Cinematic ambient manga background score with gradual tension and release.",
            "style": "ambient",
            "duration_seconds": total_duration,
        }

        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    # Backward compatible with older key from prior prompt format.
                    prompt_value = parsed.get("music_prompt") or parsed.get("strudel_prompt")
                    if isinstance(prompt_value, str) and prompt_value.strip():
                        out["music_prompt"] = prompt_value.strip()
                    if parsed.get("style") in {"ambient", "cinematic", "lo-fi", "electronic"}:
                        out["style"] = parsed["style"]
                    if isinstance(parsed.get("duration_seconds"), int):
                        out["duration_seconds"] = max(30, min(600, parsed["duration_seconds"]))
        except Exception:
            pass

        return out

    def run(self, manga_board: Dict[str, Any], session_dir: Path, base_prompt: str) -> Path | None:
        print("--- Pipeline: Music Generation ---")
        music_dir = session_dir / "music"
        music_dir.mkdir(parents=True, exist_ok=True)

        plan = self._generate_music_prompt(base_prompt=base_prompt, manga_board=manga_board)
        prompt_text = str(plan.get("music_prompt", "")).strip()
        style = str(plan.get("style", "ambient")).strip() or "ambient"
        duration_seconds = int(plan.get("duration_seconds", 60) or 60)
        plan["provider"] = self.music_provider

        (music_dir / "music_prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
        (music_dir / "music_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        # Backward-compatible artifacts for older tooling.
        (music_dir / "strudel_prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
        (music_dir / "strudel_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")

        out_path = music_dir / "generated_music.mp3"
        if self.music_provider == "lyria":
            music_agent = LyriaMusicAgent(model_name=self.lyria_model)
            if not music_agent.enabled:
                print("Lyria is not configured; prompt and plan were saved, but no audio file was generated.")
                return None
            music_agent.generate_music(
                out_path=out_path,
                prompt=prompt_text,
                duration_seconds=duration_seconds,
                model_name=self.lyria_model,
            )
            print(f"Generated music track with Lyria: {out_path}")
            return out_path

        music_agent = StrudelMusicAgent()
        if not music_agent.enabled:
            print("Strudel is not configured; prompt and plan were saved, but no audio file was generated.")
            return None

        music_agent.generate_music(
            out_path=out_path,
            prompt=prompt_text,
            duration_seconds=duration_seconds,
            style=style,
        )
        print(f"Generated music track with Strudel: {out_path}")
        return out_path
