"""
Episode Planner – Plans sequential manga episodes with continuity.

Produces: episodes/episodeN/manga-board.json
Does NOT generate images. Enforces character limits and art style.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class EpisodePlanner:
    def __init__(
        self,
        model_name: str = "models/gemini-flash-latest",
        director_model_name: str = "models/gemini-2.5-flash",
        director_fallback_model_name: str = "models/gemini-2.0-flash-lite",
        project_name: str = "AutoAnimator",
        preset_prompt: str = "",
        niche_name: str | None = None,
        niche_context: str = "",
        start_frame_path: str | None = None,
        end_frame_path: str | None = None,
        tts_voices_pool: Dict[str, str] = None,
        max_duration_mins: int = 1,
        max_chars: int = 3,
        max_panels: int = 50,
        art_style: str = "cinematic anime",
        aesthetic_guidance: str = "",
        theme: str = None,
        model_stack: Optional[Dict[str, str]] = None,
        episode_mode: bool = True,
        target_episode: int | None = None,
        tracker: Optional[LLMTracker] = None,
    ):
        self.model_name = model_name
        self.director_model_name = director_model_name
        self.director_fallback_model_name = director_fallback_model_name
        self.project_name = project_name or "AutoAnimator"
        self.preset_prompt = preset_prompt or ""
        self.niche_name = (niche_name or "").strip() or None
        self.niche_context = niche_context or ""
        self.start_frame_path = (start_frame_path or "").strip() or None
        self.end_frame_path = (end_frame_path or "").strip() or None
        self.tts_voices_pool = tts_voices_pool or {}
        self.max_duration_mins = max_duration_mins
        self.max_chars = max_chars
        self.max_panels = max_panels
        self.art_style = art_style
        self.aesthetic_guidance = aesthetic_guidance or ""
        self.theme = theme
        self.model_stack = model_stack or {}
        self.episode_mode = episode_mode
        self.target_episode = target_episode
        self.tracker = tracker

    @staticmethod
    def _word_count(text: str) -> int:
        return len((text or "").split())

    def _script_profile(self, base_prompt: str) -> str:
        wc = self._word_count(base_prompt)
        if wc <= 90:
            return "baseline_theme"
        if wc <= 320:
            return "short_script"
        return "full_script"

    @staticmethod
    def _sanitize_panel(panel: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(panel) if isinstance(panel, dict) else {}
        if not isinstance(out.get("dialogue", []), list):
            out["dialogue"] = []
        if not isinstance(out.get("characters_present", []), list):
            out["characters_present"] = []
        return out

    def _expand_panels_to_target(self, manga_board: Dict[str, Any], target_count: int) -> None:
        panels = manga_board.get("panels", [])
        if not isinstance(panels, list) or not panels:
            return
        target = max(1, int(target_count))
        if len(panels) >= target:
            return

        seed_panels = [self._sanitize_panel(p) for p in panels]
        expanded = list(seed_panels)
        idx = 0
        while len(expanded) < target and seed_panels:
            src = seed_panels[idx % len(seed_panels)]
            clone = dict(src)
            clone["camera_angle"] = clone.get("camera_angle") or "close-up"
            clone["mood"] = clone.get("mood") or "dramatic"
            base_scene = str(clone.get("scene_description", "")).strip()
            beat_num = len(expanded) + 1
            if base_scene:
                clone["scene_description"] = f"{base_scene} | cinematic beat {beat_num}: micro-shift in expression/composition"
            else:
                clone["scene_description"] = f"Cinematic beat {beat_num} with clear composition and continuity."

            dialogue = clone.get("dialogue", []) if isinstance(clone.get("dialogue", []), list) else []
            if dialogue:
                # Preserve all dialogue lines verbatim during expansion; never truncate spoken content.
                clone["dialogue"] = [dict(dl) for dl in dialogue if isinstance(dl, dict)]

            clone["duration_seconds"] = max(1, int(clone.get("duration_seconds", 1) or 1))
            expanded.append(clone)
            idx += 1

        for i, p in enumerate(expanded, start=1):
            p["panel_number"] = i
        manga_board["panels"] = expanded[:target]

    @staticmethod
    def _detect_language_hint(text: str) -> str:
        """Return a coarse language hint for planning prompts."""
        if not text:
            return "english"
        # Detect Devanagari script for Hindi prompts.
        for ch in text:
            if "\u0900" <= ch <= "\u097f":
                return "hindi"
        return "english"

    @staticmethod
    def _extract_json_object(raw: str) -> Dict[str, Any]:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _build_model_capability_notes(self) -> str:
        stack = {
            "director_text_model": self.director_model_name,
            "director_fallback_model": self.director_fallback_model_name,
            "planner_text_model": self.model_name,
            **self.model_stack,
        }
        capabilities = {
            "director_text_model": "High-quality narrative orchestration and critical rewrite pass.",
            "director_fallback_model": "Fast/efficient fallback for director reasoning and JSON recovery passes.",
            "planner_text_model": "Fast first-draft structure generation.",
            "character_image_model": "Low/medium-fidelity image generation; prompts must be explicit, visually concrete, and stable.",
            "scene_image_model": "Panel scene generation with anchor-image guidance; needs precise composition/camera/mood text.",
            "tts_engine": "Character dialogue audio; voice keys must be deterministic.",
            "music_provider": "Background score generation with constrained control.",
            "lyria_model": "Optional high-quality music clip generation when enabled.",
        }
        lines = []
        for key, model in stack.items():
            lines.append(f"- {key}: {model} | capability: {capabilities.get(key, 'Specialized generation component.')}")
        lines.append("- Resource reality: image generators are budget/quality constrained; prompts must compensate with explicit visual specificity.")
        return "\n".join(lines)

    def _director_models(self) -> list[str]:
        models: list[str] = []
        for name in [self.director_model_name, self.director_fallback_model_name]:
            if name and name not in models:
                models.append(name)
        return models

    def _director_generate_json(self, prompt: str, purpose: str) -> Dict[str, Any]:
        for model_name in self._director_models():
            try:
                model = get_model(model_name)
                response = tracked_generate(self.tracker, model, prompt, purpose=purpose)
                obj = self._extract_json_object(getattr(response, "text", "") or "")
                if obj:
                    return obj
            except Exception as e:
                print(f"Warning: Director call failed on {model_name} ({purpose}): {e}")
                continue
        return {}

    def _normalize_timeline(self, manga_board: Dict[str, Any]) -> None:
        panels = manga_board.get("panels", [])
        if not isinstance(panels, list) or not panels:
            return

        max_total = max(15, int(self.max_duration_mins * 60))
        min_panel_sec = 1
        if len(panels) > max_total:
            # Hard feasibility cap for strict duration (at least 1s per panel).
            panels = panels[:max_total]
            manga_board["panels"] = panels
        durations = []
        for p in panels:
            try:
                durations.append(max(min_panel_sec, int(p.get("duration_seconds", 6) or 6)))
            except Exception:
                durations.append(6)

        total = sum(durations)
        if total <= 0:
            total = len(panels) * 6

        if total > max_total:
            scale = max_total / float(total)
            scaled = [max(min_panel_sec, int(round(d * scale))) for d in durations]
            diff = max_total - sum(scaled)
            idx = 0
            while diff != 0 and scaled:
                step = 1 if diff > 0 else -1
                if not (step < 0 and scaled[idx] <= min_panel_sec):
                    scaled[idx] += step
                    diff -= step
                idx = (idx + 1) % len(scaled)
            durations = scaled

        for i, p in enumerate(panels):
            p["duration_seconds"] = int(durations[i])
            if not p.get("panel_number"):
                p["panel_number"] = i + 1

    def _enforce_character_consistency(
        self,
        manga_board: Dict[str, Any],
        established_chars: list[Dict[str, Any]],
    ) -> None:
        if not isinstance(manga_board, dict):
            return

        chars = manga_board.get("characters", []) if isinstance(manga_board.get("characters", []), list) else []
        if not chars:
            return

        established_by_name = {
            str(c.get("name", "")).strip().lower(): c
            for c in (established_chars or [])
            if isinstance(c, dict) and str(c.get("name", "")).strip()
        }

        known_name_by_lower: Dict[str, str] = {}
        reused_count = 0
        for c in chars:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", "")).strip()
            if not name:
                continue
            lower_name = name.lower()
            known_name_by_lower[lower_name] = name
            established = established_by_name.get(lower_name)
            if not established:
                continue

            prior_visual = str(established.get("visual_prompt", "") or "").strip()
            prior_voice = str(established.get("assigned_voice", "") or "").strip()
            if prior_visual:
                c["visual_prompt"] = prior_visual
            if prior_voice:
                c["assigned_voice"] = prior_voice
            # Prefer deterministic portrait reuse for established cast.
            c["reuse_character_from"] = name
            reused_count += 1

        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        for p in panels:
            if not isinstance(p, dict):
                continue

            present = p.get("characters_present", []) if isinstance(p.get("characters_present", []), list) else []
            normalized_present = []
            for raw_name in present:
                key = str(raw_name or "").strip().lower()
                normalized_present.append(known_name_by_lower.get(key, str(raw_name)))
            if normalized_present:
                p["characters_present"] = normalized_present

            dialogue = p.get("dialogue", []) if isinstance(p.get("dialogue", []), list) else []
            for dl in dialogue:
                if not isinstance(dl, dict):
                    continue
                dname = str(dl.get("character", "") or "").strip().lower()
                if dname in known_name_by_lower:
                    dl["character"] = known_name_by_lower[dname]

        rs = manga_board.setdefault("render_strategy", {})
        rs["consistency_audit"] = {
            "established_characters": len(established_by_name),
            "characters_reused": reused_count,
            "name_normalization_applied": True,
        }

    def _enforce_stage_show_continuity(self, manga_board: Dict[str, Any]) -> None:
        if (self.niche_name or "") != "stage_show":
            return

        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        if not panels:
            return

        rs = manga_board.setdefault("render_strategy", {})
        stage_anchor = rs.get("stage_anchor")
        episode_num = max(1, int(manga_board.get("episode_number", 1) or 1))
        show_banner_title = str(rs.get("show_banner_title", "") or "").strip() or f"{self.project_name} LIVE"
        rs["show_banner_title"] = show_banner_title
        rs["show_banner_panel"] = 1
        rs["show_banner_continuity"] = "episode1_generated_reused_after"
        if not isinstance(stage_anchor, str) or not stage_anchor.strip():
            stage_anchor = (
                "Persistent futuristic stage set: central demo platform, judges desk for core cast, "
                "audience silhouettes, consistent LED backdrop, and controlled spotlight rig."
            )
        rs["stage_anchor"] = stage_anchor
        rs["continuity_mode"] = "strict_stage_show"

        shot_cycle = [
            ("wide-shot", "establishing"),
            ("medium-shot", "presenter-demo"),
            ("close-up", "judge-reaction"),
            ("low-angle", "device-hero-shot"),
            ("wide-shot", "audience-energy"),
        ]

        for i, panel in enumerate(panels):
            if not isinstance(panel, dict):
                continue
            panel["panel_number"] = i + 1
            panel.setdefault("continuity_from_panel", i if i > 0 else None)
            if not str(panel.get("camera_angle", "")).strip():
                panel["camera_angle"] = shot_cycle[i % len(shot_cycle)][0]
            panel.setdefault("shot_intent", shot_cycle[i % len(shot_cycle)][1])
            panel.setdefault("pose_direction", "micro-shift from previous panel with same character identity")

            scene_desc = str(panel.get("scene_description", "") or "").strip()
            continuity_tag = f"Stage continuity: {stage_anchor}"
            if continuity_tag not in scene_desc:
                scene_desc = f"{scene_desc} | {continuity_tag}" if scene_desc else continuity_tag

            dialogue = panel.get("dialogue", []) if isinstance(panel.get("dialogue", []), list) else []
            spoken = []
            for dl in dialogue[:3]:
                if isinstance(dl, dict):
                    cname = str(dl.get("character", "") or "").strip()
                    line = str(dl.get("line", "") or "").strip()
                    if line:
                        spoken.append(f"{cname}: {line}" if cname else line)
            if spoken:
                scene_desc = f"{scene_desc} | Dialogue beat: {' || '.join(spoken)}"

            panel["scene_description"] = scene_desc

        # Stage-show hard rule:
        # Episode 1 must generate a canonical banner frame; later episodes must reuse that frame as panel 1.
        first_panel = panels[0] if panels and isinstance(panels[0], dict) else None
        if first_panel:
            if episode_num == 1:
                first_panel["render_method"] = "static_frame"
                first_panel["reuse_from_previous_episode_panel"] = None
                first_panel.setdefault("camera_angle", "wide-shot")
                first_panel.setdefault("mood", "dramatic")
                first_panel["scene_description"] = (
                    f"Canonical stage-show banner reveal with persistent brand identity: {show_banner_title}. "
                    f"{stage_anchor}"
                )
                first_panel["static_frame_spec"] = {
                    "renderer": "title_card",
                    "bg_color": "#0D1021",
                    "gradient": ["#0D1021", "#202A52"],
                    "show_text": True,
                    "title_text": show_banner_title,
                }
            else:
                first_panel["reuse_from_previous_episode_panel"] = 1
                first_panel["render_method"] = "llm_image"
                first_panel["scene_description"] = (
                    f"Reuse canonical stage-show banner frame from previous episode panel 1. "
                    f"{stage_anchor}"
                )
                # Reused image should remain visually identical; spoken beats start from panel 2 onward.
                first_panel["dialogue"] = []
                first_panel.pop("static_frame_spec", None)

    def _run_director_pass(
        self,
        draft_board: Dict[str, Any],
        *,
        base_prompt: str,
        prior_context: str,
        next_num: int,
        is_first: bool,
    ) -> Dict[str, Any]:
        capability_notes = self._build_model_capability_notes()
        episode_shape_hint = "pilot episode" if is_first else f"continuation episode {next_num}"
        language_hint = self._detect_language_hint(base_prompt)
        script_profile = self._script_profile(base_prompt)
        frame_refs = []
        if self.start_frame_path:
            frame_refs.append(f"START_FRAME_REFERENCE: {self.start_frame_path}")
        if self.end_frame_path:
            frame_refs.append(f"END_FRAME_REFERENCE: {self.end_frame_path}")
        frame_ref_text = "\n".join(frame_refs) if frame_refs else "none"
        preset_text = self.preset_prompt.strip() or "none"
        niche_label = self.niche_name or "auto"
        niche_context_text = self.niche_context.strip() or "none"
        niche_intro_outro_rule = ""
        if niche_label in {"1v1_battle", "stage_show"}:
            niche_intro_outro_rule = (
                "- Must include a clear intro/setup beat in early panels and a conclusive outro/payoff beat in final panels.\n"
            )
        stage_show_rule = ""
        if niche_label == "stage_show":
            stage_show_rule = (
                "- Enforce a persistent stage geography across panels (judges desk, demo zone, audience axis).\\n"
                "- Keep the recurring cast visual identity and blocking consistent; update only pose/expression/camera dynamics.\\n"
                "- Add per-panel continuity metadata: continuity_from_panel, shot_intent, pose_direction.\\n"
                "- Use lively anime camera progression (wide -> medium -> close reaction -> device hero -> crowd beat) without location drift.\\n"
                "- Keep scene_description tightly synchronized with actual dialogue beat in that panel.\\n"
                "- Character names are immutable across the episode/series: preserve exact spelling from established cast and prior context.\\n"
                "- Dialogue quality rule: avoid one-word spoken lines except intentional reaction beats (e.g., Wow!, Huh?); most lines should be full natural phrases.\\n"
            )

        strategy_prompt = (
            "You are the Director orchestrator. Build a concise production strategy as strict JSON.\n"
            "Personality in strategy text: sharp, cinematic, occasionally witty, scientifically grounded.\n"
            "Output JSON only: {\"story_arc\":\"...\",\"timeline_strategy\":\"...\",\"resource_strategy\":\"...\",\"visual_prompt_strategy\":\"...\"}\n\n"
            f"BASELINE USER STORY:\n{base_prompt}\n\n"
            f"EPISODE TYPE: {episode_shape_hint}\n"
            f"EPISODE NUMBER TARGET: {next_num}\n"
            f"THEME: {self.theme or 'none'}\n"
            f"SERIES PRESET PROMPT:\n{preset_text}\n"
            f"NICHE: {niche_label}\n"
            f"NICHE DIRECTOR CONTEXT: {niche_context_text}\n"
            f"STAGE SHOW SPECIAL RULES:\n{stage_show_rule or 'none'}\n"
                        f"PRIMARY LANGUAGE HINT: {language_hint}\n"
            f"ART STYLE: {self.art_style}\n"
            f"AESTHETIC GUIDANCE: {self.aesthetic_guidance or 'none'}\n"
            f"MAX CHARACTERS: {self.max_chars}\n"
            f"TARGET PANELS: {self.max_panels}\n"
            f"MAX EPISODE DURATION (minutes): {self.max_duration_mins}\n\n"
            f"INPUT PROFILE: {script_profile}\n\n"
            f"FRAME REFERENCES:\n{frame_ref_text}\n\n"
            f"PRIOR CONTEXT:\n{prior_context or 'none'}\n\n"
            "NARRATIVE ADHERENCE: preserve the core entities, conflict, and intent from BASELINE USER STORY as non-negotiable source-of-truth.\n\n"
            f"MODEL STACK + CAPABILITIES:\n{capability_notes}\n"
        )
        strategy = self._director_generate_json(strategy_prompt, purpose="episode_director_strategy")

        director_prompt = (
            "You are THE DIRECTOR for this episodic anime pipeline. You are the final orchestrator for story quality, "
            "resource realism, pacing, and generation-readiness.\n"
            "Creative personality: razor-sharp cinematic taste (Nolan-grade structure), occasional dry sarcasm, intelligent comic relief, "
            "scientific reasoning, and strict resource management discipline.\n"
            "Never break JSON format.\n\n"
            f"BASELINE USER STORY:\n{base_prompt}\n\n"
            f"EPISODE CONTEXT TYPE: {episode_shape_hint}\n"
            f"EPISODE NUMBER TARGET: {next_num}\n"
            f"PROJECT NAME: {self.project_name}\n"
            f"THEME: {self.theme or 'none'}\n"
            f"SERIES PRESET PROMPT:\n{preset_text}\n"
            f"NICHE: {niche_label}\n"
            f"NICHE DIRECTOR CONTEXT: {niche_context_text}\n"
            f"STAGE SHOW SPECIAL RULES:\n{stage_show_rule or 'none'}\n"
            f"ART STYLE: {self.art_style}\n"
            f"AESTHETIC GUIDANCE: {self.aesthetic_guidance or 'none'}\n"
            f"MAX CHARACTERS: {self.max_chars}\n"
            f"TARGET PANELS: {self.max_panels}\n"
            f"MAX EPISODE DURATION (minutes): {self.max_duration_mins}\n\n"
            f"INPUT PROFILE: {script_profile}\n\n"
            f"FRAME REFERENCES:\n{frame_ref_text}\n\n"
            f"PRIOR CONTEXT:\n{prior_context or 'none'}\n\n"
            f"MODEL STACK + CAPABILITIES:\n{capability_notes}\n\n"
            f"DIRECTOR STRATEGY JSON:\n{json.dumps(strategy, ensure_ascii=True)}\n\n"
            "DRAFT PLAN TO REVIEW AND REDIRECT:\n"
            f"{json.dumps(draft_board, ensure_ascii=True)}\n\n"
            "DIRECTOR OBJECTIVES:\n"
            "0) Treat SERIES PRESET PROMPT as immutable continuity source-of-truth unless user add-on explicitly changes it.\n"
            "1) Maintain strict adherence to BASELINE USER STORY intent while adapting it cinematically.\n"
            "2) Rewrite and improve the draft into a final production-ready board.\n"
            "1a) Never copy the baseline script verbatim. Adapt it into cinematic visual beats and spoken lines suitable for animation.\n"
            "2) Ensure visual prompts are explicit enough for lower-end image models.\n"
            "3) Optimize timeline pacing and panel durations to fit duration bounds.\n"
            "4) Ensure dialogue and scene progression feel cinematic and coherent from minimal baseline prompts.\n"
            "4a) For baseline_theme prompts (2-5 lines), synthesize a complete story arc with setup, escalation, payoff.\n"
            "4b) For short_script/full_script prompts, transform script prose into visual staging, narration lines, and character dialogue.\n"
            "4c) Respect NICHE DIRECTOR CONTEXT as a hard quality/style steering signal when present.\n"
            "4d) Dialogue completeness rule: keep full scene-wise spoken lines; never truncate or abbreviate dialogue text for brevity.\n"
            "5) Keep voice assignments deterministic and valid for TTS.\n"
            "6) Enforce practical render strategy for the available model stack.\n\n"
            "6a) For intense action/image-sequence moments, increase FPS hints within budget-conscious limits.\n"
            "6b) If START_FRAME_REFERENCE is provided, align opening composition to it as the first visual anchor.\n"
            "6c) If END_FRAME_REFERENCE is provided, align final payoff composition to it as the closing visual anchor.\n"
            "7) Decide panel-wise render method: either 'llm_image' or 'static_frame'. Use static_frame for simple visuals (void, black, white, solid color, title card, intertitle, simple gradient).\n"
            "8) For static_frame panels, include static_frame_spec with local-render details (renderer, bg_color or gradient, optional title_text).\n\n"
            "10) If PRIMARY LANGUAGE HINT is hindi, produce natural Hindi dialogue (Devanagari) by default; use Hinglish only when it improves clarity for modern tone.\n\n"
            "11) Decide delivery mode per spoken line: narration vs character dialogue; use neutral voiceover lines only where scene exposition is needed.\n"
            "12) Add emotional intent tags per line where useful: sarcastic, happy, overwhelmed, curious, sad, angry, tense, neutral.\n\n"
            "12b) If a spoken line is long, split it into additional lines/panels instead of cutting words from the original intent.\n"
            "12a) Spoken line quality: avoid one-word lines unless it is an intentional reaction beat; keep most spoken lines as natural full phrases (typically 6-18 words).\n"
            f"13) Niche structural rules:\n{niche_intro_outro_rule or '- Follow the niche rhythm naturally without forcing extra beats.\n'}\n"
            f"13a) Stage-show continuity rules:\n{stage_show_rule or '- Not a stage-show episode.\n'}\n"
            "14) If a panel can intentionally re-use an already generated previous-episode scene (flashback, callback, recap, same location framing), set reuse_from_previous_episode_panel to that prior panel number.\n\n"
            "9) Treat static_frame as a tool-call style decision: prefer local generation (HTML/CSS/canvas-style primitives) whenever it is cheaper and visually sufficient than calling image LLMs.\n\n"
            "RETURN RULES:\n"
            "- Return ONLY strict JSON object.\n"
            "- Keep schema compatible with downstream pipeline:\n"
            "  episode_number, episode_title, episode_summary, characters[], panels[], render_strategy{}.\n"
            "- Each panel may include optional fields:\n"
            "  render_method: 'llm_image' | 'static_frame'\n"
            "  fps: integer panel-level FPS hint (higher for intense action, lower for calm beats)\n"
            "  reuse_from_previous_episode_panel: integer panel number from previous episode to reuse scene image when appropriate\n"
            "  continuity_from_panel: integer previous panel_number for visual carry-over\n"
            "  shot_intent: short label for shot purpose\n"
            "  pose_direction: short note describing pose progression from previous panel\n"
            "  static_frame_spec: { renderer: 'solid'|'gradient'|'title_card'|'html_canvas', bg_color?: '#RRGGBB', gradient?: ['#111111','#222222'], title_text?: '...' }\n"
            "- dialogue items should prefer shape: {character, line, emotion?, delivery_mode?}.\n"
            "- render_strategy may include additional director fields (e.g., timeline_strategy, generation_notes, fps_policy:{base_fps,min_fps,max_fps}).\n"
            "- Do not include markdown fences or commentary outside JSON.\n"
        )

        directed = self._director_generate_json(director_prompt, purpose="episode_director_rewrite")
        if not directed:
            print("Warning: Director returned invalid JSON; falling back to planner draft.")
            return draft_board

        qa_prompt = (
            "You are the Director QA pass. Validate and repair this board for strict schema + resource limits.\n"
            "Return ONLY strict JSON with the SAME schema as input board.\n"
            f"LIMITS: max_chars={self.max_chars}, target_panels={self.max_panels}, max_duration_mins={self.max_duration_mins}\n"
            "Use available budget efficiently: if under target_panels, densify beats while keeping coherence and quality.\n"
            "If valid, return the board unchanged except minor cleanup.\n\n"
            f"BOARD:\n{json.dumps(directed, ensure_ascii=True)}\n"
        )
        qa_board = self._director_generate_json(qa_prompt, purpose="episode_director_qa")
        if qa_board:
            directed = qa_board

        return directed

    def run(self, base_prompt: str, session_dir: Path) -> Dict[str, Any]:
        print("--- Pipeline: Episode Planner ---")
        episodes_dir = session_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)

        # Determine next episode number
        existing = sorted(
            [d for d in episodes_dir.iterdir() if d.is_dir() and d.name.startswith("episode")],
            key=lambda p: int(p.name.replace("episode", "") or 0),
        )
        if self.target_episode is not None:
            next_num = max(1, int(self.target_episode))
        else:
            next_num = len(existing) + 1 if self.episode_mode else 1
        is_first = next_num == 1

        # Gather prior episode context for continuity
        prior_context = ""
        established_chars = []
        if self.episode_mode:
            prior_ep_dir = None
            if next_num > 1:
                explicit_prior = episodes_dir / f"episode{next_num - 1}"
                if explicit_prior.exists():
                    prior_ep_dir = explicit_prior
            elif existing:
                prior_ep_dir = existing[-1]

            last_board = (prior_ep_dir / "manga-board.json") if prior_ep_dir else None
            if last_board and last_board.exists():
                with open(last_board, "r") as f:
                    prev = json.load(f)
                established_chars = prev.get("characters", [])
                prev_episode_num = int(prev.get("episode_number", max(1, next_num - 1)) or max(1, next_num - 1))
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

                prev_scenes_dir = (prior_ep_dir / "scenes") if prior_ep_dir else None
                if prev_scenes_dir and prev_scenes_dir.exists():
                    prior_context += "\nReusable previous-episode scene assets (panel -> file):\n"
                    for p in sorted(prev_scenes_dir.glob("panel_*.png")):
                        try:
                            pn = int(p.stem.split("_")[1]) + 1
                        except Exception:
                            pn = None
                        if pn is not None:
                            prior_context += f"  - Panel {pn}: episodes/episode{prev_episode_num}/scenes/{p.name}\n"

                chars_manifest_path = session_dir / "chars" / "chars_manifest.json"
                if chars_manifest_path.exists():
                    try:
                        chars_manifest = json.loads(chars_manifest_path.read_text(encoding="utf-8"))
                    except Exception:
                        chars_manifest = {}
                    if isinstance(chars_manifest, dict) and chars_manifest:
                        prior_context += "\nReusable character image assets:\n"
                        for cname, cpath in chars_manifest.items():
                            prior_context += f"  - {cname}: {cpath}\n"

                panels = prev.get("panels", [])
                prior_context += f"\nThe episode ended with:\n"
                for p in panels[-3:]:
                    prior_context += f"  Panel {p.get('panel_number')}: {p.get('scene_description', '')}\n"
                    for dl in p.get("dialogue", []):
                        prior_context += f"    {dl.get('character', '?')}: \"{dl.get('line', '')}\"\n"
                prior_context += "\nContinue the story DIRECTLY from this point.\n"

        language_hint = self._detect_language_hint(base_prompt)
        script_profile = self._script_profile(base_prompt)

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
        frame_refs = []
        if self.start_frame_path:
            frame_refs.append(f"START_FRAME_REFERENCE: {self.start_frame_path}")
        if self.end_frame_path:
            frame_refs.append(f"END_FRAME_REFERENCE: {self.end_frame_path}")
        frame_ref_text = ("\n".join(frame_refs) + "\n") if frame_refs else ""
        preset_text = self.preset_prompt.strip()
        niche_label = self.niche_name or "auto"
        niche_context_text = self.niche_context.strip() or "none"
        niche_rules_text = ""
        if niche_label in {"1v1_battle", "stage_show"}:
            niche_rules_text = (
                "- REQUIRED: include a crisp intro/setup in opening panels and a conclusive ending beat in final panels.\n"
            )
        stage_show_planner_rules = ""
        if niche_label == "stage_show":
            stage_show_planner_rules = (
                "- Keep a persistent stage map across all panels; do not jump to unrelated locations.\n"
                "- Core recurring cast must retain consistent appearance and desk/stage position continuity.\n"
                "- Make presentation lively via camera and pose evolution, not random scene resets.\n"
                "- Each panel's scene_description must match its dialogue beat and intended action.\n"
                "- Preserve exact character names from established cast/prior context; do not rename characters.\n"
            )

        aesthetic_text = f"AESTHETIC DIRECTION: {self.aesthetic_guidance}\n" if self.aesthetic_guidance else ""

        planner_prompt = (
            f"You are a master manga storyboard artist and narrative designer.\n\n"
            f"BASE STORY PREMISE:\n{base_prompt}\n"
            f"PROJECT NAME: {self.project_name}\n"
            f"SERIES PRESET PROMPT:\n{preset_text or 'none'}\n"
            f"{frame_ref_text}"
            f"{theme_text}"
            f"NICHE: {niche_label}\n"
            f"NICHE DIRECTOR CONTEXT: {niche_context_text}\n"
            f"DEFAULT ART STYLE: {self.art_style}\n"
                        f"PRIMARY LANGUAGE HINT: {language_hint}\n"
            f"{aesthetic_text}"
            f"{prior_context}\n"
            f"EPISODE TYPE:\n{episode_type}\n"
            f"INSTRUCTIONS:\n"
            f"Create Episode {next_num}. Target ~{self.max_duration_mins} minutes "
            f"of narrated video with full scene-wise dialogue coverage.\n\n"
            f"NARRATIVE ADHERENCE RULES:\n"
            f"- SERIES PRESET PROMPT is persistent source-of-truth for this series baseline.\n"
            f"- BASE STORY PREMISE is the source-of-truth for this run; preserve its core entities, intent, and conflict.\n"
            f"- You may adapt for cinematic pacing, but do not drift away from prompt meaning.\n\n"
            f"INPUT PROFILE: {script_profile}\n"
            f"- If baseline_theme: expand into a complete arc (setup -> escalation -> payoff).\n"
            f"- If short_script/full_script: ADAPT and REWRITE into cinematic beats; do not copy script verbatim.\n"
            f"- Use panel budget efficiently for quality pacing and visual rhythm.\n\n"
            f"NICHE RULES:\n"
            f"{niche_rules_text or '- Follow niche context naturally while keeping coherent story flow.\n'}\n"
            f"STAGE SHOW PLANNING RULES:\n"
            f"{stage_show_planner_rules or '- Not a stage-show episode.\n'}\n"
            f"HARD LIMITS:\n"
            f"- Maximum {self.max_chars} characters (reuse established characters when possible)\n"
            f"- Target EXACTLY {self.max_panels} panels for high-quality pacing and dynamic movement\n"
            f"- Each character's visual_prompt MUST be identical across episodes for image generation consistency\n\n"
            f"LANGUAGE RULES:\n"
            f"- If PRIMARY LANGUAGE HINT is hindi, make dialogue naturally Hindi (Devanagari) unless scene context demands bilingual style.\n"
            f"- Keep character and panel structure compatible with downstream TTS and subtitles.\n\n"
            f"DIALOGUE QUALITY RULES:\n"
            f"- Keep full dialogue lines for each scene beat; never truncate or abbreviate line text for brevity.\n"
            f"- Avoid one-word lines except intentional reaction beats.\n"
            f"- Most spoken lines should be complete natural phrases (typically 6-18 words).\n\n"
            f"Return ONLY strict JSON:\n"
            f"{{\n"
            f'  "episode_number": {next_num},\n'
            f'  "episode_title": "string",\n'
            f'  "episode_summary": "2-3 sentence summary of this episode including key events and cliffhanger",\n'
            f'  "characters": [\n'
            f'    {{\n'
            f'      "name": "CharacterName",\n'
            f'      "description": "Role and personality",\n'
            f'      "visual_prompt": "EXACT detailed visual description for consistent image generation across episodes (hair color/style, eye color, outfit details, body type, distinguishing marks). Art style: {self.art_style}.",\n'
            f'      "voice_profile": "Voice tone description",\n'
            f'      "assigned_voice": "EXACT key from voice pool"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "panels": [\n'
            f'    {{\n'
            f'      "panel_number": 1,\n'
            f'      "characters_present": ["CharacterName"],\n'
            f'      "dialogue": [\n'
            f'        {{"character": "CharacterName", "line": "Dialogue text", "emotion": "neutral|sarcastic|happy|overwhelmed|curious|sad|angry|tense", "delivery_mode": "dialogue|narration|voiceover|silent"}}\n'
            f'      ],\n'
            f'      "scene_description": "Detailed scene for image generation with art style: {self.art_style}",\n'
            f'      "camera_angle": "close-up | medium-shot | wide-shot | birds-eye | low-angle",\n'
            f'      "mood": "tense | calm | dramatic | humorous | melancholic | action",\n'
            f'      "reuse_from_previous_episode_panel": null,\n'
            f'      "continuity_from_panel": null,\n'
            f'      "shot_intent": "establishing | presenter-demo | judge-reaction | device-hero-shot | audience-energy",\n'
            f'      "pose_direction": "micro shift from previous panel",\n'
            f'      "duration_seconds": 15\n'
            f'    }}\n'
            f'  ],\n'
            f'  "render_strategy": {{\n'
            f'    "transition_type": "cut | crossfade | fade-to-black",\n'
            f'    "panel_layout": "fullscreen",\n'
            f'    "art_style_notes": "{self.art_style}",\n'
            f'    "fps_policy": {{"base_fps": 16, "min_fps": 12, "max_fps": 24}}\n'
            f'  }}\n'
            f"}}\n\n"
            f"VOICE POOL (assign EXACT keys, max {self.max_chars} chars): {json.dumps(self.tts_voices_pool)}\n\n"
            f"Return ONLY valid JSON, no markdown fences.\n"
        )

        planner_model = get_model(self.model_name)
        planner_response = tracked_generate(self.tracker, planner_model, planner_prompt, purpose="episode_planner")
        planner_text = getattr(planner_response, "text", "") or ""
        draft_board = self._extract_json_object(planner_text)
        if not draft_board:
            raise ValueError(f"No JSON found in planner response: {planner_text[:200]}")

        draft_board["episode_number"] = next_num
        directed_board = self._run_director_pass(
            draft_board,
            base_prompt=base_prompt,
            prior_context=prior_context,
            next_num=next_num,
            is_first=is_first,
        )

        manga_board = directed_board if isinstance(directed_board, dict) else draft_board
        manga_board["episode_number"] = next_num
        manga_board.setdefault("render_strategy", {})
        manga_board["render_strategy"].setdefault("art_style_notes", self.art_style)
        manga_board["render_strategy"]["project_name"] = self.project_name
        if self.preset_prompt:
            manga_board["render_strategy"]["preset_prompt"] = self.preset_prompt
        manga_board["render_strategy"]["niche"] = self.niche_name or "auto"
        if self.niche_context:
            manga_board["render_strategy"]["niche_context"] = self.niche_context
        if (self.niche_name or "") == "stage_show":
            manga_board["render_strategy"]["first_frame_title"] = f"{self.project_name} LIVE"
            manga_board["render_strategy"]["show_banner_title"] = f"{self.project_name} LIVE"
        else:
            manga_board["render_strategy"]["first_frame_title"] = f"{self.project_name} - Episode {next_num}"
        manga_board["render_strategy"]["director_model"] = self.director_model_name
        manga_board["render_strategy"]["planner_model"] = self.model_name
        if self.start_frame_path:
            manga_board["render_strategy"]["start_frame_path"] = self.start_frame_path
        if self.end_frame_path:
            manga_board["render_strategy"]["end_frame_path"] = self.end_frame_path

        # Enforce character limit
        chars = manga_board.get("characters", [])
        if len(chars) > self.max_chars:
            print(f"Warning: LLM returned {len(chars)} characters, trimming to {self.max_chars}")
            manga_board["characters"] = chars[:self.max_chars]

        # Hard continuity guard: preserve visual identity + voice for established cast.
        self._enforce_character_consistency(manga_board, established_chars)

        # Enforce panel budget and normalize timeline for duration bounds.
        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        max_total_feasible = max(1, int(self.max_duration_mins * 60))
        target_panels = min(self.max_panels, max_total_feasible)
        if len(panels) < target_panels:
            self._expand_panels_to_target(manga_board, target_panels)
            panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        if len(panels) > self.max_panels:
            print(f"Warning: LLM returned {len(panels)} panels, trimming to {self.max_panels}")
            manga_board["panels"] = panels[:self.max_panels]
        self._normalize_timeline(manga_board)
        self._enforce_stage_show_continuity(manga_board)

        # Save
        ep_dir = episodes_dir / f"episode{next_num}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        draft_path = ep_dir / "manga-board-draft.json"
        with open(draft_path, "w") as f:
            json.dump(draft_board, f, indent=2)
        board_path = ep_dir / "manga-board.json"
        with open(board_path, "w") as f:
            json.dump(manga_board, f, indent=2)

        print(f"Episode {next_num} planned: \"{manga_board.get('episode_title', 'Untitled')}\"")
        print(f"  Characters: {len(manga_board.get('characters', []))}/{self.max_chars}")
        print(f"  Panels: {len(manga_board.get('panels', []))}")
        print(f"  Saved to: {board_path}")
        return manga_board
