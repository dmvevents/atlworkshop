#!/usr/bin/env python3
"""
Transport Supervision Arbitrator — Central coordinator for all supervision layers.

Ties together:
  1. Pod state machine (bolt-supervisor logic) — reads kubectl logs
  2. CUCo design-space advisor (cuco-advisor.py) — maps states to dimensions
  3. Evolution-guided recovery (evolution-recovery.py) — generates candidates
  4. Pre-deploy gate (pre-deploy-gate.sh) — L0/L1 validation
  5. Directive injection (inject-command.sh) — sends to tmux agent

Implements an escalation ladder:
  Level 0: OBSERVE     — watch, log metrics (cycles 1-2)
  Level 1: DIAGNOSE    — call CUCo advisor, log suggestions (cycle 3)
  Level 2: SUGGEST     — send diagnostic directive to agent (cycle 4-5)
  Level 3: EVOLVE      — run evolution-recovery, generate candidates (cycle 6-7)
  Level 4: DEPLOY      — deploy best candidate through pre-deploy gate (cycle 8+)
  Level 5: ESCALATE    — all options exhausted, alert human

Usage:
    python3 arbitrator.py --session session-b --interval 90
    python3 arbitrator.py --session session-b --interval 90 --dry-run
    python3 arbitrator.py --once   # single cycle, no loop
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("arbitrator")

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "shared-state.json"
HISTORY_FILE = SCRIPT_DIR / "logs" / "arbitrator-history.jsonl"
LOG_FILE = SCRIPT_DIR / "logs" / "arbitrator.log"

# External scripts
INJECT_CMD = Path("<HPC_STACK_ROOT>/whatsapp-agents/scripts/inject-command.sh")
CUCO_ADVISOR = SCRIPT_DIR / "cuco-advisor.py"
EVOLUTION_RECOVERY = SCRIPT_DIR / "evolution-recovery.py"
PRE_DEPLOY_GATE = SCRIPT_DIR / "pre-deploy-gate.sh"


# =============================================================================
# Escalation Ladder
# =============================================================================

class EscalationLevel(IntEnum):
    OBSERVE = 0
    DIAGNOSE = 1
    SUGGEST = 2
    EVOLVE = 3
    DEPLOY = 4
    ESCALATE = 5


ESCALATION_THRESHOLDS = {
    EscalationLevel.OBSERVE: 0,    # immediate
    EscalationLevel.DIAGNOSE: 3,   # 3 cycles in same state
    EscalationLevel.SUGGEST: 4,    # 4 cycles
    EscalationLevel.EVOLVE: 6,     # 6 cycles
    EscalationLevel.DEPLOY: 8,     # 8 cycles
    EscalationLevel.ESCALATE: 12,  # 12 cycles — human needed
}

# States that don't escalate (transient or terminal)
NO_ESCALATE_STATES = {"ALL_PASS", "BARRIER_WAIT", "NO_PODS"}


# =============================================================================
# Shared State
# =============================================================================

@dataclass
class PodMetrics:
    """Metrics extracted from pod logs."""
    bolt_init: int = 0
    bolt_workers: int = 0
    bolt_peers: str = "?"
    bolt_c0: int = 0
    bolt_dispatch: int = 0
    bolt_tx: int = 0
    bolt_staging: int = 0
    diag_f: int = 0
    passed: int = 0
    timeout: int = 0
    cuda_context_ok: int = 0
    cuda_stream_ok: int = 0


@dataclass
class SharedState:
    """Unified state shared across all supervision layers."""
    # Identity
    session: str = "session-b"
    cycle: int = 0
    timestamp: str = ""

    # Pod state machine
    state: str = "UNKNOWN"
    previous_state: str = ""
    same_state_cycles: int = 0
    metrics: dict = field(default_factory=dict)

    # Escalation
    escalation_level: int = 0
    escalation_name: str = "OBSERVE"

    # CUCo advisor
    cuco_diagnosis: Optional[dict] = None
    cuco_failing_dimension: Optional[str] = None
    cuco_suggestions: list = field(default_factory=list)

    # Evolution recovery
    recovery_report: Optional[dict] = None
    recovery_best_candidate: Optional[str] = None

    # Directive tracking
    last_directive: str = ""
    last_directive_time: str = ""
    directives_sent: int = 0

    # History
    tried_dimensions: list = field(default_factory=list)
    tried_alternatives: list = field(default_factory=list)
    cooldown_until_cycle: int = 0

    # Config
    current_config: dict = field(default_factory=lambda: {
        "backend": "d2h_ring_fi_send",
        "placement": "split_put_wait",
        "sync": "d2h_ring",
        "issuer": "multi_warp",
        "granularity": "per_expert_batch",
    })

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "SharedState":
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                state = cls()
                for k, v in data.items():
                    if hasattr(state, k):
                        setattr(state, k, v)
                return state
            except (json.JSONDecodeError, KeyError):
                pass
        return cls()

    def save(self, path: Path = STATE_FILE):
        self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


# =============================================================================
# Pod State Collector
# =============================================================================

class PodStateCollector:
    """Reads kubectl logs and extracts Transport layer state."""

    def __init__(self, namespace: str = "gpu-transport", pod: str = "workload-pod-0"):
        self.namespace = namespace
        self.pod = pod

    def collect(self) -> tuple[str, PodMetrics]:
        """Collect pod logs and determine state. Returns (state, metrics)."""
        try:
            result = subprocess.run(
                ["kubectl", "logs", self.pod, "-n", self.namespace],
                capture_output=True, text=True, timeout=30,
            )
            log = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log = ""

        if not log:
            return "NO_PODS", PodMetrics()

        m = PodMetrics(
            bolt_init=log.count("[BOLT]"),
            bolt_workers=_count_pattern(log, r"BOLT-WORKER.*started"),
            bolt_peers=_last_match(log, r"peers=(\d+)") or "?",
            bolt_c0=log.count("BOLT-C0"),
            bolt_dispatch=_count_pattern(log, r"BOLT-WORKER.*Dispatch"),
            bolt_tx=log.count("BOLT-TX"),
            bolt_staging=log.count("BOLT-STAGING"),
            diag_f=log.count("DIAG-F"),
            passed=int(_last_match(log, r"Passed:\s+(\d+)") or "0"),
            timeout=_count_pattern(log, r"timeout.*dispatch|sender timeout"),
            cuda_context_ok=log.count("CUDA context OK"),
            cuda_stream_ok=log.count("CUDA stream created"),
        )

        # State machine (same logic as bolt-supervisor-v2/v3)
        state = "UNKNOWN"
        if m.bolt_init == 0:
            state = "NO_BOLT"
        elif m.bolt_workers == 0:
            state = "NO_WORKERS"
        elif m.bolt_peers in ("0", "?"):
            state = "PEERS_MISSING"
        elif m.diag_f == 0:
            state = "BARRIER_WAIT"
        elif m.bolt_c0 == 0 and m.timeout > 0:
            state = "C0_TIMEOUT"
        elif m.bolt_c0 > 0 and m.bolt_dispatch == 0:
            state = "C0_NO_WORKER"
        elif m.bolt_dispatch > 0 and m.bolt_tx == 0:
            state = "DISPATCH_NO_TX"
        elif m.bolt_tx > 0:
            state = "DISPATCHING"

        if m.passed > 0 and m.timeout == 0:
            state = "ALL_PASS"

        return state, m


# =============================================================================
# Escalation Engine
# =============================================================================

class EscalationEngine:
    """Determines and executes the appropriate escalation level."""

    def __init__(self, session: str, dry_run: bool = False):
        self.session = session
        self.dry_run = dry_run

    def determine_level(self, state: SharedState) -> EscalationLevel:
        """Determine escalation level based on stuck cycles."""
        if state.state in NO_ESCALATE_STATES:
            return EscalationLevel.OBSERVE

        if state.cooldown_until_cycle > state.cycle:
            logger.info(f"Cooldown active until cycle {state.cooldown_until_cycle}")
            return EscalationLevel.OBSERVE

        cycles = state.same_state_cycles
        level = EscalationLevel.OBSERVE
        for lvl in EscalationLevel:
            if cycles >= ESCALATION_THRESHOLDS[lvl]:
                level = lvl
        return level

    def execute(self, level: EscalationLevel, state: SharedState) -> SharedState:
        """Execute the escalation action for the given level."""
        state.escalation_level = level.value
        state.escalation_name = level.name

        actions = {
            EscalationLevel.OBSERVE: self._observe,
            EscalationLevel.DIAGNOSE: self._diagnose,
            EscalationLevel.SUGGEST: self._suggest,
            EscalationLevel.EVOLVE: self._evolve,
            EscalationLevel.DEPLOY: self._deploy,
            EscalationLevel.ESCALATE: self._escalate,
        }

        action = actions.get(level, self._observe)
        return action(state)

    def _observe(self, state: SharedState) -> SharedState:
        """Level 0: Just watch and log."""
        logger.info(f"[OBSERVE] State={state.state} cycle={state.cycle} "
                     f"stuck={state.same_state_cycles}")
        return state

    def _diagnose(self, state: SharedState) -> SharedState:
        """Level 1: Call CUCo advisor for design-space diagnosis."""
        logger.info(f"[DIAGNOSE] Consulting CUCo advisor for state={state.state}")

        try:
            has_timeout = state.metrics.get("timeout", 0) > 0
            cmd = [
                sys.executable, str(CUCO_ADVISOR),
                "--state", state.state,
                "--json",
            ]
            if has_timeout:
                cmd.append("--timeout")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                diagnosis = json.loads(result.stdout)
                state.cuco_diagnosis = diagnosis
                state.cuco_failing_dimension = diagnosis.get("failing_dimension")
                state.cuco_suggestions = diagnosis.get("suggestions", [])
                logger.info(f"[DIAGNOSE] Dimension={state.cuco_failing_dimension} "
                            f"suggestions={len(state.cuco_suggestions)}")
            else:
                logger.warning(f"[DIAGNOSE] Advisor failed: {result.stderr[:200]}")
        except Exception as e:
            logger.error(f"[DIAGNOSE] Error: {e}")

        return state

    def _suggest(self, state: SharedState) -> SharedState:
        """Level 2: Send a diagnostic directive to the agent."""
        # Ensure we have a diagnosis first
        if not state.cuco_diagnosis:
            state = self._diagnose(state)

        dim = state.cuco_failing_dimension
        if not dim:
            # Infrastructure issue — send fixed directive
            directive = self._infrastructure_directive(state.state)
        else:
            # Build CUCo-guided suggestion
            suggestions = state.cuco_suggestions
            untried = [
                s for s in suggestions
                if isinstance(s, dict) and
                f"{dim}={s.get('value')}" not in state.tried_alternatives
            ]
            if untried:
                best = untried[0]
                val = best.get("value", "?")
                desc = best.get("description", "")[:150]
                directive = (
                    f"[CUCo L2-SUGGEST] Stuck in {state.state} for "
                    f"{state.same_state_cycles} cycles. Failing dimension: {dim}. "
                    f"Try switching to {dim}={val}. {desc}"
                )
                state.tried_alternatives.append(f"{dim}={val}")
            else:
                # All suggestions tried at this level
                checks = (state.cuco_diagnosis or {}).get("additional_checks", [])
                check_text = "; ".join(checks[:3]) if checks else "Review pod logs manually"
                directive = (
                    f"[CUCo L2-SUGGEST] All {dim} alternatives tried. "
                    f"Debug checks: {check_text}"
                )

        self._send_directive(state, directive)
        return state

    def _evolve(self, state: SharedState) -> SharedState:
        """Level 3: Run evolution-recovery to generate and evaluate candidates."""
        logger.info(f"[EVOLVE] Triggering evolution-recovery for state={state.state}")

        try:
            config_str = ",".join(
                f"{k[0].upper()}={v}" for k, v in state.current_config.items()
            )
            cmd = [
                sys.executable, str(EVOLUTION_RECOVERY),
                "--state", state.state,
                "--stuck-cycles", str(state.same_state_cycles),
                "--current-config", config_str,
                "--json",
            ]
            if self.dry_run:
                cmd.append("--dry-run")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Find JSON in output (may have logging before it)
                report = _extract_json(result.stdout)
                if report:
                    state.recovery_report = report
                    best = report.get("best_candidate")
                    if best:
                        state.recovery_best_candidate = best.get("alternative_value")
                        logger.info(
                            f"[EVOLVE] Best candidate: "
                            f"{best.get('dimension')}={best.get('alternative_value')} "
                            f"score={best.get('eval_score')}"
                        )
                    rec = report.get("recommendation", "")
                    directive = (
                        f"[CUCo L3-EVOLVE] Recovery analysis complete. "
                        f"{rec[:300]}"
                    )
                    self._send_directive(state, directive)
                else:
                    logger.warning("[EVOLVE] Could not parse recovery output")
            else:
                logger.warning(f"[EVOLVE] Recovery failed: {result.stderr[:300]}")

        except subprocess.TimeoutExpired:
            logger.error("[EVOLVE] Recovery timed out after 120s")
        except Exception as e:
            logger.error(f"[EVOLVE] Error: {e}")

        return state

    def _deploy(self, state: SharedState) -> SharedState:
        """Level 4: Deploy best candidate through pre-deploy gate."""
        if not state.recovery_best_candidate:
            logger.info("[DEPLOY] No recovery candidate available, re-running EVOLVE")
            state = self._evolve(state)

        candidate = state.recovery_best_candidate
        if not candidate:
            logger.warning("[DEPLOY] Still no candidate after EVOLVE")
            return state

        report = state.recovery_report or {}
        best = report.get("best_candidate", {})
        candidate_path = best.get("candidate_path")

        if candidate_path and Path(candidate_path).exists():
            # Run pre-deploy gate
            logger.info(f"[DEPLOY] Running pre-deploy gate on {candidate_path}")
            try:
                gate_result = subprocess.run(
                    ["bash", str(PRE_DEPLOY_GATE), candidate_path],
                    capture_output=True, text=True, timeout=60,
                )
                if gate_result.returncode == 0:
                    directive = (
                        f"[CUCo L4-DEPLOY] Candidate {candidate} passed pre-deploy gate. "
                        f"Deploy this variant: cp {candidate_path} to transport_worker.cpp, "
                        f"rebuild, and redeploy to pods."
                    )
                else:
                    directive = (
                        f"[CUCo L4-DEPLOY] Candidate {candidate} FAILED pre-deploy gate: "
                        f"{gate_result.stdout[:200]}. Manual intervention needed."
                    )
            except Exception as e:
                directive = f"[CUCo L4-DEPLOY] Gate error: {e}"
        else:
            directive = (
                f"[CUCo L4-DEPLOY] Best candidate is {candidate} but no built artifact. "
                f"Manually apply the {report.get('dimension_targeted')}={candidate} "
                f"template from recovery-templates/ to transport_worker.cpp."
            )

        self._send_directive(state, directive)
        # Set cooldown
        state.cooldown_until_cycle = state.cycle + 10
        return state

    def _escalate(self, state: SharedState) -> SharedState:
        """Level 5: All automated options exhausted. Alert human."""
        logger.warning(
            f"[ESCALATE] State {state.state} stuck for {state.same_state_cycles} "
            f"cycles. All automated recovery options exhausted."
        )
        directive = (
            f"[ARBITRATOR L5-ESCALATE] HUMAN INTERVENTION NEEDED. "
            f"State {state.state} stuck for {state.same_state_cycles} cycles. "
            f"Tried dimensions: {state.tried_dimensions}. "
            f"Tried alternatives: {state.tried_alternatives}. "
            f"CUCo failing dimension: {state.cuco_failing_dimension}. "
            f"Review the arbitrator log at {LOG_FILE} and recovery reports at "
            f"{SCRIPT_DIR}/recovery-reports/"
        )
        self._send_directive(state, directive)
        # Long cooldown after escalation
        state.cooldown_until_cycle = state.cycle + 20
        return state

    def _infrastructure_directive(self, pod_state: str) -> str:
        """Generate a fixed directive for infrastructure states."""
        directives = {
            "NO_BOLT": "Bolt not on pods. Rebuild with USE_BOLT=1 and deploy.",
            "NO_WORKERS": "No Bolt workers. Call bolt_start_worker() after peers applied.",
            "PEERS_MISSING": "Workers have peers=0. Add bolt_apply_peers() in fabric_apply_remote().",
            "C0_TIMEOUT": "DIAG-F passed but no BOLT-C0. Check g_bolt_dispatch_signals is non-null.",
            "C0_NO_WORKER": "GPU signaled C0 but worker didnt dispatch. Check host_dispatch_signals.",
            "DISPATCH_NO_TX": (
                "Worker dispatches but no BOLT-TX. The cudaMemcpy/fi_writemsg path is blocked. "
                "Check CUDA context (BOLT-WORKER should show 'CUDA context OK') and staging copy."
            ),
        }
        return directives.get(pod_state, f"Unknown state: {pod_state}")

    def _send_directive(self, state: SharedState, directive: str):
        """Send a directive to the tmux agent session."""
        if directive == state.last_directive:
            logger.info(f"[DIRECTIVE] Skipped (duplicate): {directive[:80]}...")
            return

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would send: {directive[:200]}")
        else:
            logger.info(f"[DIRECTIVE] Sending: {directive[:200]}")
            try:
                subprocess.run(
                    [str(INJECT_CMD), state.session, directive],
                    capture_output=True, timeout=10,
                )
            except Exception as e:
                logger.error(f"[DIRECTIVE] Injection failed: {e}")

        state.last_directive = directive
        state.last_directive_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state.directives_sent += 1


# =============================================================================
# Main Arbitrator Loop
# =============================================================================

class Arbitrator:
    """Central coordinator that runs the supervision loop."""

    def __init__(
        self,
        session: str = "session-b",
        interval: int = 90,
        dry_run: bool = False,
        namespace: str = "gpu-transport",
        pod: str = "workload-pod-0",
    ):
        self.session = session
        self.interval = interval
        self.dry_run = dry_run
        self.collector = PodStateCollector(namespace=namespace, pod=pod)
        self.engine = EscalationEngine(session=session, dry_run=dry_run)

        # Ensure log directory exists
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> SharedState:
        """Run a single arbitration cycle."""
        # Load shared state
        state = SharedState.load()
        state.session = self.session
        state.cycle += 1

        # Phase 1: Collect pod state
        pod_state, metrics = self.collector.collect()
        state.metrics = asdict(metrics)

        # Phase 2: Update state machine
        if pod_state == state.state:
            state.same_state_cycles += 1
        else:
            state.previous_state = state.state
            state.state = pod_state
            state.same_state_cycles = 1
            # Reset escalation on state change
            state.cuco_diagnosis = None
            state.recovery_report = None
            state.recovery_best_candidate = None

        # Phase 3: Determine escalation level
        level = self.engine.determine_level(state)

        # Phase 4: Log
        logger.info(
            f"Cycle {state.cycle}: {state.state} "
            f"({state.same_state_cycles}x) "
            f"escalation={level.name} "
            f"| init={metrics.bolt_init} workers={metrics.bolt_workers} "
            f"peers={metrics.bolt_peers} c0={metrics.bolt_c0} "
            f"dispatch={metrics.bolt_dispatch} tx={metrics.bolt_tx} "
            f"staging={metrics.bolt_staging} "
            f"cuda_ctx={metrics.cuda_context_ok} "
            f"passed={metrics.passed} timeout={metrics.timeout}"
        )

        # Phase 5: Execute escalation
        state = self.engine.execute(level, state)

        # Phase 6: Save state and history
        state.save()
        self._append_history(state)

        return state

    def run_loop(self):
        """Run the continuous arbitration loop."""
        logger.info(
            f"Arbitrator starting: session={self.session} "
            f"interval={self.interval}s dry_run={self.dry_run}"
        )
        logger.info(f"State file: {STATE_FILE}")
        logger.info(f"Escalation thresholds: {dict(ESCALATION_THRESHOLDS)}")

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.info("Arbitrator stopped by user")
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)

            time.sleep(self.interval)

    def _append_history(self, state: SharedState):
        """Append current state to history JSONL file."""
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "cycle": state.cycle,
            "timestamp": state.timestamp,
            "state": state.state,
            "same_state_cycles": state.same_state_cycles,
            "escalation": state.escalation_name,
            "directive": state.last_directive[:200] if state.last_directive else "",
            "cuco_dim": state.cuco_failing_dimension,
            "recovery_candidate": state.recovery_best_candidate,
            "metrics": {
                "init": state.metrics.get("bolt_init", 0),
                "workers": state.metrics.get("bolt_workers", 0),
                "c0": state.metrics.get("bolt_c0", 0),
                "tx": state.metrics.get("bolt_tx", 0),
                "passed": state.metrics.get("passed", 0),
            },
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")


# =============================================================================
# Status Command — read shared state and print summary
# =============================================================================

def print_status():
    """Print current arbitrator status from shared state."""
    state = SharedState.load()
    if state.cycle == 0:
        print("Arbitrator has not run yet. Start with: python3 arbitrator.py --session session-b")
        return

    print(f"=== Transport Supervision Arbitrator ===")
    print(f"Cycle:       {state.cycle}")
    print(f"Timestamp:   {state.timestamp}")
    print(f"Session:     {state.session}")
    print()
    print(f"--- Pod State ---")
    print(f"State:       {state.state} ({state.same_state_cycles} consecutive cycles)")
    print(f"Previous:    {state.previous_state}")
    m = state.metrics
    print(f"Metrics:     init={m.get('bolt_init',0)} workers={m.get('bolt_workers',0)} "
          f"peers={m.get('bolt_peers','?')} c0={m.get('bolt_c0',0)} "
          f"dispatch={m.get('bolt_dispatch',0)} tx={m.get('bolt_tx',0)} "
          f"staging={m.get('bolt_staging',0)}")
    print(f"CUDA:        context_ok={m.get('cuda_context_ok',0)} "
          f"stream_ok={m.get('cuda_stream_ok',0)}")
    print()
    print(f"--- Escalation ---")
    print(f"Level:       {state.escalation_level} ({state.escalation_name})")
    print(f"Cooldown:    {'active (until cycle ' + str(state.cooldown_until_cycle) + ')' if state.cooldown_until_cycle > state.cycle else 'none'}")
    print()
    print(f"--- CUCo Diagnosis ---")
    print(f"Failing dim: {state.cuco_failing_dimension or 'N/A'}")
    print(f"Suggestions: {len(state.cuco_suggestions)}")
    print(f"Tried:       {state.tried_alternatives}")
    print()
    print(f"--- Recovery ---")
    print(f"Best cand:   {state.recovery_best_candidate or 'none'}")
    print()
    print(f"--- Directives ---")
    print(f"Total sent:  {state.directives_sent}")
    print(f"Last:        {state.last_directive[:120] if state.last_directive else 'none'}")
    print(f"Last time:   {state.last_directive_time}")
    print()
    print(f"--- Config ---")
    for k, v in state.current_config.items():
        print(f"  {k}: {v}")


# =============================================================================
# History Command — show recent arbitration history
# =============================================================================

def print_history(limit: int = 20):
    """Print recent arbitration history."""
    if not HISTORY_FILE.exists():
        print("No history yet.")
        return

    lines = HISTORY_FILE.read_text().strip().splitlines()
    recent = lines[-limit:]

    print(f"=== Arbitrator History (last {len(recent)} cycles) ===")
    print(f"{'Cycle':>6} | {'State':<18} | {'Stuck':>5} | {'Level':<10} | {'CUCo Dim':<10} | Directive")
    print("-" * 100)
    for line in recent:
        try:
            e = json.loads(line)
            print(
                f"{e['cycle']:>6} | {e['state']:<18} | "
                f"{e['same_state_cycles']:>5} | {e['escalation']:<10} | "
                f"{(e.get('cuco_dim') or '-'):<10} | "
                f"{(e.get('directive') or '-')[:40]}"
            )
        except (json.JSONDecodeError, KeyError):
            continue


# =============================================================================
# Helpers
# =============================================================================

def _count_pattern(text: str, pattern: str) -> int:
    """Count regex pattern matches in text."""
    import re
    return len(re.findall(pattern, text))


def _last_match(text: str, pattern: str) -> Optional[str]:
    """Return the last regex match group(1) in text."""
    import re
    matches = re.findall(pattern, text)
    return matches[-1] if matches else None


def _extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from text that may contain non-JSON lines."""
    # Try the whole output first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the output
    brace_start = text.find("{")
    if brace_start < 0:
        return None

    # Find matching closing brace
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace_start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Transport Supervision Arbitrator — coordinates all supervision layers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (default)     Run the continuous arbitration loop
  --once        Run a single cycle and exit
  --status      Print current state summary
  --history     Print recent arbitration history

