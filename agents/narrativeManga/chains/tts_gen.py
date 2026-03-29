"""
TTS Generator – Multi-character dialogue audio per panel.

Produces: audio/panel_XX.mp3 + audio/panel_XX_timing.json
Uses Edge-TTS with per-character voice assignment.

Note: Edge-TTS v7+ only emits SentenceBoundary events (no WordBoundary).
      We synthesize word-level timings from sentence boundaries.
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List


class TTSGen:
    def __init__(self):
        pass

    def run(self, manga_board: Dict[str, Any], session_dir: Path) -> List[str]:
        print("--- Pipeline: TTS Generation ---")
        audio_dir = session_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        panels = manga_board.get("panels", [])
        characters = manga_board.get("characters", [])

        # Build voice map: character name -> assigned voice
        voice_map: Dict[str, str] = {}
        for char in characters:
            name = char.get("name")
            voice = char.get("assigned_voice", "en-US-AriaNeural")
            voice_map[name] = voice

        audio_files: List[str] = []

        for i, panel in enumerate(panels):
            audio_path = audio_dir / f"panel_{i:02d}.mp3"
            timing_path = audio_dir / f"panel_{i:02d}_timing.json"

            # Resume: only skip if both exist AND timing is non-empty
            if audio_path.exists() and timing_path.exists():
                with open(timing_path, "r") as f:
                    existing_timing = json.load(f)
                if existing_timing:
                    print(f"Found existing audio for panel {i}, skipping.")
                    audio_files.append(str(audio_path))
                    continue

            dialogue_lines = panel.get("dialogue", [])
            if not dialogue_lines:
                continue

            all_text_parts: List[Dict[str, str]] = []
            for dl in dialogue_lines:
                char_name = dl.get("character", "Narrator")
                line = dl.get("line", "")
                voice = voice_map.get(char_name, "en-US-AriaNeural")
                if line:
                    all_text_parts.append({
                        "character": char_name,
                        "line": line,
                        "voice": voice,
                    })

            if not all_text_parts:
                continue

            print(f"Generating audio for panel {i} ({len(all_text_parts)} lines)")

            try:
                asyncio.run(
                    self._generate_panel_audio(all_text_parts, audio_path, timing_path)
                )
                audio_files.append(str(audio_path))
            except Exception as e:
                print(f"  ✗ Error generating audio for panel {i}: {e}")

        print(f"TTS complete: {len(audio_files)} audio files")
        return audio_files

    async def _generate_panel_audio(
        self,
        text_parts: List[Dict[str, str]],
        audio_path: Path,
        timing_path: Path,
    ):
        """Generate concatenated audio for all dialogue lines in a panel."""
        import edge_tts

        all_timing: List[dict] = []
        cumulative_offset = 0  # in 100-nanosecond units

        with open(audio_path, "wb") as audio_file:
            for part in text_parts:
                line = part["line"]
                voice = part["voice"]
                char_name = part["character"]

                communicate = edge_tts.Communicate(line, voice)
                word_timings = []
                sentence_boundaries = []

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word_timings.append({
                            "character": char_name,
                            "text": chunk["text"],
                            "offset": chunk["offset"] + cumulative_offset,
                            "duration": chunk["duration"],
                        })
                    elif chunk["type"] == "SentenceBoundary":
                        sentence_boundaries.append(chunk)

                # If no WordBoundary events, synthesize from SentenceBoundary
                if not word_timings and sentence_boundaries:
                    for sb in sentence_boundaries:
                        text = sb.get("text", "")
                        words = text.split()
                        if not words:
                            continue
                        sent_offset = sb["offset"] + cumulative_offset
                        dur_per_word = sb["duration"] // len(words)
                        for wi, w in enumerate(words):
                            word_timings.append({
                                "character": char_name,
                                "text": w,
                                "offset": sent_offset + (wi * dur_per_word),
                                "duration": dur_per_word,
                            })

                # Update cumulative offset for next speaker
                if word_timings:
                    last = word_timings[-1]
                    cumulative_offset = last["offset"] + last["duration"]
                    # Small pause between speakers (~300ms)
                    cumulative_offset += 3_000_000
                elif sentence_boundaries:
                    # Fallback: estimate from sentence boundaries
                    last_sb = sentence_boundaries[-1]
                    cumulative_offset += last_sb["offset"] + last_sb["duration"] + 3_000_000

                all_timing.extend(word_timings)

        with open(timing_path, "w") as f:
            json.dump(all_timing, f, indent=2)
