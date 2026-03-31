# Mastering Agentic Coding & GPUs

**A hands-on, 2h 10m workshop focused on building, deploying, and scaling production-ready agentic systems**

---

**Instructor:** Anton Alexander, Sr. GenAI Specialist for NVIDIA -- AWS

Senior Specialist in Generative AI at AWS, focusing on scaling large training and inference workloads with AWS HyperPod. Veteran CUDA programmer and Kubernetes expert. Works with MENA Region and Government sector clients. Patent pending for ML edge computing systems. Brazilian jiu-jitsu and collegiate boxing champion, enjoys flying planes.

---

## Workshop Overview

This workshop bridges two critical disciplines: **agentic AI coding systems** and the **GPU compute infrastructure** that powers them. You will build real systems, deploy them on real hardware, and leave with working code you can take back to your team.

```
                        WORKSHOP LEARNING PATH
  ============================================================

  Part 1: Agentic Systems                Part 2: GPU Compute
  (70 min)                               (50 min)
  +--------------------------+           +--------------------------+
  | [1] Agentic Coding       |           | [5] GPU Foundations      |
  |     Fundamentals         |           |     for Developers       |
  |     (15 min)             |           |     (10 min)             |
  +-----------+--------------+           +-----------+--------------+
              |                                      |
              v                                      v
  +--------------------------+           +--------------------------+
  | [2] MCP Servers &        |           | [6] Deploying NVIDIA     |
  |     Multi-LLM            |           |     Dynamo on EKS        |
  |     Orchestration        |           |     (20 min)             |
  |     (15 min)             |           |                          |
  +-----------+--------------+           +-----------+--------------+
              |                                      |
              v                                      v
  +--------------------------+           +--------------------------+
  | [3] Deploying Coding     |           | [7] HPC Kernel           |
  |     Agents               |           |     Optimization with    |
  |     (10 min)             |           |     AI Agents            |
  +-----------+--------------+           |     (15 min)             |
              |                          +-----------+--------------+
              v                                      |
  +--------------------------+                       v
  | [4] Real-World           |           +--------------------------+
  |     Integration:         |           | [8] Scaling: Experiment  |
  |     OpenClaw + WhatsApp  |           |     to Production        |
  |     (15 min)             |           |     (5 min)              |
  +-----------+--------------+           +--------------------------+
              |                                      |
              v                                      |
  +--------------------------+                       |
  | [9] Agent Supervision:   |                       |
  |     Manager & Arbitrator |                       |
  |     (15 min)             |                       |
  +-----------+--------------+                       |
              |                                      |
              +------------------+-------------------+
                                 |
                                 v
                    +---------------------------+
                    |   Production-Ready        |
                    |   Agentic GPU Systems     |
                    +---------------------------+
```

---

## Part 1 -- Building Effective Agentic Coding Systems (70 min)

| # | Module | Time | Description |
|---|--------|------|-------------|
| 1 | [Agentic Coding Fundamentals](modules/01-agentic-coding-fundamentals/) | 15 min | Claude Code architecture, CLAUDE.md as system prompt, hooks, skills, and structured autonomous workflows |
| 2 | [MCP Servers & Multi-LLM Orchestration](modules/02-mcp-servers-multi-llm/) | 15 min | Building MCP servers, connecting 14 tools, multi-model consensus with GPT-5.4/Gemini/Claude |
| 3 | [Deploying Coding Agents](modules/03-deploying-coding-agents/) | 10 min | Deploy Claude Code, OpenCode, and oh-my-claudecode. Parallel agents, worktree isolation, agent teams |
| 4 | [Real-World Integration: OpenClaw + WhatsApp](modules/04-openclaw-whatsapp-integration/) | 15 min | OpenClaw gateway to WhatsApp/Slack/Discord, NemoClaw self-referential agent, Amazon Connect AI deployment |
| 9 | [Agent Supervision: Manager & Arbitrator](modules/09-agent-supervision-manager/) | 15 min | Supervisor system for autonomous agents: escalation ladder, loop detection, multi-LLM research, cluster lock management |

## Part 2 -- Compute Foundations for Agentic Systems (50 min)

| # | Module | Time | Description |
|---|--------|------|-------------|
| 5 | [GPU Foundations for Developers](modules/05-gpu-foundations/) | 10 min | How GPUs work, CUDA mental model, practical learning paths without getting lost in theory |
| 6 | [Deploying NVIDIA Dynamo on EKS](modules/06-dynamo-inference-eks/) | 20 min | Disaggregated inference: prefill/decode separation, NIXL KV cache transfer, EFA RDMA on P5 instances |
| 7 | [HPC Kernel Optimization with AI Agents](modules/07-hpc-kernel-optimization/) | 15 min | Live demo: using the Markdown Skills system and MCP servers to optimize GPU kernels with AI agents |
| 8 | [Scaling: Experiment to Production](modules/08-scaling-production/) | 5 min | Matching agentic workloads to compute, cost optimization, production patterns |

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/antonalexander/atlworkshop.git
cd atlworkshop

