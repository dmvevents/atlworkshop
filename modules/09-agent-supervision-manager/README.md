# Module 9: Agent Supervision -- The Manager & Arbitrator System

**Time:** 15 minutes
**Level:** Advanced
**Prerequisites:** Modules 1-3 (agentic coding fundamentals, MCP servers, deploying agents)

---

## The Problem: Autonomous Agents Need Supervision

Autonomous coding agents are powerful -- but unsupervised agents develop failure modes that waste compute and developer time:

| Failure Mode | Symptoms | Impact |
|-------------|----------|--------|
| **Loop cycling** | Same error appears 3+ times | Burns context window, no progress |
| **False progress** | "Breakthrough!" with identical test output | Wastes hours chasing phantom fixes |
| **Resource contention** | Multiple sessions deploying to same GPU cluster | Pods clobbering each other |
| **Context overflow** | Agent hits token limit mid-task | Loses all session state |
| **Unverified assumptions** | Agent guesses instead of testing | Cascading wrong decisions |

**The core insight:** Nobody watches the watchers. When you have 2-5 autonomous Claude Code sessions running in parallel across tmux windows, each working on different parts of a system, you need a supervisor that can detect when an agent is stuck and intervene -- before it wastes 30 minutes going in circles.

---

## Architecture: Manager + Arbitrator

The system has three components:

1. **Manager** -- A Claude Code session running in its own tmux window that monitors other sessions
2. **Arbitrator** -- A Python escalation engine with a 6-level intervention ladder
3. **Research Engine** -- Multi-LLM verification before any directive is sent

```
+-----------------------------------------------------+
|             MANAGER SESSION (tmux: manager)          |
|                                                      |
|  Monitor Loop -> Detect State -> Research -> Direct   |
|       ^                                    |         |
|  Background     Multi-LLM       File Inbox + tmux    |
|  Agent          (GPT-5.4,       send-keys             |
|                  Gemini,                               |
|                  Bedrock)                              |
+----------+----------------------------+--------------+
           |                            |
    +------+------+              +------+------+
    |  Session A   |              |  Session B   |
    |  tmux: dev1  |              |  tmux: dev2  |
    |  Lock: YES   |              |  Lock: no    |
    +-------------+              +-------------+
```

**How it works:**

1. The Manager captures tmux pane output from each managed session (last 150 lines)
2. Pattern matching detects what state each agent is in (thinking, idle, stuck, building)
3. If a session is stuck, the Manager dispatches the problem to multiple LLMs for research
4. A synthesized directive is sent to the stuck session via file inbox + tmux injection
5. The Arbitrator tracks how many cycles a session has been stuck and escalates intervention

---

## The Escalation Ladder (Arbitrator)

The Arbitrator implements a progressive intervention strategy. It does not jump to drastic action -- it watches first, then gradually increases involvement:

| Level | Name | Trigger | Action |
|-------|------|---------|--------|
| 0 | OBSERVE | Cycles 1-2 | Watch, log metrics. No intervention. |
| 1 | DIAGNOSE | 3 cycles same state | Analyze root cause. Run diagnostic tools. |
| 2 | SUGGEST | 4-5 cycles | Send a diagnostic directive to the agent. |
| 3 | EVOLVE | 6-7 cycles | Generate fix candidates using design-space analysis. |
| 4 | DEPLOY | 8+ cycles | Deploy the best candidate through a validation gate. |
| 5 | ESCALATE | 12+ cycles | All automated options exhausted. Alert human. |

**Key design choices:**

- **Cooldown periods** after DEPLOY (10 cycles) and ESCALATE (20 cycles) prevent thrashing
- **State changes reset escalation** -- if the agent moves to a new state, the ladder resets
- **Transient states never escalate** -- states like ALL_PASS or BARRIER_WAIT are normal
- **Duplicate directive suppression** -- never send the same directive twice in a row

