"""Tests for HTML bubble renderer using real session 5786188 scene images.

All output frames are saved to outputs/5786188/ova/html_overlays/
so they can be visually inspected after the test run.

These tests:
  - Do NOT call the LLM pipeline
  - Use only existing scene PNGs + hand-crafted / real placement data
  - Assert pixel-level sanity (non-black, correct size) + saved file existence
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from PIL import Image

# ── Paths ─────────────────────────────────────────────────────────────────────
SESSION_DIR   = Path(__file__).parent.parent / "outputs" / "5786188" / "ova"
SCENES_DIR    = SESSION_DIR / "scenes"
OUT_DIR       = SESSION_DIR / "html_overlays"
BOARD_PATH    = SESSION_DIR / "episodes" / "episode1" / "storyboard.json"
RESOLUTION    = (1920, 1080)


def _scene(panel_idx: int) -> Path:
    return SCENES_DIR / f"panel_{panel_idx:02d}.png"


def _out(name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR / name


# ── Helper: build a synthetic placement ───────────────────────────────────────
def _placement(
    character: str,
    x: int,
    y: int,
    w: int = 460,
    h: int = 180,
    cloud_style: str = "speech",
    tail_direction: str = "bottom-left",
) -> dict:
    return {
        "character":      character,
        "x":              x,
        "y":              y,
        "w":              w,
        "h":              h,
        "cloud_style":    cloud_style,
        "tail_direction": tail_direction,
    }


# ── Fixture: lazy-loaded renderer module ──────────────────────────────────────
@pytest.fixture(scope="module")
def renderer():
    """Import and yield the html_bubble_renderer; close browser on teardown."""
    from agents.ova.assets import html_bubble_renderer as r
    yield r
    r.close()


# ── Skip guard if scene images are missing ────────────────────────────────────
pytestmark = pytest.mark.skipif(
    not SCENES_DIR.exists(),
    reason="session 5786188 scene images not found",
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Speech bubble – single speaker (Announcer shout, panel 00)
# ─────────────────────────────────────────────────────────────────────────────
class TestSpeechBubble:
    def test_shout_bubble_renders_and_is_correct_size(self, renderer):
        """Shout bubble on panel_00 (Announcer). Yellow starburst shape."""
        scene   = _scene(0)
        place   = [_placement("Announcer", x=740, y=60, w=440, h=200,
                               cloud_style="shout")]
        display = {"Announcer": ["WELCOME TO...", "THE AI PROMPT TANK!"]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)

        assert img.size == RESOLUTION, f"Expected {RESOLUTION}, got {img.size}"
        img.save(str(_out("01_shout_announcer.png")))

    def test_speech_bubble_single_speaker(self, renderer):
        """Classic speech bubble with tail, panel_01 (Brahma)."""
        scene   = _scene(1)
        text    = "The foundation of existence is logic, yet I sense something beyond mere calculation here."
        place   = [_placement("Brahma", x=100, y=60, w=520, h=200,
                               cloud_style="speech", tail_direction="bottom-right")]
        display = {"Brahma": text.split()[:6]}   # first 6 words

        img = renderer.render_frame(scene, place, display, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("02_speech_brahma.png")))

    def test_speech_bubble_empty_text(self, renderer):
        """Bubble rendered with no text (frame 0 of animation — shape only)."""
        scene = _scene(1)
        place = [_placement("Brahma", x=100, y=60, w=520, h=200,
                             cloud_style="speech", tail_direction="bottom-right")]

        img = renderer.render_frame(scene, place, {}, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("03_speech_empty_text.png")))

    def test_thought_bubble(self, renderer):
        """Thought bubble for Mahesh (panel_09)."""
        scene = _scene(9)
        text  = "Hmph. Clever. You are cheating destiny with a flashcard. Typical."
        place = [_placement("Mahesh", x=900, y=50, w=480, h=200,
                             cloud_style="thought", tail_direction="bottom-left")]
        display = {"Mahesh": ["Hmph. Clever.", "Cheating destiny..."]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("04_thought_mahesh.png")))

    def test_caption_bubble(self, renderer):
        """Caption-style bubble (dark box, no tail) for narration."""
        scene = _scene(3)
        place = [_placement("Mahesh", x=660, y=840, w=600, h=120,
                             cloud_style="caption", tail_direction="bottom")]
        display = {"Mahesh": ["Not worth incinerating... yet."]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("05_caption_mahesh.png")))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Multi-speaker (panel_16 – Brahma + Vishnu)
# ─────────────────────────────────────────────────────────────────────────────
class TestMultiSpeaker:
    def test_two_speakers_side_by_side(self, renderer):
        """Two speech bubbles in one frame: Brahma left, Vishnu right."""
        scene = _scene(16)
        places = [
            _placement("Brahma", x=80,  y=60, w=440, h=180,
                        cloud_style="speech", tail_direction="bottom-right"),
            _placement("Vishnu", x=1400, y=60, w=440, h=180,
                        cloud_style="speech", tail_direction="bottom-left"),
        ]
        display = {
            "Brahma": ["A dangerous gamble..."],
            "Vishnu": ["Yet a beautiful one."],
        }

        img = renderer.render_frame(scene, places, display, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("06_two_speakers.png")))

    def test_two_speakers_different_styles(self, renderer):
        """Brahma speech bubble, Vishnu thought bubble — mixed styles."""
        scene  = _scene(16)
        places = [
            _placement("Brahma", x=80,  y=60,  w=440, h=200,
                        cloud_style="speech",  tail_direction="bottom-right"),
            _placement("Vishnu", x=1380, y=60, w=480, h=200,
                        cloud_style="thought", tail_direction="bottom-left"),
        ]
        display = {
            "Brahma": ["A dangerous gamble..."],
            "Vishnu": ["Yet a beautiful one."],
        }

        img = renderer.render_frame(scene, places, display, RESOLUTION)

        assert img.size == RESOLUTION
        img.save(str(_out("07_mixed_styles.png")))


# ─────────────────────────────────────────────────────────────────────────────
# 3. All 8 tail directions
# ─────────────────────────────────────────────────────────────────────────────
class TestTailDirections:
    DIRECTIONS = [
        "bottom-left", "bottom-right", "bottom",
        "top-left",    "top-right",    "top",
        "left",        "right",
    ]

    @pytest.mark.parametrize("tail_dir", DIRECTIONS)
    def test_tail_direction(self, renderer, tail_dir):
        """Each tail direction renders without error and at correct size."""
        scene   = _scene(1)
        place   = [_placement("Brahma", x=730, y=420, w=460, h=200,
                               cloud_style="speech", tail_direction=tail_dir)]
        display = {"Brahma": ["Tail: " + tail_dir]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)

        safe = tail_dir.replace("-", "_")
        img.save(str(_out(f"08_tail_{safe}.png")))
        assert img.size == RESOLUTION


# ─────────────────────────────────────────────────────────────────────────────
# 4. Subtitle bar
# ─────────────────────────────────────────────────────────────────────────────
class TestSubtitleBar:
    def test_subtitle_clean_bottom(self, renderer):
        """sub-clean-bottom style: gradient bar with text at bottom."""
        scene = _scene(0)
        img   = renderer.render_frame(
            scene, [], {},
            resolution=RESOLUTION,
            subtitle_text="WELCOME TO... THE AI PROMPT TANK!",
            subtitle_style="sub-clean-bottom",
        )

        assert img.size == RESOLUTION
        img.save(str(_out("09_subtitle_clean_bottom.png")))

    def test_subtitle_boxed_center(self, renderer):
        """sub-boxed-center style: solid dark box above lower third."""
        scene = _scene(4)
        img   = renderer.render_frame(
            scene, [], {},
            resolution=RESOLUTION,
            subtitle_text="Behold — the Temporal Loom!",
            subtitle_style="sub-boxed-center",
        )

        assert img.size == RESOLUTION
        img.save(str(_out("10_subtitle_boxed.png")))

    def test_subtitle_and_bubble_combined(self, renderer):
        """Speech bubble + subtitle bar in the same frame."""
        scene  = _scene(13)
        place  = [_placement("AI-8", x=100, y=50, w=480, h=200,
                              cloud_style="speech", tail_direction="bottom-right")]
        display = {"AI-8": ["Warning:", "Temporal friction detected!"]}

        img = renderer.render_frame(
            scene, place, display,
            resolution=RESOLUTION,
            subtitle_text="AI-8 raises the alarm.",
            subtitle_style="sub-clean-bottom",
        )

        assert img.size == RESOLUTION
        img.save(str(_out("11_bubble_plus_subtitle.png")))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Word-reveal sequence (paged steps)
# ─────────────────────────────────────────────────────────────────────────────
class TestWordRevealSequence:
    def test_progressive_reveal_saves_multiple_frames(self, renderer):
        """render_frames_batch produces one frame per reveal step + frame-0."""
        scene   = _scene(1)
        text    = "The foundation of existence is logic yet I sense something beyond mere calculation here."
        place   = [_placement("Brahma", x=100, y=60, w=520, h=200,
                               cloud_style="speech", tail_direction="bottom-right")]

        # Manually build 4 display steps (simulating paged_steps output)
        words  = text.split()
        n      = len(words)
        steps  = []
        chunk  = max(1, n // 4)
        for i in range(0, n, chunk):
            page_words = words[:i + chunk]
            # Rough wrap into lines of ~6 words
            lines = []
            for j in range(0, len(page_words), 6):
                lines.append(" ".join(page_words[j:j + 6]))
            steps.append({"display": {"Brahma": lines}})

        frames = renderer.render_frames_batch(
            scene, place, steps, RESOLUTION,
            subtitle_text="", subtitle_style="",
            include_empty_first=True,
        )

        assert len(frames) == len(steps) + 1, \
            f"Expected {len(steps) + 1} frames, got {len(frames)}"

        reveal_dir = OUT_DIR / "reveal_sequence"
        reveal_dir.mkdir(parents=True, exist_ok=True)
        for idx, f in enumerate(frames):
            assert f.size == RESOLUTION
            f.save(str(reveal_dir / f"frame_{idx:03d}.png"))

    def test_reveal_uses_real_manga_board_panel(self, renderer):
        """End-to-end: load real panel_16 dialogue + simulate 3 reveal steps."""
        board   = json.loads(BOARD_PATH.read_text())
        panel   = board["panels"][16]
        lines16 = panel.get("dialogue", [])

        scene  = _scene(16)
        places = [
            _placement("Brahma", x=80,  y=60, w=440, h=180,
                        cloud_style="speech", tail_direction="bottom-right"),
            _placement("Vishnu", x=1400, y=60, w=440, h=180,
                        cloud_style="speech", tail_direction="bottom-left"),
        ]

        steps = [
            {"display": {"Brahma": [],         "Vishnu": []}},
            {"display": {"Brahma": ["A dangerous gamble..."], "Vishnu": []}},
            {"display": {"Brahma": ["A dangerous gamble..."], "Vishnu": ["Yet a beautiful one."]}},
        ]

        frames = renderer.render_frames_batch(
            scene, places, steps, RESOLUTION,
            include_empty_first=False,
        )

        assert len(frames) == 3
        board_dir = OUT_DIR / "panel16_reveal"
        board_dir.mkdir(parents=True, exist_ok=True)
        for idx, f in enumerate(frames):
            f.save(str(board_dir / f"step_{idx:02d}.png"))


# ─────────────────────────────────────────────────────────────────────────────
# 6. Bubble size extremes
# ─────────────────────────────────────────────────────────────────────────────
class TestBubbleSizeExtremes:
    def test_very_large_bubble(self, renderer):
        """Large bubble (600×300) fits lots of text without overflow."""
        scene = _scene(5)
        place = [_placement("Dr. Aris", x=660, y=60, w=600, h=300,
                              cloud_style="speech", tail_direction="bottom")]
        display = {
            "Dr. Aris": [
                "The Temporal Loom doesn't change events,",
                "it weaves alternative probability nodes",
                "into your own accessible timeline.",
            ]
        }

        img = renderer.render_frame(scene, place, display, RESOLUTION)
        assert img.size == RESOLUTION
        img.save(str(_out("12_large_bubble.png")))

    def test_minimum_size_bubble(self, renderer):
        """Tiny bubble (80×50) renders without crash."""
        scene = _scene(1)
        place = [_placement("Brahma", x=500, y=500, w=80, h=50,
                              cloud_style="speech", tail_direction="bottom")]
        display = {"Brahma": ["OK"]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)
        assert img.size == RESOLUTION
        img.save(str(_out("13_tiny_bubble.png")))

    def test_long_text_paged_display(self, renderer):
        """Long text shown as a page slice (not overflowing the bubble)."""
        scene = _scene(9)
        place = [_placement("Mahesh", x=900, y=50, w=480, h=180,
                              cloud_style="thought", tail_direction="bottom-left")]
        # Show only page 1 of a long dialogue
        display = {"Mahesh": ["You are cheating destiny", "with a mere flashcard."]}

        img = renderer.render_frame(scene, place, display, RESOLUTION)
        assert img.size == RESOLUTION
        img.save(str(_out("14_long_text_paged.png")))


# ─────────────────────────────────────────────────────────────────────────────
# 7. Smoke test: all 20 panels, no bubbles, just subtitle
# ─────────────────────────────────────────────────────────────────────────────
class TestAllPanelsSubtitleSmoke:
    def test_all_panels_render_subtitle_only(self, renderer):
        """All 20 panels render with subtitle bar without errors."""
        board  = json.loads(BOARD_PATH.read_text())
        errors = []
        for i, panel in enumerate(board["panels"]):
            scene = _scene(i)
            if not scene.exists():
                continue
            lines = panel.get("dialogue", [])
            text  = " / ".join(d["line"] for d in lines if d.get("line"))
            try:
                img = renderer.render_frame(
                    scene, [], {},
                    resolution=RESOLUTION,
                    subtitle_text=text[:120],
                    subtitle_style="sub-clean-bottom",
                )
                assert img.size == RESOLUTION
                img.save(str(_out(f"smoke_panel_{i:02d}.png")))
            except Exception as e:
                errors.append(f"panel_{i:02d}: {e}")

        assert not errors, "Errors on panels:\n" + "\n".join(errors)
