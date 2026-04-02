"""Music agents for Strudel and Lyria providers."""
import subprocess
import time
import json
from pathlib import Path

from agents.shared.gemini_compat import make_gemini_client

try:
    from google.genai import types as genai_types
except Exception:
    genai_types = None

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
        print(f"[Strudel] status response: {status_resp}")
        status_text = ""
        try:
            status_text = status_resp.get("content", [{}])[0].get("text", "")
        except Exception:
            pass

        if "Server: Stopped" in status_text or "Stopped" in status_text:
            start_resp = strudel(action="start", open_browser=False)
            print(f"[Strudel] start response: {start_resp}")
            time.sleep(1)
            try:
                status_after = strudel(action="status")
                print(f"[Strudel] status after start: {status_after}")
            except Exception as e:
                print(f"[Strudel] status check after start failed: {e}")

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
        print(f"[Strudel] requested style={style} duration={duration_seconds}s")
        print(f"[Strudel] prompt: {prompt}")

        if not self.enabled:
            raise RuntimeError("Strudel is not available in this environment.")

        self._ensure_started()

        # Play a style (live coding server) to follow package intent.
        try:
            play_resp = strudel(action="play", style=style)
            print(f"[Strudel] play response: {play_resp}")
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


class LyriaMusicAgent:
    """Generate background music using Google's Lyria models via Gemini API."""

    def __init__(self, model_name: str = "lyria-3-clip-preview"):
        self.model_name = model_name
        self.client = make_gemini_client(required=False)
        self.enabled = self.client is not None and genai_types is not None

    def _build_prompt(self, prompt: str, duration_seconds: int) -> str:
        return (
            f"{prompt}\n\n"
            "Generate instrumental only, no vocals. "
            f"Target duration around {duration_seconds} seconds. "
            "Keep it suitable as cinematic manga background score."
        )

    def generate_music(
        self,
        out_path: Path,
        prompt: str = "Cinematic background music",
        duration_seconds: int = 60,
        model_name: str | None = None,
    ) -> Path:
        if not self.enabled:
            raise RuntimeError("Lyria is not available. Check GEMINI_API_KEY and google-genai installation.")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        selected_model = model_name or self.model_name
        lyria_prompt = self._build_prompt(prompt=prompt, duration_seconds=duration_seconds)

        print(f"[Lyria] model={selected_model} duration={duration_seconds}s")
        print(f"[Lyria] prompt: {lyria_prompt}")

        response = self.client.models.generate_content(
            model=selected_model,
            contents=lyria_prompt,
            config=genai_types.GenerateContentConfig(response_modalities=["AUDIO", "TEXT"]),
        )

        audio_bytes = None
        text_parts: list[str] = []

        # The SDK may expose parts either on response.parts or candidates[].content.parts.
        parts = []
        if getattr(response, "parts", None):
            parts = list(response.parts)
        elif getattr(response, "candidates", None):
            for cand in response.candidates or []:
                content = getattr(cand, "content", None)
                if content and getattr(content, "parts", None):
                    parts.extend(content.parts)

        for part in parts:
            txt = getattr(part, "text", None)
            if txt:
                text_parts.append(str(txt))
                continue
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None:
                data = getattr(inline_data, "data", None)
                if data:
                    audio_bytes = bytes(data)

        if text_parts:
            print("[Lyria] textual output:")
            for block in text_parts:
                print(block)

        if not audio_bytes:
            # Last-resort debug dump when API shape changes.
            try:
                print(f"[Lyria] raw response: {json.dumps(getattr(response, 'model_dump', lambda: {})(), default=str)[:2000]}")
            except Exception:
                print(f"[Lyria] raw response repr: {response}")
            raise RuntimeError("Lyria response did not include inline audio data.")

        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        print(f"[Lyria] audio saved to: {out_path}")
        return out_path

