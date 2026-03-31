#!/bin/bash
# =============================================================================
# 03-demo-openclaw.sh - Part 3: Deploy OpenClaw Gateway
# Mastering Agentic Coding & GPUs Workshop
# =============================================================================
# Demonstrates:
#   1. Deploy OpenClaw gateway on Kubernetes
#   2. Configure a WhatsApp channel (mock/template)
#   3. Test message routing through the gateway
#
# NOTE: This uses placeholder values. No real credentials are included.
#       Replace all <TODO: ...> markers before running against a real cluster.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Configuration -- TODO: Replace placeholders before running
# ---------------------------------------------------------------------------
NAMESPACE="${WORKSHOP_NS:-workshop-agentic}"
OPENCLAW_IMAGE="<TODO: OPENCLAW_CONTAINER_IMAGE>"       # e.g., ghcr.io/openclaw/openclaw:latest
OPENCLAW_PORT=18789
GATEWAY_TOKEN="<TODO: GATEWAY_AUTH_TOKEN>"               # Generate with: openssl rand -hex 32
OPENAI_API_KEY="<TODO: OPENAI_API_KEY>"                  # For LLM model provider
GOOGLE_API_KEY="<TODO: GOOGLE_API_KEY>"                  # For Gemini models
WHATSAPP_PHONE="<TODO: +1XXXXXXXXXX>"                    # WhatsApp phone number

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
step() {
    echo ""
    echo -e "${BOLD}${MAGENTA}--- Step $1: $2 ---${NC}"
    echo ""
}

pause() {
    echo ""
    echo -e "${YELLOW}[Press ENTER to continue...]${NC}"
    read -r
}

run_show() {
    echo -e "${CYAN}\$ $*${NC}"
    eval "$@"
    echo ""
}

