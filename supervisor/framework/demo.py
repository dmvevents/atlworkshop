#!/usr/bin/env python3
"""
Supervisor Framework Demo — demonstrates the full escalation flow.

Runs 15 cycles with simulated data showing the progression from
OBSERVE through DIAGNOSE, SUGGEST, RECOVER, and finally ESCALATE.

Usage:
    python3 -m supervisor.framework.demo
    python3 supervisor/framework/demo.py
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

# Allow running as a script from any directory
_this = Path(__file__).resolve().parent
if str(_this.parent.parent) not in sys.path:
    sys.path.insert(0, str(_this.parent.parent))

from supervisor.framework.collector import MockCollector
from supervisor.framework.classifier import RuleBasedClassifier
from supervisor.framework.advisor import RuleBasedAdvisor
from supervisor.framework.recovery import PlaybookRecovery
from supervisor.framework.delivery import NullDelivery
from supervisor.framework.escalation import EscalationLadder, EscalationStep
from supervisor.framework.state import SharedStateManager
from supervisor.framework.supervisor import Supervisor


def build_demo_supervisor(state_dir: str) -> Supervisor:
    """Build a supervisor with mock data for demonstration."""

    # --- Simulated data sequence ---
    # Cycles 1-4: agent stuck with build errors
    # Cycle 5: agent starts working (state change resets escalation)
    # Cycles 6-7: back to errors
    # Cycles 8-15: stuck with timeout errors -> full escalation ladder

    build_error_metrics = {
        "agent_prompt": 5,
        "tool_calls": 3,
        "errors": 4,
        "warnings": 1,
        "build_error": 2,
        "test_fail": 0,
        "completed": 0,
        "oom": 0,
        "timeout": 0,
        "permission": 0,
        "not_found": 0,
        "waiting": 0,
        "git_conflict": 0,
        "_raw_empty": False,
    }

    working_metrics = {
        "agent_prompt": 10,
        "tool_calls": 8,
        "errors": 0,
        "warnings": 0,
        "build_error": 0,
        "test_fail": 0,
        "completed": 0,
        "oom": 0,
        "timeout": 0,
        "permission": 0,
        "not_found": 0,
        "waiting": 0,
        "git_conflict": 0,
        "_raw_empty": False,
    }

    timeout_metrics = {
        "agent_prompt": 3,
        "tool_calls": 1,
        "errors": 2,
        "warnings": 0,
        "build_error": 0,
        "test_fail": 0,
        "completed": 0,
        "oom": 0,
        "timeout": 3,
        "permission": 0,
        "not_found": 0,
        "waiting": 2,
        "git_conflict": 0,
        "_raw_empty": False,
    }

    completed_metrics = {
        "agent_prompt": 12,
        "tool_calls": 15,
        "errors": 0,
        "warnings": 0,
        "build_error": 0,
        "test_fail": 0,
        "completed": 3,
        "oom": 0,
        "timeout": 0,
        "permission": 0,
        "not_found": 0,
        "waiting": 0,
        "git_conflict": 0,
        "_raw_empty": False,
    }

    data_sequence = [
        # Cycles 1-4: BUILD_FAILED
        ("[agent] Build failed: SyntaxError in main.ts", build_error_metrics),
        ("[agent] Build failed: SyntaxError in main.ts", build_error_metrics),
        ("[agent] Build failed: SyntaxError in main.ts", build_error_metrics),
        ("[agent] Build failed: SyntaxError in main.ts", build_error_metrics),
        # Cycle 5: agent fixes it, briefly WORKING
        ("[agent] Running tool: compile", working_metrics),
        # Cycles 6-7: back to build errors
        ("[agent] Build failed again", build_error_metrics),
        ("[agent] Build failed again", build_error_metrics),
        # Cycles 8-15: stuck with timeouts -> full ladder
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
        ("[agent] Waiting... timeout on API call", timeout_metrics),
    ]

    collector = MockCollector(data_sequence=data_sequence)

    # --- Classifier ---
    classifier = RuleBasedClassifier(
        rules=[
            {"state": "IDLE",
             "conditions": [{"metric": "_raw_empty", "op": "==", "value": True}]},
            {"state": "ERROR_OOM",
             "conditions": [{"metric": "oom", "op": ">", "value": 0}]},
            {"state": "ERROR_TIMEOUT",
             "conditions": [{"metric": "timeout", "op": ">", "value": 0},
                            {"metric": "completed", "op": "==", "value": 0}]},
            {"state": "BUILD_FAILED",
             "conditions": [{"metric": "build_error", "op": ">", "value": 0}]},
            {"state": "TESTS_FAILING",
             "conditions": [{"metric": "test_fail", "op": ">", "value": 0}]},
            {"state": "COMPLETED",
             "conditions": [{"metric": "completed", "op": ">", "value": 0},
                            {"metric": "errors", "op": "==", "value": 0}]},
            {"state": "HAS_ERRORS",
             "conditions": [{"metric": "errors", "op": ">", "value": 0}]},
        ],
        default_state="WORKING",
    )

    # --- Advisor ---
    advisor = RuleBasedAdvisor(state_map={
        "BUILD_FAILED": {
            "dimension": "build",
            "suggestions": [
                {"value": "fix syntax", "description": "Review and fix the syntax error in main.ts"},
                {"value": "clean rebuild", "description": "Clean artifacts and rebuild from scratch"},
                {"value": "check deps", "description": "Verify dependencies are installed"},
            ],
            "rationale": "Build failed. Check compiler errors for the specific issue.",
            "checks": [
                "Review the full build error output",
                "Check if deps changed recently",
                "Try a clean build with rm -rf dist && npm run build",
            ],
        },
        "ERROR_TIMEOUT": {
            "dimension": "latency",
            "suggestions": [
                {"value": "increase timeout", "description": "Raise timeout threshold to 120s"},
                {"value": "optimize operation", "description": "Profile and optimize the slow API call"},
                {"value": "add retry", "description": "Add retry with exponential backoff"},
                {"value": "use cache", "description": "Cache API responses to avoid repeated slow calls"},
            ],
            "rationale": "API calls are timing out. Either the service is slow or the timeout is too short.",
            "checks": [
                "Check network connectivity to the API endpoint",
                "Check API service health status",
                "Profile the slow path to identify bottleneck",
            ],
        },
    })

    # --- Recovery ---
    recovery = PlaybookRecovery(playbooks={
        "BUILD_FAILED": [
            {"action": "command", "value": "rm -rf dist node_modules/.cache",
             "description": "Clean build artifacts"},
            {"action": "command", "value": "npm install",
             "description": "Reinstall dependencies"},
            {"action": "command", "value": "npm run build",
             "description": "Rebuild from clean state"},
        ],
        "ERROR_TIMEOUT": [
            {"action": "directive", "value": "Switch to async API with polling",
             "description": "Convert synchronous API calls to async with polling"},
            {"action": "directive", "value": "Add circuit breaker pattern",
             "description": "Implement circuit breaker to fail fast on repeated timeouts"},
            {"action": "command", "value": "curl -s -o /dev/null -w '%{time_total}' $API_URL",
             "description": "Measure actual API latency"},
        ],
    })

    # --- Delivery (dry-run for demo) ---
    delivery = NullDelivery(log_prefix="[DEMO]")

    # --- Escalation Ladder ---
    escalation = EscalationLadder(
        steps=[
            EscalationStep("OBSERVE", 0, "observe"),
            EscalationStep("DIAGNOSE", 3, "diagnose"),
            EscalationStep("SUGGEST", 4, "suggest"),
            EscalationStep("RECOVER", 6, "recover"),
            EscalationStep("DEPLOY", 8, "deploy", cooldown_cycles=10),
            EscalationStep("ESCALATE", 10, "escalate", cooldown_cycles=15),
        ],
        no_escalate_states={"COMPLETED", "WORKING", "IDLE"},
    )

    # --- State Manager (temp dir for demo) ---
    state_manager = SharedStateManager(
        state_path=f"{state_dir}/demo-state.json",
        history_path=f"{state_dir}/demo-history.jsonl",
    )

    return Supervisor(
        collector=collector,
        classifier=classifier,
        advisor=advisor,
        recovery=recovery,
        delivery=delivery,
        escalation=escalation,
        state_manager=state_manager,
        name="demo-agent",
        dry_run=True,
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 72)
    print("  Agent Supervisor Framework -- Demo")
    print("  Running 15 cycles with simulated agent data")
    print("=" * 72)
    print()

    with tempfile.TemporaryDirectory(prefix="supervisor-demo-") as tmpdir:
        sup = build_demo_supervisor(tmpdir)

        for i in range(15):
            print(f"\n{'─' * 60}")
            print(f"  CYCLE {i + 1}")
            print(f"{'─' * 60}")

            state = sup.run_once()

            # Print compact summary
            print(f"  State:      {state.get('state', '?')} "
                  f"(stuck={state.get('same_state_cycles', 0)})")
            print(f"  Escalation: {state.get('escalation_name', '?')} "
                  f"-> {state.get('escalation_action', '?')}")

            if state.get("diagnosis"):
                diag = state["diagnosis"]
                print(f"  Diagnosis:  dim={diag.get('dimension', '?')} "
                      f"suggestions={len(diag.get('suggestions', []))}")
                if diag.get("rationale"):
                    print(f"  Rationale:  {diag['rationale'][:80]}")

            if state.get("recovery_report"):
                report = state["recovery_report"]
                print(f"  Recovery:   {len(report.get('candidates', []))} candidates")
                if report.get("recommendation"):
                    print(f"  Recommend:  {report['recommendation'][:80]}")

            last = state.get("last_directive", "")
            if last:
                print(f"  Directive:  {last[:80]}...")

            cooldown = state.get("cooldown_until_cycle", 0)
            if cooldown > state.get("cycle", 0):
                print(f"  Cooldown:   active until cycle {cooldown}")

        # Print final status
        print(f"\n{'=' * 72}")
        print("  FINAL STATUS")
        print(f"{'=' * 72}")
        print(sup.status())

        # Print history
        print(f"\n{'=' * 72}")
        print("  HISTORY (last 15 cycles)")
        print(f"{'=' * 72}")
        history = sup.history(limit=15)
        print(f"{'Cycle':>6} | {'State':<16} | {'Stuck':>5} | "
              f"{'Level':<10} | {'Action':<10} | Directive")
        print("-" * 90)
        for entry in history:
            print(
                f"{entry.get('cycle', 0):>6} | "
                f"{entry.get('state', '?'):<16} | "
                f"{entry.get('same_state_cycles', 0):>5} | "
                f"{entry.get('escalation', '?'):<10} | "
                f"{entry.get('action', '?'):<10} | "
                f"{(entry.get('directive') or '-')[:35]}"
            )

    print(f"\n{'=' * 72}")
    print("  Demo complete. Temp state files cleaned up.")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
