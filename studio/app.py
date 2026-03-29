"""CMiner Studio — Main Textual Application Shell.

This is the root application that manages navigation and layout
for the terminal-based AI content creation studio.

Screens (Dashboard, SessionExplorer, AgentLaunch) are mounted as
content widgets inside the main-content pane (not as Textual Screens)
so the sidebar remains persistent.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, Button

from studio.screens.dashboard import DashboardPanel
from studio.screens.session_explorer import SessionExplorerPanel
from studio.screens.agent_launch import AgentLaunchPanel


# ─── Constants ────────────────────────────────────────────────

STUDIO_ROOT = Path(__file__).resolve().parent
CSS_PATH = STUDIO_ROOT / "styles" / "studio.tcss"
APP_TITLE = "CMiner Studio"
APP_SUB_TITLE = "AI Content Creation Terminal"


class CMinerStudioApp(App):
    """The root CMiner Studio TUI application."""

    TITLE = APP_TITLE
    SUB_TITLE = APP_SUB_TITLE
    CSS_PATH = str(CSS_PATH)

    BINDINGS = [
        Binding("d", "show_dashboard", "Dashboard", key_display="d"),
        Binding("s", "show_sessions", "Sessions", key_display="s"),
        Binding("m", "launch_manga", "Manga", key_display="m"),
        Binding("p", "launch_podcast", "Podcast", key_display="p"),
        Binding("n", "launch_newsdesk", "Newsdesk", key_display="n"),
        Binding("q", "quit", "Quit", key_display="q"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():
            # ── Persistent Sidebar ──
            with Vertical(id="sidebar"):
                yield Static("⚡ CMINER", id="sidebar-title")
                yield Button("📊 Dashboard", classes="nav-btn -active", id="nav-dashboard")
                yield Button("📂 Sessions", classes="nav-btn", id="nav-sessions")
                yield Static("─" * 30)
                yield Button("🎬 Manga", classes="nav-btn", id="nav-manga")
                yield Button("🎙️ Podcast", classes="nav-btn", id="nav-podcast")
                yield Button("📰 Newsdesk", classes="nav-btn", id="nav-newsdesk")

            # ── Main Content (swappable) ──
            with Vertical(id="main-content"):
                yield DashboardPanel()

        yield Footer()

    # ─── Navigation helpers ───────────────────────────────────

    def _switch_content(self, widget) -> None:
        """Replace the main content area with a new widget."""
        container = self.query_one("#main-content")
        container.remove_children()
        container.mount(widget)

    def _update_nav(self, active_id: str) -> None:
        """Highlight the active sidebar button."""
        for btn in self.query(".nav-btn"):
            btn.remove_class("-active")
        try:
            self.query_one(f"#{active_id}").add_class("-active")
        except Exception:
            pass

    # ─── Actions (keybindings + buttons) ──────────────────────

    def action_show_dashboard(self) -> None:
        self._switch_content(DashboardPanel())
        self._update_nav("nav-dashboard")

    def action_show_sessions(self) -> None:
        self._switch_content(SessionExplorerPanel())
        self._update_nav("nav-sessions")

    def action_launch_agent(self, agent_id: str) -> None:
        nav_map = {
            "narrativeManga": "nav-manga",
            "podcasting": "nav-podcast",
            "newsdesk": "nav-newsdesk",
        }
        self._switch_content(AgentLaunchPanel(agent_id=agent_id))
        self._update_nav(nav_map.get(agent_id, ""))

    def action_launch_manga(self) -> None:
        self.action_launch_agent("narrativeManga")

    def action_launch_podcast(self) -> None:
        self.action_launch_agent("podcasting")

    def action_launch_newsdesk(self) -> None:
        self.action_launch_agent("newsdesk")

    # ─── Sidebar button routing ───────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "nav-dashboard":
            self.action_show_dashboard()
        elif btn_id == "nav-sessions":
            self.action_show_sessions()
        elif btn_id == "nav-manga":
            self.action_launch_manga()
        elif btn_id == "nav-podcast":
            self.action_launch_podcast()
        elif btn_id == "nav-newsdesk":
            self.action_launch_newsdesk()
