"""Dashboard Panel — Overview of all agents and recent sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.widget import Widget
from textual.widgets import Static

from studio.widgets.agent_card import AgentCard, AgentInfo


# ─── Agent Registry ──────────────────────────────────────────

AGENTS: list[AgentInfo] = [
    AgentInfo(
        name="NarrativeManga",
        agent_id="narrativeManga",
        description="Episodic manga-style video generation with character consistency and plot continuity.",
        icon="🎬",
    ),
    AgentInfo(
        name="Podcasting",
        agent_id="podcasting",
        description="Cinematic text-to-video podcasts with character & scene consistency.",
        icon="🎙️",
    ),
    AgentInfo(
        name="Newsdesk",
        agent_id="newsdesk",
        description="Automated news gathering, analysis reports and Instagram carousels.",
        icon="📰",
    ),
]


def _count_sessions(outputs_dir: Path, agent_id: str) -> int:
    """Count sessions belonging to a specific agent under outputs/."""
    count = 0
    if not outputs_dir.exists():
        return 0
    for session_dir in outputs_dir.iterdir():
        if session_dir.is_dir():
            agent_dir = session_dir / agent_id
            if agent_dir.is_dir():
                count += 1
    return count


def _get_recent_sessions(outputs_dir: Path, limit: int = 8) -> list[dict[str, Any]]:
    """Scan outputs/ for recent sessions with metadata."""
    sessions = []
    if not outputs_dir.exists():
        return sessions

    for session_dir in sorted(outputs_dir.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        for agent_dir in session_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            state_file = agent_dir / "session_state.json"
            status = "unknown"
            title = ""
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text())
                    ep_data = state.get("episodes", {})
                    latest = state.get("latest_episode", 0)
                    if str(latest) in ep_data:
                        status = ep_data[str(latest)].get("status", "unknown")
                        title = ep_data[str(latest)].get("title", "")
                except Exception:
                    pass

            sessions.append({
                "session_id": session_dir.name,
                "agent": agent_dir.name,
                "status": status,
                "title": title,
                "path": str(agent_dir),
            })

        if len(sessions) >= limit:
            break

    return sessions[:limit]


def _status_badge(status: str) -> str:
    """Return a colored status badge string."""
    badges = {
        "complete": "[green]● DONE[/green]",
        "planned": "[yellow]◐ PLAN[/yellow]",
        "running": "[blue]◉ RUN [/blue]",
        "error": "[red]✖ ERR [/red]",
    }
    return badges.get(status, "[dim]○ ----[/dim]")


class DashboardPanel(Widget):
    """Main dashboard showing agents and recent sessions."""

    DEFAULT_CSS = """
    DashboardPanel {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        outputs_dir = Path.cwd() / "outputs"

        # Enrich agent info with session counts
        for agent in AGENTS:
            agent.session_count = _count_sessions(outputs_dir, agent.agent_id)

        yield Static("⚡ CMiner Studio — Dashboard", id="dashboard-title")

        with VerticalScroll(id="dashboard"):
            # ─── Agent Grid ───
            with Horizontal(id="agent-grid"):
                for agent in AGENTS:
                    yield AgentCard(agent)

            # ─── Recent Sessions ───
            with Vertical(id="recent-sessions"):
                yield Static("📂 Recent Sessions", id="recent-title")

                sessions = _get_recent_sessions(outputs_dir)
                if not sessions:
                    yield Static(
                        "[dim]No sessions found. Launch an agent to get started.[/dim]"
                    )
                else:
                    for s in sessions:
                        badge = _status_badge(s["status"])
                        label = s.get("title") or s["session_id"]
                        yield Static(
                            f"  {badge}  [{s['agent']}]  {label}  "
                            f"[dim]({s['session_id']})[/dim]",
                            classes="session-row",
                        )

    def on_agent_card_selected(self, event: AgentCard.Selected) -> None:
        """Forward agent selection to the app for screen switching."""
        self.app.action_launch_agent(event.agent_info.agent_id)
