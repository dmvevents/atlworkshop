# Module 4: OpenClaw & WhatsApp Integration

**Duration:** 15 minutes
**Prerequisites:** Module 3 (Deploying Coding Agents)

---

## 1. OpenClaw Overview

[OpenClaw](https://github.com/openclaw/openclaw) is an AI assistant hub that connects large language models to the communication channels people already use -- WhatsApp, Slack, Discord, email, and more. Instead of switching to a chat UI or IDE to talk to an AI, OpenClaw brings the AI to your existing workflows.

### Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Multi-Channel Gateway** | Single deployment serves WhatsApp, Slack, Discord, email simultaneously |
| **Multi-LLM Backend** | Route to Claude, GPT, Gemini, or locally-served models |
| **Session Persistence** | Conversations maintain context across messages and channels |
| **tmux Injection** | Send commands directly into running Claude Code sessions from your phone |
| **Agent Routing** | Route messages to specialized agents based on content |

### Why OpenClaw?

- **You are not always at your desk.** Send a WhatsApp message to trigger a deployment, check build status, or ask a coding question.
- **Teams use different tools.** Engineering lives in Slack, support lives in email, executives use WhatsApp. One gateway serves them all.
- **Agents need a communication layer.** OpenClaw bridges the gap between AI agents and human-facing messaging platforms.

---

## 2. Architecture

```
Phone / Browser / App
    |
    | (WhatsApp, Slack, Discord, Email)
    v
+-------------------------------------------+
|         OpenClaw Gateway (:18789)          |
|                                            |
|  +-- Channel Adapters                      |
|  |   (WhatsApp, Slack, Discord, IMAP)      |
|  |                                         |
|  +-- Agent Hub                             |
|  |   Routes messages to the right agent    |
|  |                                         |
|  +-- Session Manager                       |
|  |   Tracks conversations across channels  |
|  |                                         |
|  +-- Multi-LLM Router                      |
|  |   Claude Opus | GPT | Gemini | Local    |
|  |                                         |
|  +-- tmux Injection                        |
|      Send commands into Claude Code        |
+-------------------------------------------+
    |
    v
Claude Code / Coding Agents / Custom Tools
```

### Component Responsibilities

**Channel Adapters** handle protocol-specific details (WhatsApp Business API, Slack Events API, Discord Gateway, IMAP polling) and normalize messages into a common format.

**Agent Hub** examines each incoming message and routes it to the appropriate handler -- a general-purpose LLM conversation, a specialized agent, or a tmux command injection.

**Session Manager** maintains conversation state. Each user+channel combination gets a persistent session with full message history, so the AI has context across messages.

**Multi-LLM Router** selects the backend model. You can configure a primary (e.g., Claude Opus via Bedrock) with automatic fallback (e.g., GPT when Claude is rate-limited).

**tmux Injection** is the bridge between messaging and coding agents. A WhatsApp message like "deploy the staging branch" can be injected directly into a running Claude Code tmux session.

---

## 3. WhatsApp Integration

OpenClaw connects to WhatsApp through a local bridge that pairs with your WhatsApp account via QR code -- no Business API approval needed for personal use.

### How Message Routing Works

```
1. You send a WhatsApp message
2. Bridge captures message via WebSocket
3. Gateway normalizes: { sender, text, channel: "whatsapp", timestamp }
4. Agent Hub checks routing rules:
   - Starts with "/" -> command dispatch
   - Contains project name -> route to project agent
   - Default -> general LLM conversation
5. Response sent back through the bridge to WhatsApp
```

### Example Interactions

```
You (WhatsApp):  "What's the status of the API refactor?"
OpenClaw:        "The api-refactor branch has 3 commits ahead of main.
                  Tests pass. Last commit: 'add pagination to /users
                  endpoint' (2 hours ago)."

You (WhatsApp):  "/deploy staging"
OpenClaw:        "Injecting deploy command into tmux session 'staging-deploy'...
                  Deployment started. I'll notify you when it completes."

You (WhatsApp):  "Explain the auth middleware in the connect service"
OpenClaw:        [Claude Opus analyzes the codebase and returns explanation]
```

### tmux Injection Flow

```
WhatsApp message: "/run pytest tests/test_auth.py"
         |
         v
   Agent Hub recognizes /run prefix
         |
         v
   inject-command.sh finds target tmux session
         |
         v
   tmux send-keys "pytest tests/test_auth.py" Enter
         |
         v
   Output captured and sent back to WhatsApp
```

---

## 4. NemoClaw: Self-Referential AI

NemoClaw takes the concept further -- it is an AI agent that trains, serves, and narrates using the **same model**. It demonstrates a self-referential loop where the agent's own intelligence improves with each iteration.

### The Self-Referential Loop

```
1. NeMo Curator     -> generates training data
2. NeMo RL (GRPO)   -> trains Nemotron on GPUs
3. NVIDIA Dynamo    -> serves the trained model (disaggregated inference, EFA RDMA)
4. NemoClaw agent   -> calls Dynamo for its own reasoning
5. NemoClaw         -> orchestrates steps 1-4 again (next iteration)
```

Each iteration, the model improves. NemoClaw's commentary is generated by this improving model. The agent narrates its own training in real time.

### Architecture on EKS

```
+----------------------------------------------------------------+
|                      Amazon EKS Cluster                         |
|                                                                 |
|  +----------------+     +------------------------------------+  |
|  | NemoClaw Agent |     | NVIDIA Dynamo                      |  |
|  |                |---->|                                     |  |
|  | Orchestrates   |HTTP | +----------+ NIXL  +----------+   |  |
|  | 6-step demo    |     | | Prefill  |<----->| Decode   |   |  |
|  +-------+--------+     | | (Node 1) | EFA   | (Node 2) |   |  |
|          |              | +----------+ RDMA  +----------+   |  |
|          | fallback     +------------------------------------+  |
|          v                                                      |
|  +----------------+                                             |
|  | AWS Bedrock    |  (when GPUs busy with training)             |
|  | Nemotron       |                                             |
|  +----------------+                                             |
+----------------------------------------------------------------+
```

### Auto-Discovery and Fallback

NemoClaw auto-discovers its Dynamo inference endpoint from Kubernetes pod IPs -- no hardcoded URLs:

```python
# Pseudo-code: auto-discover Dynamo endpoint
def discover_dynamo():
    pods = kubectl_get_pods(namespace="dynamo", label="app=dynamo-frontend")
    for pod in pods:
        endpoint = f"http://{pod.ip}:8000/v1"
        if health_check(endpoint):
            return endpoint
    return None  # triggers Bedrock fallback
```

When GPUs are occupied by training, NemoClaw transparently falls back to Bedrock:

```python
def get_completion(prompt):
    dynamo = discover_dynamo()
    if dynamo:
        return call_openai_compatible(dynamo, prompt)  # local model
    else:
        return call_bedrock(prompt)  # cloud fallback
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DYNAMO_ENDPOINT` | (auto-discover) | Dynamo frontend URL |
| `DYNAMO_MODEL` | Model name in registry | Model ID for Dynamo |
| `NEMOCLAW_BACKEND` | `dynamo` | Primary: `dynamo`, `bedrock`, or `auto` |
| `NEMOCLAW_FALLBACK` | `bedrock` | Fallback: `bedrock` or `none` |

---

## 5. Amazon Connect: AI-Deployed Contact Center

This demo shows an AI agent (Claude Code) deploying a **fully functional AWS contact center** from scratch using only the AWS CLI. No console clicks, no CloudFormation, no Terraform. The entire deployment takes approximately 90 seconds.

### What Gets Deployed

| Resource | Details |
|----------|---------|
| Connect Instance | Managed identity, inbound + outbound calls |
| Contact Flow (IVR) | Custom greeting with AI-generated script |
| Phone Number | US DID number, associated with the contact flow |
| Admin User | Soft phone enabled, full admin permissions |
| Queue + Routing | Default queue with basic routing profile |

### Demo Script Structure

The deployment follows a 6-step sequential process:

```bash
#!/usr/bin/env bash
# Deploy a contact center in ~90 seconds

# Step 1: Create Connect Instance
aws connect create-instance \
  --identity-management-type CONNECT_MANAGED \
  --instance-alias "demo-instance" \
  --inbound-calls-enabled \
  --outbound-calls-enabled

# Step 2: Wait for ACTIVE status (poll every 10s)
# Instance creation is asynchronous

# Step 3: Create custom contact flow (IVR)
# Contact flow defined as JSON -- version-controllable

# Step 4: Claim a phone number
# Associate it with the contact flow

# Step 5: Create admin user
# Configure with security profile and routing profile

# Step 6: Output summary
# Instance URL, phone number, admin credentials
```

### Architecture

```
Caller --> +1 (xxx) xxx-xxxx
              |
              v
        [AI-Agent-Demo-Flow]
              |
              v
        "Welcome to the AI Agent Demo..."
              |
              v
        [BasicQueue] --> [admin soft phone]
```

### Key Demo Points

1. **Zero-click deployment** -- entire contact center created via API
2. **~90 seconds** -- from nothing to a working phone number with IVR
3. **Programmatic IVR** -- contact flow defined as JSON, fully version-controllable
4. **Testable** -- chat contact started via API proves the flow works
5. **Clean teardown** -- one command removes everything
6. **Agent-driven** -- the AI agent researched the APIs, handled async waits, and wired everything together autonomously

### Teardown

```bash
# Remove all resources in reverse order
./teardown-connect.sh
# Releases phone number, deletes flow, removes instance
```

---

## 6. Hands-On: Deploy OpenClaw Gateway

### Step 1: Clone and Install

```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw
pnpm install
pnpm build
```

### Step 2: Create Configuration

```bash
mkdir -p ~/.openclaw
cat > ~/.openclaw/openclaw.json << 'EOF'
{
  "gateway": {
    "port": 18789,
    "host": "127.0.0.1"
  },
  "llm": {
    "primary": {
      "provider": "bedrock",
      "model": "us.anthropic.claude-opus-4-6-v1",
      "region": "us-west-2"
    },
    "fallback": {
      "provider": "openai",
      "model": "gpt-4o"
    }
  },
  "channels": {
    "whatsapp": {
      "enabled": true,
      "autoReply": true
    }
  },
  "sessions": {
    "persistence": true,
    "maxHistory": 100
  }
}
EOF
```

> **Security note:** Never commit API keys into configuration files. Use environment variables or a secrets manager. The config above uses IAM-based Bedrock access which does not require embedded credentials.

### Step 3: Start the Gateway

```bash
# Start the OpenClaw gateway (binds to localhost only)
pnpm openclaw gateway --port 18789
```

### Step 4: Pair WhatsApp

```bash
# In a separate terminal
pnpm openclaw channels login
```

This displays a QR code in your terminal. Scan it with WhatsApp on your phone (Settings > Linked Devices > Link a Device). Once paired, messages to your WhatsApp are processed by the gateway.

### Step 5: Test the Connection

Send a WhatsApp message to yourself:

```
Hello, what can you do?
```

The gateway should respond via Claude Opus with a description of its capabilities.

### Step 6: Configure tmux Injection (Optional)

To control Claude Code sessions from WhatsApp:

```bash
# Start a named Claude Code session
tmux new-session -s coding -d
tmux send-keys -t coding 'claude --name "my-project"' Enter

# Now from WhatsApp, you can send:
# /inject coding "check git status and summarize recent changes"
```

---

## 7. Channel Integrations

OpenClaw supports multiple channels simultaneously. Each channel adapter normalizes messages into a common format for the Agent Hub.

### Slack

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "${SLACK_BOT_TOKEN}",
      "appToken": "${SLACK_APP_TOKEN}",
      "channels": ["#ai-assistant", "#engineering"]
    }
  }
}
```

Setup:
1. Create a Slack app at api.slack.com/apps
2. Add Bot Token Scopes: `chat:write`, `channels:read`, `channels:history`
3. Enable Socket Mode for real-time events
4. Install to workspace, copy tokens to environment variables

### Discord

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "botToken": "${DISCORD_BOT_TOKEN}",
      "guilds": ["your-server-id"],
      "channels": ["ai-assistant"]
    }
  }
}
```

