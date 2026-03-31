"""
Escalation Ladder — configurable multi-level escalation engine.

Determines the appropriate escalation action based on how many cycles
the system has been stuck in the same state, with cooldown support
and configurable no-escalate states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EscalationStep:
    """A single step in the escalation ladder.

    Attributes:
        name: human-readable step name (e.g. "OBSERVE", "DIAGNOSE").
        threshold_cycles: minimum stuck cycles to reach this step.
        action: action type string — one of:
            "observe", "diagnose", "suggest", "recover", "deploy", "escalate".
        cooldown_cycles: after executing, suppress escalation for N cycles.
    """
    name: str
    threshold_cycles: int
    action: str  # "observe", "diagnose", "suggest", "recover", "deploy", "escalate"
    cooldown_cycles: int = 0


class EscalationLadder:
    """Manages the escalation ladder with cooldown and no-escalate states.

    Parameters:
        steps: list of EscalationStep instances, ordered by increasing
            threshold_cycles (lowest first).
        no_escalate_states: set of state names that should never escalate
            beyond OBSERVE (e.g. terminal/transient states).
    """

    def __init__(self, steps: list[EscalationStep],
                 no_escalate_states: set[str] | None = None):
        # Sort by threshold ascending to ensure correct evaluation
        self.steps = sorted(steps, key=lambda s: s.threshold_cycles)
        self.no_escalate_states = no_escalate_states or set()

        if not self.steps:
            self.steps = [EscalationStep(
                name="OBSERVE", threshold_cycles=0, action="observe",
            )]

    @property
    def observe_step(self) -> EscalationStep:
        """Return the lowest escalation step (always the first)."""
        return self.steps[0]

    def determine_level(self, state_name: str, stuck_cycles: int,
                        cooldown_until: int,
                        current_cycle: int) -> EscalationStep:
        """Determine the appropriate escalation step.

        Parameters:
            state_name: current state name.
            stuck_cycles: consecutive cycles in this state.
            cooldown_until: cycle number until which escalation is suppressed.
            current_cycle: current cycle number.

        Returns:
            The highest EscalationStep whose threshold is met, or the
            observe step if cooldown is active or state is in no_escalate.
        """
        # No-escalate states always get the lowest level
        if state_name in self.no_escalate_states:
            return self.observe_step

        # Cooldown check
        if cooldown_until > current_cycle:
            return self.observe_step

        # Walk the ladder and find the highest matching step
        result = self.observe_step
        for step in self.steps:
            if stuck_cycles >= step.threshold_cycles:
                result = step
        return result

    def step_by_name(self, name: str) -> EscalationStep | None:
        """Find a step by name (case-insensitive)."""
        name_lower = name.lower()
        for step in self.steps:
            if step.name.lower() == name_lower:
                return step
        return None

    def summary(self) -> list[dict[str, Any]]:
        """Return the ladder as a list of dicts for display/serialization."""
        return [
            {
                "name": s.name,
                "threshold": s.threshold_cycles,
                "action": s.action,
                "cooldown": s.cooldown_cycles,
            }
            for s in self.steps
        ]
