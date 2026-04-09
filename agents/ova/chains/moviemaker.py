"""
MovieMaker – FFmpeg-based video stitching for manga panels.

Reads render_strategy from the manga-board for transitions.
Composites scene images + text cloud overlays + audio per panel.
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple


class MovieMaker:
    def __init__(
        self,
        fps: int = 24,
        resolution: Tuple[int, int] = (1280, 720),
        enable_music: bool = False,
        target_duration_seconds: int = 120,
    ):
        self.fps = fps
        self.resolution = resolution
        self.enable_music = enable_music
        self.target_duration_seconds = target_duration_seconds

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

        panels = manga_board.get("panels", [])
        render_strategy = manga_board.get("render_strategy", {})
        transition = render_strategy.get("transition_type", "cut")

        w, h = self.resolution
        seg_paths: List[Path] = []

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            scene_path = scenes_manifest.get(panel_key)

            if not scene_path or not Path(scene_path).exists():
                print(f"  No scene image for {panel_key}, skipping.")
                continue

            # Find matching audio
            audio_path = None
            for af in audio_files:
                if panel_key in af:
                    audio_path = af
                    break

            if not audio_path or not Path(audio_path).exists():
                print(f"  No audio for {panel_key}, skipping.")
                continue

            # Get audio duration
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

            seg_path = session_dir / f"seg_{i:02d}.mp4"
            overlay_dir = session_dir / "overlays" / panel_key

            if overlay_dir.exists() and any(overlay_dir.iterdir()):
                # Composite: scene + overlays + audio
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", str(scene_path),
                        "-framerate", str(self.fps), "-i", f"{overlay_dir}/frame_%04d.png",
                        "-i", audio_path,
                        "-filter_complex",
                        f"[0:v]scale={w}:{h}[bg];[bg][1:v]overlay=shortest=1,format=yuv420p",
                        "-r", str(self.fps),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest",
                        str(seg_path),
                    ],
                    check=True,
                    capture_output=True,
                )
            else:
                # No overlays: scene + audio only
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", str(scene_path),
                        "-i", audio_path,
                        "-r", str(self.fps),
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-t", str(duration),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest",
                        str(seg_path),
                    ],
                    check=True,
                    capture_output=True,
                )

            print(f"  ✓ Segment {panel_key} ({duration:.1f}s)")
            seg_paths.append(seg_path)

        if not seg_paths:
            print("No segments to concatenate.")
            return Path("")

        # Concatenate all segments
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

        # Optional music layer (expects a pre-generated track from Step 6)
        if self.enable_music:
            music_dir = session_dir / "music"
            music_track = None
            if music_dir.exists() and music_dir.is_dir():
                tracks = sorted([p for p in music_dir.iterdir() if p.suffix.lower() in [".mp3", ".wav", ".aac"]])
                if tracks:
                    music_track = tracks[0]

            if music_track:
                final_with_music = session_dir / f"{final_path.stem}_with_music{final_path.suffix}"
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(final_path),
                        "-stream_loop", "-1", "-i", str(music_track),
                        "-filter_complex", "[1:a]volume=0.15[a2];[0:a][a2]amix=inputs=2:duration=first:dropout_transition=2",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest",
                        str(final_with_music),
                    ],
                    check=False,
                    capture_output=True,
                )
                if final_with_music.exists():
                    final_path = final_with_music
            else:
                print("Music enabled but no track found under session/music; exporting video without music.")

        final_path = self._enforce_target_duration(final_path, session_dir)

        # generate thumbnail
        thumb_path = session_dir / "thumbnail.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(final_path), "-ss", "00:00:01.000", "-vframes", "1", str(thumb_path)],
            check=False,
            capture_output=True,
        )

        # metadata
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
