"""
Cloud Generator – OpenCV-based speech bubble placement.

Uses Canny edge detection + sliding-window scoring to find the optimal
low-detail region near each speaking character's position. Places speech
bubbles accordingly. ZERO LLM calls – all local processing.

Produces: overlays/panel_XX/frame_XXXX.png (transparent PNGs)
"""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        project_name: str = "AutoAnimator",
        episode_number: int = 1,
        overlay_dir_name: str = "overlays",
        scenes_dir_name: str | None = None,
        audio_dir_name: str | None = None,
        cloud_style: str = "cloud-none",
        font_style: str = "font-geist-sans",
        subtitle_style: str = "sub-clean-bottom",
        narration_mode: str = "hybrid_subtitles_clouds",
        subtitle_scale: float = 1.0,
        subtitle_x: float | None = None,
        subtitle_y: float | None = None,
        cloud_x: float | None = None,
        cloud_y: float | None = None,
        cloud_w: float | None = None,
        cloud_h: float | None = None,
        log_prefix: str = "",
        use_panel_fps: bool = True,
        cloud_workers: int = 4,
    ):
        self.fps = fps
        self.resolution = resolution
        self.project_name = project_name or "AutoAnimator"
        self.episode_number = max(1, int(episode_number or 1))
        self.overlay_dir_name = (overlay_dir_name or "overlays").strip() or "overlays"
        default_episode_prefix = f"episodes/episode{self.episode_number}"
        self.scenes_dir_name = (scenes_dir_name or f"{default_episode_prefix}/scenes").strip()
        self.audio_dir_name = (audio_dir_name or f"{default_episode_prefix}/audio").strip()
        self.cloud_style = cloud_style
        self.font_style = font_style
        self.subtitle_style = subtitle_style
        self.narration_mode = narration_mode
        self.subtitle_scale = subtitle_scale
        self.subtitle_x = subtitle_x
        self.subtitle_y = subtitle_y
        self.cloud_x = cloud_x
        self.cloud_y = cloud_y
        self.cloud_w = cloud_w
        self.cloud_h = cloud_h
        self.log_prefix = (log_prefix or "").strip()
        self.use_panel_fps = bool(use_panel_fps)
        self.cloud_workers = max(1, int(cloud_workers or 4))

    def _log(self, message: str):
        prefix = f"{self.log_prefix} " if self.log_prefix else ""
        print(f"{prefix}{message}")

    @staticmethod
    def _audio_duration_seconds(path: Path) -> float:
        try:
            res = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return float((res.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0

    def run(self, manga_board: Dict[str, Any], session_dir: Path):
        self._log("--- Pipeline: Cloud Generation (OpenCV) ---")
        overlays_dir = session_dir / self.overlay_dir_name
        overlays_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = session_dir / self.scenes_dir_name
        audio_dir = session_dir / self.audio_dir_name

        # Compatibility fallback for older sessions.
        if not scenes_dir.exists():
            legacy_scenes_dir = session_dir / "scenes"
            if legacy_scenes_dir.exists():
                scenes_dir = legacy_scenes_dir
        if not audio_dir.exists():
            legacy_audio_dir = session_dir / "audio"
            if legacy_audio_dir.exists():
                audio_dir = legacy_audio_dir

        panels = manga_board.get("panels", [])

        base_dim = max(540, min(self.resolution[0], self.resolution[1]))
        font_size = max(20, int(base_dim * 0.032 * max(0.5, self.subtitle_scale)))
        font = _load_font(self.font_style, font_size)
        sub_style = _resolve_subtitle_style(self.subtitle_style)
        cloud_kind = _resolve_cloud_kind(self.cloud_style)

        worker_count = min(self.cloud_workers, max(1, len(panels)))
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                futures = [
                    pool.submit(
                        self._process_panel_overlays,
                        i, panel, overlays_dir, scenes_dir, audio_dir, font, sub_style, cloud_kind,
                    )
                    for i, panel in enumerate(panels)
                ]
                for f in as_completed(futures):
                    f.result()
        else:
            for i, panel in enumerate(panels):
                self._process_panel_overlays(i, panel, overlays_dir, scenes_dir, audio_dir, font, sub_style, cloud_kind)

        self._log("Cloud generation complete.")

    def _process_panel_overlays(
        self,
        i: int,
        panel: Dict[str, Any],
        overlays_dir: Path,
        scenes_dir: Path,
        audio_dir: Path,
        font: Any,
        sub_style: Dict[str, Any],
        cloud_kind: str,
    ) -> None:
        panel_key = f"panel_{i:02d}"
        timing_path = audio_dir / f"{panel_key}_timing.json"
        scene_path = scenes_dir / f"{panel_key}.png"

        if not timing_path.exists():
            self._log(f"No timing for {panel_key}, skipping clouds.")
            return

        with open(timing_path, "r") as f:
            timings = json.load(f)

        if not timings:
            return

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
        total_sec_timing = (last_t["offset"] + last_t["duration"]) / 10_000_000.0
        audio_path = audio_dir / f"{panel_key}.mp3"
        if not audio_path.exists():
            wav_path = audio_dir / f"{panel_key}.wav"
            audio_path = wav_path if wav_path.exists() else audio_path
        total_sec_audio = self._audio_duration_seconds(audio_path) if audio_path.exists() else 0.0
        total_sec = max(total_sec_timing, total_sec_audio)
        panel_fps = max(8, int(panel.get("fps", self.fps) or self.fps)) if self.use_panel_fps else max(8, int(self.fps))
        total_frames = max(1, int(np.ceil(total_sec * panel_fps)) + 2)

        panel_overlay_dir = overlays_dir / panel_key
        panel_overlay_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"Generating {total_frames} cloud frames for {panel_key} at {panel_fps} fps")

        # Sync offset (200_000 units = 20ms advance)
        SYNC_OFFSET = 200_000
        timing_idx = 0
        char_words: Dict[str, List[str]] = {}
        active_char = None

        for frame_idx in range(total_frames):
            current_time_sec = frame_idx / panel_fps
            current_time_units = (current_time_sec * 10_000_000) + SYNC_OFFSET

            # Incrementally consume timing entries up to current frame time.
            while timing_idx < len(timings) and timings[timing_idx]["offset"] <= current_time_units:
                t = timings[timing_idx]
                cname = t.get("character", "Unknown")
                active_char = cname
                if cname not in char_words:
                    char_words[cname] = []
                char_words[cname].append(t.get("text", ""))
                timing_idx += 1

            # Create transparent overlay
            img = Image.new("RGBA", self.resolution, (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            if i == 0 and frame_idx == 0:
                title = f"{self.project_name} - Episode {self.episode_number}"
                self._draw_title_overlay(draw, title, font)

            # Show currently speaking text with the same styles used by buildpack preview.
            if active_char and active_char in char_words:
                words = char_words[active_char][-15:]  # last 15 chunks
                text = " ".join(words)
                self._draw_overlay_text(
                    draw,
                    text,
                    char_positions.get(active_char, (100, 50)),
                    font,
                    sub_style,
                    cloud_kind,
                    speaker_name=active_char,
                )

            frame_path = panel_overlay_dir / f"frame_{frame_idx:04d}.png"
            img.save(frame_path)

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
            cname = dl.get("character", "Speaker")
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
        speaker_name: str | None = None,
    ):
        """Draw cloud and subtitle text using shared buildpack styles."""
        speaker = str(speaker_name or "Narrator").strip() or "Narrator"
        speaker_line = f"{speaker}:"
        pad = 20
        max_text_w = 380
        spoken_lines = self._wrap_text(text, font, draw, max_text_w)
        lines = [speaker_line] + spoken_lines

        if not lines:
            return

        # Measure text block
        line_heights = [self._text_height(draw, font, line) for line in lines]

        total_h = sum(line_heights) + (len(lines) - 1) * 4
        max_w = max(self._text_width(draw, font, line) for line in lines)

        bw = max_w + pad * 2
        bh = total_h + pad * 2


        bx1, by1 = position
        width, height = self.resolution

        # BuildPack-configured cloud placement overrides auto-computed positions.
        if self.cloud_x is not None:
            bx1 = int(width * max(0.0, min(float(self.cloud_x), 0.95)))
        if self.cloud_y is not None:
            by1 = int(height * max(0.0, min(float(self.cloud_y), 0.95)))
        if self.cloud_w is not None:
            bw = int(width * max(0.12, min(float(self.cloud_w), 0.9)))
            bx2 = bx1 + bw
        if self.cloud_h is not None:
            bh = int(height * max(0.08, min(float(self.cloud_h), 0.75)))
            by2 = by1 + bh

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

        # Subtitle region follows BuildPack layout points and clamps to resolution.
        width, height = self.resolution
        side_margin = max(24, int(width * 0.06))
        subtitle_x_norm = max(0.0, min(float(self.subtitle_x) if self.subtitle_x is not None else 0.06, 0.95))
        subtitle_x_px = int(width * subtitle_x_norm)
        band_pad_x = max(20, int(width * 0.03))
        band_pad_y = max(10, int(height * 0.008))
        subtitle_max_width = max(160, width - subtitle_x_px - side_margin - (2 * band_pad_x))

        # Never collapse subtitles into a tiny corner box. Keep a wide bracket region,
        # especially on Shorts, then place text within that region.
        min_region_ratio = 0.72 if height > width else 0.58
        min_region_width = int(width * min_region_ratio)
        if subtitle_max_width < min_region_width:
            subtitle_x_px = side_margin + band_pad_x
            subtitle_max_width = max(220, width - (2 * side_margin) - (2 * band_pad_x))

        subtitle_body_lines = self._wrap_text(text, font, draw, subtitle_max_width)
        subtitle_lines = [speaker_line] + subtitle_body_lines
        if not subtitle_lines:
            return

        # Keep subtitle blocks compact while always preserving speaker identity.
        max_subtitle_lines = 3
        max_body_lines = max(1, max_subtitle_lines - 1)
        body_lines = subtitle_lines[1:]
        if len(body_lines) > max_body_lines:
            body_lines = body_lines[:max_body_lines]
            body_lines[-1] = body_lines[-1].rstrip() + "..."
        subtitle_lines = [subtitle_lines[0]] + body_lines

        subtitle_line_heights = [self._text_height(draw, font, line) for line in subtitle_lines]
        subtitle_text_h = sum(subtitle_line_heights) + max(0, (len(subtitle_lines) - 1) * 4)
        band_h = max(int(height * 0.11), subtitle_text_h + (2 * band_pad_y))

        # Keep subtitle bracket area stable and wide across aspect ratios.
        band_x1 = side_margin
        band_x2 = width - side_margin
        subtitle_x_px = max(band_x1 + band_pad_x, min(subtitle_x_px, band_x2 - band_pad_x - 40))

        if self.subtitle_y is not None:
            band_y1 = int(height * max(0.0, min(float(self.subtitle_y), 0.95))) - band_pad_y
            band_y1 = max(0, min(height - band_h, band_y1))
        else:
            subtitle_position = str(subtitle_style.get("position", "bottom"))
            if subtitle_position == "top":
                band_y1 = max(10, int(height * 0.02))
            else:
                band_y1 = height - band_h - max(12, int(height * 0.02))
        band_y2 = band_y1 + band_h

        band = (band_x1, band_y1, band_x2, band_y2)
        if hasattr(draw, "rounded_rectangle"):
            draw.rounded_rectangle(band, radius=max(12, int(height * 0.01)), fill=tuple(subtitle_style.get("band_fill", [0, 0, 0, 140])))
        else:
            draw.rectangle(band, fill=tuple(subtitle_style.get("band_fill", [0, 0, 0, 140])))

        text_y = band_y1 + band_pad_y
        for idx, line in enumerate(subtitle_lines):
            text_w = self._text_width(draw, font, line)
            text_x = max(band_x1 + band_pad_x, min(subtitle_x_px, band_x2 - band_pad_x - text_w))
            draw.text(
                (text_x, text_y),
                line,
                font=font,
                fill=tuple(subtitle_style.get("fill", [245, 245, 245])),
                stroke_width=int(subtitle_style.get("stroke_width", 2)),
                stroke_fill=tuple(subtitle_style.get("stroke", [0, 0, 0])),
            )
            text_y += subtitle_line_heights[idx] + 4

    def _draw_title_overlay(self, draw: ImageDraw.ImageDraw, title: str, font: ImageFont.FreeTypeFont):
        width, height = self.resolution
        pad_x = max(16, int(width * 0.02))
        pad_y = max(10, int(height * 0.015))
        text_w = self._text_width(draw, font, title)
        text_h = self._text_height(draw, font, title)
        box = (
            pad_x,
            pad_y,
            min(width - pad_x, pad_x + text_w + 24),
            pad_y + text_h + 16,
        )
        fill = (0, 0, 0, 140)
        if hasattr(draw, "rounded_rectangle"):
            draw.rounded_rectangle(box, radius=10, fill=fill)
        else:
            draw.rectangle(box, fill=fill)
        draw.text((pad_x + 12, pad_y + 8), title, font=font, fill=(240, 240, 240, 255))

    def _text_width(self, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, text: str) -> int:
        try:
            return max(0, font.getbbox(text)[2] - font.getbbox(text)[0])
        except AttributeError:
            return draw.textsize(text, font=font)[0]

    def _text_height(self, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, text: str) -> int:
        try:
            return max(0, font.getbbox(text)[3] - font.getbbox(text)[1])
        except AttributeError:
            return draw.textsize(text, font=font)[1]

    def _wrap_text(self, text, font, draw, max_width):
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            test = " ".join(current_line)
            w = self._text_width(draw, font, test)
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
