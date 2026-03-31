#!/bin/bash
set -euo pipefail

# =============================================================================
# Demo 4: HPC Kernel Optimization with AI Agents
# Narrated live demo - run commands interactively
# =============================================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

narrate() { echo -e "\n${BLUE}>>> $1${NC}\n"; }
step()    { echo -e "${GREEN}[STEP]${NC} $1"; }
pause()   { echo -e "${YELLOW}[Press Enter to continue]${NC}"; read -r; }

narrate "HPC Kernel Optimization with AI Agents - Live Demo"
echo "This demo shows how Markdown Skills + MCP Servers + Multi-LLM"
echo "consensus work together to optimize GPU kernels."
pause

# --- Step 1: Show the Skills System ---
narrate "Step 1: The Skills System"
step "Skills are markdown files that encode expert methodology"
echo ""
echo "Example skills relevant to HPC optimization:"
echo "  - efa-srd-ground-truth     (corrects LLM hallucinations about EFA)"
echo "  - systematic-debugging      (enforces hypothesis-driven approach)"
echo "  - cuda-kernel-perf-patterns (CUDA micro-optimization recipes)"
echo "  - deepep-dispatch-antipatterns (prevents known failure modes)"
echo ""
step "Each skill has: trigger conditions, checklists, ground truth data"
pause

# --- Step 2: MCP Servers ---
narrate "Step 2: MCP Servers in Action"
step "14 MCP servers provide tools to the AI agent:"
echo ""
printf "  %-22s | %s\n" "Server" "Purpose"
printf "  %-22s-|-%s\n" "----------------------" "----------------------------------------"
printf "  %-22s | %s\n" "zoekt-search" "Trigram code search across repos"
printf "  %-22s | %s\n" "cplusplus-analysis" "C++ static analysis for CUDA"
printf "  %-22s | %s\n" "nccl-log-parser" "Parse NCCL debug logs"
printf "  %-22s | %s\n" "k8s-gpu" "Kubernetes GPU operations"
printf "  %-22s | %s\n" "efa-env-preflight" "EFA configuration validation"
printf "  %-22s | %s\n" "litellm-proxy" "Multi-model gateway"
printf "  %-22s | %s\n" "semantic-scholar" "Academic paper search"
printf "  %-22s | %s\n" "ragflow-query" "RAG over internal documentation"
pause

# --- Step 3: Multi-Model Dispatch ---
narrate "Step 3: Multi-LLM Consensus"
step "Same prompt sent to 3 frontier models, results synthesized"
echo ""
echo "Models: GPT-5.4 (reasoning) + Gemini 3 Pro (1M context) + Claude (deep analysis)"
echo ""
echo "Example usage:"
echo '  $Q gpt-5.4 "Analyze this CUDA kernel for optimization opportunities"'
echo '  $Q gemini-3-pro "Review EFA configuration for P5 deployment"'
echo '  $Q claude-think "Debug this NCCL collective hang"'
pause

# --- Step 4: Agent Workflow ---
narrate "Step 4: Agent Optimization Workflow"
step "The agent receives: 'Optimize MoE dispatch kernel for EFA'"
echo ""
echo "What happens automatically:"
echo "  1. Skills auto-trigger: loads EFA ground truth, checks anti-patterns"
echo "  2. MCP servers activate: code search finds relevant implementations"
echo "  3. Multi-LLM consensus: 3 models analyze independently"
echo "  4. Sub-agents investigate in parallel:"
echo "     - CUDA analyzer: kernel launch bounds, memory coalescing"
echo "     - EFA specialist: RDMA write ordering, signal delivery"
echo "     - Performance optimizer: benchmark before/after"
echo "  5. Agent synthesizes findings and implements changes"
echo "  6. Verification: automated benchmarks confirm improvement"
pause

# --- Step 5: Creating Your Own Skills ---
narrate "Step 5: Creating Domain-Specific Skills"
step "Skill template structure:"
cat <<'TEMPLATE'

  ---
  name: my-optimization-skill
  description: One-line description for relevance matching
  ---

  ## When to Use
  - Trigger condition 1
  - Trigger condition 2

  ## Ground Truth
  Facts that LLMs commonly get wrong about your domain.

  ## Checklist
  1. Step-by-step methodology
  2. Each step is actionable
  3. Include verification criteria

  ## Anti-Patterns
  Known mistakes to avoid.
TEMPLATE
pause

narrate "Demo Complete"
echo "Key takeaway: Skills + MCP Servers + Multi-LLM = Automated HPC Expertise"
echo ""
echo "Resources:"
echo "  - reference/skills-examples/    (example skills)"
echo "  - reference/mcp-configs/        (MCP configuration)"
echo "  - reference/agent-configs/      (agent team setup)"
