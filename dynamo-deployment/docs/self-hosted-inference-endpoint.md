# Using Your Self-Hosted Dynamo Endpoint with Coding Agents

Once you have a model running on Dynamo, you can point coding agents at it instead
of using cloud APIs. This gives you:

- **Zero API costs** -- inference runs on your own GPUs
- **Data privacy** -- code never leaves your cluster
- **Low latency** -- same-cluster network, no internet round-trip
- **Custom models** -- serve fine-tuned or specialized models

## Prerequisites

A running Dynamo deployment (see [../README.md](../README.md)):

```bash
# Verify your endpoint is up
kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000
curl http://localhost:8000/v1/models
# Should return: Qwen/Qwen2.5-Coder-7B-Instruct
```

Your endpoint URL:
- **Inside the cluster:** `http://qwen-coder-frontend.workshop.svc.cluster.local:8000`
- **Via port-forward:** `http://localhost:8000`

---

## Option 1: OpenCode (Recommended for Self-Hosted)

[OpenCode](https://opencode.ai) natively supports any OpenAI-compatible endpoint.

### Install

```bash
curl -fsSL https://opencode.ai/install | bash
# Binary: ~/.opencode/bin/opencode
```

### Configure

Create `opencode.json` in your project directory:

```json
{
  "provider": {
    "name": "openai-compatible",
    "apiKey": "not-needed",
    "baseUrl": "http://localhost:8000/v1",
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct"
  }
}
```

Or use environment variables:

```bash
export OPENAI_API_KEY="not-needed"
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_MODEL="Qwen/Qwen2.5-Coder-7B-Instruct"
```

### Run

```bash
cd your-project/
~/.opencode/bin/opencode
```

OpenCode will use your self-hosted Dynamo endpoint for all inference.

---

## Option 2: Claude Code Router

Use Claude Code's UX and tools, but route requests to your self-hosted model.

### Install

```bash
npm install -g @musistudio/claude-code-router
```

### Configure

Edit `~/.claude-code-router/config.json`:

```json
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "PORT": 3456,
  "APIKEY": "local",
  "API_TIMEOUT_MS": 600000,
  "Providers": [
    {
      "name": "dynamo-local",
      "api_base_url": "http://localhost:8000/v1/chat/completions",
      "api_key": "not-needed",
      "models": [
        "Qwen/Qwen2.5-Coder-7B-Instruct"
      ]
    }
  ],
  "Router": {
    "default": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct",
    "background": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct"
  }
}
```

### Run

```bash
# Start the router
ccr start

# Use Claude Code through the router
ccr code "Write a Python web server"

# Or activate environment and use claude directly
eval "$(ccr activate)"
claude
```

### Hybrid Routing (Best of Both)

Route simple tasks to your self-hosted model, complex tasks to cloud:

```json
{
  "Providers": [
    {
      "name": "dynamo-local",
      "api_base_url": "http://localhost:8000/v1/chat/completions",
      "api_key": "not-needed",
      "models": ["Qwen/Qwen2.5-Coder-7B-Instruct"]
    },
    {
      "name": "anthropic",
      "api_base_url": "https://api.anthropic.com/v1/messages",
      "api_key": "<YOUR_ANTHROPIC_KEY>",
      "models": ["claude-opus-4-6"]
    }
  ],
  "Router": {
    "default": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct",
    "background": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct",
    "think": "anthropic,claude-opus-4-6"
  }
}
```

This sends routine coding to your free self-hosted model and complex reasoning to Claude.

---

## Option 3: Direct API (Any Client)

Any tool that supports the OpenAI API can connect:

### Python (openai SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-Coder-7B-Instruct",
    messages=[{"role": "user", "content": "Write a quicksort in Python"}],
    max_tokens=300
)
print(response.choices[0].message.content)
```

### curl

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Explain async/await in Python"}],
    "max_tokens": 300,
    "stream": true
  }'
```

### Node.js

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'not-needed'
});

const completion = await client.chat.completions.create({
  model: 'Qwen/Qwen2.5-Coder-7B-Instruct',
  messages: [{ role: 'user', content: 'Write a REST API in Express' }]
});
console.log(completion.choices[0].message.content);
```

---

## Option 4: In-Cluster Access (No Port-Forward)

If your coding agent runs inside the same Kubernetes cluster:

```bash
# Use the service DNS name directly
export OPENAI_BASE_URL="http://qwen-coder-frontend.workshop.svc.cluster.local:8000/v1"
```

This eliminates port-forward overhead and gives sub-millisecond network latency.

---

## Performance Comparison

| Setup | TTFT | Cost | Privacy |
|-------|------|------|---------|
| Cloud API (Claude/GPT) | 200-500ms | $3-15/M tokens | Code sent to cloud |
| Self-hosted Dynamo (same cluster) | **47ms** | GPU cost only | Code stays on-prem |
| Self-hosted + port-forward | **100ms** | GPU cost only | Code stays local |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Connection refused" | Start port-forward: `kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000` |
| "Model not found" | Check model name exactly: `curl localhost:8000/v1/models` |
| Slow first response | Model loading into GPU. Wait 1-2 min after pod starts. |
| OpenCode won't connect | Set both `OPENAI_BASE_URL` and `OPENAI_API_KEY` (any non-empty value) |
| Router returns errors | Check `~/.claude-code-router/logs/` for details |
