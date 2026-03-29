"""High-fidelity Graphics Engine for terminal image rendering."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Any

from PIL import Image
from term_image.image import AutoImage, BlockImage


class GraphicsEngine:
    """Handles terminal-agnostic high-fidelity image rendering."""

    def __init__(self, max_width: int = 120):
        self._max_width = max_width

    def get_image_renderable(self, file_path: str | Path, width: int = 0) -> Any:
        # width=0 means auto-calculate inside term-image relative to terminal size
        path = Path(file_path)
        if not path.exists():
             return f"[red]File Not Found: {path}[/red]"

        try:
            with Image.open(path) as img:
                # Get the metadata for later
                metadata = {
                    "format": img.format,
                    "resolution": f"{img.size[0]}x{img.size[1]}",
                    "filesize": f"{os.path.getsize(path) / 1024:.1f} KB"
                }

                # Dynamically choose the best renderer for this image/terminal combo
                timg = AutoImage(img)

                # Set sizes. Note: Term-image uses cell dimensions.
                # If width is provided externally (from Textual widget), use it.
                if width > 0:
                    render_w = width
                else:
                    render_w = self._max_width

                # timg uses (columns, lines) for size.
                # If we don't set height, it preserves aspect ratio.
                timg.set_size(columns=render_w)

                # term-image provides a __str__ that returns ANSI
                return timg, metadata

        except Exception as e:
            return f"[red]Graphics Engine Error: {e}[/red]", {}


# Global instance for easy access
engine = GraphicsEngine()
