# NemoClaw: Self-Referential AI Agent on NVIDIA Dynamo

NemoClaw is an AI agent that calls a locally-served LLM via NVIDIA Dynamo
to narrate and orchestrate a demo loop. The agent is powered by the same
model it demos -- a self-referential inference loop.

## Current Configuration

| Setting | Value |
|---------|-------|
| Model | Qwen/Qwen2.5-Coder-7B-Instruct |
| Endpoint | qwen-coder-frontend.workshop.svc.cluster.local:8000 |
| Namespace | workshop |
| Backend | NVIDIA Dynamo (OpenAI-compatible API) |
| Fallback | AWS Bedrock (optional) |

## Quick Start

```bash
# Option A: Via port-forward (from bastion)
kubectl port-forward -n workshop svc/qwen-coder-frontend 8084:8000 &
DYNAMO_ENDPOINT=http://localhost:8084 python3 scripts/nemoclaw_dynamo_agent.py

# Option B: Single iteration test
DYNAMO_ENDPOINT=http://localhost:8084 \
NEMOCLAW_SINGLE=1 \
python3 scripts/nemoclaw_dynamo_agent.py

# Option C: Run the test suite
bash scripts/test_nemoclaw.sh
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| DYNAMO_ENDPOINT | (auto-discover) | Dynamo frontend URL |
| DYNAMO_MODEL | Qwen/Qwen2.5-Coder-7B-Instruct | Model name in Dynamo |
| NEMOCLAW_NAMESPACE | workshop | Kubernetes namespace |
| NEMOCLAW_BACKEND | dynamo | Primary: dynamo, bedrock, or auto |
| NEMOCLAW_FALLBACK | none | Fallback: bedrock or none |
| NEMOCLAW_SINGLE | (unset) | Set to 1 for single iteration |
| KUBECTL | kubectl | kubectl command |

## What the Agent Does

Each iteration runs a 5-step demo loop:

1. **Model Discovery** -- queries /v1/models to find available models
2. **Live Inference** -- calls itself for a coding question (self-referential)
3. **Latency Benchmark** -- measures 3 inference calls
4. **Code Generation** -- demonstrates Qwen-Coder's coding ability
5. **Self-Reflection** -- the model reflects on its own demo

## Architecture

```
  NemoClaw Agent (Python)
       |
       | HTTP POST /v1/chat/completions
       v
  Dynamo Frontend Service (port 8000)
       |
       v
  Dynamo Worker (Qwen2.5-Coder-7B-Instruct on GPU)
```

Auto-discovery order:
1. K8s service DNS (qwen-coder-frontend.workshop.svc.cluster.local)
2. kubectl get svc (ClusterIP)
3. kubectl get pods (pod IP)
4. localhost ports (8084, 8000, 8001)

## Files

- `scripts/nemoclaw_dynamo_agent.py` -- Main agent (zero deps beyond stdlib)
- `scripts/test_nemoclaw.sh` -- Smoke test (health check, inference, latency)
