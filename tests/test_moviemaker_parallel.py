import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from agents.autoAnimator.chains.moviemaker import MovieMaker


class _ProcResult:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


class MovieMakerParallelTests(unittest.TestCase):
    def test_suffix_isolates_intermediate_artifacts_for_parallel_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            scene_path = session_dir / "panel_00.png"
            scene_path.write_bytes(b"fake-scene")
            audio_path = session_dir / "panel_00.mp3"
            audio_path.write_bytes(b"fake-audio")

            manga_board = {
                "episode_number": 2,
                "episode_title": "Speed Test",
                "panels": [
                    {
                        "panel_number": 1,
                        "fps": 24,
                        "duration_seconds": 1,
                    }
                ],
                "render_strategy": {},
            }
            scenes_manifest = {"panel_00": str(scene_path)}
            audio_files = [str(audio_path)]

            def _fake_run(cmd, check=False, capture_output=False, text=False):
                if not cmd:
                    return _ProcResult()
                exe = cmd[0]
                if exe == "ffprobe":
                    return _ProcResult(stdout="1.0\n")
                if exe == "ffmpeg":
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"ok")
                    return _ProcResult(stdout="")
                return _ProcResult(stdout="")

            maker = MovieMaker(
                fps=24,
                resolution=(320, 180),
                enable_music=False,
                segment_workers=2,
            )

            with mock.patch("agents.autoAnimator.chains.moviemaker.subprocess.run", side_effect=_fake_run):
                final_path = maker.run(
                    manga_board,
                    scenes_manifest,
                    audio_files,
                    session_dir,
                    project_name="AutoAnimator",
                    output_suffix="youtube_shorts",
                    overlay_dir_name="overlays_youtube_shorts",
                )

            self.assertTrue(final_path.exists())
            self.assertEqual(final_path.name, "Episode2_Speed_Test_youtube_shorts.mp4")
            self.assertEqual(final_path.parent.name, "shorts")
            self.assertTrue((session_dir / "shorts" / "seg_00.mp4").exists())
            self.assertTrue((session_dir / "shorts" / "concat.txt").exists())
            self.assertTrue((session_dir / "shorts" / "thumbnail.jpg").exists())
            self.assertTrue((session_dir / "shorts" / "metadata.json").exists())

    def test_max_duration_cap_is_applied_to_final_concat(self):
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            scene_path = session_dir / "panel_00.png"
            scene_path.write_bytes(b"fake-scene")
            audio_path = session_dir / "panel_00.mp3"
            audio_path.write_bytes(b"fake-audio")

            manga_board = {
                "episode_number": 3,
                "episode_title": "Cap Check",
                "panels": [{"panel_number": 1, "fps": 24, "duration_seconds": 2}],
                "render_strategy": {},
            }
            scenes_manifest = {"panel_00": str(scene_path)}
            audio_files = [str(audio_path)]

            ffmpeg_cmds = []

            def _fake_run(cmd, check=False, capture_output=False, text=False):
                if not cmd:
                    return _ProcResult()
                exe = cmd[0]
                if exe == "ffprobe":
                    return _ProcResult(stdout="1.0\n")
                if exe == "ffmpeg":
                    ffmpeg_cmds.append(cmd)
                    out_path = Path(cmd[-1])
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(b"ok")
                    return _ProcResult(stdout="")
                return _ProcResult(stdout="")

            maker = MovieMaker(fps=24, resolution=(320, 180), enable_music=False, segment_workers=1)

            with mock.patch("agents.autoAnimator.chains.moviemaker.subprocess.run", side_effect=_fake_run):
                final_path = maker.run(
                    manga_board,
                    scenes_manifest,
                    audio_files,
                    session_dir,
                    project_name="AutoAnimator",
                    output_suffix="",
                    overlay_dir_name="overlays",
                    max_duration_seconds=30.0,
                )

            self.assertTrue(final_path.exists())
            # Concat command must include hard cap (-t 30.0)
            concat_cmds = [c for c in ffmpeg_cmds if "-f" in c and "concat" in c]
            self.assertTrue(concat_cmds, "Expected concat ffmpeg command")
            self.assertIn("-t", concat_cmds[0])
            t_idx = concat_cmds[0].index("-t")
            self.assertEqual(concat_cmds[0][t_idx + 1], "30.0")

            self.assertEqual(final_path.parent.name, "fullvideo")
            metadata = json.loads((session_dir / "fullvideo" / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("max_duration_seconds"), 30.0)
            self.assertIn("actual_duration_seconds", metadata)


if __name__ == "__main__":
    unittest.main()
