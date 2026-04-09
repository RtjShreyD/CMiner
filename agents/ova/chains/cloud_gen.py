"""OVA cloud patcher.

Detects pre-generated speech bubbles in scene images and overlays script text into the
same regions. This avoids relying on model-generated cloud text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from api.services.buildpacks import _load_font


class CloudGen:
    def __init__(
        self,
        fps: int = 8,
        resolution: Tuple[int, int] = (1280, 720),
        cloud_style: str = "cloud-none",
        font_style: str = "font-geist-sans",
        subtitle_style: str = "sub-clean-bottom",
        narration_mode: str = "hybrid_subtitles_clouds",
        subtitle_scale: float = 1.0,
    ):
        self.fps = fps
        self.resolution = resolution
        self.font_style = font_style
        self.subtitle_scale = subtitle_scale

    def run(self, manga_board: Dict[str, Any], session_dir: Path):
        print("--- Pipeline: OVA Cloud Detection + Patch ---")
        overlays_dir = session_dir / "overlays"
        overlays_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = session_dir / "scenes"
        audio_dir = session_dir / "audio"

        font_size = max(18, int(34 * max(0.5, self.subtitle_scale)))
        font = _load_font(self.font_style, font_size)

        for i, panel in enumerate(manga_board.get("panels", [])):
            panel_key = f"panel_{i:02d}"
            scene_path = scenes_dir / f"{panel_key}.png"
            timing_path = audio_dir / f"{panel_key}_timing.json"

            if not scene_path.exists() or not timing_path.exists():
                print(f"Skipping {panel_key}: missing scene or timing")
                continue

            timings = json.loads(timing_path.read_text())
            if not timings:
                print(f"Skipping {panel_key}: empty timing")
                continue

            scene_img = cv2.imread(str(scene_path))
            if scene_img is None:
                print(f"Skipping {panel_key}: unreadable image")
                continue

            h, w = scene_img.shape[:2]
            if (w, h) != self.resolution:
                scene_img = cv2.resize(scene_img, self.resolution)

            speech_clouds = self._detect_speech_clouds(scene_img)
            if not speech_clouds:
                speech_clouds = [
                    (40, 40, min(520, self.resolution[0] - 40), min(220, self.resolution[1] // 3))
                ]

            total_units = timings[-1]["offset"] + timings[-1]["duration"]
            total_sec = total_units / 10_000_000.0
            total_frames = max(1, int(total_sec * self.fps) + 5)

            panel_overlay_dir = overlays_dir / panel_key
            panel_overlay_dir.mkdir(parents=True, exist_ok=True)

            for frame_idx in range(total_frames):
                current_units = int((frame_idx / self.fps) * 10_000_000 + 200_000)
                active_text = self._text_until(timings, current_units)

                overlay = Image.new("RGBA", self.resolution, (0, 0, 0, 0))
                draw = ImageDraw.Draw(overlay)

                if active_text:
                    target = speech_clouds[min(frame_idx // max(1, total_frames // len(speech_clouds)), len(speech_clouds) - 1)]
                    self._patch_text(draw, active_text, target, font)

                frame_path = panel_overlay_dir / f"frame_{frame_idx:04d}.png"
                overlay.save(frame_path)

            print(f"Patched speech clouds for {panel_key}: {len(speech_clouds)} regions")

    def _detect_speech_clouds(self, image_bgr: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Find likely speech bubbles (bright enclosed regions) in upper/mid frame."""
        height, width = image_bgr.shape[:2]
        hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

        # Target bright low-saturation regions (typical white speech bubbles)
        lower = np.array([0, 0, 160], dtype=np.uint8)
        upper = np.array([180, 90, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)

        # Keep only likely closed bubble bodies.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: List[Tuple[int, int, int, int, float]] = []

        for c in contours:
            area = cv2.contourArea(c)
            if area < 2500:
                continue
            x, y, w, h = cv2.boundingRect(c)
            if w < 120 or h < 60:
                continue
            if y > int(height * 0.75):
                continue

            rect_area = float(w * h)
            fill_ratio = area / max(1.0, rect_area)
            if fill_ratio < 0.35 or fill_ratio > 0.95:
                continue

            aspect = w / max(1, h)
            if aspect < 1.1 or aspect > 4.5:
                continue

            # Prioritize upper frame and bigger clouds.
            score = area - (y * 12)
            candidates.append((x, y, x + w, y + h, score))

        candidates.sort(key=lambda c: c[4], reverse=True)
        boxes = [self._expand_box((x1, y1, x2, y2), width, height, pad=8) for x1, y1, x2, y2, _ in candidates[:4]]
        return boxes

    @staticmethod
    def _expand_box(box: Tuple[int, int, int, int], width: int, height: int, pad: int = 8) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
        return (
            max(10, x1 - pad),
            max(10, y1 - pad),
            min(width - 10, x2 + pad),
            min(height - 10, y2 + pad),
        )

    @staticmethod
    def _text_until(timings: List[Dict[str, Any]], current_units: int) -> str:
        words = [t.get("text", "") for t in timings if int(t.get("offset", 0)) <= current_units]
        joined = " ".join(w for w in words if w).strip()
        if not joined:
            return ""
        chunks = joined.split()
        return " ".join(chunks[-18:])

    def _patch_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        box: Tuple[int, int, int, int],
        font,
    ):
        x1, y1, x2, y2 = box
        draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=(255, 255, 255, 235), outline=(20, 20, 20, 255), width=3)

        max_width = max(80, (x2 - x1) - 26)
        lines = self._wrap_text(text, draw, font, max_width)

        line_h = self._line_height(draw, font)
        total_h = max(line_h, len(lines) * (line_h + 3) - 3)
        ty = y1 + max(12, ((y2 - y1) - total_h) // 2)

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            tx = x1 + max(12, ((x2 - x1) - tw) // 2)
            draw.text((tx, ty), line, font=font, fill=(22, 22, 22, 255))
            ty += line_h + 3

    @staticmethod
    def _line_height(draw: ImageDraw.ImageDraw, font) -> int:
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        return max(14, bbox[3] - bbox[1])

    def _wrap_text(self, text: str, draw: ImageDraw.ImageDraw, font, max_width: int) -> List[str]:
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

        return lines[:5]
