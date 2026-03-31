# Agent Supervisor System

A production-grade autonomous supervision system for AI coding agents. Originally built to monitor and guide Claude Code agents working on HPC/RDMA debugging tasks, the system is general-purpose and can supervise any long-running agent or process.

**Upstream:** [github.com/dmvevents/hpc-agent-stack/tree/master/supervisor](https://github.com/dmvevents/hpc-agent-stack/tree/master/supervisor)

## Architecture

```
                    YAML Profile
                        |
                        v
               +------------------+
               | SupervisorProfile|  loads config, wires components
               +------------------+
                        |
                        v
       +------------------------------------+
       |           Supervisor               |  main loop engine
       |                                    |
       |  collect -> classify -> escalate   |
       |  -> act -> deliver -> persist      |
       +------------------------------------+
            |         |        |       |       |        |
            v         v        v       v       v        v
       Collector  Classifier  Advisor  Recovery  Delivery  State
```

### Escalation Ladder

The core concept is a **progressive escalation ladder** that automatically increases intervention as the supervised agent remains stuck:

```
Level 0: OBSERVE    (cycles 0-2)   Watch and log metrics
Level 1: DIAGNOSE   (cycle 3)      Consult design-space advisor
Level 2: SUGGEST    (cycles 4-5)   Send diagnostic directive to agent
Level 3: EVOLVE     (cycles 6-7)   Evolution-guided candidate generation
Level 4: DEPLOY     (cycles 8+)    Deploy best recovery candidate
Level 5: ESCALATE   (cycle 12+)    Human intervention needed
```

Each level has a configurable **cooldown** to prevent thrashing. State changes reset the escalation to OBSERVE.

## File Listing

### Core Scripts

| File | Description |
|------|-------------|
| `monitor.sh` | Continuous session monitor with multi-LLM analysis. Captures tmux output, extracts metrics (timeouts, errors, tokens), detects patterns (stuck loops, crashes, long thinking), and dispatches to LLM for corrective directives. |
| `arbitrator.py` | Central coordinator that ties all supervision layers together. Implements the full escalation ladder with pod state machine, CUCo advisor, evolution recovery, pre-deploy gate, and directive injection. The most complete supervisor implementation. |
| `active-supervisor.sh` | Lightweight active supervisor that monitors a tmux session, detects progress stalls, and sends focused guidance. Uses institutional knowledge and multi-LLM tools. |
| `bolt-supervisor-v3.sh` | Shell-based supervisor with CUCo design-space advisor integration, tried-suggestion tracking, pre-deploy gate, and dry-run mode. Good reference for a Bash-native approach. |
| `cuco-advisor.py` | Design-space diagnostic advisor. Maps supervisor states (e.g., C0_NO_WORKER, C0_TIMEOUT, DISPATCHING) to the 5D design space (Backend x Placement x Sync x Issuer x Granularity) and suggests alternatives. |
| `evolution-recovery.py` | Evolution-guided recovery system. When stuck, enumerates design-space alternatives, splices code templates into seed kernels, runs cascaded L0/L1 evaluation, ranks candidates, and reports best recovery option. |
| `evolution-recovery-config.yaml` | Configuration for the evolution recovery system: thresholds, eval levels, current config, paths. |
| `efa-traffic-monitor.sh` | Real-time EFA hardware counter monitor. Reads tx/rx packets and bytes from pods, calculates throughput, detects anomalies (no traffic, one-way, stalled). |
| `pre-deploy-gate.sh` | L0/L1 validation gate that must pass before deploying kernel changes. Runs parse checks (balanced braces, includes) and compile checks. |
| `shared-state-example.json` | Example of the shared state JSON used by the arbitrator. Shows the state machine, escalation tracking, CUCo diagnosis, recovery candidates, and directive history. |

### Framework (Generic, Reusable)

The `framework/` directory contains a domain-independent supervision engine. No HPC dependencies.

| File | Description |
|------|-------------|
| `framework/README.md` | Framework documentation with architecture, API, and profile schema |
| `framework/__init__.py` | Package exports for all framework components |
| `framework/supervisor.py` | Main engine: `collect -> classify -> escalate -> act -> deliver -> persist` loop |
| `framework/collector.py` | Gathers metrics from tmux, kubectl, log files, or shell commands via regex patterns |
| `framework/classifier.py` | Rule-based state classification from metrics with operator support (`==`, `>`, `in`, `contains`, etc.) |
| `framework/advisor.py` | Diagnostic advisors: rule-based (static config) or script-based (external process) |
| `framework/recovery.py` | Recovery strategies: playbook-based (predefined steps) or script-based (external process) |
| `framework/delivery.py` | Directive delivery: tmux send-keys, file-based, webhook, or composite multi-target |
| `framework/escalation.py` | Configurable escalation ladder with thresholds, cooldowns, and no-escalate states |
| `framework/state.py` | Persistent JSON state and JSONL history manager |
| `framework/profile.py` | Loads a complete Supervisor from a YAML profile file |
| `framework/demo.py` | Interactive demo: 15 cycles showing the full escalation progression |

### Profiles

| File | Description |
|------|-------------|
| `profiles/example-efa.yaml` | Example profile for monitoring GPU transport on Kubernetes pods |
| `profiles/tmux-agent.yaml` | Generic profile for supervising any Claude Code agent via tmux |

### Recovery Templates

C++ code templates used by `evolution-recovery.py` to generate recovery candidates:

| File | Description |
|------|-------------|
| `recovery-templates/backend_fi_send.cpp.tmpl` | Host staging copy backend (cudaMemcpyAsync + fi_writemsg) |
| `recovery-templates/backend_fi_write.cpp.tmpl` | DMA-BUF zero-copy backend (GPU memory direct to NIC) |
| `recovery-templates/backend_gdrcopy.cpp.tmpl` | GDRCopy MMIO read backend (BAR1 mapping) |
| `recovery-templates/backend_staging_bulk.cpp.tmpl` | Bulk staging copy backend (full buffer pre-copy) |
| `recovery-templates/sync_d2h_ring.cpp.tmpl` | D2H ring buffer synchronization (GPU writes descriptors to host ring) |
| `recovery-templates/sync_gdrcopy.cpp.tmpl` | GDRCopy MMIO signal synchronization (CPU reads GPU flags directly) |
| `recovery-templates/sync_volatile.cpp.tmpl` | Volatile flag polling synchronization (host-pinned PCIe coherent) |

### Learnings (Redacted Examples)

| File | Description |
|------|-------------|
| `learnings/timeline-example.md` | Example supervision timeline showing metric capture and event extraction |
| `learnings/directives-example.md` | Example of automated directives sent to the supervised agent |
| `learnings/deep-analysis-example.md` | Example deep analysis output from periodic multi-model review |

### Multi-LLM Codegen (Redacted Examples)

| File | Description |
|------|-------------|
| `multi-llm-codegen/bedrock-example.md` | Example code generated by Claude (Bedrock) for transport layer |
| `multi-llm-codegen/gemini-example.md` | Example code generated by Gemini for transport layer |

## How to Use Each Component

### 1. Quick Start: Run the Demo

```bash
python3 supervisor/framework/demo.py
```

This runs 15 simulated cycles showing the full escalation ladder in action, from OBSERVE through DIAGNOSE, SUGGEST, RECOVER, and ESCALATE.

### 2. Generic Agent Supervision (from YAML)

```python
from supervisor.framework import SupervisorProfile

# Load a profile and start supervising
sup = SupervisorProfile.from_yaml("supervisor/profiles/tmux-agent.yaml")
sup.run_loop(interval=60)
```

### 3. Programmatic Assembly

```python
from supervisor.framework import (
    TmuxCollector,
    RuleBasedClassifier,
    RuleBasedAdvisor,
    PlaybookRecovery,
    TmuxDelivery,
    EscalationLadder,
    EscalationStep,
    SharedStateManager,
    Supervisor,
)

sup = Supervisor(
    collector=TmuxCollector("my-session", {"errors": "ERROR|error"}),
    classifier=RuleBasedClassifier([
        {"state": "HAS_ERRORS",
         "conditions": [{"metric": "errors", "op": ">", "value": 0}]},
    ]),
    advisor=RuleBasedAdvisor({"HAS_ERRORS": {
        "dimension": "runtime",
        "suggestions": [{"value": "check logs", "description": "Review output"}],
        "rationale": "Errors detected.",
        "checks": ["Check stderr"],
    }}),
    recovery=PlaybookRecovery({"HAS_ERRORS": [
        {"action": "command", "value": "make clean && make",
         "description": "Clean rebuild"},
    ]}),
    delivery=TmuxDelivery("my-session"),
    escalation=EscalationLadder([
        EscalationStep("OBSERVE", 0, "observe"),
        EscalationStep("DIAGNOSE", 3, "diagnose"),
        EscalationStep("SUGGEST", 5, "suggest"),
        EscalationStep("ESCALATE", 10, "escalate", cooldown_cycles=15),
    ]),
    state_manager=SharedStateManager("/tmp/state.json", "/tmp/history.jsonl"),
    name="my-supervisor",
)

sup.run_loop(interval=30)
```

### 4. Shell-Based Monitoring

```bash
# Simple tmux session monitor
./supervisor/monitor.sh 300 my-session

# EFA traffic monitor on K8s pods
./supervisor/efa-traffic-monitor.sh my-namespace my-pod-prefix 30

# Full state-machine supervisor with dry-run
./supervisor/bolt-supervisor-v3.sh my-session 90 --dry-run
```

### 5. Full Arbitrator (Python, Production)

```bash
# Continuous arbitration loop
python3 supervisor/arbitrator.py --session my-session --interval 90

# Single cycle (debug)
python3 supervisor/arbitrator.py --once --dry-run

# Check status
python3 supervisor/arbitrator.py --status

# View history
python3 supervisor/arbitrator.py --history --limit 50
```

### 6. Design-Space Advisor (Standalone)

```bash
# Interactive diagnostic
python3 supervisor/cuco-advisor.py --state C0_NO_WORKER

# JSON output for programmatic use
python3 supervisor/cuco-advisor.py --state DISPATCHING --timeout --json

# With current config
python3 supervisor/cuco-advisor.py --state C0_TIMEOUT \
    --config 'B=d2h_ring_fi_send,S=d2h_ring,I=multi_warp'
```

### 7. Evolution Recovery (Standalone)

```bash
# Dry run: show what alternatives exist
python3 supervisor/evolution-recovery.py --state C0_NO_WORKER \
    --stuck-cycles 5 --dry-run

# Demo mode with mock data
python3 supervisor/evolution-recovery.py --demo

# Full run with custom seed kernel
python3 supervisor/evolution-recovery.py --state DISPATCHING \
    --stuck-cycles 7 --seed-kernel /path/to/kernel.cu --json
```

## Creating a Custom Profile

Write a YAML file following the schema in `framework/README.md`:

```yaml
name: my-custom-supervisor
description: "Supervises my agent doing X"

collector:
  type: tmux
  session: my-agent
  capture_lines: 500
  patterns:
    errors: "ERROR|error|FAIL"
    progress: "Step \\d+ complete"
    waiting: "Waiting|polling"

classifier:
  type: rule_based
  default_state: WORKING
  rules:
    - state: HAS_ERRORS
      conditions:
        - {metric: errors, op: ">", value: 0}
    - state: COMPLETED
      conditions:
        - {metric: progress, op: ">", value: 5}

escalation:
  steps:
    - {name: OBSERVE, threshold: 0, action: observe}
    - {name: DIAGNOSE, threshold: 3, action: diagnose}
    - {name: SUGGEST, threshold: 5, action: suggest}
    - {name: ESCALATE, threshold: 10, action: escalate, cooldown: 20}
  no_escalate_states: [COMPLETED, WORKING]

advisor:
  type: rule_based
  state_map:
    HAS_ERRORS:
      dimension: runtime
      suggestions:
        - {value: "review logs", description: "Check error output"}
      rationale: "Errors detected in agent output."
      checks: ["Run with --verbose"]

recovery:
  type: null

delivery:
  type: tmux
  session: my-agent

state:
  path: /tmp/my-supervisor-state.json
  history_path: /tmp/my-supervisor-history.jsonl
```

Then run it:

```python
from supervisor.framework import SupervisorProfile
sup = SupervisorProfile.from_yaml("my-profile.yaml")
sup.run_loop(interval=60)
```

## Key Design Decisions

1. **Progressive escalation, not immediate intervention.** The system watches for several cycles before intervening, reducing false positives.

2. **Cooldown after action.** After deploying a recovery candidate or escalating, the system backs off for a configurable number of cycles.

3. **Design-space awareness.** The CUCo advisor maps failure states to specific dimensions of a multi-dimensional design space, enabling systematic exploration of alternatives rather than random guessing.

4. **Template-based code generation.** Recovery candidates are generated by splicing code templates into seed kernels, with L0/L1 evaluation gates before deployment.

5. **Tried-alternative tracking.** The system remembers which alternatives have been attempted, avoiding repeated failures.

6. **State change resets escalation.** If the supervised system transitions to a new state, the escalation ladder resets to OBSERVE, recognizing that a new state may resolve itself.

## Dependencies

- Python 3.12+
- PyYAML (for profile loading and design-space YAML)
- tmux (for tmux-based collectors and delivery)
- kubectl (for Kubernetes-based collectors)
- No HPC-specific dependencies in the framework itself
