"""OVA-specific LLM usage tracking with text/image split reports."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


class OVALLMTracker:
    """Tracks calls and emits both combined and split usage reports."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def record(
        self,
        model_name: str,
        purpose: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        model_type: str,
    ) -> None:
        self.calls.append(
            {
                "model": model_name,
                "model_type": model_type,
                "purpose": purpose,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": round(duration_ms, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    @staticmethod
    def _model_type(model_name: str) -> str:
        return "image" if "image" in model_name.lower() else "text"

    def _merge_existing_calls(self, out_path: Path) -> list[dict[str, Any]]:
        if not out_path.exists():
            return []
        try:
            with open(out_path, "r") as f:
                payload = json.load(f)
            return payload.get("calls", [])
        except Exception:
            return []

    def save(self, session_dir: Path) -> tuple[Path, Path]:
        combined_path = session_dir / "llm_usage.json"
        split_path = session_dir / "llm_usage_by_model_type.json"

        all_calls = self._merge_existing_calls(combined_path) + self.calls
        total_input = sum(c.get("input_tokens", 0) for c in all_calls)
        total_output = sum(c.get("output_tokens", 0) for c in all_calls)

        combined = {
            "total_calls": len(all_calls),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "models_used": sorted(set(c.get("model", "unknown") for c in all_calls)),
            "calls": all_calls,
        }
        with open(combined_path, "w") as f:
            json.dump(combined, f, indent=2)

        grouped: dict[str, dict[str, Any]] = {
            "text": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "tokens": 0, "models": set()},
            "image": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "tokens": 0, "models": set()},
        }
        for c in all_calls:
            k = c.get("model_type") or self._model_type(c.get("model", ""))
            if k not in grouped:
                grouped[k] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "tokens": 0, "models": set()}
            grouped[k]["calls"] += 1
            grouped[k]["input_tokens"] += c.get("input_tokens", 0)
            grouped[k]["output_tokens"] += c.get("output_tokens", 0)
            grouped[k]["tokens"] += c.get("input_tokens", 0) + c.get("output_tokens", 0)
            grouped[k]["models"].add(c.get("model", "unknown"))

        serializable = {
            "totals": {
                "calls": len(all_calls),
                "input_tokens": total_input,
                "output_tokens": total_output,
                "tokens": total_input + total_output,
            },
            "by_model_type": {
                key: {
                    "calls": val["calls"],
                    "input_tokens": val["input_tokens"],
                    "output_tokens": val["output_tokens"],
                    "tokens": val["tokens"],
                    "models": sorted(val["models"]),
                }
                for key, val in grouped.items()
            },
            "calls": all_calls,
        }
        with open(split_path, "w") as f:
            json.dump(serializable, f, indent=2)

        print(f"LLM usage saved: {combined_path}")
        print(f"LLM usage by model type saved: {split_path}")
        return combined_path, split_path


def track_llm_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator for model calls to record usage and latency."""

    def wrapper(
        tracker: Optional[OVALLMTracker],
        model: Any,
        contents: Any,
        *,
        purpose: str,
    ) -> Any:
        model_name = getattr(model, "model_name", str(model))
        model_type = "image" if "image" in model_name.lower() else "text"

        max_attempts = 6
        response = None
        t0 = time.perf_counter()
        for attempt in range(1, max_attempts + 1):
            try:
                response = func(tracker, model, contents, purpose=purpose)
                break
            except Exception as exc:
                msg = str(exc)
                transient = (
                    "503" in msg
                    or "UNAVAILABLE" in msg.upper()
                    or "RESOURCE_EXHAUSTED" in msg.upper()
                    or "429" in msg
                )
                if not transient or attempt == max_attempts:
                    raise
                sleep_s = min(20, 3 * attempt)
                print(
                    f"LLM retry {attempt}/{max_attempts} for {purpose} ({model_name}) after transient error: {msg[:180]}"
                )
                time.sleep(sleep_s)

        duration_ms = (time.perf_counter() - t0) * 1000

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

        if tracker is not None:
            tracker.record(
                model_name=model_name,
                purpose=purpose,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                duration_ms=duration_ms,
                model_type=model_type,
            )
        return response

    return wrapper


@track_llm_call
def llm_call(
    tracker: Optional[OVALLMTracker],
    model: Any,
    contents: Any,
    *,
    purpose: str,
) -> Any:
    return model.generate_content(contents)
