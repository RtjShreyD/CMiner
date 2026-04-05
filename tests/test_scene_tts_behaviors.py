import tempfile
import unittest
import json
import shutil
from pathlib import Path
from unittest import mock

from PIL import Image

from agents.autoAnimator.chains.scene_gen import SceneGen
from agents.autoAnimator.chains.cloud_gen import CloudGen
from agents.autoAnimator.chains.tts_gen import TTSGen
from agents.shared.llm_tracker import LLMTracker


class SceneStaticFrameTests(unittest.TestCase):
    def test_solid_static_frame_does_not_render_scene_description_text(self):
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "panel_00.png"
            scene_gen = SceneGen(resolution=(320, 180))

            panel = {
                "scene_description": "Absolute black void with no text.",
                "static_frame_spec": {
                    "renderer": "solid",
                    "bg_color": "#000000",
                },
            }

            ok = scene_gen._render_static_frame(panel, "panel_00", out_path)
            self.assertTrue(ok)
            self.assertTrue(out_path.exists())

            with Image.open(out_path) as img:
                rgb = img.convert("RGB")
                extrema = rgb.getextrema()

            # Pure black frame should remain untouched (no white title text drawn).
            self.assertEqual(extrema, ((0, 0), (0, 0), (0, 0)))


class TTSHindiVoiceRoutingTests(unittest.TestCase):
    def test_hindi_dialogue_prefers_hindi_edge_voice(self):
        tts = TTSGen(
            voices_pool={
                "hindi": ["hi-IN-SwaraNeural"],
                "hero": ["en-US-ChristopherNeural"],
            },
            tts_provider="edge",
        )

        manga_board = {
            "characters": [
                {
                    "name": "Hero",
                    "assigned_voice": "en-US-ChristopherNeural",
                }
            ],
            "panels": [
                {
                    "dialogue": [
                        {
                            "character": "Hero",
                            "line": "यह एक परीक्षण पंक्ति है",
                        }
                    ]
                }
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            with mock.patch.object(TTSGen, "_generate_all_panels_audio", new=mock.AsyncMock(return_value=[])) as mocked:
                tts.run(manga_board, session_dir)

            self.assertTrue(mocked.await_count == 1)
            panel_jobs = mocked.await_args.args[0]
            self.assertEqual(len(panel_jobs), 1)
            _, text_parts, _, _ = panel_jobs[0]
            self.assertEqual(text_parts[0]["voice"], "hi-IN-SwaraNeural")


class LLMTrackerEventTests(unittest.TestCase):
    def test_record_event_supports_non_llm_engines(self):
        tracker = LLMTracker()
        tracker.record_event(
            model="edge-tts:hi-IN-SwaraNeural",
            purpose="tts_edge_line",
            duration_ms=42.0,
            metadata={"character": "Narrator"},
        )

        self.assertEqual(len(tracker.calls), 1)
        self.assertEqual(tracker.calls[0]["model"], "edge-tts:hi-IN-SwaraNeural")
        self.assertEqual(tracker.calls[0]["purpose"], "tts_edge_line")

    def test_save_includes_calls_per_model_analytics(self):
        tracker = LLMTracker()
        tracker.record_event(model="models/a", purpose="planner", input_tokens=11, output_tokens=7, duration_ms=20)
        tracker.record_event(model="models/a", purpose="planner", input_tokens=4, output_tokens=3, duration_ms=30)
        tracker.record_event(model="models/b", purpose="director", input_tokens=9, output_tokens=5, duration_ms=10)

        with tempfile.TemporaryDirectory() as td:
            out = tracker.save(Path(td))
            report = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(report["total_calls"], 3)
        self.assertEqual(report["calls_per_model"]["models/a"], 2)
        self.assertEqual(report["calls_per_model"]["models/b"], 1)
        self.assertEqual(report["model_analytics"]["models/a"]["total_tokens"], 25)
        self.assertEqual(report["model_analytics"]["models/b"]["calls"], 1)


class TTSResumeSignatureTests(unittest.TestCase):
    def test_tts_regenerates_when_dialogue_changes(self):
        async def _fake_generate(panel_jobs):
            out = []
            for _, text_parts, audio_path, timing_path in panel_jobs:
                audio_path.write_bytes(b"fake-audio")
                timing_payload = [
                    {
                        "character": text_parts[0]["character"],
                        "text": text_parts[0]["line"],
                        "offset": 0,
                        "duration": 1_000_000,
                    }
                ]
                timing_path.write_text(json.dumps(timing_payload), encoding="utf-8")
                out.append(str(audio_path))
            return out

        tts = TTSGen(
            voices_pool={"hero": ["en-US-ChristopherNeural"]},
            tts_provider="edge",
        )

        board_v1 = {
            "characters": [{"name": "Hero", "assigned_voice": "en-US-ChristopherNeural"}],
            "panels": [{"dialogue": [{"character": "Hero", "line": "Line one"}]}],
        }
        board_v2 = {
            "characters": [{"name": "Hero", "assigned_voice": "en-US-ChristopherNeural"}],
            "panels": [{"dialogue": [{"character": "Hero", "line": "Line two changed"}]}],
        }

        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            mocked = mock.AsyncMock(side_effect=_fake_generate)
            with mock.patch.object(TTSGen, "_generate_all_panels_audio", new=mocked):
                tts.run(board_v1, session_dir)
                tts.run(board_v1, session_dir)
                tts.run(board_v2, session_dir)

                # First run generates, second run should skip (same signature), third regenerates (changed signature).
                self.assertEqual(mocked.call_count, 2)


class TTSSilentFallbackTests(unittest.TestCase):
    def test_panels_without_dialogue_generate_silent_assets(self):
        tts = TTSGen(voices_pool={"narrator": ["en-US-AriaNeural"]}, tts_provider="edge")
        board = {
            "characters": [],
            "panels": [
                {"panel_number": 1, "duration_seconds": 2, "dialogue": []},
            ],
        }

        def _fake_run(cmd, check=False, capture_output=False, text=False):
            # TTS silent fallback uses ffmpeg and writes output at final arg.
            out_path = Path(cmd[-1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"fake-silent-audio")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            with mock.patch("agents.autoAnimator.chains.tts_gen.subprocess.run", side_effect=_fake_run):
                audio_files = tts.run(board, session_dir)

            self.assertEqual(len(audio_files), 1)
            self.assertTrue((session_dir / "audio" / "panel_00.mp3").exists())
            timing_path = session_dir / "audio" / "panel_00_timing.json"
            self.assertTrue(timing_path.exists())
            timing = json.loads(timing_path.read_text(encoding="utf-8"))
            self.assertTrue(isinstance(timing, list) and len(timing) == 1)
            self.assertGreater(int(timing[0].get("duration", 0)), 0)


class ShortsSubtitleRenderTests(unittest.TestCase):
    def test_cloudgen_shorts_subtitle_preview_artifact(self):
        """Render a real Shorts-resolution overlay frame and save a preview artifact for visual check."""
        with tempfile.TemporaryDirectory() as td:
            session_dir = Path(td)
            scenes_dir = session_dir / "scenes"
            audio_dir = session_dir / "audio"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            audio_dir.mkdir(parents=True, exist_ok=True)

            # A simple portrait scene background (YouTube Shorts resolution).
            scene_path = scenes_dir / "panel_00.png"
            scene = Image.new("RGB", (1080, 1920), (26, 36, 84))
            scene.save(scene_path)

            # Timing file structure mirrors pipeline output from TTS step.
            timing_path = audio_dir / "panel_00_timing.json"
            timing_rows = [
                {
                    "character": "Narrator",
                    "text": "Another episode, and the judges are ready with sharp feedback.",
                    "offset": 0,
                    "duration": 2_500_000,
                }
            ]
            timing_path.write_text(json.dumps(timing_rows, indent=2), encoding="utf-8")

            manga_board = {
                "episode_number": 2,
                "panels": [
                    {
                        "panel_number": 1,
                        "fps": 24,
                        "dialogue": [
                            {
                                "character": "Narrator",
                                "line": "Another episode, and the judges are ready with sharp feedback.",
                            }
                        ],
                    }
                ],
            }

            cloud_gen = CloudGen(
                fps=24,
                resolution=(1080, 1920),
                project_name="TheAiPromptTank",
                episode_number=2,
                overlay_dir_name="overlays_youtube_shorts",
                cloud_style="cloud-none",
                subtitle_style="subtitle-neon-clean",
                subtitle_scale=1.2,
                subtitle_x=0.70,
                subtitle_y=0.88,
            )
            cloud_gen.run(manga_board, session_dir)

            overlay_frame = session_dir / "overlays_youtube_shorts" / "panel_00" / "frame_0000.png"
            self.assertTrue(overlay_frame.exists(), "Expected CloudGen overlay frame to be generated")

            # Compose a preview image exactly like movie composition stage (scene + overlay).
            with Image.open(scene_path).convert("RGBA") as bg, Image.open(overlay_frame).convert("RGBA") as ov:
                composed = Image.alpha_composite(bg, ov).convert("RGB")
                self.assertEqual(composed.size, (1080, 1920))

                root_dir = Path(__file__).resolve().parents[1]
                artifact_dir = root_dir / "outputs" / "test_artifacts"
                artifact_dir.mkdir(parents=True, exist_ok=True)
                artifact_path = artifact_dir / "shorts_subtitle_preview.png"
                composed.save(artifact_path)

            self.assertTrue(artifact_path.exists(), "Expected composed preview artifact to be saved")
            self.assertGreater(artifact_path.stat().st_size, 1024, "Preview artifact looks too small")
            print(f"Saved Shorts subtitle preview artifact: {artifact_path}")


if __name__ == "__main__":
    unittest.main()
