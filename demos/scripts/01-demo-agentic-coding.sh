#!/bin/bash
# =============================================================================
# 01-demo-agentic-coding.sh - Part 1: Agentic Coding with Claude Code
# Mastering Agentic Coding & GPUs Workshop
# =============================================================================
# Demonstrates:
#   1. Claude Code version and configuration
#   2. Creating a sample CLAUDE.md project configuration
#   3. Skill invocation (built-in and custom)
#   4. Multi-model query (parallel dispatch to GPT-5.4 + Gemini 3 Pro + Claude)
#   5. Parallel agent launch (sub-agents for independent tasks)
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

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRATCH_DIR="/tmp/workshop-agentic-demo-$$"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
step() {
    echo ""
    echo -e "${BOLD}${MAGENTA}--- Step $1: $2 ---${NC}"
    echo ""
}

narrate() {
    echo -e "${DIM}# $1${NC}"
}

pause() {
    echo ""
    echo -e "${YELLOW}[Press ENTER to continue...]${NC}"
    read -r
}

run_show() {
    # Print the command, then run it
    echo -e "${CYAN}\$ $*${NC}"
    eval "$@"
    echo ""
}

cleanup() {
    rm -rf "$SCRATCH_DIR"
}
trap cleanup EXIT

header() {
    echo -e "${BOLD}============================================${NC}"
    echo -e "${BOLD}  Part 1: Agentic Coding with Claude Code${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
    echo -e "  This demo walks through the core capabilities"
    echo -e "  of Claude Code as an agentic coding assistant."
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
header

# ==========================================================================
# Step 1: Claude Code Version & Configuration
# ==========================================================================
step 1 "Claude Code Version & Configuration"

narrate "Show the installed Claude Code version"
run_show claude --version 2>/dev/null || echo -e "${YELLOW}(claude CLI not in PATH -- showing mock output)${NC}
claude 2.1.81"

narrate "Show the global settings location"
run_show ls -la ~/.claude/settings.json 2>/dev/null || echo -e "${DIM}  (No global settings.json found -- that is fine for a fresh install)${NC}"

narrate "Show current Claude configuration (permissions, hooks, env)"
echo -e "${DIM}  Key configuration points:${NC}"
echo -e "${DIM}    - permissions.allow: which tools Claude can use without asking${NC}"
echo -e "${DIM}    - hooks: PreToolUse / PostToolUse automation${NC}"
echo -e "${DIM}    - env: environment variables injected into sessions${NC}"

pause

# ==========================================================================
# Step 2: Create a Sample CLAUDE.md
# ==========================================================================
step 2 "Create a Sample CLAUDE.md"

narrate "CLAUDE.md is the project-level instruction file that Claude reads on every session start."
narrate "It defines coding standards, architecture rules, and project-specific context."

mkdir -p "$SCRATCH_DIR/sample-project/.claude"

cat > "$SCRATCH_DIR/sample-project/.claude/CLAUDE.md" << 'CLAUDEMD'
# Project: GPU Inference Service

## Architecture
- FastAPI frontend on port 8000
- TensorRT-LLM backend with disaggregated prefill/decode
- NIXL for KV cache transfer between prefill and decode workers
- etcd for service discovery, NATS for message bus

## Coding Standards
- Python 3.11+, type hints required
- Use `set -euo pipefail` in all shell scripts
- Never hardcode GPU device IDs -- use CUDA_VISIBLE_DEVICES
- All K8s manifests must include resource limits

## Testing
- Unit tests: `pytest tests/unit/`
- Integration tests require a running GPU: `pytest tests/integration/ -m gpu`
- Load test: `locust -f tests/load/locustfile.py`

## Deployment
- Namespace: `inference-prod`
- Helm chart: `charts/inference-service/`
- EFA required for multi-node: set `vpc.amazonaws.com/efa: "32"` in limits

## Security
- No credentials in code -- use K8s secrets or IAM roles
- All services internal only -- no public ingress
CLAUDEMD

echo -e "${GREEN}Created sample CLAUDE.md:${NC}"
run_show cat "$SCRATCH_DIR/sample-project/.claude/CLAUDE.md"

narrate "Claude reads this file at the start of every session."
narrate "It replaces the need for lengthy onboarding docs -- the AI knows your rules."

pause

# ==========================================================================
# Step 3: Skill Invocation
# ==========================================================================
step 3 "Skill Invocation"

narrate "Skills are reusable prompt+context packages that Claude can load on demand."
narrate "They encode domain expertise: EFA networking, CUDA optimization, K8s deployment, etc."

echo -e "${BOLD}Example skills directory structure:${NC}"
echo "  ~/.claude/skills/"
echo "    efa-srd-ground-truth/     -- EFA SRD protocol rules"
echo "    cuda-kernel-perf/         -- CUDA micro-optimization patterns"
echo "    deepep-dispatch/          -- DeepEP MoE dispatch debugging"
echo "    systematic-debugging/     -- Structured debugging methodology"
echo "    workshop-demo-capture/    -- Terminal recording for demos"
echo ""

narrate "In a Claude Code session, you invoke a skill with a slash command:"
echo -e "${CYAN}  /efa-srd-ground-truth${NC}"
echo -e "${DIM}  Claude loads the skill's context and applies its rules to the conversation.${NC}"
echo ""

narrate "Skills can also be triggered automatically by hooks in settings.json:"
echo -e "${DIM}  Example: PreToolUse hook on Edit triggers 'strategic-compact' skill${NC}"
echo -e "${DIM}  to suggest context compaction at natural breakpoints.${NC}"

echo ""
narrate "Listing some available skills (from the agent-toolkit):"
if [[ -d /home/ubuntu/agent-toolkit/skills ]]; then
    run_show ls /home/ubuntu/agent-toolkit/skills/ 2>/dev/null
else
    echo -e "${DIM}  (agent-toolkit/skills not available on this machine -- showing example)${NC}"
    echo "  efa-srd-ground-truth/  cuda-kernels/  deepep-dispatch/  k8s-deploy/"
fi

pause

# ==========================================================================
# Step 4: Multi-Model Query
# ==========================================================================
step 4 "Multi-Model Query (Parallel Dispatch)"

narrate "The agent toolkit can dispatch the same prompt to multiple frontier LLMs."
narrate "Models: GPT-5.4, Gemini 3 Pro, Claude Opus 4.6 via Bedrock."
narrate "This enables cross-model validation and consensus-driven answers."

echo -e "${BOLD}Architecture:${NC}"
echo ""
echo "  +-------------+     +----------------+"
echo "  | Your Prompt |---->| dispatch-all.sh|"
echo "  +-------------+     +-------+--------+"
echo "                              |"
echo "               +--------------+--------------+"
echo "               |              |              |"
echo "          +----v----+   +----v-----+   +----v------+"
echo "          | GPT-5.4 |   |Gemini 3  |   |Claude Opus|"
echo "          | (OpenAI)|   |Pro(Google)|   |4.6 (AWS)  |"
echo "          +----+----+   +----+-----+   +----+------+"
echo "               |              |              |"
echo "               +--------------+--------------+"
echo "                              |"
echo "                     +--------v--------+"
echo "                     |  Compare/Merge  |"
echo "                     +-----------------+"
echo ""

narrate "Example dispatch command:"
echo -e "${CYAN}  \$ query-model.sh gemini-3-pro \"Explain EFA SRD protocol constraints\"${NC}"
echo -e "${CYAN}  \$ dispatch-all.sh \"What are the pitfalls of GPU-initiated RDMA on EFA?\"${NC}"
echo ""

narrate "Mock demonstration (no real API calls):"
MOCK_PROMPT="Explain why EFA SRD does not support FI_ATOMIC operations"
echo -e "  Prompt: ${BOLD}${MOCK_PROMPT}${NC}"
echo ""
echo -e "  ${GREEN}[gemini-3-pro]${NC} EFA SRD is a connectionless, unordered protocol..."
echo -e "  ${GREEN}[gpt-5.4]${NC}      AWS EFA uses Scalable Reliable Datagram (SRD) which..."
echo -e "  ${GREEN}[claude-opus]${NC}   The EFA provider in libfabric does not expose FI_ATOMIC..."
echo ""
echo -e "  ${BOLD}Consensus:${NC} All 3 models agree -- SRD's unordered delivery makes"
echo -e "  atomic operations impossible since atomics require ordering guarantees."

pause

# ==========================================================================
# Step 5: Parallel Agent Launch
# ==========================================================================
step 5 "Parallel Agent Launch (Sub-Agents)"

narrate "Claude Code can spawn parallel sub-agents for independent tasks."
narrate "Each agent runs in its own context and returns results asynchronously."
narrate "This is ideal for research, code review, and multi-file analysis."

echo -e "${BOLD}Example: Investigating a distributed training hang${NC}"
echo ""
echo "  Main Agent (you)"
echo "    |"
echo "    +-- Sub-Agent 1: efa-specialist"
echo "    |   \"Check EFA HW counters on both nodes\""
echo "    |"
echo "    +-- Sub-Agent 2: cuda-analyzer"
echo "    |   \"Analyze the dispatch kernel for deadlocks\""
echo "    |"
echo "    +-- Sub-Agent 3: troubleshooter"
echo "    |   \"Parse NCCL debug logs for timeout patterns\""
echo "    |"
echo "    +-- Sub-Agent 4: moe-expert"
echo "        \"Verify expert parallelism config vs token count\""
echo ""

narrate "In Claude Code, you would say:"
echo -e "${CYAN}  \"Launch 4 parallel agents to investigate this training hang:${NC}"
echo -e "${CYAN}   1) Check EFA counters, 2) Analyze CUDA kernel,${NC}"
echo -e "${CYAN}   3) Parse NCCL logs, 4) Verify MoE config\"${NC}"
echo ""

narrate "Each agent runs independently and reports back."
narrate "The main agent synthesizes their findings into a diagnosis."

echo ""
echo -e "${BOLD}CLI patterns for agent workflows:${NC}"
echo ""
echo -e "  ${CYAN}# Worktree-isolated session (for experimental patches)${NC}"
echo -e "  ${CYAN}claude --worktree feature-x \"implement the CPU RDMA dispatch\"${NC}"
echo ""
echo -e "  ${CYAN}# Named session for resumability${NC}"
echo -e "  ${CYAN}claude --name \"dispatch-opt\" --continue${NC}"
echo ""
echo -e "  ${CYAN}# Background non-interactive analysis${NC}"
echo -e "  ${CYAN}claude -p --print \"analyze this file\" < kernel.cu${NC}"

pause

# ==========================================================================
# Summary
# ==========================================================================
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Part 1 Complete: Agentic Coding${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo -e "  Key takeaways:"
echo -e "    1. ${BOLD}CLAUDE.md${NC} -- project-level AI instructions"
echo -e "    2. ${BOLD}Skills${NC} -- reusable domain expertise packages"
echo -e "    3. ${BOLD}Multi-model${NC} -- cross-validate with GPT-5.4, Gemini, Claude"
echo -e "    4. ${BOLD}Sub-agents${NC} -- parallelize research and analysis"
echo -e "    5. ${BOLD}Hooks${NC} -- automate quality checks via settings.json"
echo ""
echo -e "  Next: ${CYAN}02-demo-dynamo-deploy.sh${NC} -- Deploy Dynamo on EKS"
echo ""
