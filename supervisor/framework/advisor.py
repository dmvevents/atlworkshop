"""
Diagnostic Advisor — produces suggestions for a given state.

Advisors analyze the current state and metrics, then return structured
diagnostic information including the failing dimension, suggestions,
rationale, and additional checks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any


class Advisor(ABC):
    """Base class for diagnostic advisors."""

    @abstractmethod
    def diagnose(self, state: str, metrics: dict[str, Any],
                 history: list[dict]) -> dict[str, Any]:
        """Produce a diagnosis for the given state.

        Parameters:
            state: current state name.
            metrics: current metrics dict.
            history: list of recent history entries.

        Returns:
            A dict with at least:
                - dimension: the failing dimension or area.
                - suggestions: list of suggestion dicts.
                - rationale: human-readable explanation.
                - checks: list of additional diagnostic checks.
        """


class RuleBasedAdvisor(Advisor):
    """Maps states to suggestions via a static config.

    Parameters:
        state_map: dict mapping state names to diagnosis dicts. Each
            value should have keys: dimension, suggestions, rationale, checks.
        default_diagnosis: returned when state is not in the map.
    """

    def __init__(self, state_map: dict[str, dict[str, Any]],
                 default_diagnosis: dict[str, Any] | None = None):
        self.state_map = state_map
        self.default_diagnosis = default_diagnosis or {
            "dimension": "unknown",
            "suggestions": [],
            "rationale": "No diagnosis available for this state.",
            "checks": ["Review logs manually."],
        }

    def diagnose(self, state: str, metrics: dict[str, Any],
                 history: list[dict]) -> dict[str, Any]:
        diagnosis = self.state_map.get(state, self.default_diagnosis).copy()
        diagnosis["state"] = state
        diagnosis["metrics_snapshot"] = {
            k: v for k, v in metrics.items() if not k.startswith("_")
        }
        return diagnosis


class ScriptAdvisor(Advisor):
    """Calls an external script for diagnosis.

    The script should output a JSON object on stdout.

    Parameters:
        script_path: path to the script.
        args_template: list of arg strings with {state}, {metrics_json}
            placeholders that get formatted before execution.
        timeout: script timeout in seconds.
        interpreter: interpreter to use (default: current python).
    """

    def __init__(self, script_path: str, args_template: list[str] | None = None,
                 timeout: int = 30, interpreter: str | None = None):
        self.script_path = script_path
        self.args_template = args_template or ["--state", "{state}", "--json"]
        self.timeout = timeout
        self.interpreter = interpreter or sys.executable

    def diagnose(self, state: str, metrics: dict[str, Any],
                 history: list[dict]) -> dict[str, Any]:
        metrics_json = json.dumps(metrics, default=str)
        args = [
            a.format(state=state, metrics_json=metrics_json,
                     stuck_cycles=len(history))
            for a in self.args_template
        ]
        cmd = [self.interpreter, self.script_path] + args

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
            )
            if result.returncode == 0 and result.stdout.strip():
                return _extract_json(result.stdout) or self._fallback(state)
            return self._fallback(state, error=result.stderr[:300])
        except subprocess.TimeoutExpired:
            return self._fallback(state, error="Script timed out")
        except FileNotFoundError:
            return self._fallback(state, error=f"Script not found: {self.script_path}")

    def _fallback(self, state: str, error: str = "") -> dict[str, Any]:
        return {
            "dimension": "unknown",
            "suggestions": [],
            "rationale": f"Advisor script failed for state {state}. {error}",
            "checks": ["Review logs manually.", "Check advisor script availability."],
        }


class ChainedAdvisor(Advisor):
    """Runs multiple advisors in order and merges their results.

    Later advisors can augment/override earlier results.

    Parameters:
        advisors: list of (name, Advisor) tuples.
    """

    def __init__(self, advisors: list[tuple[str, Advisor]]):
        self.advisors = advisors

    def diagnose(self, state: str, metrics: dict[str, Any],
                 history: list[dict]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "dimension": "unknown",
            "suggestions": [],
            "rationale": "",
            "checks": [],
        }
        for name, advisor in self.advisors:
            try:
                result = advisor.diagnose(state, metrics, history)
                # Merge: later results take precedence for scalars,
                # lists are concatenated.
                if result.get("dimension") and result["dimension"] != "unknown":
                    merged["dimension"] = result["dimension"]
                if result.get("rationale"):
                    merged["rationale"] = result["rationale"]
                merged["suggestions"].extend(result.get("suggestions", []))
                merged["checks"].extend(result.get("checks", []))
                # Copy any extra keys
                for k, v in result.items():
                    if k not in merged:
                        merged[k] = v
            except Exception:
                continue
        return merged


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text that may contain non-JSON lines."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    brace_start = text.find("{")
    if brace_start < 0:
        return None

    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace_start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
