"""
Generic Supervisor — the main engine that ties all components together.

Runs the collect -> classify -> escalate -> act -> persist loop.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .collector import StateCollector
from .classifier import StateClassifier
from .advisor import Advisor
from .recovery import RecoveryStrategy
from .delivery import DirectiveDelivery, NullDelivery
from .escalation import EscalationLadder, EscalationStep
from .state import SharedStateManager

logger = logging.getLogger(__name__)


class Supervisor:
    """Generic supervisor that orchestrates the full supervision loop.

    Parameters:
        collector: gathers raw metrics from external sources.
        classifier: maps metrics to a named state.
        advisor: produces diagnostic suggestions.
        recovery: generates recovery candidates.
        delivery: sends directives to the supervised agent.
        escalation: the escalation ladder configuration.
        state_manager: persistent state storage.
        name: human-readable supervisor name.
        dry_run: if True, uses NullDelivery regardless of delivery param.
    """

    def __init__(
        self,
        collector: StateCollector,
        classifier: StateClassifier,
        advisor: Advisor,
        recovery: RecoveryStrategy,
        delivery: DirectiveDelivery,
        escalation: EscalationLadder,
        state_manager: SharedStateManager,
        name: str = "supervisor",
        dry_run: bool = False,
    ):
        self.collector = collector
        self.classifier = classifier
        self.advisor = advisor
        self.recovery = recovery
        self.delivery = delivery if not dry_run else NullDelivery()
        self.escalation = escalation
        self.state_manager = state_manager
        self.name = name
        self.dry_run = dry_run

    def run_once(self) -> dict[str, Any]:
        """Run a single supervision cycle.

        Returns:
            The updated state dict after this cycle.
        """
        # Load persistent state
        state = self.state_manager.load()
        cycle = state.get("cycle", 0) + 1
        state["cycle"] = cycle

        # Phase 1: Collect
        raw_text, metrics = self.collector.collect()
        state["metrics"] = {
            k: v for k, v in metrics.items() if not k.startswith("_")
        }
        state["_raw_empty"] = metrics.get("_raw_empty", False)

        # Phase 2: Classify
        current_state = self.classifier.classify(metrics)

        # Phase 3: Update state tracking
        previous_state = state.get("state", "")
        if current_state == previous_state:
            state["same_state_cycles"] = state.get("same_state_cycles", 0) + 1
        else:
            state["previous_state"] = previous_state
            state["state"] = current_state
            state["same_state_cycles"] = 1
            # Reset escalation context on state change
            state.pop("diagnosis", None)
            state.pop("recovery_report", None)

        state["state"] = current_state
        stuck = state["same_state_cycles"]

        # Phase 4: Determine escalation level
        step = self.escalation.determine_level(
            state_name=current_state,
            stuck_cycles=stuck,
            cooldown_until=state.get("cooldown_until_cycle", 0),
            current_cycle=cycle,
        )
        state["escalation_name"] = step.name
        state["escalation_action"] = step.action

        # Phase 5: Execute escalation action
        logger.info(
            f"[{self.name}] cycle={cycle} state={current_state} "
            f"stuck={stuck} escalation={step.name} ({step.action})"
        )

        directive = None
        action = step.action

        if action == "observe":
            pass  # Just log

        elif action == "diagnose":
            history = self.state_manager.read_history(limit=20)
            diagnosis = self.advisor.diagnose(current_state, metrics, history)
            state["diagnosis"] = diagnosis
            logger.info(
                f"[{self.name}] Diagnosis: dimension={diagnosis.get('dimension')} "
                f"suggestions={len(diagnosis.get('suggestions', []))}"
            )

        elif action == "suggest":
            # Ensure we have a diagnosis
            if "diagnosis" not in state:
                history = self.state_manager.read_history(limit=20)
                diagnosis = self.advisor.diagnose(current_state, metrics, history)
                state["diagnosis"] = diagnosis

            diagnosis = state.get("diagnosis", {})
            dim = diagnosis.get("dimension", "unknown")
            suggestions = diagnosis.get("suggestions", [])
            tried = state.get("tried_alternatives", [])
            untried = [
                s for s in suggestions
                if isinstance(s, dict) and
                f"{dim}={s.get('value')}" not in tried
            ]

            if untried:
                best = untried[0]
                val = best.get("value", "?")
                desc = best.get("description", "")[:150]
                directive = (
                    f"[{self.name} SUGGEST] Stuck in {current_state} for "
                    f"{stuck} cycles. Failing dimension: {dim}. "
                    f"Try: {dim}={val}. {desc}"
                )
                tried.append(f"{dim}={val}")
                state["tried_alternatives"] = tried
            else:
                checks = diagnosis.get("checks", [])
                check_text = "; ".join(checks[:3]) if checks else "Review logs"
                directive = (
                    f"[{self.name} SUGGEST] All {dim} alternatives tried. "
                    f"Debug checks: {check_text}"
                )

        elif action == "recover":
            context = {
                "metrics": metrics,
                "state": state,
                "history": self.state_manager.read_history(limit=20),
            }
            report = self.recovery.recover(current_state, stuck, context)
            state["recovery_report"] = report
            rec = report.get("recommendation", "")
            best = report.get("best_candidate")
            if best:
                state["recovery_best_candidate"] = best
                directive = (
                    f"[{self.name} RECOVER] {rec[:300]}"
                )
            else:
                directive = (
                    f"[{self.name} RECOVER] No candidates generated. {rec[:200]}"
                )

        elif action == "deploy":
            report = state.get("recovery_report", {})
            best = report.get("best_candidate")
            if not best:
                # Re-run recovery first
                context = {
                    "metrics": metrics,
                    "state": state,
                    "history": self.state_manager.read_history(limit=20),
                }
                report = self.recovery.recover(current_state, stuck, context)
                state["recovery_report"] = report
                best = report.get("best_candidate")

            if best:
                desc = best.get("description", best.get("value", ""))[:200]
                directive = (
                    f"[{self.name} DEPLOY] Deploy candidate: {desc}"
                )
            else:
                directive = (
                    f"[{self.name} DEPLOY] No deployment candidate available."
                )
            state["cooldown_until_cycle"] = cycle + step.cooldown_cycles

        elif action == "escalate":
            tried = state.get("tried_alternatives", [])
            directive = (
                f"[{self.name} ESCALATE] HUMAN INTERVENTION NEEDED. "
                f"State {current_state} stuck for {stuck} cycles. "
                f"Tried: {tried}. "
                f"All automated recovery options exhausted."
            )
            state["cooldown_until_cycle"] = cycle + step.cooldown_cycles

        # Phase 6: Send directive if generated
        if directive:
            last = state.get("last_directive", "")
            if directive != last:
                ok = self.delivery.send(directive)
                state["last_directive"] = directive
                state["last_directive_time"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                state["directives_sent"] = state.get("directives_sent", 0) + 1
                state["last_delivery_ok"] = ok
                logger.info(
                    f"[{self.name}] Directive sent (ok={ok}): "
                    f"{directive[:120]}..."
                )
            else:
                logger.debug(f"[{self.name}] Skipped duplicate directive")

        # Phase 7: Persist state and history
        self.state_manager.save(state)
        self.state_manager.append_history({
            "cycle": cycle,
            "state": current_state,
            "same_state_cycles": stuck,
            "escalation": step.name,
            "action": step.action,
            "directive": (directive or "")[:200],
            "metrics_summary": {
                k: v for k, v in list(state.get("metrics", {}).items())[:10]
            },
        })

        return state

    def run_loop(self, interval: int = 60) -> None:
        """Run the supervision loop continuously.

        Parameters:
            interval: seconds between cycles.
        """
        logger.info(
            f"[{self.name}] Starting supervision loop, "
            f"interval={interval}s, dry_run={self.dry_run}"
        )
        logger.info(f"[{self.name}] Escalation ladder: {self.escalation.summary()}")

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.info(f"[{self.name}] Stopped by user")
                break
            except Exception as e:
                logger.error(f"[{self.name}] Cycle error: {e}", exc_info=True)

            time.sleep(interval)

    def status(self) -> str:
        """Return a human-readable status summary."""
        state = self.state_manager.load()
        if not state.get("cycle"):
            return f"[{self.name}] Not started yet."

        lines = [
            f"=== {self.name} Supervisor ===",
            f"Cycle:        {state.get('cycle', 0)}",
            f"Timestamp:    {state.get('_timestamp', 'N/A')}",
            f"State:        {state.get('state', 'UNKNOWN')} "
            f"({state.get('same_state_cycles', 0)} consecutive)",
            f"Previous:     {state.get('previous_state', 'N/A')}",
            f"Escalation:   {state.get('escalation_name', 'N/A')} "
            f"({state.get('escalation_action', 'N/A')})",
            f"Cooldown:     "
            f"{'until cycle ' + str(state.get('cooldown_until_cycle', 0)) if state.get('cooldown_until_cycle', 0) > state.get('cycle', 0) else 'none'}",
            f"Directives:   {state.get('directives_sent', 0)} sent",
            f"Last:         {(state.get('last_directive') or 'none')[:120]}",
        ]

        metrics = state.get("metrics", {})
        if metrics:
            metric_str = " ".join(f"{k}={v}" for k, v in list(metrics.items())[:8])
            lines.append(f"Metrics:      {metric_str}")

        return "\n".join(lines)

    def history(self, limit: int = 20) -> list[dict]:
        """Return recent history entries."""
        return self.state_manager.read_history(limit=limit)
