"""
MovieMaker – FFmpeg-based video stitching for manga panels.

Reads render_strategy from the manga-board for transitions.
Composites scene images + text cloud overlays + audio per panel.
"""

import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple


class MovieMaker:
    def __init__(self, fps: int = 24, resolution: Tuple[int, int] = (1280, 720)):
        self.fps = fps
        self.resolution = resolution

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
                        "-c:v", "libx264", "-c:a", "aac", "-shortest",
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
                        "-c:v", "libx264", "-t", str(duration),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
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

        title = manga_board.get("episode_title", "NarrativeManga")
        safe_title = title.replace(" ", "_").replace(":", "").replace("'", "")
        ep_num = manga_board.get("episode_number", 1)
        final_name = f"Episode{ep_num}_{safe_title}.mp4"
        final_path = session_dir / final_name

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c", "copy",
                str(final_path),
            ],
            check=True,
            capture_output=True,
        )

        print(f"Final video rendered: {final_path}")
        return final_path
