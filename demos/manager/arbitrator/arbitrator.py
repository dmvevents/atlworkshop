#!/usr/bin/env python3
"""
Supervision Arbitrator -- Central coordinator for agent supervision.

Implements an escalation ladder for autonomous agent sessions:
  Level 0: OBSERVE     -- watch, log metrics (cycles 1-2)
  Level 1: DIAGNOSE    -- analyze root cause (cycle 3)
  Level 2: SUGGEST     -- send diagnostic directive to agent (cycle 4-5)
  Level 3: EVOLVE      -- generate fix candidates (cycle 6-7)
  Level 4: DEPLOY      -- deploy best candidate through validation gate (cycle 8+)
  Level 5: ESCALATE    -- all options exhausted, alert human (cycle 12+)

Usage:
    python3 arbitrator.py --session session-a --interval 90
    python3 arbitrator.py --session session-a --interval 90 --dry-run
    python3 arbitrator.py --once          # single cycle, no loop
    python3 arbitrator.py --status        # print current state
    python3 arbitrator.py --history       # print recent history
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

# Paths -- configurable via ARBITRATOR_DIR environment variable
ARBITRATOR_DIR = Path(os.environ.get("ARBITRATOR_DIR", Path(__file__).resolve().parent))
STATE_FILE = ARBITRATOR_DIR / "shared-state.json"
HISTORY_FILE = ARBITRATOR_DIR / "logs" / "arbitrator-history.jsonl"
LOG_FILE = ARBITRATOR_DIR / "logs" / "arbitrator.log"

# External scripts -- configure these for your environment
SEND_MESSAGE_SCRIPT = Path(os.environ.get(
    "SEND_MESSAGE_SCRIPT",
    str(ARBITRATOR_DIR.parent / "scripts" / "send-message.sh"),
))


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
    EscalationLevel.ESCALATE: 12,  # 12 cycles -- human needed
}

# States that don't trigger escalation (transient or terminal)
NO_ESCALATE_STATES = {"ALL_PASS", "BARRIER_WAIT", "NO_PODS", "AT_PROMPT", "JUST_FINISHED"}


# =============================================================================
# Shared State
# =============================================================================

@dataclass
class SharedState:
    """Unified state shared across all supervision layers."""
    # Identity
    session: str = "session-a"
    cycle: int = 0
    timestamp: str = ""

    # Session state
    state: str = "UNKNOWN"
    previous_state: str = ""
    same_state_cycles: int = 0
    metrics: dict = field(default_factory=dict)

    # Escalation
    escalation_level: int = 0
    escalation_name: str = "OBSERVE"

    # Diagnosis
    diagnosis: Optional[dict] = None
    failing_component: Optional[str] = None
    suggestions: list = field(default_factory=list)

    # Recovery
    recovery_report: Optional[dict] = None
    recovery_best_candidate: Optional[str] = None

    # Directive tracking
    last_directive: str = ""
    last_directive_time: str = ""
    directives_sent: int = 0

    # History
    tried_alternatives: list = field(default_factory=list)
    cooldown_until_cycle: int = 0

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
# Session State Collector
# =============================================================================

class SessionStateCollector:
    """Reads tmux capture output and determines session state."""

    def __init__(self, session: str = "session-a"):
        self.session = session

    def collect(self) -> tuple[str, dict]:
        """Capture tmux output and determine state. Returns (state, metrics)."""
        capture_file = f"/tmp/{self.session}-capture.txt"

        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", self.session, "-p", "-S", "-150"],
                capture_output=True, text=True, timeout=10,
            )
            log_text = result.stdout if result.returncode == 0 else ""
            with open(capture_file, "w") as f:
                f.write(log_text)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log_text = ""

        if not log_text:
            return "NO_SESSION", {}

        metrics = {
            "lines": len(log_text.splitlines()),
            "errors": _count_pattern(log_text, r"Error:.*|FAIL:.*"),
            "loop_count": self._detect_loop_count(log_text),
        }

        # State detection
        thinking_words = (
            "Cerebrating|Levitating|Wandering|Symbioting|Cultivating|"
            "Fermenting|Wrangling|Herding|Combobulating|Frosting|"
            "Churned|Cooked|Brewed|Worked|Spelunking|Crunched|Processing"
        )

        lines = log_text.splitlines()
        tail15 = "\n".join(lines[-15:]) if len(lines) >= 15 else log_text
        tail5 = "\n".join(lines[-5:]) if len(lines) >= 5 else log_text
        tail20 = "\n".join(lines[-20:]) if len(lines) >= 20 else log_text

        import re

        if re.search(thinking_words, tail15):
            think_match = re.findall(r"\d+m \d+s|\d+s", tail15)
            think_time = think_match[-1] if think_match else "?"
            metrics["think_time"] = think_time

            # Check if just finished
            if ">" in tail5:
                if re.search(r"(Cooked|Brewed|Churned|Worked) for", "\n".join(lines[-10:])):
                    return "JUST_FINISHED", metrics
            return "THINKING", metrics

        if ">" in tail5:
            return "AT_PROMPT", metrics

        if re.search(r"timeout.*\d+m|Running\.\.\.|BUILD|deploying|kubectl", tail20):
            return "RUNNING_TEST", metrics

        if re.search(r"SIGSEGV|Segmentation|CRASHED|Error:.*fatal", tail20):
            return "CRASHED", metrics

        return "UNKNOWN", metrics

    def _detect_loop_count(self, text: str) -> int:
        """Count maximum repetition of any single error pattern."""
        import re
        errors = re.findall(r"Error:.*|FAIL:.*", text)
        if not errors:
            return 0
        from collections import Counter
        counts = Counter(errors)
        return max(counts.values()) if counts else 0


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
        logger.info(
            f"[OBSERVE] State={state.state} cycle={state.cycle} "
            f"stuck={state.same_state_cycles}"
        )
        return state

    def _diagnose(self, state: SharedState) -> SharedState:
        """Level 1: Analyze the problem. In production, dispatch to multi-LLM."""
        logger.info(f"[DIAGNOSE] Analyzing state={state.state}")

        # In production, you would dispatch to multiple LLMs here:
        #   query_model("gpt-5.4", problem_description)
        #   query_model("gemini-3-pro", problem_description)
        #   query_model("claude-think", problem_description)
        #
        # For this demo, we log the diagnosis request.
        state.diagnosis = {
            "state": state.state,
            "stuck_cycles": state.same_state_cycles,
            "errors": state.metrics.get("errors", 0),
            "loop_count": state.metrics.get("loop_count", 0),
        }
        state.failing_component = state.state
        logger.info(f"[DIAGNOSE] Errors={state.metrics.get('errors', 0)} "
                     f"loops={state.metrics.get('loop_count', 0)}")
        return state

    def _suggest(self, state: SharedState) -> SharedState:
        """Level 2: Send a diagnostic directive to the agent."""
        if not state.diagnosis:
            state = self._diagnose(state)

        loop_count = state.metrics.get("loop_count", 0)
        if loop_count >= 3:
            directive = (
                f"[SUPERVISOR L2-SUGGEST] You have been stuck in state "
                f"{state.state} for {state.same_state_cycles} cycles. "
                f"The same error has appeared {loop_count} times. "
                f"Try a fundamentally different approach instead of "
                f"retrying the same strategy."
            )
        else:
            directive = (
                f"[SUPERVISOR L2-SUGGEST] Stuck in {state.state} for "
                f"{state.same_state_cycles} cycles. "
                f"Step back and verify your assumptions before continuing."
            )

        self._send_directive(state, directive)
        return state

    def _evolve(self, state: SharedState) -> SharedState:
        """Level 3: Generate fix candidates."""
        logger.info(f"[EVOLVE] Generating candidates for state={state.state}")

        # In production, this would run an evolution-recovery script
        # that generates alternative approaches and evaluates them.
        directive = (
            f"[SUPERVISOR L3-EVOLVE] Recovery analysis for state {state.state}. "
            f"Stuck for {state.same_state_cycles} cycles. "
            f"Previously tried: {state.tried_alternatives}. "
            f"Generate 2-3 alternative approaches and evaluate each before implementing."
        )
        self._send_directive(state, directive)
        return state

    def _deploy(self, state: SharedState) -> SharedState:
        """Level 4: Deploy the best candidate."""
        logger.info(f"[DEPLOY] Deploying recovery candidate for state={state.state}")

        directive = (
            f"[SUPERVISOR L4-DEPLOY] Automated recovery attempt. "
            f"State {state.state} stuck for {state.same_state_cycles} cycles. "
            f"Apply the most promising alternative approach. "
            f"If this does not resolve the issue, escalation to human will follow."
        )
        self._send_directive(state, directive)

        # Set cooldown -- give the intervention time to take effect
        state.cooldown_until_cycle = state.cycle + 10
        return state

    def _escalate(self, state: SharedState) -> SharedState:
        """Level 5: All automated options exhausted. Alert human."""
        logger.warning(
            f"[ESCALATE] State {state.state} stuck for {state.same_state_cycles} "
            f"cycles. All automated recovery options exhausted."
        )
        directive = (
            f"[SUPERVISOR L5-ESCALATE] HUMAN INTERVENTION NEEDED. "
            f"State {state.state} stuck for {state.same_state_cycles} cycles. "
            f"Tried alternatives: {state.tried_alternatives}. "
            f"Review the arbitrator log for full history."
        )
        self._send_directive(state, directive)

        # Long cooldown after escalation
        state.cooldown_until_cycle = state.cycle + 20
        return state

    def _send_directive(self, state: SharedState, directive: str):
        """Send a directive to the managed session."""
        if directive == state.last_directive:
            logger.info(f"[DIRECTIVE] Skipped (duplicate): {directive[:80]}...")
            return

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would send: {directive[:200]}")
        else:
            logger.info(f"[DIRECTIVE] Sending: {directive[:200]}")
            try:
                if SEND_MESSAGE_SCRIPT.exists():
                    subprocess.run(
                        [str(SEND_MESSAGE_SCRIPT), state.session, directive],
                        capture_output=True, timeout=10,
                    )
                else:
                    # Fallback: direct tmux send-keys
                    subprocess.run(
                        ["tmux", "send-keys", "-t", state.session, "-l", directive[:400]],
                        capture_output=True, timeout=10,
                    )
                    subprocess.run(
                        ["tmux", "send-keys", "-t", state.session, "Enter"],
                        capture_output=True, timeout=5,
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
        session: str = "session-a",
        interval: int = 90,
        dry_run: bool = False,
    ):
        self.session = session
        self.interval = interval
        self.dry_run = dry_run
        self.collector = SessionStateCollector(session=session)
        self.engine = EscalationEngine(session=session, dry_run=dry_run)

        # Ensure log directory exists
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> SharedState:
        """Run a single arbitration cycle."""
        # Load shared state
        state = SharedState.load()
        state.session = self.session
        state.cycle += 1

        # Phase 1: Collect session state
        session_state, metrics = self.collector.collect()
        state.metrics = metrics

        # Phase 2: Update state machine
        if session_state == state.state:
            state.same_state_cycles += 1
        else:
            state.previous_state = state.state
            state.state = session_state
            state.same_state_cycles = 1
            # Reset escalation on state change
            state.diagnosis = None
            state.recovery_report = None
            state.recovery_best_candidate = None

        # Phase 3: Determine escalation level
        level = self.engine.determine_level(state)

        # Phase 4: Log
        logger.info(
            f"Cycle {state.cycle}: {state.state} "
            f"({state.same_state_cycles}x) "
            f"escalation={level.name} "
            f"| errors={metrics.get('errors', 0)} "
            f"loops={metrics.get('loop_count', 0)}"
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
            "failing_component": state.failing_component,
            "recovery_candidate": state.recovery_best_candidate,
            "metrics": {
                "errors": state.metrics.get("errors", 0),
                "loop_count": state.metrics.get("loop_count", 0),
            },
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")


# =============================================================================
# Status and History Commands
# =============================================================================

def print_status():
    """Print current arbitrator status from shared state."""
    state = SharedState.load()
    if state.cycle == 0:
        print("Arbitrator has not run yet. Start with: python3 arbitrator.py --session session-a")
        return

    print("=== Supervision Arbitrator ===")
    print(f"Cycle:       {state.cycle}")
    print(f"Timestamp:   {state.timestamp}")
    print(f"Session:     {state.session}")
    print()
    print("--- Session State ---")
    print(f"State:       {state.state} ({state.same_state_cycles} consecutive cycles)")
    print(f"Previous:    {state.previous_state}")
    m = state.metrics
    print(f"Errors:      {m.get('errors', 0)}")
    print(f"Loop count:  {m.get('loop_count', 0)}")
    print()
    print("--- Escalation ---")
    print(f"Level:       {state.escalation_level} ({state.escalation_name})")
    cooldown_active = state.cooldown_until_cycle > state.cycle
    print(f"Cooldown:    {'active (until cycle ' + str(state.cooldown_until_cycle) + ')' if cooldown_active else 'none'}")
    print()
    print("--- Diagnosis ---")
    print(f"Component:   {state.failing_component or 'N/A'}")
    print(f"Suggestions: {len(state.suggestions)}")
    print(f"Tried:       {state.tried_alternatives}")
    print()
    print("--- Recovery ---")
    print(f"Best cand:   {state.recovery_best_candidate or 'none'}")
    print()
    print("--- Directives ---")
    print(f"Total sent:  {state.directives_sent}")
    print(f"Last:        {state.last_directive[:120] if state.last_directive else 'none'}")
    print(f"Last time:   {state.last_directive_time}")


def print_history(limit: int = 20):
    """Print recent arbitration history."""
    if not HISTORY_FILE.exists():
        print("No history yet.")
        return

    lines = HISTORY_FILE.read_text().strip().splitlines()
    recent = lines[-limit:]

    print(f"=== Arbitrator History (last {len(recent)} cycles) ===")
    print(f"{'Cycle':>6} | {'State':<18} | {'Stuck':>5} | {'Level':<10} | Directive")
    print("-" * 90)
    for line in recent:
        try:
            e = json.loads(line)
            print(
                f"{e['cycle']:>6} | {e['state']:<18} | "
                f"{e['same_state_cycles']:>5} | {e['escalation']:<10} | "
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


def _extract_json(text: str) -> Optional[dict]:
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
                    return json.loads(text[brace_start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Supervision Arbitrator -- coordinates agent escalation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (default)     Run the continuous arbitration loop
  --once        Run a single cycle and exit
  --status      Print current state summary
  --history     Print recent arbitration history

Escalation ladder:
  Level 0 OBSERVE   (cycles 0-2)  -- Watch and log
  Level 1 DIAGNOSE  (cycle 3)     -- Analyze root cause
  Level 2 SUGGEST   (cycles 4-5)  -- Send directive to agent
  Level 3 EVOLVE    (cycles 6-7)  -- Generate fix candidates
  Level 4 DEPLOY    (cycles 8+)   -- Deploy best candidate
  Level 5 ESCALATE  (cycle 12+)   -- Human intervention needed

Examples:
  python3 arbitrator.py --session session-a --interval 90
  python3 arbitrator.py --once --dry-run
  python3 arbitrator.py --status
  python3 arbitrator.py --history --limit 50
""",
    )
    parser.add_argument(
        "--session", default="session-a",
        help="tmux session name to monitor (default: session-a)",
    )
    parser.add_argument(
        "--interval", type=int, default=90,
        help="Seconds between cycles (default: 90)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log actions without sending real directives",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single cycle and exit",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print current arbitrator status",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="Print recent history",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="History entries to show (default: 20)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Reset shared state and start fresh",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )

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
    )

    if args.once:
        state = arb.run_once()
        print(json.dumps(state.to_dict(), indent=2, default=str))
        return 0

    arb.run_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
