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

                # Provide appropriate width based on Textual widget constraints
                render_w = width if width > 0 else self._max_width

                # Calculate height proportional to terminal aspect ratio (character is ~1:2)
                # Setting both width & height explicitly bypasses term-image's internal
                # checks against the active terminal bounds, which fail inside Textual.
                w, h = img.size
                
                # Protect against Textual layout lifecycle passing <= 0 widths temporarily
                safe_render_w = max(10, render_w) 
                
                render_h = max(1, int((h / w) * safe_render_w * 0.5))
                timg.set_size(width=safe_render_w, height=render_h)

                # term-image provides a __str__ that returns ANSI
                # We bypass __str__ directly to prevent terminal window bounds matching
                # which causes crashes if the Textual layout is still calculating dimensions.
                try:
                    ansi_render = timg._renderer(
                        timg._render_image, 
                        getattr(timg, '_ALPHA_THRESHOLD', None), 
                        check_size=False
                    )
                except AttributeError:
                    # Fallback if internal API changes
                    ansi_render = str(timg)
                    
                return ansi_render, metadata

        except Exception as e:
            return f"[red]Graphics Engine Error: {e}[/red]", {}


# Global instance for easy access
engine = GraphicsEngine()
