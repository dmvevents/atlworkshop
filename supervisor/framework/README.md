# Agent Supervisor Framework

A generic, reusable framework for supervising Claude Code agents (or any long-running process). Originally extracted from the Bolt EFA transport arbitrator, the framework decouples the supervision engine from domain-specific logic through composable abstractions.

## Architecture

```
                 YAML Profile
                     |
                     v
            +------------------+
            | SupervisorProfile|  (loads config, wires components)
            +------------------+
                     |
                     v
    +------------------------------------+
    |            Supervisor              |  (main loop engine)
    |                                    |
    |  collect -> classify -> escalate   |
    |  -> act -> deliver -> persist      |
    +------------------------------------+
         |         |        |       |       |        |
         v         v        v       v       v        v
    Collector  Classifier  Advisor  Recovery  Delivery  State
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **Collector** | `collector.py` | Gathers raw text and metrics from external sources (tmux, kubectl, log files, shell commands) |
| **Classifier** | `classifier.py` | Maps metrics to a named state using ordered rules |
| **Advisor** | `advisor.py` | Produces diagnostic suggestions for a given state |
| **Recovery** | `recovery.py` | Generates recovery candidates when stuck |
| **Delivery** | `delivery.py` | Sends directives to the supervised agent |
| **Escalation** | `escalation.py` | Configurable multi-level escalation ladder with cooldowns |
| **State** | `state.py` | Persistent JSON state and JSONL history |
| **Supervisor** | `supervisor.py` | Main engine that orchestrates the loop |
| **Profile** | `profile.py` | Loads a complete Supervisor from a YAML file |

## Quick Start

### 1. From YAML Profile

```python
from supervisor.framework import SupervisorProfile

sup = SupervisorProfile.from_yaml("supervisor/profiles/tmux-agent.yaml")
sup.run_loop(interval=60)
```

### 2. Programmatic Assembly

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
        {"state": "HAS_ERRORS", "conditions": [{"metric": "errors", "op": ">", "value": 0}]},
    ]),
    advisor=RuleBasedAdvisor({"HAS_ERRORS": {
        "dimension": "runtime",
        "suggestions": [{"value": "check logs", "description": "Review error output"}],
        "rationale": "Errors detected.",
        "checks": ["Check stderr"],
    }}),
    recovery=PlaybookRecovery({"HAS_ERRORS": [
        {"action": "command", "value": "make clean && make", "description": "Clean rebuild"},
    ]}),
    delivery=TmuxDelivery("my-session"),
    escalation=EscalationLadder([
        EscalationStep("OBSERVE", 0, "observe"),
        EscalationStep("DIAGNOSE", 3, "diagnose"),
        EscalationStep("SUGGEST", 5, "suggest"),
        EscalationStep("ESCALATE", 10, "escalate", cooldown_cycles=15),
    ]),
    state_manager=SharedStateManager("/tmp/my-state.json", "/tmp/my-history.jsonl"),
    name="my-supervisor",
)

# Single cycle
state = sup.run_once()

# Continuous loop
sup.run_loop(interval=30)

# Check status
print(sup.status())
```

### 3. Run the Demo

```bash
python3 supervisor/framework/demo.py
```

## Creating a Profile

Profiles are YAML files that declaratively configure all supervisor components. See `profiles/bolt-efa.yaml` for an HPC example and `profiles/tmux-agent.yaml` for a generic example.

### Profile Schema

```yaml
name: my-supervisor
description: "What this supervisor watches"

collector:
  type: tmux|kubectl|logfile|command
  # Type-specific config (session, namespace/pod, path, command)
  patterns:
    metric_name: "regex pattern"
    another_metric:
      pattern: "regex with (group)"
      extract: count|last_group1|all

classifier:
  type: rule_based
  default_state: UNKNOWN
  rules:
    - state: STATE_NAME
      conditions:
        - {metric: metric_name, op: "==", value: 0}
        # Operators: ==, !=, >, >=, <, <=, in, not_in, empty, not_empty, contains

escalation:
  steps:
    - {name: OBSERVE, threshold: 0, action: observe}
    - {name: DIAGNOSE, threshold: 3, action: diagnose}
    - {name: SUGGEST, threshold: 5, action: suggest}
    - {name: RECOVER, threshold: 8, action: recover}
    - {name: DEPLOY, threshold: 10, action: deploy, cooldown: 10}
    - {name: ESCALATE, threshold: 15, action: escalate, cooldown: 20}
  no_escalate_states: [COMPLETED, IDLE]

advisor:
  type: rule_based|script
  # rule_based: state_map dict
  # script: script path + args template

recovery:
  type: playbook|script|null
  # playbook: state -> steps mapping
  # script: external script path

delivery:
  type: tmux|file|webhook|null
  # Type-specific config

state:
  path: path/to/state.json
  history_path: path/to/history.jsonl
```

### Escalation Actions

| Action | Behavior |
|--------|----------|
| `observe` | Log metrics only |
| `diagnose` | Call advisor, store diagnosis |
| `suggest` | Send diagnostic directive from advisor suggestions |
| `recover` | Run recovery strategy, generate candidates |
| `deploy` | Deploy best recovery candidate |
| `escalate` | Alert human, all automation exhausted |

### Collector Types

| Type | Source | Key Config |
|------|--------|------------|
| `tmux` | tmux pane capture | `session`, `capture_lines` |
| `kubectl` | kubectl logs | `namespace`, `pod`, `tail_lines` |
| `logfile` | local file | `path`, `tail_lines` |
| `command` | shell command | `command`, `timeout`, `shell` |

### Pattern Extraction

Patterns can be simple regex strings (returns match count) or dicts:

```yaml
patterns:
  # Simple: count matches
  errors: "ERROR|error"

  # Extract last capture group
  version:
    pattern: "version=(\\d+\\.\\d+)"
    extract: last_group1

  # Collect all matches
  all_ips:
    pattern: "\\d+\\.\\d+\\.\\d+\\.\\d+"
    extract: all
```

## Relationship to arbitrator.py

The existing `arbitrator.py` is the Bolt-specific implementation that predates this framework. It remains untouched and fully functional. The `profiles/bolt-efa.yaml` profile recreates equivalent behavior using the framework's generic components.

For new supervision use cases, use the framework instead of copying arbitrator.py.

## Dependencies

- Python 3.12+
- PyYAML (for profile loading)
- No HPC-specific dependencies in the framework itself
