"""Image Preview Widget — Renders images in the terminal using rich-pixels."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import VerticalScroll

from PIL import Image


from studio.widgets.graphics_engine import engine


class ImagePreview(Static):
    """Displays an image file with high-fidelity terminal graphics.

    Usage:
        preview = ImagePreview()
        preview.load("/path/to/image.png")
    """

    DEFAULT_CSS = """
    ImagePreview {
        width: 100%;
        height: auto;
        padding: 1 2;
        background: $surface;
    }

    #img-meta {
        color: #fdcb6e;
        margin-bottom: 1;
        text-style: italic;
    }

    #img-render {
        width: 100%;
        height: auto;
    }
    """

    def __init__(
        self,
        file_path: Optional[str] = None,
        max_width: int = 140,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._file_path: Optional[Path] = Path(file_path) if file_path else None
        self._max_width = max_width

    def compose(self) -> ComposeResult:
        yield Static("", id="img-meta")
        yield Static("", id="img-render")

    def on_mount(self) -> None:
        if self._file_path:
            self.load(str(self._file_path))

    def load(self, file_path: str) -> None:
        """Load and render an image file with best-available graphics protocol."""
        path = Path(file_path)
        if not path.exists():
            self.query_one("#img-render", Static).update(f"[red]File Not Found: {path}[/red]")
            return

        # Show loading state
        self.query_one("#img-meta", Static).update(f"[dim]⚡ Loading {path.name}...[/dim]")
        self.query_one("#img-render", Static).update("")

        try:
            # Use engine for high-res render and metadata
            # We pass current widget width if it has one (minus padding)
            w = self.size.width - 4 if self.size.width > 20 else self._max_width
            result, metadata = engine.get_image_renderable(path, width=w)

            if isinstance(result, str) and result.startswith("[red]"):
                self.query_one("#img-render", Static).update(result)
            else:
                # Update metadata label
                meta_text = (
                    f"Dimensions: [bold]{metadata['resolution']}[/bold] | "
                    f"Format: [bold]{metadata['format']}[/bold] | "
                    f"Size: [bold]{metadata['filesize']}[/bold]"
                )
                self.query_one("#img-meta", Static).update(meta_text)

                # Update render area
                # For Chafa, result is the ANSI string. 
                # We wrap it in Text.from_ansi to preserve colors/protocols for Rich.
                from rich.text import Text
                self.query_one("#img-render", Static).update(Text.from_ansi(result))

        except Exception as e:
            self.query_one("#img-render", Static).update(f"[red]Rendering Error: {e}[/red]")

    def clear_preview(self) -> None:
        """Clear the current preview."""
        self.update("")
