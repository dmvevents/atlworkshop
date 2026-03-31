---
name: deploy-dynamo-inference
description: Use when deploying an LLM on NVIDIA Dynamo for inference on Kubernetes, when setting up a coding model endpoint, or when the user asks to serve a model on EKS with GPUs
---

# Deploy NVIDIA Dynamo Inference on Kubernetes

## When to Use

- User asks to deploy a model for inference on Kubernetes/EKS
- User wants to set up a coding model endpoint
- User needs an OpenAI-compatible API backed by a GPU model
- User wants disaggregated inference (prefill/decode separation)

## Prerequisites Checklist

Before deploying, verify:

1. **Dynamo operator running:**
   ```bash
   kubectl get pods -n default | grep dynamo.*controller
   # Must show: Running
   ```

2. **etcd and NATS running:**
   ```bash
   kubectl get pods -n default | grep -E "etcd|nats"
   # Both must show: Running
   ```

3. **GPU nodes available:**
   ```bash
   kubectl get nodes -o json | jq '.items[] | select(.status.allocatable["nvidia.com/gpu"] != "0") | .metadata.name'
   ```

4. **If operator not installed:**
   ```bash
   helm install dynamo-platform \
     oci://nvcr.io/nvidia/ai-dynamo/dynamo-platform \
     --version 0.7.0
   ```

## Deployment Steps

### Step 1: Create Namespace

```bash
kubectl create namespace workshop --dry-run=client -o yaml | kubectl apply -f -
```

### Step 2: Choose Model and Create DGD

**Option A: Small model (7B, 1 GPU)**
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
      extraPodSpec:
        nodeSelector:
          node.kubernetes.io/instance-type: <GPU_INSTANCE_TYPE>
        mainContainer:
          image: nvcr.io/nvidia/ai-dynamo/vllm-runtime:0.9.0
    Worker:
      componentType: worker
      replicas: 1
      resources:
        requests:
          gpu: "1"
          memory: "40Gi"
        limits:
          gpu: "1"
          memory: "80Gi"
      extraPodSpec:
        nodeSelector:
          node.kubernetes.io/instance-type: <GPU_INSTANCE_TYPE>
        mainContainer:
          image: nvcr.io/nvidia/ai-dynamo/vllm-runtime:0.9.0
          workingDir: /workspace/examples/backends/vllm
          command: ["python3", "-m", "dynamo.vllm"]
          args:
            - --model
            - Qwen/Qwen2.5-Coder-7B-Instruct
            - --trust-remote-code
            - --max-model-len
            - "8192"
            - --gpu-memory-utilization
            - "0.85"
            - --dtype
            - bfloat16
```

**Option B: Large model (32B, 2 GPUs, tensor parallel)**
```yaml
# Same structure but with:
#   resources.requests.gpu: "2"
#   resources.limits.gpu: "2"
#   args: --tensor-parallel-size 2
#   envFromSecret: hf-token-secret  (if gated model)
```

### Step 3: Apply and Wait

```bash
kubectl apply -f dynamo-coding-model.yaml
kubectl get pods -n workshop -w  # Wait for 1/1 Running on both pods
```

### Step 4: Verify

```bash
# Check model is loaded
kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000 &
curl http://localhost:8000/v1/models | jq .

# Test inference
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Write a hello world in Rust"}],
    "max_tokens": 100
  }'
```

## Model Selection Guide

| Model | Size | GPUs | SWE-bench | Best For |
|-------|------|------|-----------|----------|
| Qwen/Qwen2.5-Coder-7B-Instruct | 7B | 1 | — | Fast demos, quick iteration |
| Qwen/Qwen2.5-Coder-32B-Instruct | 32B | 2 (TP=2) | Base model | Production coding |
| mistralai/Devstral-Small-2505 | 24B | 2 (TP=2) | 46.6% | SWE tasks |
| agentica-org/DeepSWE-Preview | 32.8B | 2 (TP=2) | 59.0% | Best open SWE |

## GPU Memory Requirements

| Model Size | FP16/BF16 | FP8 | INT4 |
|-----------|-----------|-----|------|
| 7B | ~14 GB | ~7 GB | ~4 GB |
| 24B | ~48 GB | ~24 GB | ~12 GB |
| 32B | ~64 GB | ~32 GB | ~16 GB |
| 70B | ~140 GB | ~70 GB | ~35 GB |

## Dynamo Environment Variables (auto-set by operator)

| Variable | Purpose | Default |
|----------|---------|---------|
| `DYNAMO_PORT` | Frontend HTTP port | 8000 |
| `DYN_NAMESPACE` | Dynamo service namespace | dynamo-{dgd-name} |
| `ETCD_ENDPOINTS` | etcd address for service discovery | dynamo-platform-etcd:2379 |
| `NATS_SERVER` | NATS address for messaging | nats://dynamo-platform-nats:4222 |

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Worker pod OOMKilled | Memory limit too low | Increase to 80Gi for 7B, 160Gi for 32B |
| Worker stuck downloading | HF rate limit (429) | Add `hf-token-secret` with your token |
| Frontend returns 503 | Worker not ready yet | Wait for worker to finish loading model |
| No GPU resources | Device plugin not running | `kubectl get ds -A \| grep nvidia` |
| DGD not created | Operator not installed | Install dynamo-platform Helm chart |

## Cleanup

```bash
kubectl delete dynamographdeployment --all -n workshop
```