header() {
    echo -e "${BOLD}============================================${NC}"
    echo -e "${BOLD}  Part 3: OpenClaw Gateway${NC}"
    echo -e "${BOLD}  AI Agent Messaging Platform${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
    echo -e "  OpenClaw routes messages from WhatsApp, Slack,"
    echo -e "  and other channels to AI agents (Claude, GPT, Gemini)."
    echo ""
    echo -e "  Architecture:"
    echo -e "    WhatsApp -> BlueBubbles -> OpenClaw Gateway -> AI Agent"
    echo -e "                                    |"
    echo -e "                             Skills + Tools"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
header

# ==========================================================================
# Step 1: Deploy OpenClaw Gateway
# ==========================================================================
step 1 "Deploy OpenClaw Gateway"

echo -e "${DIM}  OpenClaw is a self-hosted AI gateway that connects messaging${NC}"
echo -e "${DIM}  channels to frontier LLM models with skill/tool support.${NC}"
echo ""

# Ensure namespace exists
if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    kubectl create namespace "$NAMESPACE"
fi

echo -e "  Deploying OpenClaw configuration..."
echo ""

echo -e "${YELLOW}  [DRY-RUN] Create the gateway secret (NEVER store real keys in scripts):${NC}"
echo ""
echo -e "${CYAN}  kubectl create secret generic openclaw-secrets -n ${NAMESPACE} \\${NC}"
echo -e "${CYAN}    --from-literal=GATEWAY_TOKEN=\$(openssl rand -hex 32) \\${NC}"
echo -e "${CYAN}    --from-literal=OPENAI_API_KEY=<your-key> \\${NC}"
echo -e "${CYAN}    --from-literal=GOOGLE_API_KEY=<your-key>${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Apply the OpenClaw manifest:${NC}"
echo ""
MANIFEST_DIR="$(cd "$DEMO_DIR/../manifests" && pwd)"
echo -e "${CYAN}  kubectl apply -f ${MANIFEST_DIR}/openclaw-workshop.yaml -n ${NAMESPACE}${NC}"
echo ""

echo -e "${DIM}  The manifest deploys:${NC}"
echo -e "    - ConfigMap: openclaw.json template with model providers"
echo -e "    - Secret reference: API keys from K8s Secret"
echo -e "    - Deployment: OpenClaw gateway (port ${OPENCLAW_PORT})"
echo -e "    - Service: ClusterIP for internal access"
echo ""

echo -e "${DIM}  OpenClaw configuration template (openclaw.json):${NC}"
cat << 'CONFIG_PREVIEW'
  {
    "models": {
      "providers": {
        "openai": { "models": ["gpt-5.4", "gpt-4.1"] },
        "google": { "models": ["gemini-3-pro", "gemini-2.5-flash"] },
        "aws-bedrock": { "models": ["claude-opus-4.6", "claude-sonnet-4.6"] }
      }
    },
    "channels": {
      "whatsapp": {
        "enabled": true,
        "dmPolicy": "allowlist",
        "allowFrom": ["+1XXXXXXXXXX"]
      }
    },
    "gateway": {
      "mode": "local",
      "auth": { "mode": "token" }
    }
  }
CONFIG_PREVIEW
echo ""

pause

# ==========================================================================
# Step 2: Configure WhatsApp Channel
# ==========================================================================
step 2 "Configure WhatsApp Channel (Template)"

echo -e "${DIM}  WhatsApp integration uses BlueBubbles as the message bridge.${NC}"
echo -e "${DIM}  BlueBubbles runs on a macOS instance and relays iMessage/WhatsApp.${NC}"
echo ""

echo -e "${BOLD}  WhatsApp Channel Architecture:${NC}"
echo ""
echo "    +----------+     +-----------+     +----------+     +--------+"
echo "    | WhatsApp |<--->|BlueBubbles|<--->| OpenClaw |<--->|  LLM   |"
echo "    | (Phone)  |     | (macOS)   |     | Gateway  |     | Agent  |"
echo "    +----------+     +-----------+     +----------+     +--------+"
echo ""

echo -e "${DIM}  Configuration steps (all done via SSH tunnel, NEVER public):${NC}"
echo ""
echo -e "  1. ${BOLD}BlueBubbles server${NC} on macOS (separate machine)"
echo -e "     Access via SSH tunnel: ${CYAN}ssh -L 1234:localhost:1234 user@mac-host${NC}"
echo ""
echo -e "  2. ${BOLD}OpenClaw gateway${NC} connects to BlueBubbles"
echo -e "     Access via SSH tunnel: ${CYAN}ssh -L ${OPENCLAW_PORT}:localhost:${OPENCLAW_PORT} user@host${NC}"
echo ""
echo -e "  3. ${BOLD}Channel config${NC} in openclaw.json:"
echo -e '     "channels": {'
echo -e '       "whatsapp": {'
echo -e '         "enabled": true,'
echo -e "         \"dmPolicy\": \"allowlist\","
echo -e "         \"allowFrom\": [\"${WHATSAPP_PHONE}\"],"
echo -e '         "mediaMaxMb": 50'
echo -e '       }'
echo -e '     }'
echo ""
echo -e "  ${RED}SECURITY: Never expose BlueBubbles or OpenClaw to the public internet.${NC}"
echo -e "  ${RED}Always use SSH tunnels for access.${NC}"

pause

# ==========================================================================
# Step 3: Test Message Routing
# ==========================================================================
step 3 "Test Message Routing"

echo -e "${DIM}  Test the gateway's message routing with a direct API call.${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Port-forward the OpenClaw service:${NC}"
echo ""
echo -e "${CYAN}  kubectl port-forward -n ${NAMESPACE} svc/openclaw-gateway ${OPENCLAW_PORT}:${OPENCLAW_PORT} &${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Test the health endpoint:${NC}"
echo ""
echo -e "${CYAN}  curl -s http://localhost:${OPENCLAW_PORT}/health${NC}"
echo ""
echo -e "${DIM}  Expected: {\"status\": \"ok\", \"version\": \"2026.3.x\"}${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Send a test message through the gateway:${NC}"
echo ""
echo -e "${CYAN}  curl -s http://localhost:${OPENCLAW_PORT}/api/v1/chat \\${NC}"
echo -e "${CYAN}    -H 'Content-Type: application/json' \\${NC}"
echo -e "${CYAN}    -H 'Authorization: Bearer \${GATEWAY_TOKEN}' \\${NC}"
echo -e "${CYAN}    -d '{${NC}"
echo -e "${CYAN}      \"message\": \"What GPU instances support EFA?\",${NC}"
echo -e "${CYAN}      \"agent\": \"hub\",${NC}"
echo -e "${CYAN}      \"model\": \"openai/gpt-5.4\"${NC}"
echo -e "${CYAN}    }'${NC}"
echo ""

echo -e "${DIM}  Expected response (mock):${NC}"
echo '  {
    "response": "The following AWS GPU instances support EFA: p4d.24xlarge (8x A100), p5.48xlarge (8x H100 80GB), p5en.48xlarge (8x H200). Each provides multiple EFA adapters for high-bandwidth inter-node RDMA.",
    "model": "openai/gpt-5.4",
    "agent": "hub",
    "tokens": { "input": 12, "output": 87 }
  }'
echo ""

echo -e "${DIM}  To test WhatsApp routing end-to-end:${NC}"
echo -e "    1. Send a WhatsApp message to the configured number"
echo -e "    2. BlueBubbles relays it to OpenClaw"
echo -e "    3. OpenClaw routes to the AI agent"
echo -e "    4. Response flows back: Agent -> OpenClaw -> BlueBubbles -> WhatsApp"

pause

# ==========================================================================
# Summary
# ==========================================================================
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Part 3 Complete: OpenClaw Gateway${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo -e "  What we covered:"
echo -e "    1. ${BOLD}Gateway deployment${NC} -- K8s Deployment + Service"
echo -e "    2. ${BOLD}Model providers${NC} -- OpenAI, Google, AWS Bedrock"
echo -e "    3. ${BOLD}WhatsApp channel${NC} -- via BlueBubbles bridge"
echo -e "    4. ${BOLD}Message routing${NC} -- API-driven agent dispatch"
echo ""
echo -e "  Security reminders:"
echo -e "    - ${RED}No public exposure${NC} -- SSH tunnels only"
echo -e "    - ${RED}No credentials in code${NC} -- K8s Secrets only"
echo -e "    - ${RED}Allowlist policy${NC} -- only permitted numbers"
echo ""
echo -e "  Next: ${CYAN}04-demo-hpc-optimization.sh${NC} -- HPC Kernel Optimization"
echo ""
