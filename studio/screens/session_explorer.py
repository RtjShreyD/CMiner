"""Session Explorer Panel — Directory tree + file preview."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    DirectoryTree,
    Static,
    Button,
    RichLog,
)

from studio.widgets.image_preview import ImagePreview


# ─── File type helpers ────────────────────────────────────────

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MEDIA_EXTS = {".mp4", ".mp3", ".wav", ".mkv", ".avi", ".ogg"}
TEXT_EXTS = {".json", ".txt", ".md", ".py", ".csv", ".log", ".yaml", ".yml", ".toml"}


def _file_category(path: Path) -> str:
    """Classify a file into a preview category."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in MEDIA_EXTS:
        return "media"
    if ext in TEXT_EXTS:
        return "text"
    return "unknown"


class SessionExplorerPanel(Widget):
    """Dual-pane session explorer with directory tree and file preview."""

    DEFAULT_CSS = """
    SessionExplorerPanel {
        width: 100%;
        height: 100%;
    }

    #explorer-container {
        width: 100%;
        height: 100%;
    }

    #tree-pane {
        width: 38;
        height: 100%;
        border-right: tall #3d3d5c;
    }

    #tree-title {
        background: #2d2d44;
        color: #00cec9;
        text-style: bold;
        padding: 1 2;
        text-align: center;
        width: 100%;
    }

    #preview-pane {
        width: 1fr;
        height: 100%;
        padding: 1 2;
    }

    #preview-header {
        height: 3;
        padding: 0 1;
    }

    #preview-filename {
        color: #a29bfe;
        text-style: bold;
    }

    #preview-body {
        height: 1fr;
        width: 100%;
    }

    #open-external-btn {
        dock: right;
    }
    """

    def __init__(self, outputs_dir: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._outputs_dir = Path(outputs_dir) if outputs_dir else Path.cwd() / "outputs"
        self._selected_path: Path | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="explorer-container"):
            # Left pane: directory tree
            with Vertical(id="tree-pane"):
                yield Static("📂 Sessions", id="tree-title")
                if self._outputs_dir.exists():
                    yield DirectoryTree(str(self._outputs_dir), id="session-tree")
                else:
                    yield Static("[dim]No outputs/ directory found. Run an agent first.[/dim]")

            # Right pane: preview
            with Vertical(id="preview-pane"):
                with Horizontal(id="preview-header"):
                    yield Static("Select a file to preview", id="preview-filename")
                    yield Button(
                        "Open ↗",
                        variant="default",
                        classes="btn-secondary",
                        id="open-external-btn",
                        disabled=True,
                    )
                with VerticalScroll(id="preview-body"):
                    yield ImagePreview(id="img-preview")
                    yield RichLog(
                        highlight=True,
                        markup=True,
                        wrap=True,
                        id="text-preview",
                    )

    def on_mount(self) -> None:
        # Hide both previews until a file is selected
        self.query_one("#img-preview").display = False
        self.query_one("#text-preview").display = False

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle file selection from the directory tree."""
        path = Path(event.path)
        self._selected_path = path
        filename_label = self.query_one("#preview-filename", Static)
        filename_label.update(f"📄 {path.name}")

        category = _file_category(path)
        img_preview = self.query_one("#img-preview", ImagePreview)
        text_preview = self.query_one("#text-preview", RichLog)
        open_btn = self.query_one("#open-external-btn", Button)

        # Reset
        img_preview.display = False
        text_preview.display = False
        open_btn.disabled = True

        if category == "image":
            img_preview.display = True
            img_preview.load(str(path))

        elif category == "text":
            text_preview.display = True
            text_preview.clear()
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if path.suffix.lower() == ".json":
                    try:
                        parsed = json.loads(content)
                        content = json.dumps(parsed, indent=2)
                    except json.JSONDecodeError:
                        pass
                if len(content) > 50_000:
                    content = content[:50_000] + "\n\n[dim]... (truncated)[/dim]"
                text_preview.write(content)
            except Exception as e:
                text_preview.write(f"[red]Error reading file: {e}[/red]")

        elif category == "media":
            text_preview.display = True
            text_preview.clear()
            size_mb = path.stat().st_size / (1024 * 1024)
            text_preview.write(f"[bold]{path.name}[/bold]")
            text_preview.write(f"Type: {path.suffix.upper()} media file")
            text_preview.write(f"Size: {size_mb:.1f} MB")
            text_preview.write("")
            text_preview.write("[dim]Click 'Open ↗' to play in your system player.[/dim]")
            open_btn.disabled = False

        else:
            text_preview.display = True
            text_preview.clear()
            text_preview.write(f"[yellow]Unsupported file type: {path.suffix}[/yellow]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-external-btn":
            if self._selected_path and self._selected_path.exists():
                try:
                    subprocess.Popen(
                        ["xdg-open", str(self._selected_path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except FileNotFoundError:
                    self.app.notify("xdg-open not found.", severity="error")