Escalation ladder:
  Level 0 OBSERVE   (cycles 0-2)  — Watch and log
  Level 1 DIAGNOSE  (cycle 3)     — CUCo design-space analysis
  Level 2 SUGGEST   (cycles 4-5)  — Send directive to agent
  Level 3 EVOLVE    (cycles 6-7)  — Evolution-guided recovery
  Level 4 DEPLOY    (cycles 8+)   — Deploy best candidate
  Level 5 ESCALATE  (cycle 12+)   — Human intervention needed

Examples:
  python3 arbitrator.py --session session-b --interval 90
  python3 arbitrator.py --once --dry-run
  python3 arbitrator.py --status
  python3 arbitrator.py --history --limit 50
""",
    )
    parser.add_argument("--session", default="session-b", help="tmux session name (default: rdma)")
    parser.add_argument("--interval", type=int, default=90, help="Seconds between cycles (default: 90)")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without sending directives")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--status", action="store_true", help="Print current arbitrator status")
    parser.add_argument("--history", action="store_true", help="Print recent history")
    parser.add_argument("--limit", type=int, default=20, help="History entries to show (default: 20)")
    parser.add_argument("--namespace", default="gpu-transport", help="K8s namespace")
    parser.add_argument("--pod", default="workload-pod-0", help="K8s pod name")
    parser.add_argument("--reset", action="store_true", help="Reset shared state and start fresh")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handlers.append(logging.FileHandler(str(LOG_FILE)))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    if args.status:
        print_status()
        return 0

    if args.history:
        print_history(args.limit)
        return 0

    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print(f"Reset: {STATE_FILE} removed")
        return 0

    arb = Arbitrator(
        session=args.session,
        interval=args.interval,
        dry_run=args.dry_run,
        namespace=args.namespace,
        pod=args.pod,
    )

    if args.once:
        state = arb.run_once()
        print(json.dumps(state.to_dict(), indent=2, default=str))
        return 0

    arb.run_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