```python
# Simplified escalation logic
THRESHOLDS = {OBSERVE: 0, DIAGNOSE: 3, SUGGEST: 4, EVOLVE: 6, DEPLOY: 8, ESCALATE: 12}

def determine_level(stuck_cycles):
    level = OBSERVE
    for lvl, threshold in THRESHOLDS.items():
        if stuck_cycles >= threshold:
            level = lvl
    return level
```

---

## Session State Detection

The Manager detects agent state by parsing tmux output with pattern matching:

| State | Detection Method | Meaning |
|-------|-----------------|---------|
| THINKING | Claude Code status words (Cerebrating, Levitating, etc.) | Agent is processing |
| JUST_FINISHED | Past-tense words (Cooked, Brewed) + prompt visible | Just completed a response |
| AT_PROMPT | Prompt character visible, no thinking indicator | Agent is idle |
| RUNNING_TEST | Keywords: `timeout`, `BUILD`, `deploying`, `kubectl` | Running external commands |
| CRASHED | Keywords: `SIGSEGV`, `Segmentation`, `CRASHED` | Agent or process crashed |
| UNKNOWN | None of the above | Cannot determine state |

**Loop detection** counts repeated error patterns:

```bash
# Count repeated errors in tmux capture
grep -oP 'Error:.*|FAIL:.*|TIMEOUT' capture.txt \
  | sort | uniq -c | sort -rn | head -1
# If count >= 3, flag as LOOP_DETECTED
```

**False progress detection** compares test output before and after a claimed fix:
- If the output is byte-identical, the "fix" did nothing
- If the agent says "breakthrough" but metrics are unchanged, flag it

---

## Communication Channels

The Manager uses three channels simultaneously for reliability:

| Channel | Reliability | Real-time | Use For |
|---------|------------|-----------|---------|
| **File inbox** | High | No (polling) | Structured directives with metadata |
| **tmux send-keys** | Medium (~80%) | Yes | Quick nudges, short messages |
| **Shared MEMORY.md** | High | No | Cross-session context, persistent state |

**Triple-channel messaging** (how `send-message.sh` works):

1. **Hook directive file** -- Written as JSON; picked up by PreToolUse hook on next tool call (most reliable)
2. **File inbox** -- Markdown file in `state/directives/<session>/inbox/` with YAML frontmatter
3. **tmux send-keys** -- Best-effort real-time injection; messages under 400 chars sent directly, longer messages are truncated

```bash
# Example: sending a directive to session-a
./scripts/send-message.sh session-a "You have been stuck on this error for 15 minutes. \
Try a different approach: instead of patching the config, rebuild with the flag enabled."
```

---

## Multi-Cluster Lock Manager

When multiple agents share GPU clusters, a lock manager prevents resource contention:

```json
{
  "clusters": {
    "gpu-cluster-1": {
      "nodes": 2,
      "gpus_per_node": 8,
      "holder": "session-a",
      "queue": ["session-b"],
      "acquired_at": "2026-03-31T10:00:00Z",
      "max_hold_min": 30,
      "namespaces": ["project-alpha", "project-beta"]
    }
  }
}
```

**Protocol:**

1. **Check** -- Read lock file, see who holds the cluster
2. **Claim** -- If free, write your session name as holder with timestamp
3. **Deploy** -- Deploy your pods to the cluster
4. **Release** -- Scale pods to 0, set holder to null, pop next from queue

**Staleness detection:** If `acquired_at` is more than 30 minutes ago, the Manager flags the lock as STALE and can force-release it.

**Queue management:** Sessions waiting for a cluster are added to the `queue` array. When the holder releases, the Manager pops the next session and notifies it.

---

## Research-First Protocol

The Manager's superpower is that it can dispatch research to multiple frontier LLMs while the stuck agent stays focused:

