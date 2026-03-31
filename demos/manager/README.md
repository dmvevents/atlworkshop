# Manager + Arbitrator Demo

Quick-start guide for running the agent supervision demo.

## Prerequisites

- tmux installed (`sudo apt install tmux` or `brew install tmux`)
- Python 3.10+
- Two or more Claude Code sessions running in named tmux windows

## Directory Structure

```
demos/manager/
+-- README.md                  # This file
+-- scripts/
|   +-- monitor-cycle.sh       # Single monitoring cycle with state detection
|   +-- send-message.sh        # Triple-channel message delivery
|   +-- poll-sessions.sh       # Quick poll returning JSON state
+-- arbitrator/
|   +-- arbitrator.py          # Escalation engine (6-level ladder)
+-- state/
    +-- registry-example.json  # Example session registry
    +-- clusters-example.json  # Example cluster lock configuration
```

## Quick Start

### 1. Set Up Your Manager Directory

```bash
# Create working directories
export MANAGER_DIR="$HOME/my-manager"
mkdir -p "$MANAGER_DIR"/{state,logs}
mkdir -p "$MANAGER_DIR"/state/directives

# Copy example configs
cp state/registry-example.json "$MANAGER_DIR/state/registry.json"
cp state/clusters-example.json "$MANAGER_DIR/state/clusters.json"
```

### 2. Start Test Sessions

```bash
# Create two named tmux sessions to manage
tmux new-session -d -s session-a "claude"
tmux new-session -d -s session-b "claude"

# Optionally start a manager session
tmux new-session -d -s manager
```

### 3. Run a Monitoring Cycle

```bash
# Set the sessions to monitor (space-separated)
export MANAGED_SESSIONS="session-a session-b"
export MANAGER_DIR="$HOME/my-manager"

# Run a single monitoring cycle
./scripts/monitor-cycle.sh
```

Expected output:

```
===========================================
  MONITOR CYCLE 14:32:07
===========================================
  session-a: THINKING(3m 22s) OK      pods=0
  session-b: AT_PROMPT(0s)    OK      pods=0
  LOCK: FREE holder=none age=0m
  ISSUES: session-b_idle
===========================================
```

### 4. Send a Directive

```bash
# Send a message to a stuck session
./scripts/send-message.sh session-a "You have been stuck on this build error \
for 10 minutes. Try cleaning the build directory first: rm -rf build && mkdir build"
```

### 5. Try the Arbitrator

```bash
# Single cycle, dry-run (no real directives sent)
cd arbitrator/
python3 arbitrator.py --once --dry-run --session session-a

# Check status
python3 arbitrator.py --status

# View history
python3 arbitrator.py --history

# Continuous monitoring (90-second intervals)
python3 arbitrator.py --session session-a --interval 90 --dry-run
```

## Customization

### Adding Sessions

Edit `$MANAGER_DIR/state/registry.json` to add your sessions:

```json
{
  "sessions": {
    "my-frontend": {
      "project": "React dashboard",
      "directory": "/home/user/dashboard",
      "state": "UNKNOWN",
      "stuck_count": 0,
      "capabilities": ["build", "test"],
      "priority": 1
    }
  }
}
```

### Configuring Clusters

Edit `$MANAGER_DIR/state/clusters.json` to define your GPU resources:

```json
{
  "clusters": {
    "dev-cluster": {
      "nodes": 1,
      "gpus_per_node": 4,
      "holder": null,
      "queue": [],
      "max_hold_min": 30
    }
  }
}
```

### Adjusting Escalation Thresholds

In `arbitrator/arbitrator.py`, modify the `ESCALATION_THRESHOLDS` dictionary:

```python
ESCALATION_THRESHOLDS = {
    EscalationLevel.OBSERVE: 0,
    EscalationLevel.DIAGNOSE: 3,   # Increase for more patience
    EscalationLevel.SUGGEST: 5,
    EscalationLevel.EVOLVE: 8,
    EscalationLevel.DEPLOY: 12,
    EscalationLevel.ESCALATE: 20,
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MANAGER_DIR` | `./` (script directory) | Manager state and logs directory |
| `MANAGED_SESSIONS` | `session-a session-b` | Space-separated tmux session names |
| `LOCK_FILE` | `$MANAGER_DIR/state/cluster-lock.json` | Cluster lock file path |
| `ARBITRATOR_DIR` | `./` (script directory) | Arbitrator working directory |

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| "no server running" | tmux not started | `tmux new-session -d -s session-a` |
| Empty capture output | Session name mismatch | Check `tmux list-sessions` |
| Directive not received | tmux send-keys unreliable | Check file inbox in `state/directives/` |
| Arbitrator shows UNKNOWN | No pods running | Expected if not using K8s -- modify collector |
