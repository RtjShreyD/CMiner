"""Music Agent via Strudel (optional, external dependency)."""
import subprocess
import time
from pathlib import Path

try:
    from strands_strudel import strudel
except ImportError:
    strudel = None


class StrudelMusicAgent:
    def __init__(self):
        self.enabled = strudel is not None
        self.started = False

    def _ensure_started(self):
        if not self.enabled:
            raise RuntimeError("Strudel is not installed in the current Python environment.")

        # Start backend if not already running
        status_resp = strudel(action="status")
        status_text = ""
        try:
            status_text = status_resp.get("content", [{}])[0].get("text", "")
        except Exception:
            pass

        if "Server: Stopped" in status_text or "Stopped" in status_text:
            strudel(action="start", open_browser=False)
            time.sleep(1)

        self.started = True

    def generate_music(
        self,
        out_path: Path,
        prompt: str = "Cinematic background music",
        duration_seconds: int = 60,
        style: str = "ambient",
    ):
        """Generate a music track using Strudel and produce an audio file placeholder."""
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.enabled:
            raise RuntimeError("Strudel is not available in this environment.")

        self._ensure_started()

        # Play a style (live coding server) to follow package intent.
        try:
            strudel(action="play", style=style)
        except Exception as e:
            print(f"Strudel play failed: {e}")

        # Generate a local MP3 fallback for downstream mixing.
        # The Strudel package does not expose file exports, so we create a short silent track.
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=cl=stereo:r=44100",
                    "-t",
                    str(duration_seconds),
                    "-q:a",
                    "9",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # ffmpeg unavailable fallback: write silence as WAV
            import wave
            import struct

            with wave.open(str(out_path), "wb") as wav:
                samp_rate = 44100
                num_frames = int(duration_seconds * samp_rate)
                nchannels = 2
                sampwidth = 2
                wav.setparams((nchannels, sampwidth, samp_rate, num_frames, "NONE", "not compressed"))
                silence = (0).to_bytes(2, byteorder="little", signed=True)
                for _ in range(num_frames):
                    wav.writeframes(silence * nchannels)

        except subprocess.CalledProcessError as e:
            print(f"ffmpeg failed generating music: {e.stderr.decode('utf-8', errors='ignore') if hasattr(e, 'stderr') else e}")
            raise

        return out_path

