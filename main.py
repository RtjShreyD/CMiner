"""CMiner root CLI for managing and running functools."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def _load_root_config() -> dict[str, Any]:
    cfg_path = ROOT / "config.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CMiner CLI")
    subparsers = parser.add_subparsers(dest="command")

    openclaw_parser = subparsers.add_parser(
        "openclaw",
        help="Pass through to OpenClaw CLI",
        description="Pass through to OpenClaw CLI",
    )
    openclaw_parser.add_argument(
        "openclaw_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to openclaw",
    )

    newsdesk_parser = subparsers.add_parser(
        "newsdesk",
        help="Run OpenClaw newsdesk report pipeline",
        description="Run OpenClaw newsdesk report pipeline",
    )
    newsdesk_parser.add_argument("--workspace", default=".", help="Workspace root")
    newsdesk_parser.add_argument("--agent", default="newsaligator", help="OpenClaw agent id")
    newsdesk_parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    newsdesk_parser.add_argument("--hours", type=int, default=24, help="Time window in hours")
    newsdesk_parser.add_argument("--articles", type=int, default=12, help="Number of articles")
    newsdesk_parser.add_argument(
        "--thinking",
        choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        default="high",
        help="OpenClaw thinking level",
    )
    newsdesk_parser.add_argument(
        "--insta-count",
        type=int,
        default=5,
        help="Number of Instagram slides (clamped to 4-5 by pipeline)",
    )
    
    podcasting_parser = subparsers.add_parser(
        "podcasting",
        help="Run podcasting agent pipeline",
        description="Run podcasting agent pipeline (Modular Step-by-Step or End-to-End)",
    )
    podcasting_parser.add_argument("--workspace", default=".", help="Workspace root")
    podcasting_parser.add_argument("--agent", default="podcaster", help="OpenClaw agent id")
    podcasting_parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    podcasting_parser.add_argument("--prompt", help="User prompt for the podcast")
    podcasting_parser.add_argument("--script", help="Path to a script text file")
    podcasting_parser.add_argument("--char", action="append", help="Path to a character image (up to 3)")
    podcasting_parser.add_argument("--scene", help="Path to a scene background image")
    podcasting_parser.add_argument("--step", choices=["all", "planner", "images", "audio", "clouds", "video"], default="all", help="Execute specific pipeline step")
    podcasting_parser.add_argument("--session", help="Continue work in an existing session directory")
    podcasting_parser.add_argument(
        "--thinking",
        choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        default="high",
        help="OpenClaw thinking level",
    )

    return parser



def _run_openclaw_passthrough(openclaw_args: list[str]) -> int:
    cmd = ["openclaw", *openclaw_args]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _run_newsdesk(
    workspace: str,
    agent: str,
    openclaw_bin: str,
    hours: int,
    articles: int,
    thinking: str,
    insta_count: int,
) -> int:
    script = ROOT / "agents" / "newsdesk" / "run_newsdesk.py"
    cmd = [
        sys.executable,
        str(script),
        "--workspace",
        workspace,
        "--agent",
        agent,
        "--openclaw-bin",
        openclaw_bin,
        "--hours",
        str(hours),
        "--articles",
        str(articles),
        "--thinking",
        thinking,
        "--insta-count",
        str(insta_count),
    ]
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _run_podcasting(
    workspace: str,
    agent: str,
    openclaw_bin: str,
    prompt: str | None,
    thinking: str,
    script: str | None = None,
    char: list[str] | None = None,
    scene: str | None = None,
    step: str = "all",
    session: str | None = None,
) -> int:
    runner_link = ROOT / "agents" / "podcasting" / "run.py"
    venv_python = ROOT / ".venv" / "bin" / "python3"
    
    cmd = [
        str(venv_python) if venv_python.exists() else sys.executable,
        str(runner_link),
        "--workspace",
        workspace,
        "--agent",
        agent,
        "--openclaw-bin",
        openclaw_bin,
        "--thinking",
        thinking,
        "--step",
        step,
    ]
    if prompt:
        cmd.extend(["--prompt", prompt])
    if script:
        cmd.extend(["--script", script])
    if char:
        for c in char:
            cmd.extend(["--char", c])
    if scene:
        cmd.extend(["--scene", scene])
    if session:
        cmd.extend(["--session", session])
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args(sys.argv[1:])

    if args.command == "openclaw":
        raise SystemExit(_run_openclaw_passthrough(args.openclaw_args))

    if args.command == "newsdesk":
        raise SystemExit(
            _run_newsdesk(
                workspace=args.workspace,
                agent=args.agent,
                openclaw_bin=args.openclaw_bin,
                hours=args.hours,
                articles=args.articles,
                thinking=args.thinking,
                insta_count=args.insta_count,
            )
        )

    if args.command == "podcasting":
        raise SystemExit(
            _run_podcasting(
                workspace=args.workspace,
                agent=args.agent,
                openclaw_bin=args.openclaw_bin,
                prompt=args.prompt,
                thinking=args.thinking,
                script=args.script,
                char=args.char,
                scene=args.scene,
                step=args.step,
                session=args.session,
            )
        )


    parser.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