1. **Capture** the problem from tmux output (last 150 lines)
2. **Dispatch** to 3 models in parallel:
   ```bash
   $QUERY_SCRIPT gpt-5.4 "$problem_description" > /tmp/response-gpt.txt &
   $QUERY_SCRIPT gemini-3-pro "$problem_description" > /tmp/response-gemini.txt &
   $QUERY_SCRIPT claude-think "$problem_description" > /tmp/response-bedrock.txt &
   wait
   ```
3. **Synthesize** consensus -- look for agreement across models
4. **Send** a focused directive with citations (which model recommended what)

**Why this matters:** An individual agent session cannot easily step back and consult other models while debugging. The Manager acts as a "research assistant" that brings external perspective to stuck agents.

---

## Anti-Regression Detection

The Manager watches for patterns that indicate wasted effort:

| Pattern | Detection | Response |
|---------|-----------|----------|
| Same error 3+ times | Error string frequency count | "Try a different approach" |
| Identical test output after "fix" | Diff of before/after output | "Your fix had no effect" |
| Rebuilding without code changes | Build triggered but no file changes | "Change code before rebuilding" |
| >15 min analysis without implementing | Time since last file edit | "Implement smallest fix and test" |
| Context window approaching limit | Token count estimation | "Run /compact with state summary" |
| Ignoring previous findings | Directive sent but same approach continued | Re-send findings in directive |

---

## Hands-on: Set Up Your Own Manager

### Step 1: Create the Manager Directory

```bash
mkdir -p ~/my-manager/{state,scripts,logs}
mkdir -p ~/my-manager/state/directives
```

### Step 2: Create a Session Registry

```bash
cat > ~/my-manager/state/registry.json << 'EOF'
{
  "sessions": {
    "session-a": {
      "project": "Frontend refactoring",
      "directory": "/home/user/projects/frontend",
      "state": "UNKNOWN",
      "stuck_count": 0,
      "last_activity": "",
      "capabilities": ["build", "test"],
      "priority": 1
    },
    "session-b": {
      "project": "API optimization",
      "directory": "/home/user/projects/api",
      "state": "UNKNOWN",
      "stuck_count": 0,
      "last_activity": "",
      "capabilities": ["build", "test", "deploy"],
      "priority": 2
    }
  }
}
EOF
```

### Step 3: Write a Monitor Cycle Script

```bash
cat > ~/my-manager/scripts/monitor-cycle.sh << 'SCRIPT'
#!/bin/bash
# monitor-cycle.sh -- Single monitoring cycle
set -euo pipefail

MANAGER_DIR="${MANAGER_DIR:-$HOME/my-manager}"
SESSIONS=("session-a" "session-b")  # Edit to match your tmux sessions

detect_state() {
    local f="$1"
    local thinking_words='Cerebrating|Levitating|Wandering|Symbioting|Cultivating'
    if tail -15 "$f" | grep -qE "$thinking_words" 2>/dev/null; then
        echo "THINKING"
        return
    fi
    if tail -5 "$f" | grep -q '>' 2>/dev/null; then
        echo "AT_PROMPT"
        return
    fi
    echo "UNKNOWN"
}

detect_loop() {
    local f="$1"
    local top=$(grep -oP 'Error:.*|FAIL:.*|TIMEOUT' "$f" 2>/dev/null \
      | sort | uniq -c | sort -rn | head -1)
    local count=$(echo "$top" | awk '{print $1}')
    if [ "${count:-0}" -ge 3 ]; then
        echo "LOOP_DETECTED"
    else
        echo "OK"
    fi
}

echo "=== Monitor Cycle $(date +%H:%M:%S) ==="
for s in "${SESSIONS[@]}"; do
    capture="/tmp/${s}-capture.txt"
    tmux capture-pane -t "$s" -p -S -150 > "$capture" 2>/dev/null || true
    state=$(detect_state "$capture")
    loop=$(detect_loop "$capture")
    printf "  %-12s state=%-12s loop=%s\n" "$s:" "$state" "$loop"
done
SCRIPT
chmod +x ~/my-manager/scripts/monitor-cycle.sh
```

