"""Agent Card Widget — Displays agent summary information."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, Button


@dataclass
class AgentInfo:
    """Data class representing an agent's metadata."""

    name: str
    agent_id: str
    description: str
    icon: str = "🤖"
    session_count: int = 0
    last_status: str = "idle"


class AgentCard(Widget):
    """A clickable card that summarises an agent.

    Posts an `AgentCard.Selected` message when clicked.
    """

    DEFAULT_CSS = """
    AgentCard {
        height: auto;
        min-height: 8;
    }
    """

    class Selected(Message):
        """Sent when the user clicks 'Launch' on an agent card."""

        def __init__(self, agent_info: AgentInfo) -> None:
            super().__init__()
            self.agent_info = agent_info

    def __init__(self, agent_info: AgentInfo, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent_info = agent_info

    def compose(self) -> ComposeResult:
        info = self.agent_info
        status_class = {
            "idle": "text-dim",
            "running": "badge-success",
            "complete": "badge-success",
            "error": "badge-error",
        }.get(info.last_status, "text-dim")

        with Vertical(classes="agent-card"):
            yield Static(
                f"{info.icon}  {info.name}",
                classes="agent-card-title",
            )
            yield Static(info.description, classes="agent-card-desc")
            yield Static(
                f"Sessions: {info.session_count}  •  Status: [{status_class}]{info.last_status}[/]",
                classes="agent-card-stats",
            )
            yield Button("Launch ▶", variant="primary", classes="btn-primary", id=f"launch-{info.agent_id}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("launch-"):
            self.post_message(self.Selected(self.agent_info))
