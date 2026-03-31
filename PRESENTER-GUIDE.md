# Presenter Guide

## Workshop: Mastering Agentic Coding & GPUs

**Duration:** 2 hours
**Format:** Live coding + slides + demos
**Audience:** Software engineers, ML engineers, DevOps/Platform engineers

## Timing Breakdown

```
 0:00 -  0:05  Welcome and Overview                     [5 min]
 0:05 -  0:20  Module 1: Agentic Coding Fundamentals   [15 min]
 0:20 -  0:35  Module 2: MCP Servers & Multi-LLM       [15 min]
 0:35 -  0:45  Module 3: Deploying Coding Agents       [10 min]
 0:45 -  1:00  Module 4: OpenClaw + WhatsApp            [15 min]
 1:00 -  1:05  Break                                    [5 min]
 1:05 -  1:15  Module 5: GPU Foundations                [10 min]
 1:15 -  1:35  Module 6: Dynamo Inference on EKS       [20 min]
 1:35 -  1:50  Module 7: HPC Kernel Optimization       [15 min]
 1:50 -  1:55  Module 8: Scaling to Production          [5 min]
 1:55 -  2:00  Q&A                                      [5 min]
```

## Pre-Workshop Checklist

### 1 Day Before
- [ ] Verify cluster is running: `kubectl get nodes`
- [ ] GPU nodes have `nvidia.com/gpu` in allocatable
- [ ] EFA devices visible: `kubectl get nodes -o json | jq '.items[].status.allocatable["vpc.amazonaws.com/efa"]'`
- [ ] Dynamo operator installed
- [ ] Run `demos/scripts/00-preflight.sh`
- [ ] Pre-pull container images on nodes
- [ ] Test all demo scripts end-to-end

### 30 Minutes Before
- [ ] Open terminal with large font (20pt+)
- [ ] Set up tmux with named windows for each demo
- [ ] Pre-open browser tabs for any web UIs
- [ ] Disable notifications on presenter machine
- [ ] Have backup slides/screenshots in case of cluster issues

### Fallback Plan
If cluster is unavailable:
- Screenshots and recordings in `demos/recordings/`
- Pre-recorded terminal sessions (asciinema)
- Switch to architecture discussion using diagrams

## Demo Tips

### Terminal Setup
```bash
# Large font, dark background, high contrast
export PS1='\[\033[1;32m\]workshop\[\033[0m\]:\[\033[1;34m\]\W\[\033[0m\]$ '

# tmux windows
tmux new-session -s workshop
tmux rename-window 'demo'
tmux new-window -n 'agents'
tmux new-window -n 'k8s'
tmux new-window -n 'logs'
```

### Pacing
- Pause after each command for audience to read
- Explain BEFORE running, not after
- Keep `kubectl get pods -w` running in a side pane
- Use `watch` for status updates during deployments

### Audience Engagement
- Ask "Who has used Claude Code?" at start
- Ask "Who has deployed on Kubernetes?" at GPU section
- Encourage questions between modules
- Share the repo URL early so people can follow along

## Key Messages

1. **Agentic coding is a methodology, not just a tool** - CLAUDE.md, skills, hooks create a system
2. **Multi-LLM consensus reduces hallucination** - Never trust a single model for HPC code
3. **GPUs aren't magic** - They're massively parallel processors; understanding the mental model unlocks them
4. **Disaggregated inference is the future** - Dynamo separates prefill/decode for independent scaling
5. **AI agents can optimize GPU kernels** - Skills + MCP servers + multi-model = automated HPC expertise