Setup:
1. Create a Discord application at discord.com/developers
2. Add a bot, enable Message Content Intent
3. Generate invite URL with `bot` and `applications.commands` scopes
4. Copy bot token to environment variable

### Email (via IMAP)

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "imap": {
        "host": "imap.gmail.com",
        "port": 993,
        "user": "${EMAIL_USER}",
        "password": "${EMAIL_APP_PASSWORD}"
      },
      "smtp": {
        "host": "smtp.gmail.com",
        "port": 587
      },
      "pollInterval": 30
    }
  }
}
```

Setup:
1. Generate an app-specific password (never use your main password)
2. Set environment variables for credentials
3. Configure poll interval (seconds between IMAP checks)

### oh-my-claudecode Integration

OMC can forward Claude Code session events to an OpenClaw gateway, enabling automated responses:

```bash
# Inside a Claude Code session with OMC installed:
/oh-my-claudecode:configure-notifications
# When prompted, select "OpenClaw Gateway"
```

Or configure manually:

```json
{
  "enabled": true,
  "gateways": {
    "my-gateway": {
      "url": "http://localhost:18789/wake",
      "method": "POST",
      "timeout": 10000
    }
  },
  "hooks": {
    "session-start": {
      "gateway": "my-gateway",
      "instruction": "Session started for {{projectName}}",
      "enabled": true
    },
    "stop": {
      "gateway": "my-gateway",
      "instruction": "Session completed for {{projectName}}",
      "enabled": true
    }
  }
}
```

Supported hook events: `session-start`, `stop`, `keyword-detector`, `ask-user-question`, `pre-tool-use`, `post-tool-use`.

---

## Channel Comparison

| Channel | Latency | Rich Media | Threading | Best For |
|---------|---------|-----------|-----------|----------|
| WhatsApp | ~1-2s | Images, docs | Reply chains | Mobile-first, personal use |
| Slack | <1s | Full markdown, files | Native threads | Team engineering workflows |
| Discord | <1s | Embeds, reactions | Forum channels | Community, open-source projects |
| Email | 30s+ (poll) | Full HTML, attachments | Thread subjects | Formal communication, audit trail |

---

## Key Takeaways

1. **OpenClaw bridges AI and communication** -- bring Claude to WhatsApp, Slack, Discord, email
2. **Gateway architecture** -- one deployment serves all channels with a common Agent Hub
3. **tmux injection** -- control coding agents from your phone
4. **NemoClaw shows self-referential AI** -- an agent powered by the model it trains and serves
5. **Amazon Connect in 90 seconds** -- AI agents can deploy production infrastructure autonomously
6. **Security first** -- credentials in environment variables, gateway bound to localhost, no public exposure

---

**Next:** [Module 5 - GPU Foundations](../05-gpu-foundations/README.md)
