"""High-Performance TUI Video Player.

Uses OpenCV for decoding and Chafa for pixel-perfect terminal rendering.
Supports MP4, GIF, MOV, and AVI in native terminal protocols (Sixel/Kitty).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import cv2
try:
    import chafa
    HAS_CHAFA = True
except ImportError:
    HAS_CHAFA = False

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class VideoPreview(Vertical):
    """A TUI widget for real-time video playback in the terminal."""

    DEFAULT_CSS = """
    VideoPreview {
        width: 100%;
        height: 100%;
        background: $boost;
        border: solid $accent;
        padding: 1;
    }
    #vid-render {
        width: 100%;
        height: auto;
        content-align: center middle;
    }
    #vid-meta {
        height: 1;
        dock: top;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, file_path: str | Path | None = None, id: str | None = None):
        super().__init__(id=id)
        self._file_path = file_path
        self._cap: Optional[cv2.VideoCapture] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._fps = 24
        self._is_playing = False
        self._chafa_config: Optional[chafa.CanvasConfig] = None

    def compose(self) -> ComposeResult:
        yield Static("", id="vid-meta")
        yield Static("", id="vid-render")

    def on_mount(self) -> None:
        if self._file_path:
            self.load(str(self._file_path))

    def load(self, file_path: str) -> None:
        """Initialize video capture and prepare rendering."""
        self._file_path = Path(file_path)
        if not self._file_path.exists():
            self.query_one("#vid-render", Static).update(f"[red]Video not found: {file_path}[/red]")
            return

        self.stop()
        self._cap = cv2.VideoCapture(str(self._file_path))
        
        # Get video properties
        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 24
        
        meta_text = f"📹 {self._file_path.name} | {width}x{height} | {self._fps:.1f} FPS"
        self.query_one("#vid-meta", Static).update(meta_text)

        # Start playback
        self.play()

    def play(self) -> None:
        """Start the playback loop."""
        if not self._cap or not HAS_CHAFA:
            return
        
        self._is_playing = True
        self._step_frame()

    def stop(self) -> None:
        """Stop and release resources."""
        self._is_playing = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._cap:
            self._cap.release()
            self._cap = None

    def _step_frame(self) -> None:
        """Decode and render a single frame, then schedule the next."""
        if not self._is_playing or not self._cap:
             return

        ret, frame = self._cap.read()
        if not ret:
            # Loop video
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret:
                return

        # Prepare Chafa on first frame or resize
        render_w = self.size.width - 4
        if render_w < 20: render_w = 80 # Fallback
        
        h, w = frame.shape[:2]
        render_h = max(1, int((h / w) * render_w * 0.5))

        if not self._chafa_config or self._chafa_config.width != render_w:
            self._chafa_config = chafa.CanvasConfig()
            self._chafa_config.width = render_w
            self._chafa_config.height = render_h

        # Convert to RGBA for Chafa
        frame_rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        pixels = frame_rgba.tobytes()

        # Render with Chafa
        canvas = chafa.Canvas(self._chafa_config)
        canvas.draw_all_pixels(chafa.PixelMode.RGBA8, pixels, w, h, w * 4)
        ansi_output = canvas.print().decode("utf-8")

        # Update TUI
        self.query_one("#vid-render", Static).update(Text.from_ansi(ansi_output))

        # Schedule next frame
        delay = 1.0 / self._fps
        self._timer = asyncio.get_event_loop().call_later(delay, self._step_frame)

    def on_unmount(self) -> None:
        self.stop()
