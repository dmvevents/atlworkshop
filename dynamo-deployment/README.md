# Deploying NVIDIA Dynamo Inference on Kubernetes

This directory contains everything needed to deploy an open-source coding model
on NVIDIA Dynamo for GPU-accelerated inference on Amazon EKS.

**Upstream:** [NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) | [NGC Container](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/ai-dynamo/containers/vllm-runtime)

## What's Here

```
dynamo-deployment/
├── README.md                              # This file
├── manifests/
│   ├── 01-namespace.yaml                  # Workshop namespace
│   ├── 02-hf-token-secret.yaml            # HuggingFace token (for gated models)
│   ├── 03-dynamo-coding-model.yaml        # Qwen2.5-Coder-7B (1 GPU)
│   └── 04-dynamo-large-model.yaml         # 32B model with TP=2 (2 GPUs)
├── scripts/
│   ├── deploy.sh                          # One-command deployment
│   ├── test.sh                            # Inference test suite
│   └── teardown.sh                        # Clean removal
└── docs/
    ├── deploy-dynamo-skill.md             # Agent skill for Dynamo deployment
    └── self-hosted-inference-endpoint.md   # Using your endpoint with coding agents
```

## Quick Start

```bash
# Deploy (one command)
./scripts/deploy.sh

# Test
./scripts/test.sh

# Teardown
./scripts/teardown.sh
```

## How We Built This

### 1. Infrastructure (already running)

The Dynamo platform was installed via Helm:

```bash
helm install dynamo-platform \
  oci://nvcr.io/nvidia/ai-dynamo/dynamo-platform \
  --version 0.7.0
```

This installs three components:
- **Dynamo Operator** -- watches for DynamoGraphDeployment CRDs and creates pods
- **etcd** -- service discovery (workers register, frontend discovers them)
- **NATS** -- event messaging between components

### 2. Container Image

We use the official NGC container:

```
nvcr.io/nvidia/ai-dynamo/vllm-runtime:0.9.0
```

This container includes:
- NVIDIA Dynamo runtime (Rust + Python)
- vLLM inference engine (v0.14.1)
- CUDA 12.8 + cuDNN
- Flash Attention 2
- Model downloader (HuggingFace Hub)

No custom Docker build needed -- the NGC container handles everything.

### 3. Deployment YAML (DynamoGraphDeployment)

The key resource is a `DynamoGraphDeployment` (DGD) -- a custom Kubernetes resource
that tells the Dynamo operator what to deploy:

```yaml
apiVersion: nvidia.com/v1alpha1
kind: DynamoGraphDeployment
metadata:
  name: qwen-coder
  namespace: workshop
spec:
  services:
    Frontend:
      componentType: frontend
      replicas: 1
    QwenCoderWorker:
      componentType: worker
      replicas: 1
      resources:
        requests: { gpu: "1", memory: "40Gi" }
        limits:   { gpu: "1", memory: "80Gi" }
```

The operator creates:
- A Deployment + Service for the Frontend (HTTP API, port 8000)
- A Deployment for each Worker (GPU inference)
- Auto-wires etcd discovery and NATS messaging

### 4. What Happens at Startup

1. **Worker pod starts** -> downloads model from HuggingFace (~14GB for 7B)
2. **vLLM initializes** -> loads model into GPU memory, compiles CUDA graphs
3. **Worker registers** -> announces itself to etcd with its endpoint
4. **Frontend discovers** -> finds the worker via etcd, routes requests
5. **Ready** -> `/v1/models` returns the model, `/health` returns healthy

### 5. API

The frontend exposes an OpenAI-compatible API:

```bash
# List models
GET /v1/models

# Chat completions
POST /v1/chat/completions
{
  "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
  "messages": [{"role": "user", "content": "Write a hello world"}],
  "max_tokens": 100,
  "stream": true
}

# Health check
GET /health
```

## Performance (Measured)

Benchmarked with NVIDIA AIPerf on A100 40GB:

| Metric | Concurrency=1 | Concurrency=4 |
|--------|---------------|---------------|
| Time to First Token | 46.81 ms | 52.19 ms |
| Inter Token Latency | 12.36 ms | 12.97 ms |
| Output Throughput | 77 tok/s | 282 tok/s |
| Request Throughput | 1.25 req/s | 4.59 req/s |

## Connecting Coding Agents to Your Endpoint

See [docs/self-hosted-inference-endpoint.md](docs/self-hosted-inference-endpoint.md)
for how to point OpenCode, Claude Code Router, or custom agents at this endpoint.
