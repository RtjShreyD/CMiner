"""
Character Generator – Generates reference portraits with strict consistency.

Produces: chars/char_NAME.png + chars/chars_manifest.json
Resume: skips if character image already exists.
Art style is enforced from config for cross-episode consistency.
"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from PIL import Image

from agents.autoAnimator.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class CharGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 5,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        aesthetic_guidance: str = "",
        tracker: Optional[LLMTracker] = None,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.aesthetic_guidance = aesthetic_guidance or ""
        self.tracker = tracker

    def _build_prompt(self, visual_prompt: str) -> str:
        width, height = self.resolution
        aesthetics = f" Aesthetic direction: {self.aesthetic_guidance}." if self.aesthetic_guidance else ""
        return (
            f"A full-body character portrait for manga. {visual_prompt}. "
            f"Art style: {self.art_style}. "
            f"{aesthetics}"
            f"Clean background, professional character sheet style. "
            f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution."
        )

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
                # Reject near-solid placeholder-like images.
                if all((mx - mn) < 8 for mn, mx in extrema):
                    return False
            return True
        except Exception:
            return False

    def run(self, manga_board: Dict[str, Any], session_dir: Path, force_names: Optional[set[str]] = None) -> Dict[str, str]:
        """Generate character portraits. Returns {char_name: image_path}."""
        print("--- Pipeline: Character Generation ---")
        chars_dir = session_dir / "chars"
        chars_dir.mkdir(parents=True, exist_ok=True)

        characters = manga_board.get("characters", [])
        manifest: Dict[str, str] = {}
        anchor_path = None
        gen_count = 0
        model = get_model(self.image_model_name)
        current_episode = max(1, int(manga_board.get("episode_number", 1) or 1))
        episode_chars_dir = session_dir / "episodes" / f"episode{current_episode}" / "chars"
        episode_chars_dir.mkdir(parents=True, exist_ok=True)

        existing_manifest_path = chars_dir / "chars_manifest.json"
        existing_manifest: Dict[str, str] = {}
        if existing_manifest_path.exists():
            try:
                parsed = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    existing_manifest = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                existing_manifest = {}

        for i, char in enumerate(characters):
            if gen_count >= self.max_generations:
                print(f"Hit max_generations ({self.max_generations}), stopping.")
                break

            name = char.get("name", f"char_{i}")
            safe_name = name.replace(" ", "_").lower()
            char_path = chars_dir / f"char_{safe_name}.png"
            force_regen = bool(force_names and name in force_names)

            # Allow planner/director to explicitly reuse an existing character image.
            reuse_char = str(char.get("reuse_character_from", "") or "").strip()
            if not force_regen and reuse_char:
                source_path = existing_manifest.get(reuse_char)
                if source_path:
                    src = Path(source_path)
                    if src.exists() and self._is_valid_generated_image(src):
                        shutil.copy2(src, char_path)
                        manifest[name] = str(char_path)
                        ep_copy = episode_chars_dir / f"char_{safe_name}.png"
                        self._mirror_to_episode(char_path, ep_copy)
                        if anchor_path is None:
                            anchor_path = char_path
                        print(f"Reused character image for {name} from {reuse_char}.")
                        continue

            # Resume: skip only if existing image is valid.
            if char_path.exists():
                if force_regen:
                    print(f"Force-regenerating portrait for {name}.")
                    char_path.unlink(missing_ok=True)
                else:
                    if self._is_valid_generated_image(char_path):
                        print(f"Found existing portrait for {name}, skipping.")
                        manifest[name] = str(char_path)
                        ep_copy = episode_chars_dir / f"char_{safe_name}.png"
                        self._mirror_to_episode(char_path, ep_copy)
                        if anchor_path is None:
                            anchor_path = char_path
                        continue
                    print(f"Found invalid portrait for {name}, regenerating.")
                    char_path.unlink(missing_ok=True)

            visual_prompt = char.get("visual_prompt", char.get("description", "An anime character"))
            prompt = self._build_prompt(visual_prompt)

            print(f"Generating portrait ({gen_count + 1}/{self.max_generations}): {name}")

            generated_ok = False
            max_attempts = 3
            anchor_bytes = None
            if anchor_path and anchor_path.exists():
                anchor_bytes = anchor_path.read_bytes()
            for attempt in range(1, max_attempts + 1):
                try:
                    if anchor_bytes:
                        response = tracked_generate(
                            self.tracker,
                            model,
                            [
                                {"mime_type": "image/png", "data": anchor_bytes},
                                f"Generate a NEW character in the EXACT same art style. {prompt}",
                            ],
                            purpose="char_gen",
                        )
                    else:
                        response = tracked_generate(self.tracker, model, prompt, purpose="char_gen")

                    image_data = self._extract_inline_image_bytes(response)
                    if not image_data:
                        raise ValueError("No image in response")

                    char_path.write_bytes(image_data)
                    self._force_resize(char_path)
                    if not self._is_valid_generated_image(char_path):
                        raise ValueError("Generated image failed validation")

                    print(f"  ✓ Generated: {char_path.name}")
                    gen_count += 1
                    generated_ok = True
                    break
                except Exception as e:
                    print(f"  ✗ Attempt {attempt}/{max_attempts} failed for {name}: {e}")
                    char_path.unlink(missing_ok=True)

            if not generated_ok:
                raise RuntimeError(f"Character generation failed for '{name}' after {max_attempts} attempts")

            manifest[name] = str(char_path)
            ep_copy = episode_chars_dir / f"char_{safe_name}.png"
            self._mirror_to_episode(char_path, ep_copy)
            if anchor_path is None:
                anchor_path = char_path

        # Save manifest and anchor metadata for cross-step consistency
        manifest_path = chars_dir / "chars_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        anchors = {}
        for char in characters:
            name = char.get("name")
            if name and name in manifest:
                anchors[name] = {
                    "image": manifest[name],
                    "visual_prompt": char.get("visual_prompt", char.get("description", "")),
                    "style": self.art_style,
                }

        anchor_path = chars_dir / "char_anchors.json"
        with open(anchor_path, "w") as f:
            json.dump(anchors, f, indent=2)

        print(f"Character manifest: {len(manifest)} characters ({gen_count} generated)")
        print(f"Character anchors saved to {anchor_path}")
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
