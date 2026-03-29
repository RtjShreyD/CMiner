"""Agent Launch Panel — Form-based agent configuration and async execution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import (
    Static,
    Input,
    Select,
    Button,
    Checkbox,
)

from studio.widgets.log_panel import LogPanel


# ─── Agent Form Definitions ──────────────────────────────────

AGENT_FORMS = {
    "narrativeManga": {
        "title": "🎬 NarrativeManga",
        "fields": [
            {"id": "prompt", "label": "Prompt (optional)", "type": "input", "placeholder": "Override prompt.txt..."},
            {"id": "session", "label": "Session Directory", "type": "input", "placeholder": "outputs/XXXXXXX/narrativeManga"},
            {
                "id": "step",
                "label": "Pipeline Step",
                "type": "select",
                "options": [
                    ("All (End-to-End)", "all"),
                    ("Planner", "planner"),
                    ("Characters", "chars"),
                    ("Scenes", "scenes"),
                    ("Audio (TTS)", "audio"),
                    ("Clouds (Speech Bubbles)", "clouds"),
                    ("Video (Final Render)", "video"),
                ],
            },
            {
                "id": "episodes",
                "label": "Episode Mode",
                "type": "select",
                "options": [
                    ("New Series", "new"),
                    ("Continue Series", "continue"),
                ],
            },
            {"id": "develop", "label": "Auto-develop after planning", "type": "checkbox"},
        ],
    },
    "podcasting": {
        "title": "🎙️ Podcasting",
        "fields": [
            {"id": "prompt", "label": "Podcast Topic", "type": "input", "placeholder": "A debate about AI ethics..."},
            {"id": "session", "label": "Session Directory", "type": "input", "placeholder": "outputs/XXXXXXX/podCasting"},
            {
                "id": "step",
                "label": "Pipeline Step",
                "type": "select",
                "options": [
                    ("All", "all"),
                    ("Planner", "planner"),
                    ("Images", "images"),
                    ("Audio", "audio"),
                    ("Clouds", "clouds"),
                    ("Video", "video"),
                ],
            },
        ],
    },
    "newsdesk": {
        "title": "📰 Newsdesk",
        "fields": [
            {"id": "hours", "label": "Time Window (hours)", "type": "input", "placeholder": "24"},
            {"id": "articles", "label": "Number of Articles", "type": "input", "placeholder": "12"},
        ],
    },
}


class AgentLaunchPanel(Widget):
    """Form panel to configure and launch agent pipelines with live log streaming."""

    DEFAULT_CSS = """
    AgentLaunchPanel {
        width: 100%;
        height: 100%;
    }

    #launch-container {
        width: 100%;
        height: 100%;
    }

    #form-pane {
        width: 50;
        height: 100%;
        border-right: tall #3d3d5c;
        padding: 1 2;
    }

    #form-title {
        color: #00cec9;
        text-style: bold;
        padding: 1 0;
        text-align: center;
    }

    #output-pane {
        width: 1fr;
        height: 100%;
    }

    .form-field {
        margin-bottom: 1;
        height: auto;
    }

    .field-label {
        color: #a29bfe;
        padding: 0 0 0 1;
    }

    #action-bar {
        height: 5;
        padding: 1 2;
        dock: bottom;
    }
    """

    def __init__(self, agent_id: str = "narrativeManga", **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent_id = agent_id
        self._process: Optional[asyncio.subprocess.Process] = None

    def compose(self) -> ComposeResult:
        form_def = AGENT_FORMS.get(self._agent_id, AGENT_FORMS["narrativeManga"])

        with Horizontal(id="launch-container"):
            # Left: Configuration form
            with Vertical(id="form-pane"):
                yield Static(f"{form_def['title']} — Configuration", id="form-title")

                with VerticalScroll():
                    for field in form_def["fields"]:
                        with Vertical(classes="form-field"):
                            yield Static(field["label"], classes="field-label")

                            if field["type"] == "input":
                                yield Input(
                                    placeholder=field.get("placeholder", ""),
                                    id=f"field-{field['id']}",
                                )
                            elif field["type"] == "select":
                                yield Select(
                                    [(label, value) for label, value in field["options"]],
                                    id=f"field-{field['id']}",
                                    allow_blank=False,
                                )
                            elif field["type"] == "checkbox":
                                yield Checkbox(
                                    field["label"],
                                    id=f"field-{field['id']}",
                                )

                with Horizontal(id="action-bar"):
                    yield Button(
                        "▶ Run Pipeline",
                        variant="success",
                        classes="btn-primary",
                        id="btn-run",
                    )
                    yield Button(
                        "⏹ Stop",
                        variant="error",
                        classes="btn-danger",
                        id="btn-stop",
                        disabled=True,
                    )

            # Right: Live output
            with Vertical(id="output-pane"):
                yield LogPanel(title=f"{form_def['title']} Output", id="pipeline-log")

    def _collect_form_values(self) -> dict[str, str]:
        """Read all form field values."""
        values = {}
        form_def = AGENT_FORMS.get(self._agent_id, {})
        for field in form_def.get("fields", []):
            fid = f"field-{field['id']}"
            try:
                widget = self.query_one(f"#{fid}")
                if field["type"] == "input":
                    values[field["id"]] = widget.value.strip()
                elif field["type"] == "select":
                    values[field["id"]] = str(widget.value)
                elif field["type"] == "checkbox":
                    values[field["id"]] = "true" if widget.value else ""
            except Exception:
                pass
        return values

    def _build_command(self, values: dict[str, str]) -> list[str]:
        """Build the CLI command from form values."""
        venv_python = Path.cwd() / ".venv" / "bin" / "python3"
        python = str(venv_python) if venv_python.exists() else sys.executable

        if self._agent_id == "narrativeManga":
            runner = str(Path.cwd() / "agents" / "narrativeManga" / "run.py")
            cmd = [python, runner]
            if values.get("prompt"):
                cmd.extend(["--prompt", values["prompt"]])
            if values.get("session"):
                cmd.extend(["--session", values["session"]])
            step = values.get("step", "all")
            if step and step != "all":
                cmd.extend(["--step", step])
            if values.get("episodes") == "continue":
                cmd.extend(["--episodes", "continue"])
            if values.get("develop"):
                cmd.append("--develop")
            return cmd

        elif self._agent_id == "podcasting":
            runner = str(Path.cwd() / "agents" / "podcasting" / "run.py")
            cmd = [python, runner]
            if values.get("prompt"):
                cmd.extend(["--prompt", values["prompt"]])
            if values.get("session"):
                cmd.extend(["--session", values["session"]])
            step = values.get("step", "all")
            if step and step != "all":
                cmd.extend(["--step", step])
            return cmd

        elif self._agent_id == "newsdesk":
            runner = str(Path.cwd() / "agents" / "newsdesk" / "run_newsdesk.py")
            cmd = [python, runner]
            if values.get("hours"):
                cmd.extend(["--hours", values["hours"]])
            if values.get("articles"):
                cmd.extend(["--articles", values["articles"]])
            return cmd

        return [python, "-c", "print('Unknown agent')"]

    async def _run_pipeline(self, cmd: list[str]) -> None:
        """Execute the agent pipeline as an async subprocess with live log streaming."""
        log_panel = self.query_one("#pipeline-log", LogPanel)
        log_panel.clear()
        log_panel.write(f"[bold cyan]$ {' '.join(cmd)}[/bold cyan]")
        log_panel.write("")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(Path.cwd()),
            )

            async for line in self._process.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip()
                log_panel.write(decoded)

            exit_code = await self._process.wait()
            log_panel.write("")
            if exit_code == 0:
                log_panel.write("[bold green]✓ Pipeline completed successfully.[/bold green]")
                self.app.notify("Pipeline completed!", severity="information")
            else:
                log_panel.write(f"[bold red]✖ Pipeline exited with code {exit_code}[/bold red]")
                self.app.notify(f"Pipeline failed (exit {exit_code})", severity="error")

        except asyncio.CancelledError:
            if self._process:
                self._process.terminate()
            log_panel.write("[yellow]⏹ Pipeline cancelled.[/yellow]")
        except Exception as e:
            log_panel.write(f"[red]Error: {e}[/red]")
        finally:
            self._process = None
            self._set_running(False)

    def _set_running(self, is_running: bool) -> None:
        """Toggle button states based on pipeline running status."""
        try:
            self.query_one("#btn-run", Button).disabled = is_running
            self.query_one("#btn-stop", Button).disabled = not is_running
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-run":
            values = self._collect_form_values()
            cmd = self._build_command(values)
            self._set_running(True)
            self.run_worker(self._run_pipeline(cmd), thread=False, exclusive=True)

        elif event.button.id == "btn-stop":
            if self._process:
                self._process.terminate()
