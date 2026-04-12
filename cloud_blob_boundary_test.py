#!/usr/bin/env python3
"""Detect closed manga cloud blobs and patch-fill detected cloud interiors.

This script follows a strict heuristic:
1. Build a binary white-region mask from RGB/HSV thresholds.
2. Find closed contours from the binary mask.
3. Keep contours where:
   - Inner boundary is mostly white.
   - Outer boundary is mostly dark.
4. Export boundary coordinates and debug renders.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

# Allow importing from the project root.
sys.path.insert(0, str(Path(__file__).parent))

from agents.ova.chains.cloud_gen import CloudGen  # noqa: E402  (after sys.path fix)
from api.services.buildpacks import _load_font  # noqa: E402

# User-requested test inputs.
DEFAULT_IMAGES = [
    Path("/home/rtj/Krsna/CMiner/outputs/5786188/ova/scenes/panel_01.png"),
    Path("/home/rtj/Krsna/CMiner/outputs/5786188/ova/scenes/panel_07.png"),
    Path("/home/rtj/Krsna/CMiner/outputs/5786188/ova/scenes/panel_13.png"),
]


def build_white_binary(image_bgr: np.ndarray) -> np.ndarray:
    """Threshold likely cloud-white pixels into a binary mask."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # White in HSV: low saturation + high value.
    hsv_white = cv2.inRange(hsv, np.array([0, 0, 175], dtype=np.uint8), np.array([180, 70, 255], dtype=np.uint8))

    # White in RGB/BGR: all channels relatively high.
    bgr_white = cv2.inRange(image_bgr, np.array([185, 185, 185], dtype=np.uint8), np.array([255, 255, 255], dtype=np.uint8))

    white = cv2.bitwise_and(hsv_white, bgr_white)

    # Morphological smoothing to merge cloud interiors and remove speckles.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    white = cv2.morphologyEx(white, cv2.MORPH_CLOSE, k, iterations=2)
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, k, iterations=1)
    return white


def _ratio(mask: np.ndarray, cond: np.ndarray) -> float:
    idx = mask > 0
    if not np.any(idx):
        return 0.0
    return float(np.mean(cond[idx]))


def classify_cloud(contour: np.ndarray) -> str:
    """Return 'regular' or 'distorted' based on shape compactness metrics.

    Circularity: 4π·area / perimeter²  (1.0 = perfect circle; jagged blobs → 0)
    Solidity:    area / convex_hull_area (fragmented / concave blobs → 0)
    A cloud is 'regular' when both values meet their thresholds.
    """
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    circularity = (4.0 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0.0

    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    solidity = (area / hull_area) if hull_area > 0 else 0.0

    is_regular = circularity >= 0.20 and solidity >= 0.60
    return "regular" if is_regular else "distorted"


def detect_cloud_contours(image_bgr: np.ndarray, white_mask: np.ndarray) -> list[tuple[np.ndarray, str]]:
    """Find cloud-like closed contours using inner-white and outer-dark checks.
    Returns list of (contour, label) where label is 'regular' or 'distorted'.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    img_area = float(h * w)

    contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    accepted: list[np.ndarray] = []
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 1200 or area > img_area * 0.5:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter < 120:
            continue

        x, y, cw, ch = cv2.boundingRect(contour)
        aspect = cw / max(1.0, float(ch))
        if aspect < 0.6 or aspect > 6.0:
            continue

        filled = np.zeros_like(gray, dtype=np.uint8)
        cv2.drawContours(filled, [contour], -1, 255, thickness=cv2.FILLED)

        # Inner boundary ring: near contour but still inside.
        eroded = cv2.erode(filled, k, iterations=2)
        inner_ring = cv2.subtract(filled, eroded)

        # Outer boundary ring: immediately outside contour.
        dilated = cv2.dilate(filled, k, iterations=2)
        outer_ring = cv2.subtract(dilated, filled)

        inner_white_ratio = _ratio(inner_ring, white_mask > 0)
        outer_dark_ratio = _ratio(outer_ring, gray < 120)

        # Heuristic criteria from user spec.
        if inner_white_ratio < 0.60:
            continue
        if outer_dark_ratio < 0.25:
            continue

        accepted.append(contour)

    # Keep only the largest 2 clouds.
    accepted.sort(key=cv2.contourArea, reverse=True)
    return [(c, classify_cloud(c)) for c in accepted[:2]]


def render_outputs(image_path: Path, output_dir: Path) -> tuple[Path, list[str]]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read image: {image_path}")

    white_mask = build_white_binary(image)
    results = detect_cloud_contours(image, white_mask)

    cloud_only = np.zeros_like(white_mask)
    labels: list[str] = []
    for contour, label in results:
        cv2.drawContours(cloud_only, [contour], -1, 255, thickness=cv2.FILLED)
        labels.append(label)

    cloud_only_path = output_dir / f"{image_path.stem}_cloud_only_mask.png"
    cv2.imwrite(str(cloud_only_path), cloud_only)
    return cloud_only_path, labels


# Sample dialogue lines – one per cloud slot.
_SAMPLE_LINES = [
    "What prompt did you use for this scene?",
    "The Weaver of Realities begins now!",
    "Brahma judges your creativity!",
]


def render_text_in_clouds(image_path: Path, output_dir: Path) -> Path:
    """Detect top-2 clouds and patch sample text into them using OVA CloudGen."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(f"Could not read: {image_path}")

    white_mask = build_white_binary(image)
    results = detect_cloud_contours(image, white_mask)

    # Convert to PIL RGBA for text compositing.
    pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGBA))
    overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    cg = CloudGen(fps=24, resolution=(pil_img.width, pil_img.height))
    font = _load_font("font-geist-sans", 28)

    for idx, (contour, label) in enumerate(results):
        x, y, cw, ch = cv2.boundingRect(contour)
        text = _SAMPLE_LINES[idx % len(_SAMPLE_LINES)]

        # Draw text directly into the cloud — no background box.
        max_w = max(80, cw - 24)
        lines = cg._wrap_text(text, draw, font, max_w)
        line_h = cg._line_height(draw, font)
        total_h = len(lines) * (line_h + 3) - 3
        ty = y + max(8, (ch - total_h) // 2)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            tx = x + max(8, (cw - tw) // 2)
            # Thin white halo for readability, then dark text on top.
            for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
                draw.text((tx + dx, ty + dy), line, font=font, fill=(255, 255, 255, 200))
            draw.text((tx, ty), line, font=font, fill=(15, 15, 15, 255))
            ty += line_h + 3

    composited = Image.alpha_composite(pil_img, overlay).convert("RGB")
    out_path = output_dir / f"{image_path.stem}_text_rendered.png"
    composited.save(str(out_path))
    return out_path


def main() -> None:
    output_dir = Path("/home/rtj/Krsna/CMiner")

    print("Running cloud boundary detection test...")
    for path in DEFAULT_IMAGES:
        out, labels = render_outputs(path, output_dir)
        label_str = ", ".join(f"cloud{i+1}={l}" for i, l in enumerate(labels)) if labels else "no clouds"
        print(f"Input: {path.name}  ->  {out.name}  [{label_str}]")
        text_out = render_text_in_clouds(path, output_dir)
        print(f"  text rendered: {text_out.name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
