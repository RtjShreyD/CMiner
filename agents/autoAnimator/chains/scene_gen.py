"""
Scene Generator – Generates panel scenes with character consistency.

Produces: scenes/panel_XX.png + scenes/scenes_manifest.json
Uses character portraits as multimodal anchors for consistency.
Resume: skips existing. Budget-aware: respects max_generations.
"""

import json
import hashlib
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class SceneGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 45,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        aesthetic_guidance: str = "",
        project_name: str = "AutoAnimator",
        tracker: Optional[LLMTracker] = None,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.aesthetic_guidance = aesthetic_guidance or ""
        self.project_name = project_name or "AutoAnimator"
        self.tracker = tracker

    def _panel_signature(self, panel: Dict[str, Any], char_visuals: Dict[str, str]) -> str:
        payload = {
            "scene_description": str(panel.get("scene_description", "") or ""),
            "render_method": str(panel.get("render_method", "llm_image") or "llm_image"),
            "characters_present": [str(c) for c in (panel.get("characters_present", []) if isinstance(panel.get("characters_present", []), list) else [])],
            "camera_angle": str(panel.get("camera_angle", "") or ""),
            "mood": str(panel.get("mood", "") or ""),
            "reuse_from_previous_episode_panel": panel.get("reuse_from_previous_episode_panel"),
            "static_frame_spec": panel.get("static_frame_spec") if isinstance(panel.get("static_frame_spec"), dict) else None,
            "art_style": self.art_style,
            "aesthetic_guidance": self.aesthetic_guidance,
            "resolution": [int(self.resolution[0]), int(self.resolution[1])],
            "char_visuals": {k: char_visuals.get(k, "") for k in sorted(char_visuals.keys())},
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _render_static_frame(self, panel: Dict[str, Any], panel_key: str, out_path: Path) -> bool:
        spec = panel.get("static_frame_spec") if isinstance(panel.get("static_frame_spec"), dict) else {}
        renderer = str(spec.get("renderer", "solid") or "solid").strip().lower()
        width, height = self.resolution
        bg = str(spec.get("bg_color", "#111111") or "#111111")

        img = Image.new("RGB", self.resolution, color=bg)
        if renderer == "gradient":
            gradient = spec.get("gradient") if isinstance(spec.get("gradient"), list) else []
            c1 = str(gradient[0] if len(gradient) > 0 else "#090909")
            c2 = str(gradient[1] if len(gradient) > 1 else "#1a1a1a")
            try:
                from PIL import ImageColor

                r1, g1, b1 = ImageColor.getrgb(c1)
                r2, g2, b2 = ImageColor.getrgb(c2)
                for y in range(height):
                    t = y / max(1, height - 1)
                    color = (
                        int(r1 + (r2 - r1) * t),
                        int(g1 + (g2 - g1) * t),
                        int(b1 + (b2 - b1) * t),
                    )
                    for x in range(width):
                        img.putpixel((x, y), color)
            except Exception:
                pass

        draw = ImageDraw.Draw(img)

        if renderer in {"title_card", "solid", "gradient"}:
            show_text = bool(spec.get("show_text", renderer == "title_card"))
            title = str(spec.get("title_text") or "")
            if show_text:
                font = ImageFont.load_default()
                max_chars = 42
                lines = []
                words = title.split()
                cur = []
                for w in words:
                    cur.append(w)
                    if len(" ".join(cur)) > max_chars:
                        cur.pop()
                        lines.append(" ".join(cur))
                        cur = [w]
                if cur:
                    lines.append(" ".join(cur))
                lines = lines[:4] if lines else [f"{self.project_name} - {panel_key}"]

                y = int(height * 0.32)
                for line in lines:
                    bbox = font.getbbox(line)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    x = max(24, (width - tw) // 2)
                    draw.text((x, y), line, fill=(240, 240, 240), font=font)
                    y += th + 12

        img.save(out_path)
        return True

    @staticmethod
    def _parse_reuse_panel_index(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value - 1 if value > 0 else None
        try:
            raw = str(value).strip().lower()
            if raw.startswith("panel_"):
                return int(raw.split("_", 1)[1])
            num = int(raw)
            return num - 1 if num > 0 else None
        except Exception:
            return None

    @staticmethod
    def _extract_inline_image_bytes(response: Any) -> bytes | None:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return None
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None) if inline else None
            if data:
                return data
        return None

    @staticmethod
    def _is_valid_generated_image(path: Path) -> bool:
        try:
            if not path.exists() or path.stat().st_size < 1024:
                return False
            with Image.open(path) as img:
                rgb = img.convert("RGB")
                extrema = rgb.getextrema()
                if all((mx - mn) < 8 for mn, mx in extrema):
                    return False
            return True
        except Exception:
            return False

    def run(
        self,
        manga_board: Dict[str, Any],
        char_manifest: Dict[str, str],
        session_dir: Path,
    ) -> Dict[str, str]:
        print("--- Pipeline: Scene Generation ---")
        scenes_dir = session_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        current_episode = max(1, int(manga_board.get("episode_number", 1) or 1))
        episode_scenes_dir = session_dir / "episodes" / f"episode{current_episode}" / "scenes"
        episode_scenes_dir.mkdir(parents=True, exist_ok=True)
        prior_episode_scenes_dir = session_dir / "episodes" / f"episode{current_episode - 1}" / "scenes"
        signatures_path = scenes_dir / "scene_signatures.json"
        scene_signatures: Dict[str, str] = {}
        if signatures_path.exists():
            try:
                parsed = json.loads(signatures_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    scene_signatures = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                scene_signatures = {}

        panels = manga_board.get("panels", [])
        render_strategy = manga_board.get("render_strategy", {}) if isinstance(manga_board.get("render_strategy", {}), dict) else {}
        characters = manga_board.get("characters", [])
        char_visuals = {c["name"]: c.get("visual_prompt", c.get("description", "")) for c in characters}

        def _load_ref_bytes(ref_path: str | None) -> bytes | None:
            if not ref_path:
                return None
            try:
                p = Path(ref_path)
                if not p.is_absolute():
                    p = session_dir / ref_path
                if p.exists() and p.is_file():
                    return p.read_bytes()
            except Exception:
                return None
            return None

        start_frame_bytes = _load_ref_bytes(str(render_strategy.get("start_frame_path", "") or ""))
        end_frame_bytes = _load_ref_bytes(str(render_strategy.get("end_frame_path", "") or ""))

        # Load anchor-based descriptions when available
        char_anchors_path = session_dir / "chars" / "char_anchors.json"
        if char_anchors_path.exists():
            try:
                with open(char_anchors_path, "r") as f:
                    char_anchors = json.load(f)
                for name, data in char_anchors.items():
                    prompt_text = data.get("visual_prompt") or char_visuals.get(name)
                    if prompt_text:
                        char_visuals[name] = prompt_text
            except Exception as e:
                print(f"  ⚠️ Warning: failed to load char anchors: {e}")

        manifest: Dict[str, str] = {}
        gen_count = 0
        budget_fallback_announced = False
        model = get_model(self.image_model_name)

        char_anchor_bytes: Dict[str, bytes] = {}
        for cname, char_img_path in (char_manifest or {}).items():
            try:
                p = Path(char_img_path)
                if p.exists():
                    char_anchor_bytes[cname] = p.read_bytes()
            except Exception:
                continue

        previous_scene_bytes: bytes | None = None

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            scene_path = scenes_dir / f"{panel_key}.png"
            panel_sig = self._panel_signature(panel, char_visuals)

            # Resume only for valid existing files whose generation signature still matches.
            if scene_path.exists():
                if self._is_valid_generated_image(scene_path) and scene_signatures.get(panel_key) == panel_sig:
                    print(f"Found existing {panel_key}, skipping.")
                    manifest[panel_key] = str(scene_path)
                    continue
                print(f"Found invalid {panel_key}, regenerating.")
                scene_path.unlink(missing_ok=True)

            if gen_count >= self.max_generations:
                if not budget_fallback_announced:
                    print(f"Hit budget ({self.max_generations}), switching remaining panels to local static fallback.")
                    budget_fallback_announced = True
                scene_desc = str(panel.get("scene_description", "")).strip()
                title_text = scene_desc[:90] if scene_desc else f"{self.project_name} - {panel_key}"
                fallback_panel = {
                    "scene_description": scene_desc,
                    "static_frame_spec": {
                        "renderer": "gradient",
                        "gradient": ["#0f1228", "#1e2450"],
                        "show_text": False,
                        "title_text": title_text,
                    },
                }
                ok = self._render_static_frame(fallback_panel, panel_key, scene_path)
                if not ok or (not scene_path.exists()) or scene_path.stat().st_size < 256:
                    raise RuntimeError(f"Static fallback generation failed for '{panel_key}'")
                manifest[panel_key] = str(scene_path)
                scene_signatures[panel_key] = panel_sig
                ep_copy = episode_scenes_dir / f"{panel_key}.png"
                self._mirror_to_episode(scene_path, ep_copy)
                continue

            scene_desc = panel.get("scene_description", "A dramatic manga scene")
            render_method = str(panel.get("render_method", "llm_image") or "llm_image").strip().lower()
            chars_present = panel.get("characters_present", [])
            camera = panel.get("camera_angle", "medium-shot")
            mood = panel.get("mood", "dramatic")
            continuity_from_panel = panel.get("continuity_from_panel")
            shot_intent = str(panel.get("shot_intent", "") or "").strip()
            pose_direction = str(panel.get("pose_direction", "") or "").strip()
            dialogue_rows = panel.get("dialogue", []) if isinstance(panel.get("dialogue", []), list) else []
            dialogue_context = []
            for dl in dialogue_rows[:5]:
                if not isinstance(dl, dict):
                    continue
                cname = str(dl.get("character", "Speaker") or "Speaker")
                line = str(dl.get("line", "") or "").strip()
                if line:
                    dialogue_context.append(f"{cname}: {line}")
            dialogue_snippet = " | ".join(dialogue_context)

            reuse_idx = self._parse_reuse_panel_index(panel.get("reuse_from_previous_episode_panel"))
            if current_episode > 1 and reuse_idx is not None and prior_episode_scenes_dir.exists():
                reuse_src = prior_episode_scenes_dir / f"panel_{reuse_idx:02d}.png"
                if reuse_src.exists() and self._is_valid_generated_image(reuse_src):
                    shutil.copy2(reuse_src, scene_path)
                    manifest[panel_key] = str(scene_path)
                    scene_signatures[panel_key] = panel_sig
                    ep_copy = episode_scenes_dir / f"{panel_key}.png"
                    self._mirror_to_episode(scene_path, ep_copy)
                    print(f"Reused previous-episode scene for {panel_key} from panel_{reuse_idx:02d}.")
                    continue

            if render_method == "static_frame":
                print(f"Generating static frame: {panel_key}")
                ok = self._render_static_frame(panel, panel_key, scene_path)
                if not ok or (not scene_path.exists()) or scene_path.stat().st_size < 256:
                    raise RuntimeError(f"Static frame generation failed for '{panel_key}'")
                manifest[panel_key] = str(scene_path)
                scene_signatures[panel_key] = panel_sig
                gen_count += 1
                continue

            char_snippets = []
            for cname in chars_present:
                vis = char_visuals.get(cname, cname)
                char_snippets.append(f"{cname}: {vis}")
            chars_in_scene = "; ".join(char_snippets) if char_snippets else "No specific characters"

            width, height = self.resolution
            aesthetics = f"Aesthetic direction: {self.aesthetic_guidance}. " if self.aesthetic_guidance else ""
            prompt = (
                f"A cinematic manga panel. {scene_desc}. "
                f"Camera: {camera}. Mood: {mood}. "
                f"Characters in scene: {chars_in_scene}. "
                f"Dialogue context for this panel: {dialogue_snippet or 'no spoken lines'}. "
                f"Shot intent: {shot_intent or 'story progression'}. "
                f"Pose progression: {pose_direction or 'maintain continuity from previous panel'}. "
                f"Continuity from panel: {continuity_from_panel}. "
                "Strict continuity rules: keep character identity, costumes, and stage/location coherent with previous panels. "
                "Do not introduce unrelated scene changes that conflict with the storyboard and dialogue context. "
                f"Art style: {self.art_style}. "
                f"{aesthetics}"
                f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution."
            )

            print(f"Generating ({gen_count + 1}/{self.max_generations}): {panel_key} ({camera}, {mood})")

            generated_ok = False
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    # Use multiple anchors for character identity and scene continuity.
                    anchor_payload = []
                    if i == 0 and start_frame_bytes:
                        anchor_payload.append({"mime_type": "image/png", "data": start_frame_bytes})
                    if i == (len(panels) - 1) and end_frame_bytes:
                        anchor_payload.append({"mime_type": "image/png", "data": end_frame_bytes})
                    if previous_scene_bytes:
                        anchor_payload.append({"mime_type": "image/png", "data": previous_scene_bytes})

                    if isinstance(continuity_from_panel, int) and continuity_from_panel > 0:
                        prior_idx = continuity_from_panel - 1
                        prior_path = scenes_dir / f"panel_{prior_idx:02d}.png"
                        if prior_path.exists():
                            try:
                                anchor_payload.append({"mime_type": "image/png", "data": prior_path.read_bytes()})
                            except Exception:
                                pass
                    for cname in chars_present:
                        cached = char_anchor_bytes.get(cname)
                        if cached:
                            anchor_payload.append({"mime_type": "image/png", "data": cached})
                        if len(anchor_payload) >= 4:
                            break

                    if anchor_payload:
                        response = tracked_generate(
                            self.tracker,
                            model,
                            anchor_payload + [
                                f"Generate a scene featuring the character(s) from the attached reference images. "
                                f"Character consistency is CRITICAL. {prompt}",
                            ],
                            purpose="scene_gen",
                        )
                    else:
                        response = tracked_generate(self.tracker, model, prompt, purpose="scene_gen")

                    image_data = self._extract_inline_image_bytes(response)
                    if not image_data:
                        raise ValueError("No image in response")

                    scene_path.write_bytes(image_data)
                    self._force_resize(scene_path)
                    if not self._is_valid_generated_image(scene_path):
                        raise ValueError("Generated image failed validation")

                    print(f"  ✓ Generated: {scene_path.name}")
                    previous_scene_bytes = scene_path.read_bytes()
                    gen_count += 1
                    generated_ok = True
                    break
                except Exception as e:
                    print(f"  ✗ Attempt {attempt}/{max_attempts} failed for {panel_key}: {e}")
                    scene_path.unlink(missing_ok=True)

            if not generated_ok:
                raise RuntimeError(f"Scene generation failed for '{panel_key}' after {max_attempts} attempts")

            manifest[panel_key] = str(scene_path)
            scene_signatures[panel_key] = panel_sig
            ep_copy = episode_scenes_dir / f"{panel_key}.png"
            self._mirror_to_episode(scene_path, ep_copy)

        manifest_path = scenes_dir / "scenes_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        with open(signatures_path, "w") as f:
            json.dump(scene_signatures, f, indent=2)

        print(f"Scene manifest: {len(manifest)} panels ({gen_count} generated)")
        return manifest

    def _force_resize(self, img_path: Path):
        with Image.open(img_path) as img:
            if img.size != self.resolution:
                print(f"  Resizing from {img.size} to {self.resolution}")
                img = img.resize(self.resolution, Image.Resampling.LANCZOS)
            img.save(img_path)

    @staticmethod
    def _mirror_to_episode(src: Path, dst: Path):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink(missing_ok=True)
        try:
            # Prefer hardlink to avoid duplicate disk usage.
            dst.hardlink_to(src)
        except Exception:
            shutil.copy2(src, dst)
