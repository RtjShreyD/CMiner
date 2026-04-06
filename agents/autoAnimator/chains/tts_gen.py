"""
TTS Generator – Multi-character dialogue audio per panel.

Produces: audio/panel_XX.mp3 + audio/panel_XX_timing.json
Uses Edge-TTS with per-character voice assignment.

Note: Edge-TTS v7+ only emits SentenceBoundary events (no WordBoundary).
      We synthesize word-level timings from sentence boundaries.
"""

import asyncio
import hashlib
import json
import tempfile
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List

from agents.shared.gemini_compat import make_gemini_client

try:
    from google.genai import types as genai_types
except Exception:
    genai_types = None


class TTSGen:
    def __init__(
        self,
        voices_pool: Dict[str, List[str]] = None,
        max_parallel_panels: int = 4,
        tts_provider: str = "edge",
        gemini_tts_model: str = "models/gemini-2.5-flash-tts",
        tracker: Any = None,
    ):
        self.voices_pool = voices_pool or {}
        self.max_parallel_panels = max(1, int(max_parallel_panels or 1))
        self.tts_provider = (tts_provider or "edge").strip().lower()
        self.gemini_tts_model = gemini_tts_model
        self.tracker = tracker

    @staticmethod
    def _emotion_tts_profile(emotion: str) -> tuple[str, str]:
        key = str(emotion or "neutral").strip().lower()
        profiles = {
            "sarcastic": ("-5%", "-2Hz"),
            "happy": ("+8%", "+3Hz"),
            "overwhelmed": ("+12%", "+5Hz"),
            "curious": ("+4%", "+2Hz"),
            "sad": ("-12%", "-4Hz"),
            "angry": ("+10%", "+2Hz"),
            "tense": ("+6%", "+1Hz"),
            "neutral": ("+0%", "+0Hz"),
        }
        return profiles.get(key, profiles["neutral"])

    def _record_tts_call(
        self,
        *,
        model: str,
        purpose: str,
        duration_ms: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        if self.tracker is None:
            return
        try:
            self.tracker.record_event(
                model=model,
                purpose=purpose,
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                metadata=metadata or {},
            )
        except Exception:
            pass

    @staticmethod
    def _is_hindi_text(text: str) -> bool:
        if not text:
            return False
        for ch in text:
            if "\u0900" <= ch <= "\u097f":
                return True
        return False

    def _preferred_hindi_voice(self) -> str:
        hindi_pool = self.voices_pool.get("hindi") if isinstance(self.voices_pool.get("hindi"), list) else []
        if hindi_pool:
            return str(hindi_pool[0])
        # Best-effort fallback to known Hindi neural voice.
        return "hi-IN-SwaraNeural"

    @staticmethod
    def _panel_signature(text_parts: List[Dict[str, str]], *, tts_provider: str, gemini_tts_model: str) -> str:
        payload = {
            "tts_provider": str(tts_provider or "edge"),
            "gemini_tts_model": str(gemini_tts_model or ""),
            "text_parts": [
                {
                    "character": str(p.get("character", "")),
                    "line": str(p.get("line", "")),
                    "voice": str(p.get("voice", "")),
                    "emotion": str(p.get("emotion", "neutral") or "neutral"),
                    "delivery_mode": str(p.get("delivery_mode", "dialogue") or "dialogue"),
                }
                for p in (text_parts or [])
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _silent_panel_signature(*, duration_sec: float, tts_provider: str, gemini_tts_model: str) -> str:
        payload = {
            "silent": True,
            "duration_sec": round(float(duration_sec or 0.0), 3),
            "tts_provider": str(tts_provider or "edge"),
            "gemini_tts_model": str(gemini_tts_model or ""),
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _create_silence_assets(self, audio_path: Path, timing_path: Path, duration_sec: float) -> None:
        duration = max(0.8, float(duration_sec or 2.0))
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(duration),
                "-q:a", "9",
                "-acodec", "libmp3lame",
                str(audio_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            raise RuntimeError("Failed to generate fallback silent audio.")

        duration_units = int(round(duration * 10_000_000))
        timing_payload = [{
            "character": "Speaker",
            "text": "",
            "offset": 0,
            "duration": max(1, duration_units),
        }]
        with open(timing_path, "w") as f:
            json.dump(timing_payload, f, indent=2)
        self._record_tts_call(
            model="local-silence-generator",
            purpose="tts_silent_panel",
            metadata={"duration_seconds": duration},
        )

    def run(self, manga_board: Dict[str, Any], session_dir: Path) -> List[str]:
        print("--- Pipeline: TTS Generation ---")
        audio_dir = session_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        signatures_path = audio_dir / "panel_signatures.json"
        panel_signatures: Dict[str, str] = {}
        if signatures_path.exists():
            try:
                parsed = json.loads(signatures_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    panel_signatures = {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                panel_signatures = {}

        panels = manga_board.get("panels", [])
        characters = manga_board.get("characters", [])

        # Build voice map: character name -> assigned voice
        voice_map: Dict[str, str] = {}
        for char in characters:
            name = char.get("name")
            assigned_voice = char.get("assigned_voice")
            voice_profile = char.get("voice_profile")
            voice = assigned_voice

            if not voice and voice_profile and voice_profile in self.voices_pool:
                candidates = self.voices_pool.get(voice_profile, [])
                voice = candidates[0] if candidates else None

            if not voice:
                # fallback to first available voice from any category
                for vcs in self.voices_pool.values():
                    if vcs:
                        voice = vcs[0]
                        break

            if not voice:
                voice = "en-US-AriaNeural"

            voice_map[name] = voice

        audio_files: List[str] = []

        panel_jobs = []
        pending_signatures: Dict[str, str] = {}
        for i, panel in enumerate(panels):
            audio_path = audio_dir / f"panel_{i:02d}.mp3"
            timing_path = audio_dir / f"panel_{i:02d}_timing.json"
            panel_key = f"panel_{i:02d}"

            dialogue_lines = panel.get("dialogue", [])
            all_text_parts: List[Dict[str, str]] = []
            if isinstance(dialogue_lines, list):
                for dl in dialogue_lines:
                    char_name = dl.get("character", "Speaker")
                    line = dl.get("line", "")
                    voice = voice_map.get(char_name, "en-US-AriaNeural")
                    if self.tts_provider == "edge" and self._is_hindi_text(line):
                        # Route Hindi lines to Hindi-capable voice even if planner assigned an English voice.
                        if not str(voice).lower().startswith("hi-in-"):
                            voice = self._preferred_hindi_voice()
                    if line:
                        all_text_parts.append({
                            "character": char_name,
                            "line": line,
                            "voice": voice,
                            "emotion": str(dl.get("emotion", "neutral") or "neutral"),
                            "delivery_mode": str(dl.get("delivery_mode", "dialogue") or "dialogue"),
                        })

            # Ensure every panel has audio/timing artifacts. For silent panels,
            # generate synthetic silence so downstream cloud/video steps stay aligned.
            if not all_text_parts:
                silent_duration = float(panel.get("duration_seconds", 2) or 2)
                panel_sig = self._silent_panel_signature(
                    duration_sec=silent_duration,
                    tts_provider=self.tts_provider,
                    gemini_tts_model=self.gemini_tts_model,
                )
                pending_signatures[panel_key] = panel_sig
                existing_sig = panel_signatures.get(panel_key)

                if audio_path.exists() and timing_path.exists() and existing_sig == panel_sig:
                    with open(timing_path, "r") as f:
                        existing_timing = json.load(f)
                    if existing_timing:
                        print(f"Found matching silent audio for panel {i}, skipping.")
                        audio_files.append(str(audio_path))
                        continue

                audio_path.unlink(missing_ok=True)
                timing_path.unlink(missing_ok=True)
                self._create_silence_assets(audio_path, timing_path, silent_duration)
                audio_files.append(str(audio_path))
                continue

            panel_sig = self._panel_signature(
                all_text_parts,
                tts_provider=self.tts_provider,
                gemini_tts_model=self.gemini_tts_model,
            )
            pending_signatures[panel_key] = panel_sig
            existing_sig = panel_signatures.get(panel_key)

            # Resume only when artifacts exist, timings are non-empty, and content signature matches.
            if audio_path.exists() and timing_path.exists() and existing_sig == panel_sig:
                with open(timing_path, "r") as f:
                    existing_timing = json.load(f)
                if existing_timing:
                    print(f"Found matching audio for panel {i}, skipping.")
                    audio_files.append(str(audio_path))
                    continue

            audio_path.unlink(missing_ok=True)
            timing_path.unlink(missing_ok=True)
            panel_jobs.append((i, all_text_parts, audio_path, timing_path))

        if panel_jobs:
            generated_files = asyncio.run(self._generate_all_panels_audio(panel_jobs))
            audio_files.extend(generated_files)

        for i, panel in enumerate(panels):
            panel_key = f"panel_{i:02d}"
            if panel_key in pending_signatures and (audio_dir / f"{panel_key}.mp3").exists():
                panel_signatures[panel_key] = pending_signatures[panel_key]

        with open(signatures_path, "w") as f:
            json.dump(panel_signatures, f, indent=2)

        print(f"TTS complete: {len(audio_files)} audio files")
        return audio_files

    async def _generate_all_panels_audio(self, panel_jobs: List[tuple]) -> List[str]:
        semaphore = asyncio.Semaphore(self.max_parallel_panels)

        async def _worker(job):
            panel_idx, all_text_parts, audio_path, timing_path = job
            print(f"Generating audio for panel {panel_idx} ({len(all_text_parts)} lines)")
            async with semaphore:
                try:
                    await self._generate_panel_audio(all_text_parts, audio_path, timing_path)
                    return str(audio_path)
                except Exception as e:
                    print(f"  ✗ Error generating audio for panel {panel_idx}: {e}")
                    return None

        tasks = [asyncio.create_task(_worker(job)) for job in panel_jobs]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r]

    async def _generate_panel_audio(
        self,
        text_parts: List[Dict[str, str]],
        audio_path: Path,
        timing_path: Path,
    ):
        if self.tts_provider == "gemini":
            await self._generate_panel_audio_gemini(text_parts, audio_path, timing_path)
            return

        """Generate concatenated audio for all dialogue lines in a panel."""
        import edge_tts

        all_timing: List[dict] = []
        cumulative_offset = 0  # in 100-nanosecond units

        successful_lines = 0
        with open(audio_path, "wb") as audio_file:
            for part in text_parts:
                line = str(part.get("line", "") or "").strip()
                if not line:
                    continue

                voice = part["voice"]
                char_name = part["character"]
                emotion = str(part.get("emotion", "neutral") or "neutral")
                rate, pitch = self._emotion_tts_profile(emotion)

                fallback_voice = "en-US-AriaNeural"
                if self._is_hindi_text(line):
                    fallback_voice = self._preferred_hindi_voice()
                candidate_voices: List[str] = []
                for v in [voice, fallback_voice]:
                    sv = str(v or "").strip()
                    if sv and sv not in candidate_voices:
                        candidate_voices.append(sv)

                line_error = None
                for candidate_voice in candidate_voices:
                    for attempt in range(1, 4):
                        try:
                            t0 = time.perf_counter()
                            communicate = edge_tts.Communicate(line, candidate_voice, rate=rate, pitch=pitch)
                            line_audio = bytearray()
                            word_timings = []
                            sentence_boundaries = []

                            async for chunk in communicate.stream():
                                if chunk["type"] == "audio":
                                    line_audio.extend(chunk["data"])
                                elif chunk["type"] == "WordBoundary":
                                    word_timings.append({
                                        "character": char_name,
                                        "text": chunk["text"],
                                        "offset": chunk["offset"] + cumulative_offset,
                                        "duration": chunk["duration"],
                                    })
                                elif chunk["type"] == "SentenceBoundary":
                                    sentence_boundaries.append(chunk)

                            if not line_audio:
                                raise RuntimeError("No audio was received. Please verify that your parameters are correct.")

                            audio_file.write(bytes(line_audio))

                            # If no WordBoundary events, synthesize from SentenceBoundary.
                            if not word_timings and sentence_boundaries:
                                for sb in sentence_boundaries:
                                    text = sb.get("text", "")
                                    words = text.split()
                                    if not words:
                                        continue
                                    sent_offset = sb["offset"] + cumulative_offset
                                    dur_per_word = max(80_000, sb["duration"] // len(words))
                                    for wi, w in enumerate(words):
                                        word_timings.append({
                                            "character": char_name,
                                            "text": w,
                                            "offset": sent_offset + (wi * dur_per_word),
                                            "duration": dur_per_word,
                                        })

                            # Update cumulative offset for next speaker.
                            if word_timings:
                                last = word_timings[-1]
                                cumulative_offset = last["offset"] + last["duration"]
                                cumulative_offset += 3_000_000  # ~300ms speaker gap
                            elif sentence_boundaries:
                                last_sb = sentence_boundaries[-1]
                                cumulative_offset += last_sb["offset"] + last_sb["duration"] + 3_000_000
                            else:
                                # No boundary metadata available; estimate based on words.
                                word_count = max(1, len(line.split()))
                                cumulative_offset += (word_count * 260_0000) + 3_000_000

                            all_timing.extend(word_timings)
                            successful_lines += 1
                            self._record_tts_call(
                                model=f"edge-tts:{candidate_voice}",
                                purpose="tts_edge_line",
                                duration_ms=(time.perf_counter() - t0) * 1000,
                                metadata={
                                    "character": char_name,
                                    "emotion": emotion,
                                    "text_chars": len(line),
                                    "delivery_mode": str(part.get("delivery_mode", "dialogue")),
                                },
                            )
                            line_error = None
                            break
                        except Exception as e:
                            line_error = e
                            if attempt < 3:
                                await asyncio.sleep(0.4 * attempt)
                    if line_error is None:
                        break

                if line_error is not None:
                    print(f"  ⚠️ Skipping line for '{char_name}' after retries: {line_error}")

        if successful_lines == 0:
            raise RuntimeError("No audio lines could be synthesized for this panel after retries.")

        with open(timing_path, "w") as f:
            json.dump(all_timing, f, indent=2)

    @staticmethod
    def _extract_audio_bytes(response: Any) -> bytes | None:
        parts = []
        if getattr(response, "parts", None):
            parts = list(response.parts)
        elif getattr(response, "candidates", None):
            for cand in response.candidates or []:
                content = getattr(cand, "content", None)
                if content and getattr(content, "parts", None):
                    parts.extend(content.parts)

        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None:
                data = getattr(inline_data, "data", None)
                if data:
                    return bytes(data)
        return None

    @staticmethod
    def _audio_duration_seconds(path: Path) -> float:
        try:
            res = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return float((res.stdout or "").strip() or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _build_synthetic_word_timings(text_parts: List[Dict[str, str]], total_duration_sec: float) -> List[dict]:
        words: List[tuple[str, str]] = []
        for part in text_parts:
            cname = str(part.get("character", "Speaker") or "Speaker")
            line = str(part.get("line", "") or "")
            for w in line.split():
                words.append((cname, w))

        if not words:
            return []

        total_units = int(max(total_duration_sec, 1.0) * 10_000_000)
        dur = max(80_000, total_units // len(words))
        out: List[dict] = []
        offset = 0
        for cname, w in words:
            out.append({
                "character": cname,
                "text": w,
                "offset": offset,
                "duration": dur,
            })
            offset += dur
        return out

    async def _generate_panel_audio_gemini(
        self,
        text_parts: List[Dict[str, str]],
        audio_path: Path,
        timing_path: Path,
    ):
        client = make_gemini_client(required=False)
        if client is None or genai_types is None:
            raise RuntimeError("Gemini TTS is not available. Check GEMINI_API_KEY and google-genai package.")

        script = "\n".join([f"{p.get('character', 'Speaker')}: {p.get('line', '')}" for p in text_parts])
        prompt = (
            "Synthesize clear narrated dialogue audio for the following script. "
            "Keep pacing natural and cinematic.\n\n"
            f"{script}"
        )

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=self.gemini_tts_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_modalities=["AUDIO", "TEXT"]),
        )
        usage = getattr(response, "usage_metadata", None)
        in_toks = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_toks = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        audio_bytes = self._extract_audio_bytes(response)
        if not audio_bytes:
            raise RuntimeError("Gemini TTS response did not include audio bytes.")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            tmp_path = Path(tmp.name)

        try:
            # Normalize to mp3 so downstream behavior matches existing edge output.
            conv = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-i", str(tmp_path), str(audio_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if getattr(conv, "returncode", 1) != 0:
                audio_path.write_bytes(audio_bytes)

            duration = self._audio_duration_seconds(audio_path)
            timings = self._build_synthetic_word_timings(text_parts, duration)
            with open(timing_path, "w") as f:
                json.dump(timings, f, indent=2)
            self._record_tts_call(
                model=self.gemini_tts_model,
                purpose="tts_gemini_panel",
                input_tokens=in_toks,
                output_tokens=out_toks,
                metadata={
                    "lines": len(text_parts),
                    "duration_seconds": duration,
                },
            )
        finally:
            tmp_path.unlink(missing_ok=True)
