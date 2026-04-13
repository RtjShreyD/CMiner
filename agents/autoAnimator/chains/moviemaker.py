"""
MovieMaker – FFmpeg-based video stitching for manga panels.

Reads render_strategy from storyboard for transitions.
Composites scene images + text cloud overlays + audio per panel.
"""

import json
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, List, Tuple

from PIL import Image


class MovieMaker:
    def __init__(
        self,
        fps: int = 24,
        resolution: Tuple[int, int] = (1280, 720),
        enable_music: bool = False,
        segment_workers: int = 1,
        use_panel_fps: bool = True,
    ):
        self.fps = fps
        self.resolution = resolution
        self.enable_music = enable_music
        self.segment_workers = max(1, int(segment_workers or 1))
        self.use_panel_fps = bool(use_panel_fps)

    def _variant_dir_name(self, output_suffix: str) -> str:
        key = (output_suffix or "").strip().lower()
        if key == "youtube_shorts":
            return "shorts"
        return "youtube_full"

    @staticmethod
    def _audio_duration_seconds(audio_path: str) -> float:
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
            return float((res.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _video_duration_seconds(video_path: Path) -> float:
        try:
            res = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
            )
            return float((res.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0

    def _enforce_final_duration_cap(self, video_path: Path, max_duration_seconds: float) -> Path:
        if max_duration_seconds <= 0 or not video_path.exists():
            return video_path
        actual = self._video_duration_seconds(video_path)
        if actual <= (max_duration_seconds + 0.15):
            return video_path

        trimmed_path = video_path.with_name(f"{video_path.stem}_capped{video_path.suffix}")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-t", str(max_duration_seconds),
                "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                str(trimmed_path),
            ],
            check=False,
            capture_output=True,
        )
        if trimmed_path.exists() and trimmed_path.stat().st_size > 0:
            video_path.unlink(missing_ok=True)
            trimmed_path.replace(video_path)
            return video_path
        return video_path

    def _render_segment(
        self,
        *,
        panel_idx: int,
        panel_key: str,
        scene_path: str,
        audio_path: str | None,
        duration: float,
        panel_fps: int,
        session_dir: Path,
        overlay_dir_name: str,
        output_suffix: str,
        render_dir: Path,
    ) -> tuple[int, Path, float, int, str]:
        w, h = self.resolution
        seg_path = render_dir / f"seg_{panel_idx:02d}.mp4"
        overlay_dir = session_dir / overlay_dir_name / panel_key

        has_overlay = overlay_dir.exists() and any(overlay_dir.iterdir())
        has_audio = bool(audio_path and Path(audio_path).exists())

        if has_overlay:
            # Composite: scene + overlays + (audio or silent track)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(scene_path),
                "-framerate", str(panel_fps), "-i", f"{overlay_dir}/frame_%04d.png",
            ]
            if has_audio:
                cmd.extend(["-i", str(audio_path)])
            else:
                cmd.extend(["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            cmd.extend(
                [
                    "-filter_complex",
                    f"[0:v]scale={w}:{h}[bg];[bg][1:v]overlay=shortest=1,format=yuv420p",
                    "-r", str(self.fps), "-c:v", "libx264", "-c:a", "aac", "-shortest",
                    str(seg_path),
                ]
            )
            subprocess.run(cmd, check=True, capture_output=True)
        else:
            # No overlays: scene + (audio or silent track)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(scene_path),
            ]
            if has_audio:
                cmd.extend(["-i", str(audio_path)])
            else:
                cmd.extend(["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            cmd.extend(
                [
                    "-r", str(self.fps), "-c:v", "libx264", "-t", str(duration),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(seg_path),
                ]
            )
            subprocess.run(cmd, check=True, capture_output=True)

        return panel_idx, seg_path, duration, panel_fps, panel_key

    @staticmethod
    def _is_usable_scene_image(scene_path: Path) -> bool:
        try:
            if not scene_path.exists() or scene_path.stat().st_size < 1024:
                return False
            with Image.open(scene_path) as img:
                rgb = img.convert("RGB")
                extrema = rgb.getextrema()
                if all((mx - mn) < 8 for mn, mx in extrema):
                    return False
                gray = rgb.convert("L").resize((192, 192), Image.Resampling.BILINEAR)
                hist = gray.histogram()
                total = float(sum(hist) or 1)
                dark_ratio = float(sum(hist[:12])) / total
                bright_ratio = float(sum(hist[245:])) / total
                if dark_ratio > 0.995 and bright_ratio < 0.0005:
                    return False
            return True
        except Exception:
            return False

    def run(
        self,
        manga_board: Dict[str, Any],
        scenes_manifest: Dict[str, str],
        audio_files: List[str],
        session_dir: Path,
        project_name: str = "AutoAnimator",
        output_suffix: str = "",
        overlay_dir_name: str = "overlays",
        output_dir_name: str | None = None,
        max_duration_seconds: float | None = None,
    ) -> Path:
        variant_label = self._variant_dir_name(output_suffix)
        print(f"--- Pipeline: Movie Maker [{variant_label}] ---")
        frames_dir = session_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        ep_num = manga_board.get("episode_number", 1)
        if output_dir_name:
            variant_dir = session_dir / output_dir_name
        else:
            variant_dir = session_dir / "episodes" / f"episode{ep_num}" / self._variant_dir_name(output_suffix)
        variant_dir.parent.mkdir(parents=True, exist_ok=True)
        if variant_dir.exists():
            for old_file in variant_dir.glob('seg_*.mp4'):
                old_file.unlink(missing_ok=True)
            old_concat = variant_dir / 'concat.txt'
            old_concat.unlink(missing_ok=True)
        variant_dir.mkdir(parents=True, exist_ok=True)

        panels = manga_board.get("panels", [])
        render_strategy = manga_board.get("render_strategy", {})
        transition = render_strategy.get("transition_type", "cut")
        episode_audio_dir = session_dir / "episodes" / f"episode{ep_num}" / "audio"
        if not episode_audio_dir.exists():
            episode_audio_dir = session_dir / "audio"

        w, h = self.resolution
        seg_paths: List[Path] = []
        audio_map: Dict[str, str] = {}
        for af in audio_files:
            stem = Path(af).stem
            if stem.startswith("panel_"):
                audio_map[stem] = af

        segment_jobs: List[dict[str, Any]] = []
        last_good_scene_path: str | None = None
        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            scene_path = scenes_manifest.get(panel_key)
            panel_fps = max(8, int(panel.get("fps", self.fps) or self.fps)) if self.use_panel_fps else max(8, int(self.fps))
            panel_duration = max(2.0, float(panel.get("duration_seconds", 4.0) or 4.0))

            if not scene_path or not Path(scene_path).exists() or not self._is_usable_scene_image(Path(scene_path)):
                if last_good_scene_path and Path(last_good_scene_path).exists():
                    print(f"  Invalid/missing scene for {panel_key}; reusing previous valid scene.")
                    scene_path = last_good_scene_path
                else:
                    print(f"  No usable scene image for {panel_key}, skipping.")
                    continue
            else:
                last_good_scene_path = scene_path

            # Find matching audio
            audio_path = audio_map.get(panel_key)

            if not audio_path or not Path(audio_path).exists():
                print(f"  No audio for {panel_key}; using silent track for this panel.")
                audio_path = None

            # Get audio duration
            if audio_path:
                try:
                    timing_path = session_dir / "audio" / f"{panel_key}_timing.json"
                    if not timing_path.exists():
                        timing_path = episode_audio_dir / f"{panel_key}_timing.json"
                    duration = None
                    if timing_path.exists():
                        try:
                            with open(timing_path, "r") as f:
                                timings = json.load(f)
                            if timings:
                                last = timings[-1]
                                duration = (float(last.get("offset", 0)) + float(last.get("duration", 0))) / 10_000_000.0
                        except Exception:
                            duration = None
                    if duration is None:
                        duration = self._audio_duration_seconds(audio_path)
                    if duration <= 0:
                        duration = panel_duration
                except Exception:
                    duration = panel_duration
            else:
                duration = panel_duration

            segment_jobs.append(
                {
                    "panel_idx": i,
                    "panel_key": panel_key,
                    "scene_path": str(scene_path),
                    "audio_path": str(audio_path),
                    "duration": float(duration),
                    "panel_fps": int(panel_fps),
                }
            )

        if self.segment_workers == 1 or len(segment_jobs) <= 1:
            for job in segment_jobs:
                _, seg_path, duration, panel_fps, panel_key = self._render_segment(
                    session_dir=session_dir,
                    overlay_dir_name=overlay_dir_name,
                    output_suffix=output_suffix,
                    render_dir=variant_dir,
                    **job,
                )
                print(f"  [{variant_label}] ✓ Segment {panel_key} ({duration:.1f}s @ {panel_fps} fps)")
                seg_paths.append(seg_path)
        else:
            worker_count = min(self.segment_workers, len(segment_jobs))
            results: List[tuple[int, Path, float, int, str]] = []
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(
                        self._render_segment,
                        session_dir=session_dir,
                        overlay_dir_name=overlay_dir_name,
                        output_suffix=output_suffix,
                        render_dir=variant_dir,
                        **job,
                    )
                    for job in segment_jobs
                ]
                for future in as_completed(futures):
                    results.append(future.result())

            for _, seg_path, duration, panel_fps, panel_key in sorted(results, key=lambda item: item[0]):
                print(f"  [{variant_label}] ✓ Segment {panel_key} ({duration:.1f}s @ {panel_fps} fps)")
                seg_paths.append(seg_path)

        if not seg_paths:
            print(f"[{variant_label}] No segments to concatenate.")
            return Path("")

        # Concatenate all segments
        concat_file = variant_dir / "concat.txt"
        with open(concat_file, "w") as f:
            for sp in seg_paths:
                f.write(f"file '{sp.resolve()}'\n")

        title = manga_board.get("episode_title", f"{project_name} Episode")
        safe_title = title.replace(" ", "_").replace(":", "").replace("'", "")
        ep_num = manga_board.get("episode_number", 1)
        suffix = f"_{output_suffix}" if output_suffix else ""
        final_name = f"Episode{ep_num}_{safe_title}{suffix}.mp4"
        final_path = variant_dir / final_name

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                *(["-t", str(float(max_duration_seconds))] if max_duration_seconds and float(max_duration_seconds) > 0 else []),
                "-r", str(self.fps),
                "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                str(final_path),
            ],
            check=True,
            capture_output=True,
        )

        # Optional music layer (expects a pre-generated track from Step 6)
        music_track = None
        if self.enable_music:
            music_dir = session_dir / "episodes" / f"episode{ep_num}" / "music"
            if not music_dir.exists():
                music_dir = session_dir / "music"
            music_track = None
            if music_dir.exists() and music_dir.is_dir():
                tracks = sorted([p for p in music_dir.iterdir() if p.suffix.lower() in [".mp3", ".wav", ".aac"]])
                if tracks:
                    music_track = tracks[0]

            if music_track:
                final_with_music = variant_dir / f"{final_path.stem}_with_music{final_path.suffix}"
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(final_path),
                        "-stream_loop", "-1", "-i", str(music_track),
                        "-filter_complex", "[1:a]volume=0.15[a2];[0:a][a2]amix=inputs=2:duration=first:dropout_transition=2",
                        "-c:v", "copy", "-c:a", "aac", "-shortest",
                        str(final_with_music),
                    ],
                    check=False,
                    capture_output=True,
                )
                if final_with_music.exists():
                    final_path = final_with_music
            else:
                print(f"[{variant_label}] Music enabled but no track found under episode music dir; exporting video without music.")

        if max_duration_seconds and float(max_duration_seconds) > 0:
            final_path = self._enforce_final_duration_cap(final_path, float(max_duration_seconds))
        actual_duration_seconds = self._video_duration_seconds(final_path)

        # generate thumbnail
        thumb_path = variant_dir / "thumbnail.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(final_path), "-ss", "00:00:01.000", "-vframes", "1", str(thumb_path)],
            check=False,
            capture_output=True,
        )

        # metadata
        metadata = {
            "episode": manga_board.get("episode_number", 1),
            "project_name": project_name,
            "title": manga_board.get("episode_title", "AutoAnimator"),
            "final_video": str(final_path),
            "thumbnail": str(thumb_path),
            "resolution": f"{self.resolution[0]}x{self.resolution[1]}",
            "fps": self.fps,
            "fps_policy": (manga_board.get("render_strategy", {}) or {}).get("fps_policy", {}),
            "output_suffix": output_suffix,
            "music_attached": bool(music_track is not None),
            "max_duration_seconds": float(max_duration_seconds) if max_duration_seconds and float(max_duration_seconds) > 0 else None,
            "actual_duration_seconds": actual_duration_seconds,
        }
        metadata_name = "metadata.json"
        with open(variant_dir / metadata_name, "w") as f:
            json.dump(metadata, f, indent=2)

        # Compatibility mirror: expose latest outputs in legacy session-root folders.
        legacy_variant_dir = session_dir / ("shorts" if variant_label == "shorts" else "fullvideo")
        legacy_variant_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(final_path, legacy_variant_dir / final_path.name)
            if thumb_path.exists():
                shutil.copy2(thumb_path, legacy_variant_dir / thumb_path.name)
            shutil.copy2(variant_dir / metadata_name, legacy_variant_dir / metadata_name)
        except Exception:
            # Non-fatal; primary render output remains under episode-scoped directories.
            pass

        print(f"[{variant_label}] Final video rendered: {final_path}")
        print(f"[{variant_label}] Thumbnail saved: {thumb_path}")
        print(f"[{variant_label}] Metadata saved: {variant_dir / metadata_name}")
        return final_path
