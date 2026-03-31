# Qwen2.5-Coder Quick Start Guide

## ✅ Deployment Status

**OPERATIONAL** - Qwen2.5-Coder-7B-Instruct is running on Dynamo

```
Frontend:  qwen-coder-frontend-699456469c-dkqgt         READY 1/1
Worker:    qwen-coder-qwencoderworker-56ff69bf4-82nvw   READY 1/1
```

## 🚀 Quick Test (30 seconds)

```bash
kubectl run test --rm -i --restart=Never --image=curlimages/curl:latest -n workshop -- \
  curl -s -X POST http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-Coder-7B-Instruct","messages":[{"role":"user","content":"Write quicksort in Python"}],"max_tokens":200}'
```

## 📡 API Endpoint

**Internal**: `http://qwen-coder-frontend.workshop.svc.cluster.local:8000`

**External** (via port-forward):
```bash
kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000
# Then: curl http://localhost:8000/v1/chat/completions ...
```

## 💬 Example Request

```bash
curl -X POST http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Explain what a binary search tree is."}
    ],
    "max_tokens": 300,
    "temperature": 0.7
  }'
```

## 📊 Resource Usage

- **CPU**: 2 cores (worker)
- **Memory**: 8.5 GB (worker)
- **GPU**: 1x A100 (14.25 GB VRAM)
- **KV Cache**: 20,924 blocks
- **Max batch**: 256 sequences

## 🔍 Monitoring

```bash
# Pod status
kubectl get pods -n workshop

# Logs
kubectl logs -n workshop -l nvidia.com/dynamo-component=QwenCoderWorker -f

# GPU usage (from inside worker pod)
kubectl exec -n workshop qwen-coder-qwencoderworker-56ff69bf4-82nvw -- nvidia-smi
```

## 🛠️ Management

```bash
# Restart
kubectl rollout restart deployment -n workshop qwen-coder-qwencoderworker

# Scale (add more GPUs)
kubectl edit dynamographdeployment qwen-coder -n workshop
# Change: spec.services.QwenCoderWorker.replicas: 2

# Delete
kubectl delete dynamographdeployment qwen-coder -n workshop
```

## 📝 Files

- **Deployment**: `/home/ubuntu/atlworkshop/qwen-coder-dynamo.yaml`
- **Test Script**: `/home/ubuntu/atlworkshop/test-qwen-coder.sh`
- **Full Docs**: `/home/ubuntu/atlworkshop/QWEN-CODER-DEPLOYMENT.md`

## 🎯 Use Cases

1. **Code Generation**: "Write a REST API in FastAPI"
2. **Code Explanation**: "Explain this function: [paste code]"
3. **Debugging**: "Why does this code fail? [paste error]"
4. **Refactoring**: "Improve this code: [paste code]"
5. **Documentation**: "Write docstrings for this class"

## 🔥 Pro Tips

1. **System Prompt**: Add `{"role": "system", "content": "You are an expert in X"}` for better responses
2. **Temperature**: Use 0.2-0.5 for code (more deterministic), 0.7-1.0 for explanations
3. **Max Tokens**: Code generation needs 200-500 tokens typically
4. **Streaming**: Add `"stream": true` for real-time responses

## ⚡ Performance

- **Latency**: ~50-200ms for short prompts
- **Throughput**: ~100-150 tokens/sec
- **Context**: Up to 8192 tokens
- **Batch**: Up to 256 concurrent requests

---

**Ready to code!** 🎉
