"""
Cloud Generator – OpenCV-based speech bubble placement.

Uses Canny edge detection + sliding-window scoring to find the optimal
low-detail region near each speaking character's position. Places speech
bubbles accordingly. ZERO LLM calls – all local processing.

Produces: overlays/panel_XX/frame_XXXX.png (transparent PNGs)
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from api.services.buildpacks import _draw_cloud, _load_font, _resolve_cloud_kind, _resolve_subtitle_style


class CloudGen:
    def __init__(
        self,
        fps: int = 24,
        resolution: Tuple[int, int] = (1280, 720),
        cloud_style: str = "cloud-none",
        font_style: str = "font-geist-sans",
        subtitle_style: str = "sub-clean-bottom",
        narration_mode: str = "hybrid_subtitles_clouds",
        subtitle_scale: float = 1.0,
    ):
        self.fps = fps
        self.resolution = resolution
        self.cloud_style = cloud_style
        self.font_style = font_style
        self.subtitle_style = subtitle_style
        self.narration_mode = narration_mode
        self.subtitle_scale = subtitle_scale

    def run(self, manga_board: Dict[str, Any], session_dir: Path):
        print("--- Pipeline: Cloud Generation (OpenCV) ---")
        overlays_dir = session_dir / "overlays"
        overlays_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = session_dir / "scenes"
        audio_dir = session_dir / "audio"

        panels = manga_board.get("panels", [])
        characters = manga_board.get("characters", [])

        font_size = max(20, int(34 * max(0.5, self.subtitle_scale)))
        font = _load_font(self.font_style, font_size)
        sub_style = _resolve_subtitle_style(self.subtitle_style)
        cloud_kind = _resolve_cloud_kind(self.cloud_style)

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            timing_path = audio_dir / f"{panel_key}_timing.json"
            scene_path = scenes_dir / f"{panel_key}.png"

            if not timing_path.exists():
                print(f"No timing for {panel_key}, skipping clouds.")
                continue

            with open(timing_path, "r") as f:
                timings = json.load(f)

            if not timings:
                continue

            # Load scene image for OpenCV analysis
            if scene_path.exists():
                scene_img = cv2.imread(str(scene_path))
            else:
                # Create a blank scene if missing
                scene_img = np.zeros((self.resolution[1], self.resolution[0], 3), dtype=np.uint8)

            # Resize scene to match overlay resolution if needed
            h, w = scene_img.shape[:2]
            if (w, h) != self.resolution:
                scene_img = cv2.resize(scene_img, self.resolution)

            # Find optimal placement regions for each character
            dialogue_lines = panel.get("dialogue", [])
            char_positions = self._assign_character_positions(
                dialogue_lines, scene_img
            )

            # Calculate total frames from timing
            last_t = timings[-1]
            total_sec = (last_t["offset"] + last_t["duration"]) / 10_000_000.0
            total_frames = int(total_sec * self.fps) + 5

            panel_overlay_dir = overlays_dir / panel_key
            panel_overlay_dir.mkdir(parents=True, exist_ok=True)

            print(f"Generating {total_frames} cloud frames for {panel_key}")

            # Sync offset (200_000 units = 20ms advance)
            SYNC_OFFSET = 200_000

            for frame_idx in range(total_frames):
                current_time_sec = frame_idx / self.fps
                current_time_units = (current_time_sec * 10_000_000) + SYNC_OFFSET

                # Gather spoken words up to now, grouped by character
                char_words: Dict[str, List[str]] = {}
                active_char = None
                for t in timings:
                    if t["offset"] <= current_time_units:
                        cname = t.get("character", "Unknown")
                        active_char = cname
                        if cname not in char_words:
                            char_words[cname] = []
                        char_words[cname].append(t["text"])

                # Create transparent overlay
                img = Image.new("RGBA", self.resolution, (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)

                # Show currently speaking text with the same styles used by buildpack preview.
                if active_char and active_char in char_words:
                    words = char_words[active_char][-15:]  # last 15 chunks
                    text = " ".join(words)
                    self._draw_overlay_text(draw, text, char_positions.get(active_char, (100, 50)), font, sub_style, cloud_kind)

                frame_path = panel_overlay_dir / f"frame_{frame_idx:04d}.png"
                img.save(frame_path)

        print("Cloud generation complete.")

    def _assign_character_positions(
        self,
        dialogue_lines: List[Dict],
        scene_img: np.ndarray,
    ) -> Dict[str, Tuple[int, int]]:
        """
        Use OpenCV edge detection to find low-detail regions for cloud placement.
        Assigns bubble positions for each speaking character.
        """
        h, w = scene_img.shape[:2]
        gray = cv2.cvtColor(scene_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # Get unique speakers
        speakers = []
        for dl in dialogue_lines:
            cname = dl.get("character", "Narrator")
            if cname not in speakers:
                speakers.append(cname)

        positions: Dict[str, Tuple[int, int]] = {}
        safe_margin = 40
        bubble_w = 420
        bubble_h = 120

        # Divide horizontal space among speakers
        num_speakers = max(len(speakers), 1)
        for idx, speaker in enumerate(speakers):
            # Assign horizontal zone
            zone_w = (w - 2 * safe_margin) // num_speakers
            zone_x_start = safe_margin + idx * zone_w
            zone_x_end = zone_x_start + zone_w

            # Search the UPPER portion of the frame (manga convention)
            search_top = safe_margin
            search_bottom = min(h // 3, h - safe_margin - bubble_h)

            best_score = float("inf")
            best_pos = (zone_x_start, search_top)

            # Sliding window: find the region with fewest edges
            step = 40
            for y in range(search_top, max(search_top + 1, search_bottom), step):
                for x in range(zone_x_start, max(zone_x_start + 1, zone_x_end - bubble_w), step):
                    x2 = min(x + bubble_w, w - safe_margin)
                    y2 = min(y + bubble_h, h - safe_margin)
                    roi = edges[y:y2, x:x2]
                    score = np.sum(roi)  # fewer edges = better

                    if score < best_score:
                        best_score = score
                        best_pos = (x, y)

            # Clamp final position
            bx = max(safe_margin, min(best_pos[0], w - safe_margin - bubble_w))
            by = max(safe_margin, min(best_pos[1], h - safe_margin - bubble_h))
            positions[speaker] = (bx, by)

        return positions

    def _draw_overlay_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        position: Tuple[int, int],
        font: ImageFont.FreeTypeFont,
        subtitle_style: Dict[str, Any],
        cloud_kind: str,
    ):
        """Draw cloud and subtitle text using shared buildpack styles."""
        pad = 20
        max_text_w = 380
        lines = self._wrap_text(text, font, draw, max_text_w)

        if not lines:
            return

        # Measure text block
        line_heights = []
        for line in lines:
            try:
                bbox = font.getbbox(line)
                line_heights.append(bbox[3] - bbox[1])
            except AttributeError:
                w_dim, h_dim = draw.textsize(line, font=font)
                line_heights.append(h_dim)

        total_h = sum(line_heights) + (len(lines) - 1) * 4
        try:
            max_w = max(font.getbbox(line)[2] - font.getbbox(line)[0] for line in lines)
        except AttributeError:
            max_w = max(draw.textsize(line, font=font)[0] for line in lines)

        bw = max_w + pad * 2
        bh = total_h + pad * 2


        bx1, by1 = position
        width, height = self.resolution

        # Clamp within frame
        if bx1 + bw > width - 40:
            bx1 = width - 40 - bw
        if bx1 < 40:
            bx1 = 40
        if by1 + bh > height - 40:
            by1 = height - 40 - bh
        if by1 < 40:
            by1 = 40

        bx2 = bx1 + bw
        by2 = by1 + bh

        if self.narration_mode != "subtitles_only" and cloud_kind != "none":
            _draw_cloud(draw, cloud_kind, (bx1, by1, bx2, by2))
            cy = by1 + pad
            for j, line in enumerate(lines):
                draw.text((bx1 + pad, cy), line, font=font, fill=(12, 18, 34, 255))
                cy += line_heights[j] + 4

        band_h = max(80, int(self.resolution[1] * 0.11))
        if subtitle_style.get("position") == "top":
            band = (0, 0, self.resolution[0], band_h)
            text_y = 14
        else:
            band = (0, self.resolution[1] - band_h, self.resolution[0], self.resolution[1])
            text_y = self.resolution[1] - band_h + 14
        draw.rectangle(band, fill=tuple(subtitle_style.get("band_fill", [0, 0, 0, 140])))

        summary = " ".join(lines)
        try:
            text_w = draw.textbbox((0, 0), summary, font=font)[2]
        except AttributeError:
            text_w = draw.textsize(summary, font=font)[0]
        text_x = max((self.resolution[0] - text_w) // 2, 24)
        draw.text(
            (text_x, text_y),
            summary,
            font=font,
            fill=tuple(subtitle_style.get("fill", [245, 245, 245])),
            stroke_width=int(subtitle_style.get("stroke_width", 2)),
            stroke_fill=tuple(subtitle_style.get("stroke", [0, 0, 0])),
        )

    def _wrap_text(self, text, font, draw, max_width):
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            test = " ".join(current_line)
            try:
                w = font.getbbox(test)[2] - font.getbbox(test)[0]
            except AttributeError:
                w, _ = draw.textsize(test, font=font)
            if w > max_width:
                if len(current_line) == 1:
                    lines.append(current_line[0])
                    current_line = []
                else:
                    current_line.pop()
                    lines.append(" ".join(current_line))
                    current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    def _load_font(self, size: int):
        return _load_font(self.font_style, size)
