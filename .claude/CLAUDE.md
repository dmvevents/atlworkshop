# Mastering Agentic Coding & GPUs - Workshop Repository

## Project Overview

This is a 2-hour hands-on workshop: "Mastering Agentic Coding & GPUs" by Anton Alexander.
It covers building, deploying, and scaling production-ready agentic systems with GPU acceleration.

## Repository Structure

```
atlworkshop/
├── modules/                    # 9 workshop modules (Part 1: 1-4, Part 1.5: 9, Part 2: 5-8)
│   ├── 01-agentic-coding-fundamentals/
│   ├── 02-mcp-servers-multi-llm/
│   ├── 03-deploying-coding-agents/
│   ├── 04-openclaw-whatsapp-integration/
│   ├── 05-gpu-foundations/
│   ├── 06-dynamo-inference-eks/
│   ├── 07-hpc-kernel-optimization/
│   ├── 08-scaling-production/
│   └── 09-agent-supervision-manager/
├── demos/
│   ├── scripts/                # Executable demo scripts (00-preflight through 99-teardown)
│   ├── manifests/              # K8s deployment manifests
│   ├── nemoclaw/               # NemoClaw self-referential agent
│   ├── manager/                # Manager + Arbitrator supervision system
│   └── recordings/             # Pre-recorded demos and benchmark results
├── reference/
│   ├── skills-examples/        # Example skill files for attendees
│   ├── mcp-configs/            # MCP server configuration examples
│   └── agent-configs/          # Claude Code and agent team configs
├── infrastructure/
│   ├── kubernetes/             # K8s infrastructure (namespace, test pods)
│   ├── docker/                 # Dockerfiles for workshop containers
│   └── terraform/              # (Optional) cluster provisioning
└── assets/                     # Images, diagrams, slides
```

## Source Material Locations

These directories contain the source material that this workshop draws from.
Use them for reference, deeper examples, and deployment configurations:

| Source | Location | Content |
|--------|----------|---------|
| HPC Agent Stack | /home/ubuntu/deepep-intergration/hpc-agent-stack/ | MCP servers, 220+ skills, multi-model scripts |
| Agent Toolkit | /home/ubuntu/agent-toolkit/ | Portable multi-LLM dispatch, session manager |
| AWS GPU Workshop | /home/ubuntu/aws-gpu-workshop/ | Dynamo, NemoClaw, NeMo Agent Toolkit modules |
| Dynamo Vault | /home/ubuntu/dynamo-vault/ | TRT-LLM + Dynamo K8s deployment configs |
| NVIDIA Dynamo | /home/ubuntu/dynamo-v0.9.0/ | Dynamo v0.9.0 source code |
| OpenClaw | /home/ubuntu/openclaw-personal/ | OpenClaw + WhatsApp/Slack/Discord integration |
| Connect Demo | /home/ubuntu/connect/ | Amazon Connect AI deployment (90-second demo) |
| Everything Claude Code | /home/ubuntu/everything-claude-code/ | 50K-star Claude Code reference |
| oh-my-claudecode | /home/ubuntu/oh-my-claudecode/ | Multi-agent orchestration for Claude Code |
| Superpowers | /home/ubuntu/superpowers/ | Skills-based development workflows |
| EFA/NCCL Docs | /home/ubuntu/efa-nccl-doc/ | EFA networking documentation |
| Manager | /home/ubuntu/manager/ | Multi-session supervisor with lock management |
| Arbitrator | /home/ubuntu/deepep-intergration/hpc-agent-stack/supervisor/ | Escalation engine, evolution recovery |

## Autonomous Deployment Instructions

When told to "deploy the workshop" or "test end-to-end", follow this sequence:

### Phase 1: Cluster Preparation
1. Check cluster lock: `cat ~/.claude/cluster-lock.json`
2. Verify cluster access: `kubectl get nodes`
3. Confirm GPU nodes: `kubectl get nodes -o json | jq '.items[].status.allocatable["nvidia.com/gpu"]'`
4. Confirm EFA devices: `kubectl get nodes -o json | jq '.items[].status.allocatable["vpc.amazonaws.com/efa"]'`
5. Create namespace: `kubectl apply -f infrastructure/kubernetes/namespace.yaml`
6. Run preflight: `bash demos/scripts/00-preflight.sh`

### Phase 2: Deploy Dynamo Inference
1. Install Dynamo operator (Helm chart from dynamo-v0.9.0)
2. Deploy etcd and NATS for service discovery
3. Apply `demos/manifests/dynamo-workshop.yaml` (after replacing placeholders)
4. Verify pods are Running: `kubectl get pods -n workshop -l app=dynamo-frontend`
5. Test inference: `curl -X POST http://<frontend-svc>:8000/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"meta-llama/Llama-3.1-8B-Instruct","messages":[{"role":"user","content":"Hello"}]}'`

### Phase 3: Deploy OpenClaw Gateway
1. Apply `demos/manifests/openclaw-workshop.yaml` (after replacing placeholders)
2. Verify gateway pod: `kubectl get pods -n workshop -l app=openclaw-gateway`
3. Test health: `kubectl exec -it <pod> -n workshop -- curl localhost:18789/health`

### Phase 4: Verify All Demos
1. Run each demo script in sequence (01 through 04)
2. Verify all demos complete without errors
3. Take screenshots for `demos/recordings/`

### Phase 5: Teardown
1. Run `bash demos/scripts/99-teardown.sh`
2. Release cluster lock

## Security Rules - STRICTLY ENFORCED

- **NO customer data** - Never include customer names, account IDs, or proprietary information
- **NO Amazon internal info** - No internal wikis, tickets, roadmaps, or team details
- **NO API keys/tokens** - Use `<PLACEHOLDER>` markers. Never commit real credentials
- **NO public internet exposure** - All services use ClusterIP. Access via kubectl port-forward
- **NO sensitive file commits** - .env, .secrets/, credentials.json are in .gitignore

## Demo Execution Notes

- Use large terminal font (20pt+) for audience visibility
- Run `kubectl get pods -w` in a side pane during deployments
- Explain BEFORE running commands, not after
- Have fallback screenshots in demos/recordings/ if cluster has issues
- Module 7 (HPC Optimization) is a narrated live demo - run 04-demo-hpc-optimization.sh

## Testing Each Module

| Module | Test Command | Expected Result |
|--------|-------------|-----------------|
| 1 | `claude --version` | Claude Code version output |
| 2 | `bash demos/scripts/01-demo-agentic-coding.sh` | Completes without errors |
| 3 | `claude -p "What is 2+2?"` | Returns "4" |
| 5 | `kubectl apply -f infrastructure/kubernetes/gpu-test-pod.yaml` | Pod completes with nvidia-smi output |
| 6 | `kubectl get pods -n workshop -l app=dynamo-frontend` | 1/1 Running |
| 7 | `bash demos/scripts/04-demo-hpc-optimization.sh` | Interactive demo runs |

## Content Guidelines

- All content is public-safe: no NDA material, no internal references
- Attribute open-source projects properly
- Workshop is for external audiences (customers, partners, conference attendees)
- Tone: professional, technical, hands-on
