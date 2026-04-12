"""
MovieMaker – FFmpeg-based video stitching for manga panels.

Each panel is rendered as: scene image + bottom subtitle bar + TTS audio.
No speech bubbles or cloud overlays — subtitles only.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from api.services.buildpacks import _load_font

_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def _get_font(font_style: str, size: int) -> ImageFont.FreeTypeFont:
    key = (font_style, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = _load_font(font_style, size)
    return _FONT_CACHE[key]


def _wrap_text(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    max_width: int,
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
    return lines or [""]


def _render_subtitle_frame(
    scene_path: Path,
    subtitle_text: str,
    resolution: Tuple[int, int],
    font_style: str = "font-geist-sans",
) -> Image.Image:
    """Render the scene image with a subtitle bar composited at the bottom."""
    w, h = resolution
    scene = Image.open(scene_path).convert("RGBA")
    if scene.size != (w, h):
        scene = scene.resize((w, h), Image.Resampling.LANCZOS)

    if not subtitle_text:
        return scene.convert("RGB")

    gradient_h = int(h * 0.24)
    gradient = Image.new("RGBA", (w, gradient_h), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    for y in range(gradient_h):
        alpha = int(215 * (gradient_h - y) / gradient_h)
        grad_draw.rectangle([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    scene.alpha_composite(gradient, (0, h - gradient_h))

    draw = ImageDraw.Draw(scene)
    font_size = max(24, int(h * 0.028))
    font = _get_font(font_style, font_size)

    pad_x = int(w * 0.06)
    max_text_w = w - pad_x * 2
    lines = _wrap_text(subtitle_text, draw, font, max_text_w)

    lh = font_size + 8
    total_text_h = len(lines) * lh
    base_y = h - int(h * 0.04) - total_text_h

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        tx = (w - tw) // 2
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 2), (0, -2), (-2, 0), (2, 0)]:
            draw.text((tx + dx, base_y + dy), line, font=font, fill=(0, 0, 0, 220))
        draw.text((tx, base_y), line, font=font, fill=(255, 255, 255, 255))
        base_y += lh

    return scene.convert("RGB")


def _make_subtitle_segment(
    panel_key: str,
    scene_path: Path,
    subtitle_text: str,
    audio_path: Path,
    session_dir: Path,
    resolution: Tuple[int, int],
    fps: int,
    audio_duration: float,
    font_style: str = "font-geist-sans",
) -> Optional[Path]:
    """Encode a single panel: rendered subtitle frame + TTS audio → MP4 segment."""
    frames_dir = session_dir / "frames" / panel_key
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    frame_path = frames_dir / "f_000.png"
    img = _render_subtitle_frame(scene_path, subtitle_text, resolution, font_style)
    img.save(str(frame_path))

    concat_path = frames_dir / "concat.txt"
    with open(concat_path, "w") as cf:
        cf.write("ffconcat version 1.0\n")
        cf.write(f"file '{frame_path.name}'\n")
        cf.write(f"duration {audio_duration:.4f}\n")
        cf.write(f"file '{frame_path.name}'\n")

    w, h = resolution
    seg_path = session_dir / f"seg_anim_{panel_key}.mp4"
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_path),
            "-i", str(audio_path),
            "-vf", f"fps={fps},scale={w}:{h}",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
            "-map", "0:v", "-map", "1:a",
            "-shortest",
            str(seg_path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"  Warning: subtitle segment failed for {panel_key}: {result.stderr[-300:]}")
        return None
    return seg_path


class MovieMaker:
    def __init__(
        self,
        fps: int = 24,
        resolution: Tuple[int, int] = (1280, 720),
        enable_music: bool = False,
        target_duration_seconds: int = 120,
        font_style: str = "font-geist-sans",
        subtitle_style: str = "sub-clean-bottom",
    ):
        self.fps = fps
        self.resolution = resolution
        self.enable_music = enable_music
        self.target_duration_seconds = target_duration_seconds
        self.font_style = font_style
        self.subtitle_style = subtitle_style

    def run(
        self,
        manga_board: Dict[str, Any],
        scenes_manifest: Dict[str, str],
        audio_files: List[str],
        session_dir: Path,
    ) -> Path:
        print("--- Pipeline: Movie Maker ---")
        frames_dir = session_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        scenes_dir = session_dir / "scenes"
        panels = manga_board.get("panels", [])
        w, h = self.resolution
        seg_paths: List[Path] = []

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"

            original_scene = scenes_dir / f"{panel_key}.png"
            scene_path_str = scenes_manifest.get(panel_key)
            if original_scene.exists():
                scene_path = original_scene
            elif scene_path_str and Path(scene_path_str).exists():
                scene_path = Path(scene_path_str)
            else:
                print(f"  No scene image for {panel_key}, skipping.")
                continue

            audio_path = None
            for af in audio_files:
                if panel_key in af:
                    audio_path = af
                    break

            if not audio_path or not Path(audio_path).exists():
                print(f"  No audio for {panel_key}, skipping.")
                continue

            try:
                res = subprocess.run(
                    [
                        "ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        audio_path,
                    ],
                    capture_output=True,
                    text=True,
                )
                duration = float(res.stdout.strip())
            except Exception:
                duration = panel.get("duration_seconds", 5.0)

            dialogue_lines: List[Dict[str, str]] = panel.get("dialogue", [])
            subtitle_text = "  /  ".join(
                f"{dl.get('character', 'Narrator')}: {dl.get('line', '').strip()}"
                for dl in dialogue_lines
                if dl.get("line", "").strip()
            )

            seg_path = session_dir / f"seg_{i:02d}.mp4"

            anim_seg = _make_subtitle_segment(
                panel_key=panel_key,
                scene_path=scene_path,
                subtitle_text=subtitle_text,
                audio_path=Path(audio_path),
                session_dir=session_dir,
                resolution=self.resolution,
                fps=self.fps,
                audio_duration=duration,
                font_style=self.font_style,
            )

            if anim_seg and anim_seg.exists():
                anim_seg.rename(seg_path)
            else:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", str(scene_path),
                        "-i", audio_path,
                        "-r", str(self.fps),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-t", str(duration),
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                        "-shortest",
                        str(seg_path),
                    ],
                    check=True,
                    capture_output=True,
                )

            print(f"  \u2713 Segment {panel_key} ({duration:.1f}s)")
            seg_paths.append(seg_path)

        if not seg_paths:
            print("No segments to concatenate.")
            return Path("")

        concat_file = session_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for sp in seg_paths:
                f.write(f"file '{sp.name}'\n")

        title = manga_board.get("episode_title", "OVA")
        safe_title = title.replace(" ", "_").replace(":", "").replace("'", "")
        ep_num = manga_board.get("episode_number", 1)
        final_name = f"Episode{ep_num}_{safe_title}.mp4"
        final_path = session_dir / final_name

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                "-pix_fmt", "yuv420p", "-r", str(self.fps),
                "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                str(final_path),
            ],
            check=True,
            capture_output=True,
        )

        if self.enable_music:
            music_dir = session_dir / "music"
            music_track = None
            if music_dir.exists() and music_dir.is_dir():
                tracks = sorted(
                    [p for p in music_dir.iterdir() if p.suffix.lower() in [".mp3", ".wav", ".aac"]]
                )
                if tracks:
                    music_track = tracks[0]

            if music_track:
                final_with_music = session_dir / f"{final_path.stem}_with_music{final_path.suffix}"
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(final_path),
                        "-stream_loop", "-1", "-i", str(music_track),
                        "-filter_complex",
                        "[1:a]volume=0.15[a2];[0:a][a2]amix=inputs=2:duration=first:dropout_transition=2",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                        "-shortest",
                        str(final_with_music),
                    ],
                    check=False,
                    capture_output=True,
                )
                if final_with_music.exists():
                    final_path = final_with_music
            else:
                print("Music enabled but no track found; exporting without music.")

        final_path = self._enforce_target_duration(final_path, session_dir)

        thumb_path = session_dir / "thumbnail.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(final_path), "-ss", "00:00:01.000", "-vframes", "1", str(thumb_path)],
            check=False,
            capture_output=True,
        )

        metadata = {
            "episode": manga_board.get("episode_number", 1),
            "title": manga_board.get("episode_title", "OVA"),
            "final_video": str(final_path),
            "thumbnail": str(thumb_path),
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "fps": self.fps,
            "music_attached": bool(self.enable_music and (session_dir / "music").exists()),
        }
        with open(session_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        print(f"Final video rendered: {final_path}")
        print(f"Thumbnail saved: {thumb_path}")
        print(f"Metadata saved: {session_dir / 'metadata.json'}")
        return final_path

    def _probe_duration(self, file_path: Path) -> float:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            return float((res.stdout or "0").strip())
        except Exception:
            return 0.0

    def _enforce_target_duration(self, final_path: Path, session_dir: Path) -> Path:
        current = self._probe_duration(final_path)
        target = float(self.target_duration_seconds)
        if current <= 0:
            print("Could not probe duration, skipping exact-duration pass.")
            return final_path

        if abs(current - target) <= 0.2:
            print(f"Duration already near target: {current:.2f}s")
            return final_path

        exact_path = session_dir / f"{final_path.stem}_exact120{final_path.suffix}"
        if current > target:
            print(f"Trimming video from {current:.2f}s to {target:.2f}s")
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(final_path),
                    "-t", str(target),
                    "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                    str(exact_path),
                ],
                check=True,
                capture_output=True,
            )
        else:
            pad = max(0.0, target - current)
            print(f"Padding video from {current:.2f}s to {target:.2f}s")
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(final_path),
                    "-filter_complex",
                    f"[0:v]tpad=stop_mode=clone:stop_duration={pad}[v];[0:a]apad=pad_dur={pad},atrim=0:{target}[a]",
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                    str(exact_path),
                ],
                check=True,
                capture_output=True,
            )

        return exact_path if exact_path.exists() else final_path
