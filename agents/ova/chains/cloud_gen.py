"""OVA speech bubble compositor.

Strategy (replaces CV2 blob detection):
1. Scene images are generated WITHOUT speech bubbles.
2. BubbleFinder (lightweight vision LLM) locates optimal placement regions.
3. A static cloud template (speech / shout / thought / caption) is rendered
   at the target size and composited over the scene.
4. Dialogue text is drawn inside the bubble region.
5. The composited image overwrites the scenes_manifest entry so the MovieMaker
   picks it up without needing per-frame overlays.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from agents.ova.chains.bubble_finder import BubbleFinder
from agents.ova.assets.cloud_templates import render_template
from api.services.buildpacks import _load_font


class CloudGen:
    def __init__(
        self,
        bubble_finder_model: str = "models/gemini-flash-latest",
        resolution: Tuple[int, int] = (1280, 720),
        font_style: str = "font-geist-sans",
        font_size: int = 26,
        tracker=None,
        # Legacy params accepted but unused (keeps run.py call compatible)
        fps: int = 24,
        cloud_style: str = "speech",
        subtitle_style: str = "",
        narration_mode: str = "",
        subtitle_scale: float = 1.0,
    ):
        self.bubble_finder_model = bubble_finder_model
        self.resolution = resolution
        self.font_style = font_style
        self.font_size = font_size
        self.tracker = tracker
        self.default_cloud_style = cloud_style or "speech"

    # ── Main entry point ──────────────────────────────────────

    def run(self, storyboard: Dict[str, Any], session_dir: Path) -> None:
        print("--- Pipeline: OVA Speech Bubble Compositor ---")
        scenes_dir = session_dir / "scenes"
        scenes_manifest_path = scenes_dir / "scenes_manifest.json"

        if not scenes_manifest_path.exists():
            print("No scenes_manifest.json found; skipping cloud compositor.")
            return

        with open(scenes_manifest_path) as f:
            manifest: Dict[str, str] = json.load(f)

        finder = BubbleFinder(model_name=self.bubble_finder_model, tracker=self.tracker)
        font = _load_font(self.font_style, self.font_size)
        w, h = self.resolution

        for i, panel in enumerate(storyboard.get("panels", [])):
            panel_key = f"panel_{i:02d}"
            scene_path_str = manifest.get(panel_key)
            if not scene_path_str or not Path(scene_path_str).exists():
                continue

            scene_path = Path(scene_path_str)
            dialogue_lines: List[Dict[str, str]] = panel.get("dialogue", [])
            if not dialogue_lines:
                continue

            cloud_style = panel.get("cloud_style", self.default_cloud_style)

            print(f"  {panel_key}: finding bubble placement ({cloud_style})...")
            placements = finder.locate(scene_path, dialogue_lines, w, h, cloud_style)
            if not placements:
                print(f"  {panel_key}: no placements found, skipping.")
                continue

            # Build char -> concatenated dialogue text
            char_text: Dict[str, str] = {}
            for dl in dialogue_lines:
                cn = dl.get("character", "")
                line = dl.get("line", "").strip()
                if cn and line:
                    char_text[cn] = (char_text.get(cn, "") + " " + line).strip()

            # Load scene as RGBA
            scene_pil = Image.open(scene_path).convert("RGBA")
            if scene_pil.size != (w, h):
                scene_pil = scene_pil.resize((w, h), Image.Resampling.LANCZOS)

            composite = scene_pil.copy()
            placed = 0
            for placement in placements:
                char = placement["character"]
                bx, by = placement["x"], placement["y"]
                bw, bh = placement["w"], placement["h"]
                style = placement.get("cloud_style", cloud_style)
                text = char_text.get(char, "")
                if not text:
                    continue

                # Render + paste cloud template
                template_img = render_template(style, bw, bh)
                composite.paste(template_img, (bx, by), template_img)

                # Draw text inside
                text_layer = Image.new("RGBA", composite.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(text_layer)
                self._draw_text_inside(draw, text, bx, by, bw, bh, font)
                composite = Image.alpha_composite(composite, text_layer)
                placed += 1

            # Save composited scene and update manifest
            out_path = scenes_dir / f"{panel_key}_with_speech.png"
            composite.convert("RGB").save(str(out_path))
            manifest[panel_key] = str(out_path)
            print(f"  + {panel_key}: {placed} bubble(s) -> {out_path.name}")

        # Persist updated manifest
        with open(scenes_manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        print("Speech bubble compositor done.")

    # ── Text helpers ──────────────────────────────────────────

    def _draw_text_inside(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        bx: int,
        by: int,
        bw: int,
        bh: int,
        font,
    ) -> None:
        margin = max(10, min(bw, bh) // 8)
        max_w = max(40, bw - margin * 2)
        lines = self._wrap_text(text, draw, font, max_w)
        line_h = self._line_height(draw, font)
        total_h = max(line_h, len(lines) * (line_h + 3) - 3)
        ty = by + max(margin, (bh - total_h) // 2)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            tx = bx + max(margin, (bw - tw) // 2)
            # White halo for readability
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((tx + dx, ty + dy), line, font=font, fill=(255, 255, 255, 180))
            draw.text((tx, ty), line, font=font, fill=(14, 14, 14, 255))
            ty += line_h + 3

    @staticmethod
    def _line_height(draw: ImageDraw.ImageDraw, font) -> int:
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        return max(14, bbox[3] - bbox[1])

    def _wrap_text(
        self, text: str, draw: ImageDraw.ImageDraw, font, max_width: int
    ) -> List[str]:
        words = text.split()
        lines: List[str] = []
        current: List[str] = []
        for word in words:
            current.append(word)
            trial = " ".join(current)
            bbox = draw.textbbox((0, 0), trial, font=font)
            if (bbox[2] - bbox[0]) > max_width:
                if len(current) == 1:
                    lines.append(trial)
                    current = []
                else:
                    current.pop()
                    lines.append(" ".join(current))
                    current = [word]
        if current:
            lines.append(" ".join(current))
        return lines[:6]
