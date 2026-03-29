"""Log Panel Widget — Scrollable log viewer with controls."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widget import Widget
from textual.widgets import RichLog, Static, Button


class LogPanel(Widget):
    """A log output panel with auto-scroll and a clear button.

    Usage:
        panel = LogPanel(title="Pipeline Output")
        panel.write("Step 1 complete")
        panel.write("[green]✓ Success[/green]")
    """

    DEFAULT_CSS = """
    LogPanel {
        height: 100%;
        width: 100%;
    }
    """

    def __init__(self, title: str = "Logs", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="log-panel"):
            with Horizontal(classes="log-header"):
                yield Static(f" 📋 {self._title}")
                yield Button("Clear", variant="default", classes="btn-secondary", id="log-clear")
            yield RichLog(highlight=True, markup=True, wrap=True, id="log-output")

    def write(self, text: str) -> None:
        """Append a line to the log output."""
        try:
            log = self.query_one("#log-output", RichLog)
            log.write(text)
        except Exception:
            pass

    def clear(self) -> None:
        """Clear all log content."""
        try:
            log = self.query_one("#log-output", RichLog)
            log.clear()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "log-clear":
            self.clear()
