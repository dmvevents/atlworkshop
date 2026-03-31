# Connecting Claude Code Router & OpenCode to Your Dynamo Endpoint

This guide walks through safely configuring the Claude Code Router and OpenCode
to use your self-hosted Dynamo inference endpoint. Every step is reversible.

**Verified working:** 2026-03-31 against Qwen2.5-Coder-7B on Dynamo v0.9.0.

---

## Prerequisites

- Dynamo model running in the `workshop` namespace
- Port-forward active: `kubectl port-forward -n workshop svc/qwen-coder-frontend 8000:8000`

Verify:
```bash
curl -s http://localhost:8000/v1/models | jq -r '.data[0].id'
# Expected: Qwen/Qwen2.5-Coder-7B-Instruct
```

---

## Part 1: OpenCode (Safe — Isolated by Design)

OpenCode uses project-local config, so it never affects other tools.

### Step 1: Install

```bash
curl -fsSL https://opencode.ai/install | bash
# Binary: ~/.opencode/bin/opencode (v1.3.10)
```

### Step 2: Configure Provider

```bash
# Navigate to your project
cd your-project/

# Set environment variables
export OPENAI_API_KEY="not-needed"
export OPENAI_BASE_URL="http://localhost:8000/v1"
```

Or create `opencode.json` in the project root:

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

### Step 3: Test

```bash
# Interactive TUI
~/.opencode/bin/opencode

# Or one-shot command
~/.opencode/bin/opencode run "Write a hello world in Go"
```

### Revert

Just unset the environment variables or delete `opencode.json`. No global state is changed.

```bash
unset OPENAI_API_KEY OPENAI_BASE_URL
rm opencode.json  # if created
```

---

## Part 2: Claude Code Router (Requires Care — Modifies Global Config)

The router intercepts ALL Claude Code requests. Follow this process exactly.

### Safety Protocol

```
1. BACKUP current config       ← you can always restore
2. TEST on a separate port     ← doesn't touch your active setup
3. VERIFY the test works       ← confirm before switching
4. UPDATE the real config      ← only after test passes
5. KEEP the backup             ← rollback in seconds if needed
```

### Step 1: Backup Current Config

```bash
# Create timestamped backup
cp ~/.claude-code-router/config.json \
   ~/.claude-code-router/config.json.backup-$(date +%Y%m%d_%H%M%S)

# Verify backup exists
ls -la ~/.claude-code-router/config.json.backup-*
```

### Step 2: Test on Separate Port (Port 9090)

Create a test config that doesn't interfere with anything:

```bash
cat > /tmp/ccr-test-config.json << 'TESTEOF'
{
  "LOG": true,
  "HOST": "127.0.0.1",
  "PORT": 9090,
  "APIKEY": "test-local",
  "API_TIMEOUT_MS": 60000,
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
    "default": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct"
  }
}
TESTEOF
```

Test the routing manually (no router process needed):

```bash
# Simulate what the router does: send OpenAI-format request to Dynamo
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer not-needed" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "What is 2+2? Just the number."}],
    "max_tokens": 5
  }' | jq '.choices[0].message.content'
# Expected: "4"
```

Verify response compatibility:

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Hi"}],
    "max_tokens": 5
  }' | jq '{
    has_id: (.id != null),
    has_choices: (.choices != null),
    has_usage: (.usage != null),
    finish_reason: .choices[0].finish_reason,
    object: .object
  }'
# All fields must be present. object must be "chat.completion".
```

### Step 3: Update Config (Only After Test Passes)

**Option A: Add Dynamo as an additional provider** (recommended — keeps existing providers)

```bash
# Read current config, add dynamo provider, write back
python3 << 'PYEOF'
import json

config_path = "/home/ubuntu/.claude-code-router/config.json"
with open(config_path) as f:
    config = json.load(f)

# Add dynamo-local provider
dynamo_provider = {
    "name": "dynamo-local",
    "api_base_url": "http://localhost:8000/v1/chat/completions",
    "api_key": "not-needed",
    "models": ["Qwen/Qwen2.5-Coder-7B-Instruct"]
}

# Only add if not already present
provider_names = [p["name"] for p in config["Providers"]]
if "dynamo-local" not in provider_names:
    config["Providers"].append(dynamo_provider)

# Add background routing to local model (keeps default as-is)
config["Router"]["background"] = "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct"

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print("Added dynamo-local provider")
print(f"Background tasks now route to: dynamo-local")
print(f"Default still routes to: {config['Router']['default']}")
PYEOF
```

**Option B: Route everything to Dynamo** (for testing only)

```bash
python3 << 'PYEOF'
import json

