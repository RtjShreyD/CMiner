"""
Episode Planner – Plans sequential manga episodes with continuity.

Produces: episodes/episodeN/storyboard.json
Does NOT generate images. Enforces character limits and art style.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

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
        intro_only: bool = False,
        target_episode: int | None = None,
        tracker: Optional[LLMTracker] = None,
        planner_skill_ids: Optional[list[str]] = None,
        planner_skill_prompt: str = "",
        planner_skills_catalog: Optional[Dict[str, Any]] = None,
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
        self.intro_only = bool(intro_only)
        self.target_episode = target_episode
        self.tracker = tracker
        self.planner_skill_ids = [str(s).strip() for s in (planner_skill_ids or []) if str(s).strip()]
        self.planner_skill_prompt = str(planner_skill_prompt or "").strip()
        self.planner_skills_catalog = planner_skills_catalog or {}

    def _active_planner_skill_directives(self) -> str:
        parts: list[str] = []
        for sid in self.planner_skill_ids:
            cfg = self.planner_skills_catalog.get(sid, {}) if isinstance(self.planner_skills_catalog, dict) else {}
            if not isinstance(cfg, dict):
                continue
            label = str(cfg.get("label", sid) or sid)
            description = str(cfg.get("description", "") or "").strip()
            prompt = str(cfg.get("prompt", "") or "").strip()
            block = f"- SKILL[{sid}] {label}"
            if description:
                block += f": {description}"
            if prompt:
                block += f"\n  Directive: {prompt}"
            parts.append(block)
        if self.planner_skill_prompt:
            parts.append(f"- USER_DEFINED_SKILL_DIRECTIVE: {self.planner_skill_prompt}")
        return "\n".join(parts)

    @staticmethod
    def _word_count(text: str) -> int:
        return len((text or "").split())

    @classmethod
    def parse_base_prompt(
        cls,
        raw_prompt: str,
        model_name: str = "models/gemini-flash-latest",
        art_style: str = "cinematic manga",
        tracker: Optional[LLMTracker] = None,
    ) -> Dict[str, Any]:
        """
        Parse a large raw user prompt (show bible, story premise, char descriptions, etc.)
        and extract structured production data:
          - project_name, premise, preset_prompt
          - characters[] with visual_prompt, bubble_style
          - objects[] with visual_prompt, object_type
          - storyboard_outline[] (basic panel beat descriptions)
          - recommended_niche, art_style_suggestion

        Returns a dict ready to populate UI fields.
        """
        if not raw_prompt.strip():
            return {}
        try:
            model = get_model(model_name)
            prompt = (
                "You are a production assistant for an animated manga series pipeline.\n"
                "A user has provided a large source document (show bible, story premise, character descriptions, world-building notes, etc.).\n"
                "Extract all production-relevant data and return ONLY strict JSON.\n\n"
                "EXTRACTION RULES:\n"
                "1. project_name: short memorable title for this series/show.\n"
                "2. premise: 3-5 sentence distilled story premise (world, protagonist, central conflict, stakes).\n"
                "3. preset_prompt: 120-220 word persistent series source-of-truth covering: world, recurring cast intent, tone, stakes, series continuity rules. Do NOT copy verbatim.\n"
                "4. characters[]: for every named character found, create an entry with:\n"
                "   - name: exact as mentioned\n"
                "   - description: role and personality (2-3 sentences)\n"
                "   - visual_prompt: MANGA CHARACTER REFERENCE enumerating: (1) hair color/length/style; (2) eye color/shape; (3) skin tone; (4) face shape/marks; (5) outfit items/colors; (6) body build; (7) props always carried. Art style: " + art_style + ".\n"
                "   - bubble_style: inferred from personality (rounded/sharp-edged/thought-bubble/jagged/electric/cloudy/whisper)\n"
                "   - voice_profile: voice tone and manner description\n"
                "5. objects[]: for every significant device, invention, prop, vehicle, or landmark, create an entry with:\n"
                "   - name: object name\n"
                "   - description: what it is and its role\n"
                "   - object_type: device|prop|infographic|invention|vehicle|location\n"
                "   - visual_prompt: MANGA OBJECT REFERENCE enumerating: shape/dimensions, materials/textures, color scheme, labels/markings, distinctive features. Art style: " + art_style + ".\n"
                "   - role_in_story: when and how it appears\n"
                "6. storyboard_outline[]: extract or infer 5-10 key beat descriptions as short strings (each 1 sentence describing a key visual/story moment).\n"
                "7. recommended_niche: one of: stage_show|1v1_battle|educational|drama|comedy|action|thriller|auto — choose the best fit based on tone/format.\n"
                "8. art_style_suggestion: suggest one of: cinematic manga|shonen manga|shojo manga|seinen manga|noir manga|comedic manga|sci-fi manga — based on tone.\n\n"
                "SOURCE DOCUMENT:\n"
                f"{raw_prompt}\n\n"
                "Return ONLY valid JSON matching this schema (no markdown fences):\n"
                "{\n"
                '  "project_name": "...",\n'
                '  "premise": "...",\n'
                '  "preset_prompt": "...",\n'
                '  "characters": [{"name":"...","description":"...","visual_prompt":"...","bubble_style":"...","voice_profile":"..."}],\n'
                '  "objects": [{"name":"...","description":"...","object_type":"...","visual_prompt":"...","role_in_story":"..."}],\n'
                '  "storyboard_outline": ["beat 1...", "beat 2..."],\n'
                '  "recommended_niche": "...",\n'
                '  "art_style_suggestion": "..."\n'
                "}"
            )
            response = tracked_generate(tracker, model, prompt, purpose="parse_base_prompt")
            raw_text = getattr(response, "text", "") or ""
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return {}
            parsed = json.loads(raw_text[start:end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception as e:
            print(f"Warning: parse_base_prompt failed: {e}")
            return {}

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
        elif total < max_total:
            diff = max_total - total
            idx = 0
            while diff > 0 and durations:
                durations[idx] += 1
                diff -= 1
                idx = (idx + 1) % len(durations)

        for i, p in enumerate(panels):
            p["duration_seconds"] = int(durations[i])
            if not p.get("panel_number"):
                p["panel_number"] = i + 1

    @staticmethod
    def _timeline_total_seconds(manga_board: Dict[str, Any]) -> int:
        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        total = 0
        for p in panels:
            try:
                total += max(1, int((p or {}).get("duration_seconds", 0) or 0))
            except Exception:
                total += 1
        return int(total)

    def _enforce_intro_structure(self, manga_board: Dict[str, Any], *, is_first: bool) -> None:
        """Guarantee strong intro sequencing in both intro-only and generic episodes."""
        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        if not panels:
            return

        intro_ratio = 1.0 if self.intro_only else (0.35 if is_first else 0.22)
        intro_count = max(3, min(len(panels), int(round(len(panels) * intro_ratio))))
        beat_tags = [
            "intro_hook",
            "premise_grounding",
            "world_context",
            "character_reveal",
            "stakes_setup",
            "transition_to_conflict",
        ]

        for i in range(min(intro_count, len(panels))):
            panel = panels[i] if isinstance(panels[i], dict) else {}
            if not isinstance(panel, dict):
                continue
            tag = beat_tags[min(i, len(beat_tags) - 1)]
            panel["shot_intent"] = f"{tag}:{panel.get('shot_intent', 'intro_progression')}"
            scene = str(panel.get("scene_description", "") or "").strip()
            if "INTRO_BEAT" not in scene:
                panel["scene_description"] = f"INTRO_BEAT[{i+1}/{intro_count}|{tag}] {scene}".strip()
            panel["duration_seconds"] = max(2, int(panel.get("duration_seconds", 3) or 3))

    def _enforce_intro_only_policy(self, manga_board: Dict[str, Any]) -> None:
        """Force intro-only episodes to remain setup-focused and non-object-driven."""
        if not self.intro_only or not isinstance(manga_board, dict):
            return

        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        if not panels:
            return

        object_names = [
            str(o.get("name", "")).strip()
            for o in (manga_board.get("objects", []) if isinstance(manga_board.get("objects", []), list) else [])
            if isinstance(o, dict) and str(o.get("name", "")).strip()
        ]
        manga_board["objects"] = []

        cast_names = [
            str(c.get("name", "")).strip()
            for c in (manga_board.get("characters", []) if isinstance(manga_board.get("characters", []), list) else [])
            if isinstance(c, dict) and str(c.get("name", "")).strip()
        ]

        total = len(panels)
        for i, panel in enumerate(panels):
            if not isinstance(panel, dict):
                continue

            panel["objects_present"] = []
            scene = str(panel.get("scene_description", "") or "").strip()
            for obj_name in object_names:
                scene = scene.replace(obj_name, "show-world detail")

            if i == 0:
                panel["shot_intent"] = "intro_hook"
                panel["scene_description"] = (
                    f"INTRO_BEAT[{i+1}/{total}|intro_hook] Opening premise hook that introduces the core show concept and tone."
                )
            elif i == 1:
                panel["shot_intent"] = "world_context"
                panel["scene_description"] = (
                    f"INTRO_BEAT[{i+1}/{total}|world_context] Establish the primary location/world, atmosphere, and stakes."
                )
            elif i == 2:
                panel["shot_intent"] = "character_reveal"
                panel["scene_description"] = (
                    f"INTRO_BEAT[{i+1}/{total}|character_reveal] Character introduction beat with personality-defining moment."
                )
            elif i == total - 1:
                panel["shot_intent"] = "teaser_outro"
                panel["scene_description"] = (
                    f"INTRO_BEAT[{i+1}/{total}|teaser_outro] Final teaser card/scene signaling the next episode continuation."
                )
                panel["dialogue"] = [
                    {
                        "character": "Narrator",
                        "line": "Next episode coming soon.",
                        "emotion": "neutral",
                        "delivery_mode": "narration",
                    }
                ]
                panel["speech_bubbles"] = [
                    {
                        "character": "Narrator",
                        "text": "Next episode coming soon.",
                        "style": "whisper",
                        "position": "center-bottom",
                    }
                ]
            else:
                if "INTRO_BEAT" in scene:
                    panel["scene_description"] = scene
                else:
                    panel["scene_description"] = f"INTRO_BEAT[{i+1}/{total}|setup_progression] {scene}".strip()

            existing_present = panel.get("characters_present", []) if isinstance(panel.get("characters_present", []), list) else []
            if cast_names and not existing_present:
                panel["characters_present"] = [cast_names[min(i, len(cast_names) - 1)]]

        summary = str(manga_board.get("episode_summary", "") or "").strip()
        if "next episode coming soon" not in summary.lower():
            manga_board["episode_summary"] = (summary + " Next episode coming soon.").strip()

    def _timeline_patch_review_loop(
        self,
        manga_board: Dict[str, Any],
        *,
        base_prompt: str,
        target_seconds: int,
        is_first: bool,
    ) -> tuple[Dict[str, Any], int]:
        """Iteratively patch storyboard through director prompt review for strict timeline fit."""
        board = manga_board
        applied = 0
        max_passes = 2
        for i in range(max_passes):
            current_total = self._timeline_total_seconds(board)
            if current_total == target_seconds and i > 0:
                break

            patch_prompt = (
                "You are the Timeline Compliance Director. Patch the storyboard to meet strict runtime and intro-depth constraints.\n"
                "Return ONLY strict JSON in the same storyboard schema.\n"
                f"TARGET TOTAL DURATION (exact): {target_seconds} seconds.\n"
                f"CURRENT TOTAL DURATION: {current_total} seconds.\n"
                f"MODE: {'intro_only' if self.intro_only else 'generic_episode'}.\n"
                f"FIRST_EPISODE: {'yes' if is_first else 'no'}.\n"
                "Hard patch rules:\n"
                "- Keep narrative coherence and panel continuity.\n"
                "- Keep or improve dialogue clarity; do not truncate meaning.\n"
                "- Add detailed intro progression in opening panels: hook -> premise -> world/context -> stakes.\n"
                "- Ensure panel duration_seconds are realistic integers and sum to target exactly.\n"
                "- Adjust panel durations first; if needed, split/merge beats by editing panels while preserving story logic.\n"
                "- Preserve character/object consistency and names.\n"
                f"BASE STORY SOURCE:\n{base_prompt}\n\n"
                f"BOARD TO PATCH:\n{json.dumps(board, ensure_ascii=True)}\n"
            )
            patched = self._director_generate_json(patch_prompt, purpose=f"episode_timeline_patch_pass_{i+1}")
            if patched and isinstance(patched, dict) and isinstance(patched.get("panels", []), list) and patched.get("panels"):
                board = patched
                applied += 1
        return board, applied

    def _expand_panels_with_director_loop(
        self,
        storyboard: Dict[str, Any],
        *,
        base_prompt: str,
        target_count: int,
        is_first: bool,
    ) -> tuple[Dict[str, Any], int, list[Dict[str, Any]]]:
        """Ask the director to add new unique panels instead of locally cloning repeated beats."""
        board = storyboard
        applied = 0
        max_passes = 3
        target = max(1, int(target_count or 1))
        trace: list[Dict[str, Any]] = []

        for i in range(max_passes):
            panels = board.get("panels", []) if isinstance(board.get("panels", []), list) else []
            current_count = len(panels)
            if current_count >= target:
                break

            missing = target - current_count
            expand_prompt = (
                "You are the Story Expansion Director. Expand this storyboard by adding NEW, non-repetitive panels.\n"
                "Return ONLY strict JSON in the exact storyboard schema.\n"
                f"MODE: {'intro_only' if self.intro_only else 'generic_episode'}\n"
                f"FIRST_EPISODE: {'yes' if is_first else 'no'}\n"
                f"CURRENT_PANEL_COUNT: {current_count}\n"
                f"TARGET_PANEL_COUNT: {target}\n"
                f"PANELS_TO_ADD_MINIMUM: {missing}\n"
                "Hard expansion rules:\n"
                "- Add new story beats; do NOT duplicate existing dialogue or scene_description blocks.\n"
                "- Preserve continuity, character identities, and world state.\n"
                "- Keep panel numbering sequential and valid.\n"
                "- Preserve existing panels while extending with meaningful progression.\n"
                "- Keep dialogue natural and non-redundant.\n"
                f"BASE STORY SOURCE:\n{base_prompt}\n\n"
                f"BOARD TO EXPAND:\n{json.dumps(board, ensure_ascii=True)}\n"
            )
            patched = self._director_generate_json(expand_prompt, purpose=f"episode_panel_expand_pass_{i+1}")
            if not patched or not isinstance(patched, dict):
                trace.append(
                    {
                        "pass": i + 1,
                        "before": current_count,
                        "target": target,
                        "after": current_count,
                        "status": "no_json",
                    }
                )
                break

            new_panels = patched.get("panels", []) if isinstance(patched.get("panels", []), list) else []
            if len(new_panels) <= current_count:
                trace.append(
                    {
                        "pass": i + 1,
                        "before": current_count,
                        "target": target,
                        "after": len(new_panels),
                        "status": "no_growth",
                    }
                )
                break

            board = patched
            applied += 1
            trace.append(
                {
                    "pass": i + 1,
                    "before": current_count,
                    "target": target,
                    "after": len(new_panels),
                    "status": "expanded",
                }
            )

        return board, applied, trace

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

    def _enforce_object_consistency(
        self,
        manga_board: Dict[str, Any],
        established_objects: list[Dict[str, Any]],
    ) -> None:
        """Preserve object visual_prompts from prior episodes across continuations."""
        if not isinstance(manga_board, dict) or not established_objects:
            return

        objects = manga_board.get("objects", []) if isinstance(manga_board.get("objects", []), list) else []
        if not objects:
            return

        established_by_name = {
            str(o.get("name", "")).strip().lower(): o
            for o in established_objects
            if isinstance(o, dict) and str(o.get("name", "")).strip()
        }

        for obj in objects:
            if not isinstance(obj, dict):
                continue
            name = str(obj.get("name", "")).strip()
            if not name:
                continue
            established = established_by_name.get(name.lower())
            if not established:
                continue
            prior_visual = str(established.get("visual_prompt", "") or "").strip()
            if prior_visual:
                obj["visual_prompt"] = prior_visual

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
        episode_shape_hint = "intro-only pilot" if self.intro_only else ("pilot episode" if is_first else f"continuation episode {next_num}")
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
        planner_skill_directives = self._active_planner_skill_directives()
        planner_skill_text = planner_skill_directives if planner_skill_directives else "none"
        if niche_label in {"1v1_battle", "stage_show"}:
            niche_intro_outro_rule = (
                "- Must include a clear intro/setup beat in early panels and a conclusive outro/payoff beat in final panels.\n"
            )
        niche_structure_block = niche_intro_outro_rule or "- Follow the niche rhythm naturally without forcing extra beats.\n"
        stage_show_rule = ""
        first_episode_rule = ""
        if is_first:
            first_episode_rule = (
                "- First episode must open with a clear introduction/setup sequence establishing core premise, key characters, and stakes. "
                "Do not start in the middle of the story; earn the first act with an intro scene or title card.\\n"
            )
        if niche_label == "stage_show":
            stage_show_rule = (
                "- Enforce a persistent stage geography across panels (judges desk, demo zone, audience axis).\\n"
                "- Keep the recurring cast visual identity and blocking consistent; update only pose/expression/camera dynamics.\\n"
                "- Add per-panel continuity metadata: continuity_from_panel, shot_intent, pose_direction.\\n"
                "- Use lively anime camera progression (wide -> medium -> close reaction -> device hero -> crowd beat) without location drift.\\n"
                "- Preserve the current location state, lighting, set geography, and scene dynamics described in the prompt or show bible.\\n"
                "- Do not reset or change location state unless the story explicitly calls for a new setting.\\n"
                "- Keep scene_description tightly synchronized with actual dialogue beat in that panel.\\n"
                "- Character names are immutable across the episode/series: preserve exact spelling from established cast and prior context.\\n"
                "- Dialogue quality rule: avoid one-word spoken lines except intentional reaction beats (e.g., Wow!, Huh?); most lines should be full natural phrases.\\n"
            )
            stage_show_continuity_block = stage_show_rule or "- Not a stage-show episode.\n"

        strategy_prompt = (
            "You are the Director orchestrator. Build a production strategy as strict JSON.\n"
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
            f"FIRST EPISODE INTRO RULE:\n{first_episode_rule if is_first else '- Not the first episode; continue the established narrative.'}\n"
                        f"PRIMARY LANGUAGE HINT: {language_hint}\n"
            f"ART STYLE: {self.art_style}\n"
            f"AESTHETIC GUIDANCE: {self.aesthetic_guidance or 'none'}\n"
            f"MAX CHARACTERS: {self.max_chars}\n"
            f"PANEL BUDGET (UP TO): {self.max_panels}\n"
            f"MAX EPISODE DURATION (minutes): {self.max_duration_mins}\n\n"
            f"INPUT PROFILE: {script_profile}\n\n"
            f"FRAME REFERENCES:\n{frame_ref_text}\n\n"
            f"PRIOR CONTEXT:\n{prior_context or 'none'}\n\n"
            "NARRATIVE ADHERENCE: preserve the core entities, conflict, and intent from BASELINE USER STORY as non-negotiable source-of-truth.\n\n"
            f"MODEL STACK + CAPABILITIES:\n{capability_notes}\n"
            f"OPTIONAL PLANNER SKILL DIRECTIVES:\n{planner_skill_text}\n"
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
            f"FIRST EPISODE INTRO RULE:\n{first_episode_rule if is_first else '- Not the first episode; continue the established narrative.'}\n"
            f"ART STYLE: {self.art_style}\n"
            f"AESTHETIC GUIDANCE: {self.aesthetic_guidance or 'none'}\n"
            f"MAX CHARACTERS: {self.max_chars}\n"
            f"PANEL BUDGET (UP TO): {self.max_panels}\n"
            f"MAX EPISODE DURATION (minutes): {self.max_duration_mins}\n\n"
            f"INPUT PROFILE: {script_profile}\n\n"
            f"FRAME REFERENCES:\n{frame_ref_text}\n\n"
            f"PRIOR CONTEXT:\n{prior_context or 'none'}\n\n"
            f"MODEL STACK + CAPABILITIES:\n{capability_notes}\n\n"
            f"OPTIONAL PLANNER SKILL DIRECTIVES:\n{planner_skill_text}\n\n"
            f"DIRECTOR STRATEGY JSON:\n{json.dumps(strategy, ensure_ascii=True)}\n\n"
            "DRAFT PLAN TO REVIEW AND REDIRECT:\n"
            f"{json.dumps(draft_board, ensure_ascii=True)}\n\n"
            "DIRECTOR OBJECTIVES:\n"
            "0) Treat SERIES PRESET PROMPT as immutable continuity source-of-truth unless user add-on explicitly changes it.\n"
            "1) Maintain strict adherence to BASELINE USER STORY intent while adapting it cinematically.\n"
            "2) Rewrite and improve the draft into a final production-ready board.\n"
            "1a) Never copy the baseline script verbatim. Adapt it into cinematic visual beats and spoken lines suitable for animation.\n"
            "2) Ensure visual prompts are explicit enough for lower-end image models.\n"
            "2a) ART STYLE MANDATE: every scene_description must be written as a MANGA/COMIC PANEL description — bold ink outline environment, named characters in specific poses, flat-color toned background. NEVER write scene_descriptions as if they are photographs or painted illustrations.\n"
            "2b) Character visual_prompt IMMUTABILITY: each character's visual_prompt must be a precise, reproducible manga-trait list (specific hair color name, eye color, outfit item names and hex/named colors, accessories). Word-for-word identical across all panels and episodes. Vague terms like 'normal clothing' or 'looks menacing' are forbidden.\n"
            "3) Optimize timeline pacing and panel durations to fit duration bounds.\n"
            "4) Ensure dialogue and scene progression feel cinematic and coherent from minimal baseline prompts.\n"
            "4a) For baseline_theme prompts (2-5 lines), synthesize a complete story arc with setup, escalation, payoff.\n"
            "4b) For short_script/full_script prompts, transform script prose into visual staging, narration lines, and character dialogue.\n"
            "4c) Respect NICHE DIRECTOR CONTEXT as a hard quality/style steering signal when present.\n"
            "4d) Dialogue completeness rule: keep full scene-wise spoken lines; never truncate or abbreviate dialogue text for brevity.\n"
            "4e) Character naming integrity rule: preserve complete character names from draft/prior context; do not shorten or abbreviate names.\n"
            "4f) Creative anti-repetition rule: do not repeat near-identical scene_description/dialogue blocks across panels; each panel must advance story state.\n"
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
            "12c) Spoken clarity rule: each non-reaction spoken line should be grammatically clear, precise, and context-complete (not acronym-only or token-only lines).\n"
            f"13) Niche structural rules:\n{niche_structure_block}\n"
            f"13a) Stage-show continuity rules:\n{stage_show_continuity_block}\n"
            "14) If a panel can intentionally re-use an already generated previous-episode scene (flashback, callback, recap, same location framing), set reuse_from_previous_episode_panel to that prior panel number.\n\n"
            "15) Speech bubble enforcement: every panel with non-empty dialogue must have a speech_bubbles array. "
            "Each entry's 'text' field must be a character-for-character verbatim copy of the corresponding dialogue 'line' — do NOT reword, shorten, or paraphrase it. "
            "Each entry's 'character' field must exactly match the dialogue 'character' name. "
            "Assign bubble_style from the character roster (infer if absent: rounded for hosts/protagonists, sharp-edged for authority/antagonist figures, thought-bubble for internal monologue, whisper/caption for narration). "
            "The image generation model reads speech_bubbles[].text directly and renders it inside the bubble — incorrect text will be visible in the final frame.\n\n"
            "16) Show bible compliance: if SERIES PRESET PROMPT is a full show format document, extract and ENFORCE these as hard constraints: (a) every listed character's visual identity and bubble_style, (b) the defined stage layout/blocking in scene_descriptions, (c) the specified comedic/dramatic rhythm structure (e.g. mandatory beat sequence), (d) the episode anatomy format. These override any default assumptions.\n\n"
            "17) If FIRST EPISODE INTRO RULE is present, enforce an explicit intro setup arc before escalation: opening hook -> premise grounding -> cast/context reveal -> escalation trigger.\n\n"
            "18) Visual pedagogy enhancement: when the story calls for explanation/demo content, include designed infographic-like panels (diagrams, labels, process arrows, split-slide layouts) using static_frame or scene composition directives, while preserving manga style.\n\n"
            "9) Treat static_frame as a tool-call style decision: prefer local generation (HTML/CSS/canvas-style primitives) whenever it is cheaper and visually sufficient than calling image LLMs.\n\n"
            "RETURN RULES:\n"
            "- Return ONLY strict JSON object.\n"
            "- Keep schema compatible with downstream pipeline:\n"
            "  episode_number, episode_title, episode_summary, characters[], objects[], panels[], render_strategy{}.\n"
            "- Each panel may include optional fields:\n"
            "  render_method: 'llm_image' | 'static_frame'\n"
            "  fps: integer panel-level FPS hint (higher for intense action, lower for calm beats)\n"
            "  reuse_from_previous_episode_panel: integer panel number from previous episode to reuse scene image when appropriate\n"
            "  continuity_from_panel: integer previous panel_number for visual carry-over\n"
            "  shot_intent: short label for shot purpose\n"
            "  pose_direction: short note describing pose progression from previous panel\n"
            "  speech_bubbles: array of {character, text, style, position} — REQUIRED for every panel with dialogue\n"
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
            f"LIMITS: max_chars={self.max_chars}, max_panels={self.max_panels}, max_duration_mins={self.max_duration_mins}\n"
            f"OPTIONAL PLANNER SKILL DIRECTIVES:\n{planner_skill_text}\n"
            "Do NOT compress names or dialogue for brevity. Keep full character names and clear complete spoken lines.\n"
            "Panel count can be below max_panels when needed for dialogue clarity and coherent pacing.\n"
            "Speech bubble validation: for every panel that has non-empty dialogue entries, verify speech_bubbles is present and populated. "
            "For each dialogue entry, confirm a matching speech_bubble exists with (a) 'text' as a verbatim character-for-character copy of the dialogue 'line', and (b) 'character' matching the dialogue 'character' name exactly. "
            "If speech_bubbles is missing or any text field is a paraphrase/truncation of the dialogue line, repair it by copying the dialogue line verbatim into speech_bubbles[].text.\n"
            "If valid, return the board unchanged except minor cleanup.\n\n"
            f"BOARD:\n{json.dumps(directed, ensure_ascii=True)}\n"
        )
        qa_board = self._director_generate_json(qa_prompt, purpose="episode_director_qa")
        if qa_board:
            directed = qa_board

        review_prompt = (
            "You are the final Director reviewer. Improve this board with one last iterative pass for quality, creativity, pacing, and non-repetition.\n"
            "Return ONLY strict JSON in the same schema.\n"
            f"HARD LIMITS: max_chars={self.max_chars}, max_panels={self.max_panels}, max_duration_mins={self.max_duration_mins}.\n"
            f"OPTIONAL PLANNER SKILL DIRECTIVES:\n{planner_skill_text}\n"
            "Checklist:\n"
            "- Timeline coverage should closely use the target duration budget without abrupt under-fill.\n"
            "- Ensure no duplicated panel beats or repeated dialogue blocks unless explicitly intentional.\n"
            "- Ensure continuity of character visuals, names, and location state dynamics.\n"
            "- Ensure first episode has clear intro structure when applicable.\n"
            "- Keep it cinematic and inventive, not generic.\n\n"
            f"BOARD:\n{json.dumps(directed, ensure_ascii=True)}\n"
        )
        reviewed = self._director_generate_json(review_prompt, purpose="episode_director_final_review")
        if reviewed:
            directed = reviewed

        return directed

    @staticmethod
    def _sync_panel_speech_bubbles(panel: Dict[str, Any]) -> None:
        if not isinstance(panel, dict):
            return
        dialogue = panel.get("dialogue", []) if isinstance(panel.get("dialogue", []), list) else []
        if not dialogue:
            panel["speech_bubbles"] = []
            return

        existing = panel.get("speech_bubbles", []) if isinstance(panel.get("speech_bubbles", []), list) else []
        existing_map: Dict[tuple[str, str], Dict[str, Any]] = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("character", "") or "").strip(), str(item.get("text", "") or "").strip())
            if key[0] and key[1]:
                existing_map[key] = item

        fixed: list[Dict[str, Any]] = []
        for dl in dialogue:
            if not isinstance(dl, dict):
                continue
            char_name = str(dl.get("character", "Narrator") or "Narrator").strip() or "Narrator"
            line = str(dl.get("line", "") or "").strip()
            if not line:
                continue
            preserved = existing_map.get((char_name, line), {})
            fixed.append(
                {
                    "character": char_name,
                    "text": line,
                    "style": str(preserved.get("style", "rounded") or "rounded"),
                    "position": str(preserved.get("position", "top-right") or "top-right"),
                }
            )
        panel["speech_bubbles"] = fixed

    def prepare_for_scene_generation(self, manga_board: Dict[str, Any], session_dir: Path) -> Dict[str, Any]:
        """Planner-owned preflight pass before scene generation.

        Verifies storyboard readiness, repairs common schema/continuity issues,
        and persists a planner-approved board for SceneGen consumption.
        """
        print("--- Planner Preflight: Scene Generation Readiness ---")
        if not isinstance(manga_board, dict):
            raise ValueError("Storyboard must be a JSON object before scene generation.")

        episode_number = max(1, int(manga_board.get("episode_number", 1) or 1))
        episodes_dir = session_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)

        board = dict(manga_board)
        board.setdefault("characters", [])
        board.setdefault("objects", [])
        board.setdefault("panels", [])
        board.setdefault("render_strategy", {})
        skill_directives = self._active_planner_skill_directives()
        board["render_strategy"]["planner_skill_ids"] = list(self.planner_skill_ids)
        if self.planner_skill_prompt:
            board["render_strategy"]["planner_skill_prompt"] = self.planner_skill_prompt
        if skill_directives:
            board["render_strategy"]["planner_skill_directives"] = skill_directives

        known_chars: Dict[str, str] = {}
        for c in board.get("characters", []):
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", "") or "").strip()
            if not name:
                continue
            known_chars[name.lower()] = name
            c.setdefault("description", "")
            c.setdefault("visual_prompt", c.get("description", ""))
            c.setdefault("bubble_style", "rounded")

        panels = board.get("panels", []) if isinstance(board.get("panels", []), list) else []
        repaired_panels: list[Dict[str, Any]] = []
        edits_count = 0

        for idx, raw_panel in enumerate(panels):
            if not isinstance(raw_panel, dict):
                edits_count += 1
                continue

            panel = dict(raw_panel)
            panel["panel_number"] = idx + 1
            panel.setdefault("camera_angle", "medium-shot")
            panel.setdefault("mood", "dramatic")
            panel["duration_seconds"] = max(1, int(panel.get("duration_seconds", 4) or 4))

            chars_present = panel.get("characters_present", []) if isinstance(panel.get("characters_present", []), list) else []
            normalized_present = []
            for cp in chars_present:
                key = str(cp or "").strip().lower()
                if not key:
                    continue
                normalized_present.append(known_chars.get(key, str(cp).strip()))
            if chars_present != normalized_present:
                edits_count += 1
            panel["characters_present"] = normalized_present

            dialogue = panel.get("dialogue", []) if isinstance(panel.get("dialogue", []), list) else []
            normalized_dialogue = []
            for dl in dialogue:
                if not isinstance(dl, dict):
                    edits_count += 1
                    continue
                char_name = str(dl.get("character", "Narrator") or "Narrator").strip() or "Narrator"
                line = str(dl.get("line", "") or "").strip()
                if not line:
                    continue
                canonical = known_chars.get(char_name.lower(), char_name)
                if canonical != char_name:
                    edits_count += 1
                normalized_dialogue.append(
                    {
                        "character": canonical,
                        "line": line,
                        "emotion": str(dl.get("emotion", "neutral") or "neutral"),
                        "delivery_mode": str(dl.get("delivery_mode", "dialogue") or "dialogue"),
                    }
                )
            panel["dialogue"] = normalized_dialogue

            scene_description = str(panel.get("scene_description", "") or "").strip()
            if not scene_description:
                if normalized_dialogue:
                    spoken = " | ".join(
                        f"{d.get('character', 'Narrator')}: {d.get('line', '')}" for d in normalized_dialogue[:3]
                    )
                    scene_description = (
                        f"Manga panel continuation: {spoken}. Keep composition coherent with prior panel and preserve character identity."
                    )
                elif normalized_present:
                    scene_description = (
                        "Manga panel showing "
                        + ", ".join(normalized_present)
                        + " in a coherent continuation shot with clear foreground and background separation."
                    )
                else:
                    scene_description = (
                        "Manga panel continuation beat with clear setting continuity and strong visual composition."
                    )
                edits_count += 1
            panel["scene_description"] = scene_description

            if idx > 0 and panel.get("continuity_from_panel") in [None, "", 0]:
                panel["continuity_from_panel"] = idx
                edits_count += 1

            self._sync_panel_speech_bubbles(panel)
            repaired_panels.append(panel)

        board["panels"] = repaired_panels

        # Apply standard planner guards again before handoff to SceneGen.
        if len(board.get("characters", [])) > self.max_chars:
            board["characters"] = board.get("characters", [])[: self.max_chars]
            edits_count += 1

        self._normalize_timeline(board)
        if (self.niche_name or "") == "stage_show":
            self._enforce_stage_show_continuity(board)

        board["render_strategy"]["scene_preflight"] = {
            "ready": True,
            "edits_applied": int(edits_count),
            "panel_count": len(board.get("panels", [])),
        }

        ep_dir = episodes_dir / f"episode{episode_number}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        preflight_path = ep_dir / "storyboard-pre-scene.json"
        with open(preflight_path, "w") as f:
            json.dump(board, f, indent=2)
        board_path = ep_dir / "storyboard.json"
        with open(board_path, "w") as f:
            json.dump(board, f, indent=2)

        print(
            f"Planner preflight complete: panels={len(board.get('panels', []))}, edits_applied={edits_count}, saved={preflight_path}"
        )
        return board

    def run(self, base_prompt: str, session_dir: Path) -> Dict[str, Any]:
        print("--- Pipeline: Episode Planner ---")
        logger.info("EpisodePlanner.run() started | session=%s", session_dir)
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
        established_objects: list[Dict[str, Any]] = []
        if self.episode_mode:
            prior_ep_dir = None
            if next_num > 1:
                explicit_prior = episodes_dir / f"episode{next_num - 1}"
                if explicit_prior.exists():
                    prior_ep_dir = explicit_prior
            elif existing:
                prior_ep_dir = existing[-1]

            last_board = (prior_ep_dir / "storyboard.json") if prior_ep_dir else None
            if last_board and last_board.exists():
                with open(last_board, "r") as f:
                    prev = json.load(f)
                established_chars = prev.get("characters", [])
                established_objects = prev.get("objects", []) if isinstance(prev.get("objects", []), list) else []
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
                established_objects = prev.get("objects", [])
                if established_objects:
                    prior_context += "Established objects (MUST reuse with IDENTICAL visual_prompt for consistency):\n"
                    for obj in established_objects:
                        prior_context += (
                            f"  - {obj.get('name', '?')} [{obj.get('object_type', 'prop')}]: "
                            f"{obj.get('visual_prompt', obj.get('description', ''))}\n"
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
        if self.intro_only:
            episode_type = (
                f"This is Episode {next_num} in INTRO-ONLY mode. Focus ONLY on:\n"
                "- Premise hook and show concept setup\n"
                "- World/location establishment and tone\n"
                "- Character introductions with clear identity moments\n"
                "- Closing teaser that explicitly says the next episode is coming soon\n"
                "- Avoid object/device/invention demonstration arcs in this episode\n"
            )
        elif is_first:
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
        niche_rules_block = niche_rules_text or "- Follow niche context naturally while keeping coherent story flow.\n"
        stage_show_planning_block = stage_show_planner_rules or "- Not a stage-show episode.\n"

        aesthetic_text = f"AESTHETIC DIRECTION: {self.aesthetic_guidance}\n" if self.aesthetic_guidance else ""
        planner_skill_directives = self._active_planner_skill_directives()
        planner_skill_text = (
            "OPTIONAL PLANNER SKILLS (treat as additional hard guidance when relevant):\n"
            f"{planner_skill_directives}\n"
            if planner_skill_directives
            else ""
        )
        object_rules_text = (
            "- In intro_only mode, keep objects[] empty unless a world landmark is absolutely essential.\n"
            "- Do not structure beats as object/device/invention demos; prioritize premise, world, character introductions, and teaser ending.\n"
            if self.intro_only
            else (
                "- Every significant object, device, or invention mentioned in the story MUST appear in the objects[] array with a detailed visual_prompt.\n"
                "- Object visual_prompts are IMMUTABLE across episodes — copy verbatim from prior context when continuing a series.\n"
                "- Panels that prominently feature an object must reference it by name in scene_description so the image model can apply its visual_prompt.\n"
            )
        )

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
            f"{planner_skill_text}"
            f"{prior_context}\n"
            f"EPISODE TYPE:\n{episode_type}\n"
            f"INSTRUCTIONS:\n"
            f"Create Episode {next_num}. Target ~{self.max_duration_mins} minutes "
            f"of narrated video with full scene-wise dialogue coverage.\n\n"
            f"STRICT TIMELINE RULES:\n"
            f"- The final storyboard must fit EXACTLY into {int(self.max_duration_mins * 60)} seconds total after panel durations are summed.\n"
            f"- Plan panel_count and duration_seconds together; do not treat timing as an afterthought.\n"
            f"- Use detailed opening progression even in generic mode (intro hook -> premise grounding -> context -> stakes).\n"
            f"- If intro_only mode is active, keep the entire episode as detailed introduction and setup while still hitting exact runtime.\n\n"
            f"NARRATIVE ADHERENCE RULES:\n"
            f"- SERIES PRESET PROMPT is persistent source-of-truth for this series baseline.\n"
            f"- BASE STORY PREMISE is the source-of-truth for this run; preserve its core entities, intent, and conflict.\n"
            f"- You may adapt for cinematic pacing, but do not drift away from prompt meaning.\n"
            f"- SHOW BIBLE DETECTION: if SERIES PRESET PROMPT contains a full show universe reference document (character roster, episode anatomy, stage layout, visual identity rules, comedic/dramatic rhythm pattern, speech bubble styles), parse it completely and treat ALL defined rules as HARD CONSTRAINTS:\n"
            f"  * Extract every character's visual identity and assigned bubble_style verbatim.\n"
            f"  * Enforce the defined stage layout and camera geometry in every scene_description.\n"
            f"  * Follow the specified comedic/dramatic rhythm pattern (e.g. mandatory multi-step beat sequences).\n"
            f"  * Apply per-character bubble styles to every speech_bubbles entry in every panel.\n"
            f"  * Structure episode beats to exactly match the show's defined episode anatomy.\n\n"
            f"INPUT PROFILE: {script_profile}\n"
            f"- If baseline_theme: expand into a complete arc (setup -> escalation -> payoff).\n"
            f"- If short_script/full_script: ADAPT and REWRITE into cinematic beats; do not copy script verbatim.\n"
            f"- Use panel budget efficiently for quality pacing and visual rhythm.\n\n"
            f"NICHE RULES:\n"
            f"{niche_rules_block}\n"
            f"STAGE SHOW PLANNING RULES:\n"
            f"{stage_show_planning_block}\n"
            f"SPEECH BUBBLE RULES:\n"
            f"- Every panel that has non-empty dialogue MUST include a populated speech_bubbles array.\n"
            f"- speech_bubbles[n].text MUST be a character-for-character copy of the corresponding dialogue[n].line — no rewording, no summarizing, no truncating.\n"
            f"- speech_bubbles[n].character MUST exactly match dialogue[n].character (same name, same capitalisation).\n"
            f"- Assign each character their designated bubble_style from the character roster (or from the show bible).\n"
            f"- Default bubble styles when not specified: protagonist → rounded, antagonist → sharp-edged, narrator → whisper, crowd → cloudy.\n"
            f"- Position bubbles to avoid covering the character's face or the dominant visual element.\n"
            f"- Panels with only narration/voiceover lines: use a whisper or caption-style bubble with no tail.\n"
            f"- CRITICAL: the image generation model will read speech_bubbles[].text and render it directly inside the bubble. Any error in that text field will appear visibly wrong in the final frame — double-check every text value before outputting.\n\n"
            f"ART STYLE ENFORCEMENT:\n"
            f"- ALL scene images MUST be generated as manga/comic panels in style: {self.art_style}.\n"
            f"- scene_description fields must describe scenes that work as flat-color, ink-outlined manga panels — never describe photorealistic or painted scenes.\n"
            f"- visual_prompt fields must enumerate each character's manga-drawable traits precisely: specific hair color, eye color, outfit item names and colors, accessories.\n"
            f"- Vague appearance terms (\"normal clothes\", \"tall\", \"looks cool\") are FORBIDDEN in visual_prompt — every trait must be a concrete, reproducible description.\n"
            f"- Each character's visual_prompt must remain WORD-FOR-WORD IDENTICAL across all episodes (copy from prior context exactly when continuing a series).\n\n"
            f"HARD LIMITS:\n"
            f"- Maximum {self.max_chars} characters (reuse established characters when possible)\n"
            f"- Panel budget is UP TO {self.max_panels}; prefer coherent pacing over forcing panel count\n"
            f"- Each character's visual_prompt MUST be identical across episodes for image generation consistency\n"
            f"{object_rules_text}"
            f"- In scene_description and objects_present fields you MAY reference any character or object using @Name syntax. "
            f"Example: '@Arjun picks up the @QuantumDevice'. The pipeline will expand @Name tokens into inline visual anchors during image generation — use them for precision.\n\n"
            f"LANGUAGE RULES:\n"
            f"- If PRIMARY LANGUAGE HINT is hindi, make dialogue naturally Hindi (Devanagari) unless scene context demands bilingual style.\n"
            f"- Keep character and panel structure compatible with downstream TTS and subtitles.\n\n"
            f"DIALOGUE QUALITY RULES:\n"
            f"- Keep full dialogue lines for each scene beat; never truncate or abbreviate line text for brevity.\n"
            f"- Avoid one-word lines except intentional reaction beats.\n"
            f"- Most spoken lines should be complete natural phrases (typically 6-18 words).\n\n"
            f"- Preserve complete character names exactly as generated; do not shorten names in later panels.\n\n"
            f"Return ONLY strict JSON:\n"
            f"{{\n"
            f'  "episode_number": {next_num},\n'
            f'  "episode_title": "string",\n'
            f'  "episode_summary": "2-3 sentence summary of this episode including key events and cliffhanger",\n'
            f'  "characters": [\n'
            f'    {{\n'
            f'      "name": "CharacterName",\n'
            f'      "description": "Role and personality",\n'
            f'      "visual_prompt": "MANGA CHARACTER REFERENCE: enumerate every trait precisely so the image model can reproduce them identically across all episodes — (1) hair: color, length, style/texture; (2) eyes: color, shape, size; (3) skin tone; (4) face shape and any distinguishing marks; (5) outfit: garment names, colors, accessories, footwear; (6) body type/build; (7) any props always carried. Art style: {self.art_style}. NO vague terms like tall or normal — be specific and measurable.",\n'
            f'      "bubble_style": "rounded|sharp-edged|thought-bubble|jagged|electric|cloudy|whisper — leave blank to auto-assign; set from show bible if defined",\n'
            f'      "voice_profile": "Voice tone description",\n'
            f'      "assigned_voice": "EXACT key from voice pool"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "objects": [\n'
            f'    {{\n'
            f'      "name": "ObjectName",\n'
            f'      "description": "What it is and its narrative role",\n'
            f'      "object_type": "device|prop|infographic|invention|vehicle|location",\n'
            f'      "visual_prompt": "MANGA OBJECT REFERENCE: precise reproducible description — (1) primary shape and dimensions; (2) materials and surface texture; (3) color scheme with named/hex colors; (4) distinctive features, labels, dials, or markings; (5) any text printed on it; (6) scale relative to a person; (7) how it looks in this story universe. Art style: {self.art_style}. This description is IMMUTABLE — copy word-for-word in every episode.",\n'
            f'      "role_in_story": "When and how this object appears; its function in the narrative"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "panels": [\n'
            f'    {{\n'
            f'      "panel_number": 1,\n'
            f'      "characters_present": ["CharacterName"],\n'
            f'      "dialogue": [\n'
            f'        {{"character": "CharacterName", "line": "Dialogue text", "emotion": "neutral|sarcastic|happy|overwhelmed|curious|sad|angry|tense", "delivery_mode": "dialogue|narration|voiceover|silent"}}\n'
            f'      ],\n'
            f'      "speech_bubbles": [\n'
            f'        {{"character": "CharacterName", "text": "Exact dialogue text verbatim", "style": "rounded|sharp-edged|thought-bubble|jagged|electric|whisper", "position": "top-left|top-right|bottom-left|bottom-right|center-top|center-bottom"}}\n'
            f'      ],\n'
            f'      "scene_description": "Manga panel scene description: specify foreground subjects with exact poses, midground elements, background setting, lighting direction, and mood. MUST be renderable as a manga/comic panel with bold ink outlines and cel-shaded colors in art style: {self.art_style}. Reference characters by name so the image model can apply their visual_prompt traits.",\n'
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
        target_seconds = max(15, int(self.max_duration_mins * 60))
        manga_board, timeline_patch_passes = self._timeline_patch_review_loop(
            manga_board,
            base_prompt=base_prompt,
            target_seconds=target_seconds,
            is_first=is_first,
        )
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
        manga_board["render_strategy"]["planner_skill_ids"] = list(self.planner_skill_ids)
        if self.planner_skill_prompt:
            manga_board["render_strategy"]["planner_skill_prompt"] = self.planner_skill_prompt
        if planner_skill_directives:
            manga_board["render_strategy"]["planner_skill_directives"] = planner_skill_directives
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

        # Hard continuity guard: preserve object visual_prompts across episodes.
        self._enforce_object_consistency(manga_board, established_objects)

        # Enforce panel budget and normalize timeline for duration bounds.
        panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
        max_total_feasible = max(1, int(self.max_duration_mins * 60))
        target_panels = min(self.max_panels, max_total_feasible)
        panel_expand_passes = 0
        panel_expand_trace: list[Dict[str, Any]] = []
        if len(panels) < target_panels:
            manga_board, panel_expand_passes, panel_expand_trace = self._expand_panels_with_director_loop(
                manga_board,
                base_prompt=base_prompt,
                target_count=target_panels,
                is_first=is_first,
            )
            panels = manga_board.get("panels", []) if isinstance(manga_board.get("panels", []), list) else []
            if len(panels) < target_panels:
                print(
                    f"Warning: panel expansion reached {len(panels)}/{target_panels}; "
                    "timeline will be filled by duration allocation without cloning panels."
                )
        print(
            f"Planner timeline analysis: target_seconds={target_seconds}, target_panels={target_panels}, "
            f"actual_panels={len(manga_board.get('panels', []))}, expansion_passes={panel_expand_passes}"
        )
        if len(panels) > self.max_panels:
            print(f"Warning: LLM returned {len(panels)} panels, trimming to {self.max_panels}")
            manga_board["panels"] = panels[:self.max_panels]
        self._enforce_intro_structure(manga_board, is_first=is_first)
        self._enforce_intro_only_policy(manga_board)
        self._normalize_timeline(manga_board)
        # Strict exact-duration lock: patch durations until sum hits target exactly.
        for _ in range(3):
            total_now = self._timeline_total_seconds(manga_board)
            if total_now == target_seconds:
                break
            self._normalize_timeline(manga_board)
        self._enforce_stage_show_continuity(manga_board)
        manga_board["render_strategy"]["timeline_target_seconds"] = target_seconds
        manga_board["render_strategy"]["timeline_total_seconds"] = self._timeline_total_seconds(manga_board)
        manga_board["render_strategy"]["timeline_patch_passes"] = timeline_patch_passes
        manga_board["render_strategy"]["panel_expand_passes"] = panel_expand_passes
        manga_board["render_strategy"]["panel_target"] = target_panels
        manga_board["render_strategy"]["panel_actual"] = len(manga_board.get("panels", []))
        manga_board["render_strategy"]["timeline_planner_analysis"] = {
            "target_seconds": target_seconds,
            "target_panels": target_panels,
            "actual_panels": len(manga_board.get("panels", [])),
            "expansion_passes": panel_expand_passes,
            "expansion_trace": panel_expand_trace,
        }
        manga_board["render_strategy"]["intro_policy"] = "intro_only_detailed" if self.intro_only else "generic_with_strong_intro"

        # Save
        ep_dir = episodes_dir / f"episode{next_num}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        draft_path = ep_dir / "storyboard-draft.json"
        with open(draft_path, "w") as f:
            json.dump(draft_board, f, indent=2)
        board_path = ep_dir / "storyboard.json"
        with open(board_path, "w") as f:
            json.dump(manga_board, f, indent=2)

        title = manga_board.get('episode_title', 'Untitled')
        n_chars = len(manga_board.get('characters', []))
        n_panels = len(manga_board.get('panels', []))
        n_objects = len(manga_board.get('objects', []))
        print(f"Episode {next_num} planned: \"{title}\"")
        print(f"  Characters: {n_chars}/{self.max_chars}")
        print(f"  Objects: {n_objects}")
        print(f"  Panels: {n_panels}")
        print(f"  Saved to: {board_path}")
        logger.info("Storyboard saved | ep=%s title=%r chars=%s objects=%s panels=%s path=%s",
                    next_num, title, n_chars, n_objects, n_panels, board_path)
        return manga_board
