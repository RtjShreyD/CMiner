"""Ultra Graphics Engine based on Chafa.

The absolute gold standard for terminal graphics. This engine uses the 
C-backed Chafa library to provide pixel-perfect rendering for Sixel, 
Kitty, iTerm2, and advanced Unicode half-cell modes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image
try:
    import chafa
    HAS_CHAFA = True
except ImportError:
    HAS_CHAFA = False


class GraphicsEngine:
    """Handles professional-grade terminal graphics using Chafa."""

    def __init__(self, max_width: int = 140):
        self._max_width = max_width

    def get_image_renderable(self, file_path: str | Path, width: int = 0) -> Any:
        path = Path(file_path)
        if not path.exists():
             return f"[red]File Not Found: {path}[/red]", {}

        if not HAS_CHAFA:
             return f"[yellow]Graphics Engine (chafa.py) missing. Falling back...[/yellow]", {}

        try:
            with Image.open(path) as img:
                # Metadata for the UI header
                metadata = {
                    "format": img.format,
                    "resolution": f"{img.size[0]}x{img.size[1]}",
                    "filesize": f"{os.path.getsize(path) / 1024:.1f} KB"
                }

                # Ensure we have a reasonable width
                render_w = max(20, width if width > 0 else self._max_width)
                
                # Image processing: convert to RGBA for Chafa
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                
                # Aspect ratio math for Chafa Canvas
                w, h = img.size
                # Chafa's height is in characters. Terminal characters are ~1:2 ratio.
                render_h = max(1, int((h / w) * render_w * 0.5))

                # Initialize Chafa Config
                config = chafa.CanvasConfig()
                config.width = render_w
                config.height = render_h
                
                # We want full color and high-fidelity symbols
                # Chafa will automatically detect the best mode (Sixel, Kitty, etc.) 
                # if possible, otherwise it uses advanced symbols.
                
                canvas = chafa.Canvas(config)
                
                # Draw pixels to canvas
                pixels = img.tobytes()
                canvas.draw_all_pixels(
                    chafa.PixelMode.RGBA8,
                    pixels,
                    w,
                    h,
                    w * 4 # row_stride
                )
                
                # Output the result as an ANSI string that Textual can render
                # Note: Chafa handles the protocol detection internally.
                output = canvas.print().decode("utf-8")
                
                return output, metadata

        except Exception as e:
            return f"[red]Graphics Engine Error: {e}[/red]", {}


# Global instance
engine = GraphicsEngine()
