# Qwen2.5-Coder-7B-Instruct on NVIDIA Dynamo - Deployment Summary

## Overview

Successfully deployed **Qwen/Qwen2.5-Coder-7B-Instruct** (7B parameter open-source coding model) on AWS EKS using NVIDIA Dynamo with vLLM backend.

## Cluster Configuration

- **Nodes**: 2x P4d.24xlarge (8x A100 40GB each, 4 EFA each)
- **Namespace**: `workshop`
- **Dynamo Version**: 0.9.0 (platform installed in `default` namespace)
- **Backend**: vLLM runtime with NVIDIA Dynamo orchestration

## Deployment Details

### Components

1. **Frontend Pod**: HTTP API server (port 8000)
   - Service: `qwen-coder-frontend.workshop.svc.cluster.local:8000`
   - Status: Running (1/1 READY)

2. **Worker Pod**: vLLM inference engine
   - GPU allocation: 1x A100 (40GB)
   - Memory: 40Gi request, 80Gi limit
   - Model loaded: 14.25 GiB GPU memory
   - Status: Running (1/1 READY)

### Model Configuration

- **Model**: Qwen/Qwen2.5-Coder-7B-Instruct
- **Max sequence length**: 8192 tokens
- **Data type**: bfloat16
- **GPU memory utilization**: 85%
- **Features**:
  - Flash Attention enabled
  - Chunked prefill (max 2048 tokens)
  - Prefix caching enabled
  - Asynchronous scheduling

## API Endpoints

### Chat Completions (OpenAI-compatible)

**Endpoint**: `http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1/chat/completions`

**Example Request**:
```bash
curl -X POST "http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [
      {
        "role": "user",
        "content": "Write a Python function to compute the Fibonacci sequence using dynamic programming."
      }
    ],
    "max_tokens": 500,
    "temperature": 0.7
  }'
```

**Example Response**:
```json
{
  "id": "chatcmpl-...",
  "choices": [{
    "index": 0,
    "message": {
      "content": "Certainly! Here is a simple \"Hello, World!\" function in Python:\n\n```python\ndef hello_world():\n    print(\"Hello, World!\")\n\nhello_world()\n```",
      "role": "assistant"
    },
    "finish_reason": "stop"
  }],
  "created": 1774965674,
  "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
  "object": "chat.completion",
  "usage": {
    "prompt_tokens": 37,
    "completion_tokens": 95,
    "total_tokens": 132
  }
}
```

## Testing

### From Within Cluster

```bash
kubectl run test-client --rm -i --restart=Never --image=curlimages/curl:latest -n workshop -- sh -c '
curl -s -X POST "http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"Qwen/Qwen2.5-Coder-7B-Instruct\",
    \"messages\": [{\"role\": \"user\", \"content\": \"Write a hello world function in Python.\"}],
    \"max_tokens\": 100,
    \"temperature\": 0.7
  }"
'
```

### From Local Machine (via kubectl port-forward)

```bash
# Terminal 1: Port forward
kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000

# Terminal 2: Test
curl -X POST "http://localhost:8000/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Write a binary search in Python."}],
    "max_tokens": 300
  }'
```

## Files Created

1. **Deployment Manifest**: `/home/ubuntu/atlworkshop/qwen-coder-dynamo.yaml`
   - DynamoGraphDeployment CRD
   - Frontend and worker configuration

2. **Test Script**: `/home/ubuntu/atlworkshop/test-qwen-coder.sh`
   - Automated API testing

3. **This Document**: `/home/ubuntu/atlworkshop/QWEN-CODER-DEPLOYMENT.md`

## Management Commands

### Check Status
```bash
# Pods
kubectl get pods -n workshop

# DynamoGraphDeployment
kubectl get dynamographdeployments -n workshop

# Services
kubectl get svc -n workshop

# Logs
kubectl logs -n workshop -l nvidia.com/dynamo-component=QwenCoderWorker
kubectl logs -n workshop -l nvidia.com/dynamo-component=Frontend
```

### Scale Deployment
```bash
# Edit the deployment
kubectl edit dynamographdeployment qwen-coder -n workshop

# Change replicas for worker (add more GPUs)
# spec.services.QwenCoderWorker.replicas: 2
```

### Delete Deployment
```bash
kubectl delete dynamographdeployment qwen-coder -n workshop
```

## Performance Characteristics

- **Model load time**: ~23 seconds
- **GPU memory**: 14.25 GiB
- **KV cache blocks**: 20,924 GPU blocks
- **Max batch size**: 256 sequences
- **Max batched tokens**: 2048

## Why Qwen2.5-Coder-7B?

1. **Size**: 7B parameters fit easily in A100 40GB (14GB used)
2. **Performance**: Optimized for code generation tasks
3. **Speed**: Fast inference with Flash Attention
4. **License**: Apache 2.0 (fully open source)
5. **Quality**: State-of-the-art for its size on coding benchmarks

## Alternative Models (also work on A100 40GB)

If you want to try different models, edit the YAML:

```yaml
# In qwen-coder-dynamo.yaml, change:
args:
  - --model
  - Qwen/Qwen2.5-Coder-7B-Instruct  # ← Change this

# Other options:
# - deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct (16B)
# - codellama/CodeLlama-7b-Instruct-hf
# - bigcode/starcoder2-7b
```

Then apply:
```bash
kubectl delete dynamographdeployment qwen-coder -n workshop
kubectl apply -f /home/ubuntu/atlworkshop/qwen-coder-dynamo.yaml
```

## Troubleshooting

### Pod Not Ready
```bash
kubectl describe pod -n workshop -l nvidia.com/dynamo-component=QwenCoderWorker
kubectl logs -n workshop -l nvidia.com/dynamo-component=QwenCoderWorker
```

### Model Download Issues
Check HuggingFace token secret:
```bash
kubectl get secret hf-token-secret -n workshop -o yaml
```

### GPU Not Allocated
Verify node resources:
```bash
kubectl describe node | grep -A5 "Allocated resources"
```

## Next Steps

1. **Add monitoring**: Integrate with Prometheus/Grafana
2. **Enable autoscaling**: Scale based on request load
3. **Add LoRA adapters**: Fine-tune for specific coding tasks
4. **Multi-model serving**: Deploy additional models

## Summary

✅ **Deployment Status**: OPERATIONAL
✅ **Model**: Qwen2.5-Coder-7B-Instruct
✅ **API**: OpenAI-compatible chat completions
✅ **Performance**: Fast inference with Flash Attention
✅ **Resource Usage**: 1 GPU, 14GB VRAM, efficient

The deployment is ready for workshop demos and testing!
