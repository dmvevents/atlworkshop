---
name: deploy-opencode-self-hosted
description: Use when deploying OpenCode with a self-hosted vLLM/Dynamo endpoint, when OpenCode returns Bad Request errors against local models, or when connecting any OpenAI Responses API client to vLLM
---

# Deploy OpenCode with Self-Hosted vLLM/Dynamo

## When to Use

- OpenCode returns "Bad Request: Failed to deserialize" against vLLM
- OpenCode returns "missing field `strict`" errors
- OpenCode returns "ChatCompletionRequestUserMessageContent" errors
- Any OpenAI Responses API client needs to connect to vLLM
- Context window overflow from tool definitions

## Known Incompatibilities (vLLM + OpenCode)

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `missing field 'strict'` | OpenCode sends `strict: true` in tool schemas | Strip `strict` from tools |
| `ChatCompletionRequestUserMessageContent` | Content sent as array, not string | Flatten array content |
| `/v1/responses` 404 | OpenCode uses Responses API, vLLM only has Chat Completions | Translation proxy |
| `prompt length exceeds max_model_len` | OpenCode sends ~50K tokens of tool defs | Truncate instructions + skip tools |

## Solution: Translation Proxy

Run `opencode-proxy.py` between OpenCode and vLLM:

```
OpenCode → :8001 (proxy) → :8000 (vLLM)
```

The proxy:
1. Translates `/v1/responses` → `/v1/chat/completions`
2. Flattens array content to plain strings
3. Strips `strict` field from tool definitions
4. Truncates system instructions (3000 char cap)
5. Caps total input to 20K chars to fit context window
6. Skips tool forwarding (tools alone are ~50K tokens)
7. Forces all requests to the loaded model name

## Deployment Steps

```bash
# 1. Port-forward to Dynamo
kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000 &

# 2. Start translation proxy
python3 dynamo-deployment/scripts/opencode-proxy.py &

# 3. Launch OpenCode through proxy
OPENAI_API_KEY=not-needed OPENAI_BASE_URL=http://localhost:8001/v1 \
  opencode -m openai/gpt-4o
```

## Checklist Before Claiming It Works

- [ ] Port-forward alive: `curl localhost:8000/v1/models`
- [ ] Proxy alive: `curl localhost:8001/v1/models`
- [ ] Manual Responses API test: `curl localhost:8001/v1/responses -d '{"model":"gpt-4o","input":"hi","max_output_tokens":5}'`
- [ ] OpenCode `run` mode: `opencode run -m openai/gpt-4o "What is 2+2?"`
- [ ] OpenCode interactive: `opencode -m openai/gpt-4o`
- [ ] Check proxy logs for `<<< OK` (not `<<< ERR` or `<<< HTTP`)

## Anti-Patterns

- **Do NOT** try `--enable-auto-tool-choice` with `dynamo.vllm` -- it's not supported
- **Do NOT** create `opencode.json` with `"providers"` key -- wrong schema
- **Do NOT** assume `strict` field is the only issue -- the real problem is `/v1/responses`
- **Do NOT** increase `--max-model-len` past 32K for 7B models -- OOM on A100 40GB
