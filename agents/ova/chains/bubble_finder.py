"""BubbleFinder – vision LLM identifies speech bubble placement coords.

Given a scene image and dialogue lines, a lightweight vision LLM returns
optimal regions (as percentage of image dimensions) where speech bubbles
should be placed — avoiding character faces and using available empty space.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.ova.utils import get_model
from agents.ova.usage_tracker import OVALLMTracker, llm_call


class BubbleFinder:
    def __init__(
        self,
        model_name: str = "models/gemini-flash-latest",
        tracker: Optional[OVALLMTracker] = None,
    ):
        self.model_name = model_name
        self.tracker = tracker

    def locate(
        self,
        image_path: Path,
        dialogue_lines: List[Dict[str, str]],
        width: int,
        height: int,
        panel_cloud_style: str = "speech",
    ) -> List[Dict[str, Any]]:
        """Return speech bubble placement coords for up to 2 characters.

        Returns list of:
            {"character": str, "x": int, "y": int, "w": int, "h": int, "cloud_style": str}
        All coords are absolute pixels.  Falls back to heuristic positions on LLM error.
        """
        if not image_path.exists() or not dialogue_lines:
            return []

        # Collect up to 2 unique speakers
        unique_chars: List[str] = []
        for dl in dialogue_lines:
            c = dl.get("character", "")
            if c and c not in unique_chars:
                unique_chars.append(c)
        unique_chars = unique_chars[:2]

        if not unique_chars:
            return []

        chars_json = json.dumps([{"character": c} for c in unique_chars])
        prompt = (
            f"This is a manga/comic panel image ({width}x{height} pixels).\n"
            f"I need to overlay speech bubbles for these characters: {chars_json}\n\n"
            "For each character find the BEST empty region in this image to place a speech bubble so that:\n"
            "1. It does NOT cover the character's face or important action\n"
            "2. It sits inside image bounds with at least 10px clearance from edges\n"
            "3. It prefers the upper 60% of the image (manga convention)\n"
            "4. It uses available sky/background/empty space\n\n"
            "Return ONLY a JSON array — no extra text:\n"
            "[\n"
            "  {\n"
            "    \"character\": \"Name\",\n"
            "    \"x_pct\": 0.05,\n"
            "    \"y_pct\": 0.03,\n"
            "    \"w_pct\": 0.28,\n"
            "    \"h_pct\": 0.17,\n"
            f"    \"cloud_style\": \"{panel_cloud_style}\"\n"
            "  }\n"
            "]\n"
            "x_pct/y_pct = top-left corner as fraction of image width/height.\n"
            "w_pct/h_pct = bubble size as fraction. Minimum w_pct=0.18, h_pct=0.10."
        )

        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except OSError as e:
            print(f"  BubbleFinder: cannot read image: {e}")
            return self._fallback(unique_chars, width, height, panel_cloud_style)

        model = get_model(self.model_name)
        try:
            response = llm_call(
                self.tracker,
                model,
                [{"mime_type": "image/png", "data": image_bytes}, prompt],
                purpose="bubble_finder",
            )
            text = response.text or ""
        except Exception as e:
            print(f"  BubbleFinder LLM error: {e}")
            return self._fallback(unique_chars, width, height, panel_cloud_style)

        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if not match:
            print("  BubbleFinder: no JSON array in response, using fallback")
            return self._fallback(unique_chars, width, height, panel_cloud_style)

        try:
            raw = json.loads(match.group(0))
        except json.JSONDecodeError:
            return self._fallback(unique_chars, width, height, panel_cloud_style)

        result: List[Dict[str, Any]] = []
        for item in raw:
            x = max(10, int(float(item.get("x_pct", 0.05)) * width))
            y = max(10, int(float(item.get("y_pct", 0.03)) * height))
            w = max(120, int(float(item.get("w_pct", 0.25)) * width))
            h = max(80, int(float(item.get("h_pct", 0.15)) * height))
            # Clamp to image bounds
            w = min(w, width - x - 10)
            h = min(h, height - y - 10)
            result.append({
                "character": item.get("character", "Unknown"),
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "cloud_style": item.get("cloud_style", panel_cloud_style),
            })

        if not result:
            return self._fallback(unique_chars, width, height, panel_cloud_style)
        return result

    def _fallback(
        self,
        chars: List[str],
        width: int,
        height: int,
        style: str,
    ) -> List[Dict[str, Any]]:
        """Evenly distribute bubbles across the top of the image."""
        w_b = min(int(width * 0.28), 420)
        h_b = min(int(height * 0.17), 150)
        n = len(chars)
        result = []
        for i, char in enumerate(chars):
            x = int(width * (0.05 + 0.45 * i / max(1, n - 0.5)))
            result.append({"character": char, "x": max(10, x), "y": 20, "w": w_b, "h": h_b, "cloud_style": style})
        return result