# Start with Module 1
cd modules/01-agentic-coding-fundamentals/
```

Each module directory contains its own README with step-by-step instructions, code samples, and exercises.

---

## Prerequisites

### Knowledge

- Basic command-line proficiency (bash, git)
- Familiarity with at least one programming language (Python preferred)
- General understanding of cloud services (AWS account helpful but not required for Part 1)

### Software

| Tool | Version | Required For |
|------|---------|--------------|
| Git | 2.30+ | All modules |
| Python | 3.10+ | Modules 1-4, 7 |
| Node.js | 18+ | MCP server development (Module 2) |
| Docker | 24+ | Modules 3, 6 |
| kubectl | 1.28+ | Modules 6, 8 |
| AWS CLI v2 | 2.15+ | Part 2 (GPU modules) |
| Claude Code | 2.1+ | Modules 1-3, 7 |
| helm | 3.14+ | Module 6 |

### Hardware (for Part 2 hands-on)

| Resource | Specification | Purpose |
|----------|---------------|---------|
| EKS Cluster | 1.29+ | Dynamo deployment target |
| P5.48xlarge (x2) | 8x H100 80GB each | Disaggregated inference, EFA RDMA |
| P4d.24xlarge (x2) | 8x A100 40GB each | Alternative for GPU foundations |
| EFA NICs | 32 per P5 node | RDMA networking for NIXL |
| gp3 EBS | 500GB+ per node | Container images and model weights |

> **Note:** Part 1 (Modules 1-4) requires only a laptop with internet access. GPU hardware is only needed for the Part 2 hands-on exercises.

---

## Repository Structure

```
atlworkshop/
+-- README.md                          # This file
+-- .claude/
|   +-- CLAUDE.md                      # Autonomous deployment instructions
+-- modules/
|   +-- 01-agentic-coding-fundamentals/
|   +-- 02-mcp-servers-multi-llm/
|   +-- 03-deploying-coding-agents/
|   +-- 04-openclaw-whatsapp-integration/
|   +-- 05-gpu-foundations/
|   +-- 06-dynamo-inference-eks/
|   +-- 07-hpc-kernel-optimization/
|   +-- 08-scaling-production/
+-- demos/
|   +-- scripts/                       # Runnable demo scripts
|   +-- recordings/                    # Terminal recordings (asciinema)
|   +-- manifests/                     # K8s manifests for live demos
+-- infrastructure/
|   +-- docker/                        # Dockerfiles for workshop services
|   +-- kubernetes/                    # K8s deployment manifests
|   +-- terraform/                     # Infrastructure as code
+-- reference/
|   +-- agent-configs/                 # Example CLAUDE.md and agent configs
|   +-- mcp-configs/                   # MCP server configurations
|   +-- skills-examples/              # Markdown Skills system examples
+-- assets/
    +-- diagrams/                      # Architecture diagrams
    +-- images/                        # Screenshots and photos
    +-- slides/                        # Presentation materials
```

---

## Related Repositories

| Repository | Description |
|------------|-------------|
| [everything-claude-code](https://github.com/anthropics/courses) | Claude Code architecture reference |
| [oh-my-claudecode](https://github.com/anthropics/claude-code) | Multi-agent orchestration framework |
| [NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) | Disaggregated inference framework |
| [OpenClaw](https://github.com/openclaw) | Multi-channel AI gateway |
| [HPC Agent Stack](https://github.com/antonalexander/hpc-agent-stack) | MCP servers and skills for GPU/HPC |

---

## Workshop Flow

| Time | Activity | Module |
|------|----------|--------|
| 0:00 - 0:15 | Agentic Coding Fundamentals | 1 |
| 0:15 - 0:30 | MCP Servers & Multi-LLM Orchestration | 2 |
| 0:30 - 0:40 | Deploying Coding Agents | 3 |
| 0:40 - 0:55 | OpenClaw + WhatsApp Integration | 4 |
| 0:55 - 1:10 | Agent Supervision: Manager & Arbitrator | 9 |
| 1:10 - 1:15 | -- Break -- | |
| 1:15 - 1:25 | GPU Foundations for Developers | 5 |
| 1:25 - 1:45 | Deploying NVIDIA Dynamo on EKS | 6 |
| 1:45 - 2:00 | HPC Kernel Optimization with AI Agents | 7 |
| 2:00 - 2:05 | Scaling: Experiment to Production | 8 |
| 2:05 - 2:10 | Q&A and Wrap-up | |

---

## Key Takeaways

By the end of this workshop, participants will be able to:

1. **Configure and deploy autonomous coding agents** using CLAUDE.md, hooks, skills, and MCP servers
2. **Build multi-LLM orchestration pipelines** that combine GPT-5.4, Gemini 3 Pro, and Claude for consensus-driven development
3. **Deploy real-time AI integrations** through OpenClaw to WhatsApp, Slack, Discord, and Amazon Connect
4. **Understand GPU architecture** at a practical level sufficient to make informed compute decisions
5. **Deploy NVIDIA Dynamo** for disaggregated inference with prefill/decode separation and EFA RDMA
6. **Use AI agents to optimize GPU kernels** through the Markdown Skills system and MCP tool ecosystem
7. **Design production scaling strategies** that match agentic workloads to appropriate compute tiers

---

## License

This workshop material is provided for educational purposes. See individual module directories for specific licensing terms.

---

*Last updated: 2026-03-31*