config_path = "/home/ubuntu/.claude-code-router/config.json"
with open(config_path) as f:
    config = json.load(f)

# Save original default for rollback reference
print(f"Original default: {config['Router']['default']}")

# Add dynamo provider if needed
provider_names = [p["name"] for p in config["Providers"]]
if "dynamo-local" not in provider_names:
    config["Providers"].append({
        "name": "dynamo-local",
        "api_base_url": "http://localhost:8000/v1/chat/completions",
        "api_key": "not-needed",
        "models": ["Qwen/Qwen2.5-Coder-7B-Instruct"]
    })

# Route everything to local
config["Router"]["default"] = "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct"
config["Router"]["background"] = "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct"

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print("ALL routing now goes to dynamo-local")
PYEOF
```

### Step 4: Restart Router

```bash
ccr restart
ccr status
# Should show: Running on port 8080
```

### Step 5: Test via Router

```bash
# Quick test through the router
ccr code "What is 2+2?"

# Or test with curl
curl -s http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "messages": [{"role": "user", "content": "Write hello world in Rust"}],
    "max_tokens": 100
  }' | jq '.choices[0].message.content'
```

---

## Rollback (Instant)

If anything goes wrong:

```bash
# Option 1: Restore from backup (instant)
cp ~/.claude-code-router/config.json.backup-* ~/.claude-code-router/config.json
ccr restart

# Option 2: Stop the router entirely (Claude Code uses Anthropic API directly)
ccr stop

# Option 3: Remove just the dynamo provider
python3 << 'PYEOF'
import json
config_path = "/home/ubuntu/.claude-code-router/config.json"
with open(config_path) as f:
    config = json.load(f)
config["Providers"] = [p for p in config["Providers"] if p["name"] != "dynamo-local"]
config["Router"]["default"] = "openai,gpt-5.2"  # restore original
config["Router"].pop("background", None)
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
print("Removed dynamo-local, restored defaults")
PYEOF
ccr restart
```

---

## Recommended Setup: Hybrid Routing

Route cheap/fast tasks to your self-hosted model, expensive tasks to cloud:

```json
{
  "Router": {
    "default": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct",
    "background": "dynamo-local,Qwen/Qwen2.5-Coder-7B-Instruct",
    "think": "anthropic,claude-opus-4-5-20250929",
    "longContext": "gemini,gemini-2.5-pro"
  }
}
```

| Task Type | Routed To | Cost |
|-----------|-----------|------|
| Default coding | Dynamo (local) | Free |
| Background tasks | Dynamo (local) | Free |
| Complex reasoning | Claude Opus (cloud) | $15/M tokens |
| Long context (>60K) | Gemini Pro (cloud) | $1.25/M tokens |

---

## Verification Checklist

After setup, verify everything works:

```bash
# 1. Dynamo endpoint is healthy
curl -s http://localhost:8000/v1/models | jq .

# 2. OpenCode connects
OPENAI_API_KEY=x OPENAI_BASE_URL=http://localhost:8000/v1 \
  ~/.opencode/bin/opencode run "say hello"

# 3. Python SDK connects
python3 -c "
from openai import OpenAI
c = OpenAI(base_url='http://localhost:8000/v1', api_key='x')
print(c.chat.completions.create(
    model='Qwen/Qwen2.5-Coder-7B-Instruct',
    messages=[{'role':'user','content':'Hi'}], max_tokens=5
).choices[0].message.content)
"

# 4. Router connects (if configured)
ccr status
curl -s http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer local" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen2.5-Coder-7B-Instruct","messages":[{"role":"user","content":"Hi"}],"max_tokens":5}' \
  | jq .choices[0].message.content

# 5. Backup exists
ls ~/.claude-code-router/config.json.backup-*
```

---

## Compatibility Matrix (Verified)

| Client | Works with Dynamo | Notes |
|--------|-------------------|-------|
| OpenAI Python SDK | Yes | `base_url="http://localhost:8000/v1"` |
| OpenAI Node.js SDK | Yes | `baseURL: "http://localhost:8000/v1"` |
| curl | Yes | Standard OpenAI chat/completions format |
| OpenCode v1.3.10 | Yes | Via `OPENAI_BASE_URL` env var |
| Claude Code Router v1.0.73 | Yes | Add as `openai-compatible` provider |
| LangChain | Yes | Use `ChatOpenAI(base_url=...)` |
| LlamaIndex | Yes | Use `OpenAI(api_base=...)` |
| Streaming | Yes | SSE format, `"stream": true` |

All fields in the response (id, model, choices, usage, finish_reason) are present
and correctly formatted. No transformation needed.
