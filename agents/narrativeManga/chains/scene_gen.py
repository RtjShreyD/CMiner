"""
Scene Generator – Generates panel scenes with character consistency.

Produces: scenes/panel_XX.png + scenes/scenes_manifest.json
Uses character portraits as multimodal anchors for consistency.
Resume: skips existing. Budget-aware: respects max_generations.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from PIL import Image

from agents.narrativeManga.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class SceneGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 45,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        tracker: Optional[LLMTracker] = None,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.tracker = tracker

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

        panels = manga_board.get("panels", [])
        characters = manga_board.get("characters", [])
        char_visuals = {c["name"]: c.get("visual_prompt", c.get("description", "")) for c in characters}

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

        for i, panel in enumerate(panels):
            if gen_count >= self.max_generations:
                print(f"Hit budget ({self.max_generations}), stopping scene generation.")
                break

            panel_key = f"panel_{i:02d}"
            scene_path = scenes_dir / f"{panel_key}.png"

            # Resume only for valid existing files.
            if scene_path.exists():
                if self._is_valid_generated_image(scene_path):
                    print(f"Found existing {panel_key}, skipping.")
                    manifest[panel_key] = str(scene_path)
                    continue
                print(f"Found invalid {panel_key}, regenerating.")
                scene_path.unlink(missing_ok=True)

            scene_desc = panel.get("scene_description", "A dramatic manga scene")
            chars_present = panel.get("characters_present", [])
            camera = panel.get("camera_angle", "medium-shot")
            mood = panel.get("mood", "dramatic")

            char_snippets = []
            for cname in chars_present:
                vis = char_visuals.get(cname, cname)
                char_snippets.append(f"{cname}: {vis}")
            chars_in_scene = "; ".join(char_snippets) if char_snippets else "No specific characters"

            width, height = self.resolution
            prompt = (
                f"A cinematic manga panel. {scene_desc}. "
                f"Camera: {camera}. Mood: {mood}. "
                f"Characters in scene: {chars_in_scene}. "
                f"Art style: {self.art_style}. "
                f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution."
            )

            print(f"Generating ({gen_count + 1}/{self.max_generations}): {panel_key} ({camera}, {mood})")

            model = get_model(self.image_model_name)
            generated_ok = False
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    # Find best character anchor (first present character with an image)
                    anchor_bytes = None
                    for cname in chars_present:
                        char_img_path = char_manifest.get(cname)
                        if char_img_path and Path(char_img_path).exists():
                            with open(char_img_path, "rb") as f:
                                anchor_bytes = f.read()
                            break

                    if anchor_bytes:
                        response = tracked_generate(
                            self.tracker,
                            model,
                            [
                                {"mime_type": "image/png", "data": anchor_bytes},
                                f"Generate a scene featuring the character(s) from the attached reference. "
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
                    gen_count += 1
                    generated_ok = True
                    break
                except Exception as e:
                    print(f"  ✗ Attempt {attempt}/{max_attempts} failed for {panel_key}: {e}")
                    scene_path.unlink(missing_ok=True)

            if not generated_ok:
                raise RuntimeError(f"Scene generation failed for '{panel_key}' after {max_attempts} attempts")

            manifest[panel_key] = str(scene_path)

        manifest_path = scenes_dir / "scenes_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        print(f"Scene manifest: {len(manifest)} panels ({gen_count} generated)")
        return manifest

    def _force_resize(self, img_path: Path):
        with Image.open(img_path) as img:
            if img.size != self.resolution:
                print(f"  Resizing from {img.size} to {self.resolution}")
                img = img.resize(self.resolution, Image.Resampling.LANCZOS)
            img.save(img_path)
