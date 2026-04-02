"""
Character Generator – Generates reference portraits with strict consistency.

Produces: chars/char_NAME.png + chars/chars_manifest.json
Resume: skips if character image already exists.
Art style is enforced from config for cross-episode consistency.
"""

import json
import random
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from PIL import Image

from agents.narrativeManga.utils import get_model
from agents.shared.llm_tracker import LLMTracker, tracked_generate


class CharGen:
    def __init__(
        self,
        image_model_name: str = "models/gemini-2.5-flash-image",
        max_generations: int = 5,
        resolution: Tuple[int, int] = (1280, 720),
        art_style: str = "cinematic anime",
        tracker: Optional[LLMTracker] = None,
    ):
        self.image_model_name = image_model_name
        self.max_generations = max_generations
        self.resolution = resolution
        self.art_style = art_style
        self.tracker = tracker

    def run(self, manga_board: Dict[str, Any], session_dir: Path) -> Dict[str, str]:
        """Generate character portraits. Returns {char_name: image_path}."""
        print("--- Pipeline: Character Generation ---")
        chars_dir = session_dir / "chars"
        chars_dir.mkdir(parents=True, exist_ok=True)

        characters = manga_board.get("characters", [])
        manifest: Dict[str, str] = {}
        anchor_path = None
        gen_count = 0

        for i, char in enumerate(characters):
            if gen_count >= self.max_generations:
                print(f"Hit max_generations ({self.max_generations}), stopping.")
                break

            name = char.get("name", f"char_{i}")
            safe_name = name.replace(" ", "_").lower()
            char_path = chars_dir / f"char_{safe_name}.png"

            # Resume: skip if exists
            if char_path.exists():
                print(f"Found existing portrait for {name}, skipping.")
                manifest[name] = str(char_path)
                if anchor_path is None:
                    anchor_path = char_path
                continue

            visual_prompt = char.get("visual_prompt", char.get("description", "An anime character"))
            width, height = self.resolution
            prompt = (
                f"A full-body character portrait for manga. "
                f"{visual_prompt}. "
                f"Art style: {self.art_style}. "
                f"Clean background, professional character sheet style. "
                f"CRITICAL: {width}:{height} aspect (exact {width}x{height}) resolution."
            )

            print(f"Generating portrait ({gen_count + 1}/{self.max_generations}): {name}")

            try:
                model = get_model(self.image_model_name)

                if anchor_path and anchor_path.exists():
                    with open(anchor_path, "rb") as f:
                        anchor_bytes = f.read()
                    response = tracked_generate(
                        self.tracker, model,
                        [
                            {"mime_type": "image/png", "data": anchor_bytes},
                            f"Generate a NEW character in the EXACT same art style. {prompt}",
                        ],
                        purpose="char_gen",
                    )
                else:
                    response = tracked_generate(self.tracker, model, prompt, purpose="char_gen")

                image_data = None
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        image_data = part.inline_data.data
                        break

                if image_data:
                    char_path.write_bytes(image_data)
                    self._force_resize(char_path)
                    print(f"  ✓ Generated: {char_path.name}")
                    gen_count += 1
                else:
                    raise ValueError("No image in response")

            except Exception as e:
                print(f"  ✗ Failed for {name}: {e}. Creating placeholder.")
                color = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
                Image.new("RGB", self.resolution, color=color).save(char_path)
                gen_count += 1

            manifest[name] = str(char_path)
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
