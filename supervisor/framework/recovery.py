"""
Recovery Strategy — generates and evaluates recovery candidates.

Recovery strategies produce one or more candidate actions when the
system is stuck, rank them, and return a recommendation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any


class RecoveryStrategy(ABC):
    """Base class for recovery strategies."""

    @abstractmethod
    def recover(self, state: str, stuck_cycles: int,
                context: dict[str, Any]) -> dict[str, Any]:
        """Generate recovery candidates.

        Parameters:
            state: current stuck state name.
            stuck_cycles: how many consecutive cycles in this state.
            context: additional context (metrics, history, config, etc.).

        Returns:
            A dict with:
                - candidates: list of candidate dicts.
                - best_candidate: the top candidate dict (or None).
                - recommendation: human-readable recommendation string.
        """


class ScriptRecovery(RecoveryStrategy):
    """Calls an external script for recovery candidate generation.

    Parameters:
        script_path: path to the recovery script.
        args_template: argument template list with placeholders.
        timeout: script timeout in seconds.
        interpreter: interpreter to use.
    """

    def __init__(self, script_path: str,
                 args_template: list[str] | None = None,
                 timeout: int = 120,
                 interpreter: str | None = None):
        self.script_path = script_path
        self.args_template = args_template or [
            "--state", "{state}",
            "--stuck-cycles", "{stuck_cycles}",
            "--json",
        ]
        self.timeout = timeout
        self.interpreter = interpreter or sys.executable

    def recover(self, state: str, stuck_cycles: int,
                context: dict[str, Any]) -> dict[str, Any]:
        args = [
            a.format(state=state, stuck_cycles=stuck_cycles)
            for a in self.args_template
        ]
        cmd = [self.interpreter, self.script_path] + args

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
            )
            if result.returncode == 0 and result.stdout.strip():
                report = _extract_json(result.stdout)
                if report:
                    return report
            return self._fallback(state, error=result.stderr[:300])
        except subprocess.TimeoutExpired:
            return self._fallback(state, error="Recovery script timed out")
        except FileNotFoundError:
            return self._fallback(state,
                                  error=f"Script not found: {self.script_path}")

    def _fallback(self, state: str, error: str = "") -> dict[str, Any]:
        return {
            "candidates": [],
            "best_candidate": None,
            "recommendation": f"Recovery failed for state {state}. {error}",
        }


class PlaybookRecovery(RecoveryStrategy):
    """Executes predefined recovery playbooks from config.

    Each playbook is a list of steps. Steps can be shell commands,
    directives, or config changes.

    Parameters:
        playbooks: dict mapping state names to lists of step dicts.
            Each step: {action: "command"|"directive"|"config",
                        value: str, description: str}
        default_playbook: fallback if state not in playbooks.
    """

    def __init__(self, playbooks: dict[str, list[dict[str, Any]]],
                 default_playbook: list[dict[str, Any]] | None = None):
        self.playbooks = playbooks
        self.default_playbook = default_playbook or []

    def recover(self, state: str, stuck_cycles: int,
                context: dict[str, Any]) -> dict[str, Any]:
        steps = self.playbooks.get(state, self.default_playbook)
        if not steps:
            return {
                "candidates": [],
                "best_candidate": None,
                "recommendation": f"No recovery playbook for state {state}.",
            }

        candidates = []
        for i, step in enumerate(steps):
            candidates.append({
                "rank": i + 1,
                "action": step.get("action", "directive"),
                "value": step.get("value", ""),
                "description": step.get("description", ""),
                "step_index": i,
            })

        best = candidates[0] if candidates else None
        desc_list = "; ".join(
            s.get("description", s.get("value", ""))[:60]
            for s in steps[:3]
        )
        return {
            "candidates": candidates,
            "best_candidate": best,
            "recommendation": (
                f"Playbook for {state} ({len(steps)} steps): {desc_list}"
            ),
        }


class ChainedRecovery(RecoveryStrategy):
    """Tries multiple recovery strategies in order, returns first success.

    Parameters:
        strategies: list of (name, RecoveryStrategy) tuples.
    """

    def __init__(self, strategies: list[tuple[str, RecoveryStrategy]]):
        self.strategies = strategies

    def recover(self, state: str, stuck_cycles: int,
                context: dict[str, Any]) -> dict[str, Any]:
        for name, strategy in self.strategies:
            result = strategy.recover(state, stuck_cycles, context)
            if result.get("candidates"):
                result["strategy_used"] = name
                return result
        return {
            "candidates": [],
            "best_candidate": None,
            "recommendation": "All recovery strategies exhausted.",
        }


class NullRecovery(RecoveryStrategy):
    """No-op recovery that always returns empty. Useful as a placeholder."""

    def recover(self, state: str, stuck_cycles: int,
                context: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidates": [],
            "best_candidate": None,
            "recommendation": "No recovery strategy configured.",
        }


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
