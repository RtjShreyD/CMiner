"""CMiner root CLI for managing and running agents."""

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


    parser.add_argument("--target-agent", default="newsAligator", help="Target agent used by rootAgent")
    parser.add_argument(
        "--use-nemoclaw",
        action="store_true",
        help="When running rootAgent, route orchestration to nemoclawAgent",
    )
    return parser.parse_args(argv)


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
        help="Run OpenClaw podcasting report pipeline",
        description="Run OpenClaw podcasting report pipeline",
    )
    podcasting_parser.add_argument("--workspace", default=".", help="Workspace root")
    podcasting_parser.add_argument("--agent", default="podcaster", help="OpenClaw agent id")
    podcasting_parser.add_argument("--openclaw-bin", default="openclaw", help="OpenClaw binary path")
    podcasting_parser.add_argument("--prompt", required=True, help="User prompt for the podcast")
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
    script = ROOT / "tools" / "newsdesk" / "run_newsdesk.py"
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
    prompt: str,
    thinking: str,
) -> int:
    script = ROOT / "tools" / "podcasting" / "run.py"
    venv_python = ROOT / ".venv" / "bin" / "python3"
    
    cmd = [
        str(venv_python) if venv_python.exists() else sys.executable,
        str(script),
        "--workspace",
        workspace,
        "--agent",
        agent,
        "--openclaw-bin",
        openclaw_bin,
        "--prompt",
        prompt,
        "--thinking",
        thinking,
    ]
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
            )
        )


    parser.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