### Step 4: Write a Send Message Script

```bash
cat > ~/my-manager/scripts/send-message.sh << 'SCRIPT'
#!/bin/bash
# send-message.sh -- Send directive to a managed session
set -euo pipefail

SESSION="${1:?Usage: send-message.sh <session> <message>}"
MESSAGE="${2:?Usage: send-message.sh <session> <message>}"
MANAGER_DIR="${MANAGER_DIR:-$HOME/my-manager}"
TS=$(date -Iseconds)
TS_FILE=$(date +%Y%m%d-%H%M%S)

# Channel 1: File inbox
INBOX="$MANAGER_DIR/state/directives/$SESSION/inbox"
mkdir -p "$INBOX"
cat > "$INBOX/${TS_FILE}.md" << EOF
---
from: manager
to: $SESSION
timestamp: $TS
---

$MESSAGE
EOF

# Channel 2: tmux send-keys
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux send-keys -t "$SESSION" -l "$MESSAGE"
    sleep 0.2
    tmux send-keys -t "$SESSION" Enter
fi

echo "Directive sent to $SESSION via file + tmux"
SCRIPT
chmod +x ~/my-manager/scripts/send-message.sh
```

### Step 5: Run a Monitoring Cycle

```bash
# Start two Claude Code sessions in tmux first
tmux new-session -d -s session-a
tmux new-session -d -s session-b

# Run the monitor
./scripts/monitor-cycle.sh
```

### Step 6: Try the Arbitrator

See `demos/manager/arbitrator/arbitrator.py` for the full escalation engine. Run it in dry-run mode to see how escalation works without sending real directives:

```bash
python3 arbitrator.py --once --dry-run
python3 arbitrator.py --status
python3 arbitrator.py --history
```

---

## Architecture Patterns

### Pattern 1: Passive Monitoring

The simplest mode -- run `monitor-cycle.sh` manually when you want to check on your agents:

```
You (human) --> run monitor-cycle.sh --> see state --> decide to intervene or not
```

### Pattern 2: Background Agent Loop

A dedicated Claude Code agent runs the monitoring loop automatically:

```
Manager Agent (tmux: manager) --> every 2-5 min: poll --> detect --> research --> direct
```

### Pattern 3: Full Arbitrator

The Python arbitrator runs continuously, escalating automatically:

```
arbitrator.py --interval 90 --> collects state --> escalation ladder --> directives
```

---

## Key Design Principles

1. **Research before directing** -- Never send a directive without multi-LLM verification. The Manager's research engine is its primary value-add.

2. **Progressive escalation** -- Watch first, then nudge, then intervene. Jumping to DEPLOY on the first sign of trouble causes more problems than it solves.

3. **Graceful degradation** -- If the Manager goes down, agents continue working independently. The lock file protocol still works as a manual coordination mechanism.

4. **Triple-channel reliability** -- Any single communication channel can fail. Using three channels (hook file, inbox file, tmux injection) ensures the message gets through.

5. **Cooldown after intervention** -- After deploying a fix candidate or escalating to a human, wait before checking again. Give the intervention time to take effect.

---

## Summary

| Component | Role | Implementation |
|-----------|------|----------------|
| Manager | Supervisor session | Claude Code in tmux, runs monitor scripts |
| Arbitrator | Escalation engine | Python, 6-level ladder, state machine |
| Research Engine | Multi-LLM verification | Parallel queries to GPT-5.4, Gemini, Bedrock |
| Lock Manager | Resource coordination | JSON files, 30-min max hold, queue-based |
| Communication Bus | Agent messaging | File inbox + tmux send-keys + shared memory |
| Anti-Regression | Waste detection | Pattern matching on tmux capture |

**Next step:** Try the demo scripts in `demos/manager/` to see the system in action.

---

*Estimated time: 15 minutes*
