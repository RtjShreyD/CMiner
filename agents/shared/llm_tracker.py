"""
LLM Usage Tracker – Decorator + context manager for tracking all Gemini API calls.

Usage:
    from agents.shared.llm_tracker import LLMTracker, tracked_generate

    tracker = LLMTracker()
    model = genai.GenerativeModel("models/gemini-flash-latest")
    response = tracked_generate(tracker, model, prompt_or_parts, purpose="episode_planner")
    tracker.save(session_dir)
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class LLMTracker:
    """Accumulates LLM call metadata across a pipeline run."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    # ── recording ──────────────────────────────────────────────

    def record(
        self,
        model_name: str,
        purpose: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        self.calls.append({
            "model": model_name,
            "purpose": purpose,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "duration_ms": round(duration_ms, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ── persistence ────────────────────────────────────────────

    def save(self, session_dir: Path) -> Path:
        """Write accumulated usage to llm_usage.json in the session directory."""
        total_input = sum(c["input_tokens"] for c in self.calls)
        total_output = sum(c["output_tokens"] for c in self.calls)
        models_used = sorted(set(c["model"] for c in self.calls))

        report = {
            "total_calls": len(self.calls),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "models_used": models_used,
            "calls": self.calls,
        }

        out_path = session_dir / "llm_usage.json"
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"LLM Usage Report saved → {out_path}")
        print(f"  Total calls: {len(self.calls)}  |  Tokens: {total_input} in / {total_output} out")
        return out_path

    # ── summary ────────────────────────────────────────────────

    def summary(self) -> str:
        total_input = sum(c["input_tokens"] for c in self.calls)
        total_output = sum(c["output_tokens"] for c in self.calls)
        return (
            f"LLM Tracker: {len(self.calls)} calls, "
            f"{total_input} input tokens, {total_output} output tokens"
        )


def tracked_generate(
    tracker: Optional["LLMTracker"],
    model: Any,
    contents: Any,
    *,
    purpose: str = "unknown",
) -> Any:
    """
    Call model.generate_content(contents) while tracking usage.

    Works as a drop-in wrapper:
        response = tracked_generate(tracker, model, prompt, purpose="planner")

    If tracker is None the call still goes through – just untracked.
    """
    model_name = getattr(model, "model_name", str(model))

    t0 = time.perf_counter()
    response = model.generate_content(contents)
    duration_ms = (time.perf_counter() - t0) * 1000

    # Extract token counts from response metadata (Gemini SDK)
    input_tokens = 0
    output_tokens = 0
    usage = getattr(response, "usage_metadata", None)
    if usage:
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

    if tracker is not None:
        tracker.record(
            model_name=model_name,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
        )

    return response
