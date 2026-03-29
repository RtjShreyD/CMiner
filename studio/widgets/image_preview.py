"""Image Preview Widget — Renders images in the terminal using rich-pixels."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.widget import Widget
from textual.widgets import Static
from textual.containers import VerticalScroll

from PIL import Image
from rich_pixels import Pixels


class ImagePreview(Static):
    """Displays an image file rendered as terminal pixels.

    Usage:
        preview = ImagePreview()
        preview.load("/path/to/image.png")
    """

    DEFAULT_CSS = """
    ImagePreview {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
        padding: 0;
    }
    """

    def __init__(
        self,
        file_path: Optional[str] = None,
        max_width: int = 80,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._file_path: Optional[Path] = Path(file_path) if file_path else None
        self._max_width = max_width

    def on_mount(self) -> None:
        if self._file_path:
            self.load(str(self._file_path))

    def load(self, file_path: str) -> None:
        """Load and render an image file."""
        path = Path(file_path)
        if not path.exists():
            self.update(f"[red]File not found: {path}[/red]")
            return

        suffix = path.suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            self.update(f"[yellow]Unsupported image format: {suffix}[/yellow]")
            return

        try:
            with Image.open(path) as img:
                # Resize to fit terminal width while preserving aspect ratio
                # Terminal chars are ~2x taller than wide, so we halve height
                w, h = img.size
                scale = min(self._max_width / w, 1.0)
                new_w = int(w * scale)
                new_h = int(h * scale)
                resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                pixels = Pixels.from_image(resized)
                self.update(pixels)

        except Exception as e:
            self.update(f"[red]Error loading image: {e}[/red]")

    def clear_preview(self) -> None:
        """Clear the current preview."""
        self.update("")
