# Module 7: AI-Powered HPC Kernel Optimization

**Duration:** 15 minutes (live demo)
**Format:** Instructor-led demonstration
**Prerequisites:** Modules 1-2 (agentic coding fundamentals, MCP servers)

---

## Overview

This module is the product showcase. You will see a production agent stack --
220+ markdown skills, 14 MCP servers, multi-LLM consensus, and specialized
sub-agents -- applied to one of the hardest problems in cloud computing:
optimizing GPU kernels for distributed training over high-speed networking.

---

## 1. The Problem

Optimizing GPU kernels for distributed training requires simultaneous expertise
across domains that rarely overlap:

| Domain | Example Questions |
|--------|-------------------|
| **CUDA kernels** | Should this store use `st.global.wb` or `st.global.wt`? What launch bounds minimize register pressure? |
| **EFA/RDMA networking** | Does EFA SRD guarantee write ordering? What is the QP budget on a P5.48xlarge? |
| **Distributed systems** | How do we synchronize a MoE dispatch across 16 nodes without a global barrier? |
| **Kubernetes** | Why is this pod falling back to TCP instead of RDMA? Is the EFA device plugin mounted? |

A single optimization pass might touch all four domains. A human expert in CUDA
may not know that EFA SRD delivers RDMA writes out of order, leading to a
"working" kernel that silently corrupts data at scale. A networking expert may
not realize that `ld_volatile_global` bypasses L1 but not L2 on H100 (sm_90),
causing stale reads from RDMA-written buffers.

Most teams do not have this breadth of expertise in-house. The result: weeks of
debugging cycles, known anti-patterns rediscovered the hard way, and
optimizations that work on InfiniBand but break silently on EFA.

---

## 2. The Solution: An AI-Powered HPC Agent Stack

The HPC Agent Stack combines four capabilities into a single Claude Code
environment:

```
                  +----------------------------------------------+
                  |            Claude Code Session                |
                  |                                               |
                  |  +------------------+  +------------------+   |
                  |  |  220+ Markdown   |  |  14 MCP Servers  |   |
                  |  |  Skills          |  |  (code search,   |   |
                  |  |  (methodology,   |  |   static analysis,|  |
                  |  |   ground truth,  |  |   log parsing,   |   |
                  |  |   anti-patterns) |  |   K8s ops)       |   |
                  |  +------------------+  +------------------+   |
                  |                                               |
                  |  +------------------+  +------------------+   |
                  |  | Multi-LLM        |  | Specialized       |  |
                  |  | Consensus        |  | Sub-Agents        |  |
                  |  | (GPT-5.4 +       |  | (CUDA analyzer,   |  |
                  |  |  Gemini 3 Pro +  |  |  EFA specialist,  |  |
                  |  |  Claude)         |  |  perf optimizer)  |  |
                  |  +------------------+  +------------------+   |
                  +----------------------------------------------+
```

### Component Summary

| Component | Count | Purpose |
|-----------|-------|---------|
| Markdown Skills | 220+ | Structured methodology documents with trigger conditions, checklists, and ground truth |
| MCP Servers | 14 | Tool servers for code search, static analysis, log parsing, K8s operations |
| LLM Models | 3 | GPT-5.4, Gemini 3 Pro, Claude for independent cross-validation |
| Sub-Agents | 23 | Specialized agents (CUDA, EFA, troubleshooting, MoE, performance) |

---

## 3. How Markdown Skills Work

Skills are structured markdown documents that encode expert methodology. They
are not prompts -- they are methodology specifications with trigger conditions,
checklists, ground truth assertions, and ban lists of known failures.

### Anatomy of a Skill

Every skill follows this structure:

```markdown
---
name: skill-name
description: When to trigger this skill
---

# Skill Title

## Overview
What problem this solves and why guessing fails.

## When to Use
Specific trigger conditions (error messages, task types, failure patterns).

## The Process
Step-by-step methodology with checkpoints.

## Ground Truth
Verified facts that override LLM hallucinations.

## Anti-Patterns / Ban List
Approaches proven to fail -- never try these again.

## Verification
How to confirm the fix actually worked.
```

### Example: `efa-srd-ground-truth`

This skill injects verified hardware facts into every EFA-related conversation,
preventing the most common LLM hallucinations about AWS networking:

```markdown
---
name: efa-srd-ground-truth
description: >
  Use when sending ANY prompt about EFA, RDMA, libfabric, fi_writemsg,
  signal ordering, or counter synchronization on AWS
---

# EFA SRD Ground Truth (P5.48xlarge, verified)

## Immutable Facts
- NO FI_ATOMIC support on EFA (unlike InfiniBand)
- NO message ordering (max_order_waw_size=0)
- CQ completion is LOCAL (sender-side, NOT remote delivery confirmation)
- Single RDMA WRITE <= 8KB = one SRD packet = atomic delivery
- WriteCombined memory: GPU->CPU direction NEEDS WC; NIC->GPU MUST NOT have WC
- CPU->GPU polling: use ld.global.nc (bypasses L2 cache)
- ld_volatile_global bypasses L1 only, NOT L2 on H100 sm_90

## Why This Matters
Every frontier LLM (GPT-5.4, Gemini, Claude) will hallucinate that
EFA supports atomic operations and ordered writes -- because most RDMA
training data describes InfiniBand. Without this ground truth injection,
the agent will suggest fi_atomic calls that silently fail and ordering
assumptions that cause data corruption.
```

### Example: `systematic-debugging`

This skill enforces hypothesis-driven debugging instead of random fix attempts:

```markdown
---
name: systematic-debugging
description: >
  Use when encountering any bug, test failure, or unexpected behavior,
  before proposing fixes
---

# The Iron Law
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.
If you have not completed Phase 1, you cannot propose fixes.

# The Four Phases
1. Root Cause Investigation - read errors, reproduce, trace data flow
2. Pattern Analysis - find working examples, compare differences
3. Hypothesis and Testing - one variable at a time, test minimally
4. Implementation - failing test first, single fix, verify

# Red Flags (STOP and return to Phase 1)
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- Proposing solutions before tracing data flow
- 3+ fixes failed -> question the architecture, not the symptoms
```

### Example: `deepep-dispatch-antipatterns`

This skill contains a ban list of approaches proven to fail during 89+
optimization iterations on DeepEP MoE dispatch:

```markdown
---
name: deepep-dispatch-antipatterns
description: >
  Use when debugging DeepEP dispatch or combine on EFA, when about to
  try a new optimization approach, when a timeout occurs
---

# Ban List (never try these again)
- ld_nc_ca_global for RX polling (broke delivery: v77, v80)
- st_na_global for Phase 2 metadata (broke epoch: v80d)
- Removing WC from meta_ready/tail_ready (GPU->CPU needs WC: v81d)
- ibv_wr_set_inline_data on RDMA WRITE WITH IMM (EINVAL on EFA)
- break without outer-loop gave_up flag (infinite hang)

# Attempt Registry (last 10 iterations)
| Version | Hypothesis | Change | Result | Verdict |
|---------|-----------|--------|--------|---------|
| v85a | Scoped fence | __threadfence_block -> _system | 12% improvement | confirmed |
| v84c | Double buffer | Alternate staging buffers | No change | falsified |
| ... | ... | ... | ... | ... |
```

### Why Skills Beat Prompts

| Approach | Problem |
|----------|---------|
| Long system prompts | Context window fills up; LLM ignores instructions buried in 40K tokens |
| RAG over docs | Retrieves fragments without methodology; no ban lists or checklists |
| Fine-tuning | Expensive; can not update when new failure patterns are discovered |
| **Markdown Skills** | **Loaded on-demand by trigger condition; compact; include ban lists and ground truth; version-controlled in git** |

---

## 4. MCP Servers in Action

The 14 MCP servers provide tool access that goes beyond what file search and
grep can achieve:

### Server Inventory

| Server | Port | What It Does |
|--------|------|-------------|
| **zoekt-search** | 6070 | Trigram code search across indexed HPC repositories. Finds symbol references in milliseconds across millions of lines. |
| **opengrok-search** | 8080 | Symbol cross-referencing with definition/usage tracking. "Where is this function defined? Who calls it?" |
| **cplusplus-analysis** | local | libclang-based C++ static analysis. Class hierarchies, call graphs, function signatures -- semantic understanding, not grep. |
| **nccl-log-parser** | local | Parses `NCCL_DEBUG=TRACE` output to detect transport issues, topology problems, plugin loading failures, and collective operation performance. |
| **k8s-gpu** | local | Kubernetes GPU operations: deploy pods, check EFA device mounts, read GPU health, monitor training jobs. |
| **codegraph-context** | local | Call chain analysis across function boundaries. Traces data flow through multi-layer systems. |
| **efa-env-preflight** | local | Validates EFA environment before deployment: provider detection, NCCL plugin verification, device mount checks. |
| **gdb-debug** | local | Automated GDB sessions for debugging CUDA kernels and C++ networking code. |
| **semantic-scholar** | API | Academic paper search for HPC optimization techniques and networking research. |
| **tavily-search** | API | Web search for GitHub issues, StackOverflow answers, and vendor documentation. |
| **ragflow-query** | 9380 | RAG over 47+ internal EFA/NCCL/CUDA documents. |
| **litellm-proxy** | 4000 | Multi-model gateway providing access to 300+ LLMs with unified API. |
| **openrouter-gateway** | API | Alternative multi-model routing for cross-validation queries. |
| **abi-checker** | local | Binary ABI compatibility checking for shared libraries. |

### Demo: Zoekt Trigram Code Search

The agent needs to find every place in DeepEP that calls `fi_writemsg`:

```
Agent: "Search for fi_writemsg across all indexed repositories"

zoekt-search result (23ms):
  deepep/csrc/kernels/internode.cu:847    fi_writemsg(ep, &msg, FI_REMOTE_CQ_DATA)
  deepep/csrc/kernels/internode.cu:912    fi_writemsg(ep, &msg, FI_DELIVERY_COMPLETE)
  nccl-gin/src/transport.c:1203           fi_writemsg(rail->ep, &msg, flags)
  nixl/src/libfabric_plugin.cpp:445       fi_writemsg(endpoint_, &msg, 0)
```

Compare with grep: grep must scan every file sequentially. Zoekt uses
pre-built trigram indexes and returns results in milliseconds regardless
of repository size.

### Demo: C++ Static Analysis

The agent needs to understand the class hierarchy for the dispatch kernel:

```
Agent: "Get the class hierarchy for DispatchKernel"

cplusplus-analysis result:
  DispatchKernel
    -> inherits from: KernelBase
    -> members: num_experts_, topk_, dispatch_buffer_
    -> methods: launch(), configure(), validate_config()
    -> called by: MoELayer::forward(), InterNodeDispatch::run()
    -> calls: cuda_dispatch_kernel<<<>>>, nvshmem_put_signal()
```

### Demo: NCCL Log Parser

Training hangs after 100 iterations. The agent parses the NCCL debug log:

```
Agent: "Parse this NCCL log for transport issues"

nccl-log-parser result:
  WARNING: TCP fallback detected on rank 4
    - NET/Socket transport in use (expected NET/OFI with EFA)
    - Cause: NCCL_NET_PLUGIN not set, aws-ofi-nccl.so not in LD_LIBRARY_PATH
    - Impact: 10-50x bandwidth reduction on affected ranks

  INFO: Ring topology detected, 8 channels
    - Channel 0-3: NVLink (intra-node)
    - Channel 4-7: NET/Socket (SHOULD be EFA)

  RECOMMENDATION: Set NCCL_NET_PLUGIN=ofi and verify EFA device mounts
```

---

## 5. Live Demo: Optimizing a MoE Dispatch Kernel

This is the core demo. We walk through an end-to-end optimization session
where the agent optimizes a Mixture-of-Experts dispatch kernel for EFA
on AWS P5.48xlarge instances.

### The Task

```
Human: "The MoE dispatch kernel is hitting 340us latency on EFA.
The target is 214us (matching the pplx-kernels reference).
Optimize it."
```

### Step 1: Skills Auto-Trigger

The agent recognizes key terms ("MoE dispatch", "EFA", "kernel", "optimize")
and automatically loads relevant skills:

```
[skill loaded] efa-srd-ground-truth
  -> Injecting EFA hardware constraints into context

[skill loaded] deepep-dispatch-antipatterns
  -> Loading ban list of 47 proven failures

[skill loaded] bound-optimization-ceiling
  -> Calculating theoretical minimum latency

[skill loaded] measure-before-theorize
  -> Requiring baseline measurements before any changes
```

### Step 2: Baseline Measurement

Following the `measure-before-theorize` skill, the agent collects data
before proposing any changes:

```
Agent uses k8s-gpu MCP server:
  -> kubectl exec into training pod
  -> Run dispatch benchmark: 340us average, 380us p99
  -> Collect EFA hardware counters:
     /sys/class/infiniband/rdmap0s6/ports/1/hw_counters/
     tx_pkts: 1,247,832   rx_pkts: 1,247,830 (2 drops)
     rdma_read_bytes: 0   rdma_write_bytes: 847,291,648
```

### Step 3: Multi-LLM Consensus Analysis

The agent dispatches the same focused question to three models independently:

```bash
# Three models analyze in parallel
Q=$HPC_STACK_ROOT/scripts/multi-model/query-model.sh

$Q gpt-5.4 "$PROMPT" > /tmp/gpt54.txt &
$Q gemini-3-pro "$PROMPT" > /tmp/gemini.txt &
$Q claude-think "$PROMPT" > /tmp/bedrock.txt &
wait
```

The prompt follows the 4-layer template:

```
LAYER A: Immutable Facts (EFA SRD ground truth)
LAYER B: Attempt Registry (ban list of 47 failures)
LAYER C: Current State (340us baseline, EFA counters, source diff)
LAYER D: Focused Question ("What is the highest-impact single change
         to reduce dispatch latency, given these constraints?")
```

Results from three models:

| Model | Recommendation | Confidence |
|-------|---------------|------------|
| GPT-5.4 | Replace per-operation fence with scoped fence (`__threadfence_block`) | High |
| Gemini 3 Pro | Batch RDMA writes (4 small writes -> 1 coalesced write under 8KB) | High |
| Claude | Replace `ld_volatile_global` with `ld.global.nc` for RDMA target polling | High |

The `consensus-synthesizer` agent combines findings:

```
CONSENSUS: All three changes are independent and non-conflicting.
  - Scoped fence: reduces GPU synchronization overhead
  - Write batching: reduces EFA doorbell rings (each has ~2us overhead)
  - Cache bypass load: prevents stale L2 reads of RDMA-written buffers

CONFLICT CHECK: None. Apply in order of expected impact.
BAN LIST CHECK: None of these appear in the anti-pattern registry.
GROUND TRUTH CHECK: ld.global.nc is correct for NIC->GPU direction (confirmed).
```

### Step 4: Parallel Sub-Agent Investigation

The agent launches specialized sub-agents to investigate in parallel:

```
[cuda-analyzer]     Analyzing kernel register pressure and occupancy
[efa-specialist]    Checking QP budget and multi-rail configuration
[perf-optimizer]    Profiling the CPU proxy loop for bottlenecks
[moe-expert]        Validating expert parallelism configuration
```

Each sub-agent runs in an isolated context and reports back:

```
cuda-analyzer:
  Current: 48 registers/thread, 75% occupancy
  With scoped fence: 44 registers/thread, 87% occupancy (+16%)

efa-specialist:
  QP budget: using 412 of 512 QPs (80% -- near limit)
  Recommendation: share endpoints across channels (efa-endpoint-sharing skill)

perf-optimizer:
  CPU proxy loop: 8us per iteration (2us in CQ poll, 6us in sched_yield)
  Recommendation: remove sched_yield, pin to dedicated core

moe-expert:
  Expert config valid. 64 experts, top-2, 8-way EP.
  No divisibility issues.
```

### Step 5: Implementation and Verification

The agent implements changes one at a time (following `systematic-debugging`):

```
Change 1: Scoped fence
  Before: 340us   After: 298us   Delta: -42us (12.4%)

Change 2: Write batching
  Before: 298us   After: 261us   Delta: -37us (12.4%)

Change 3: Cache bypass loads
  Before: 261us   After: 238us   Delta: -23us (8.8%)

Change 4: CPU proxy core pinning (from perf-optimizer)
  Before: 238us   After: 221us   Delta: -17us (7.1%)

Total: 340us -> 221us (35% reduction)
Target: 214us -- within 3.3% of pplx-kernels reference
```

### What Made This Work

1. **Ground truth prevented wrong turns** -- without `efa-srd-ground-truth`, the
   agent would have tried `fi_atomic` (which does not exist on EFA) and assumed
   write ordering (which EFA SRD does not provide).

2. **Ban list saved hours** -- the anti-pattern registry contained 47 approaches
   already proven to fail. Without it, the agent would have tried
   `ld_nc_ca_global` for RX polling (which broke delivery in v77 and v80).

3. **Multi-LLM consensus caught blind spots** -- no single model suggested all
   four changes. Cross-validation produced a more complete optimization plan.

4. **Parallel sub-agents reduced wall-clock time** -- four investigations that
   would take 30 minutes sequentially completed in 8 minutes.

---

## 6. Creating Your Own Skills

You can create domain-specific skills for any area of expertise. Here is the
template:

### Skill Template

```markdown
---
name: your-skill-name
description: >
  One sentence: when should this skill trigger?
  Include specific error messages, task types, or keywords.
---

# Your Skill Title

## Overview
What problem does this solve? Why do LLMs get it wrong without this skill?
(2-3 sentences maximum)

## When to Use
- Specific trigger condition 1
- Specific trigger condition 2
- Specific error message or pattern

## Ground Truth
Facts that LLMs commonly hallucinate about in this domain:
- Verified fact 1 (cite source: documentation URL, test result, hardware spec)
- Verified fact 2
- Verified fact 3

## Process
### Step 1: [Name]
What to do first. Be specific -- include exact commands or checks.

### Step 2: [Name]
What to do next. Include expected outputs.

### Step 3: [Name]
...

## Anti-Patterns (Ban List)
Approaches proven to fail. Include WHY they fail:
- Do NOT do X (fails because Y -- discovered in iteration Z)
- Do NOT do X (causes Y on platform Z)

## Verification
How to confirm the fix worked:
- [ ] Check 1
- [ ] Check 2
- [ ] Check 3
```

### Best Practices for Skill Authors

1. **Keep skills focused.** One skill per problem domain. A skill that covers
   "everything about CUDA" is too broad. A skill that covers "CUDA store/load
   instruction selection for RDMA target buffers" is the right granularity.

2. **Include the ban list.** This is the highest-value section. Every failed
   approach you document saves the next user hours of debugging.

3. **Cite sources.** Ground truth must reference specific documentation, test
   results, or hardware specifications. "EFA does not support atomics" must
   link to the libfabric provider capabilities query or the `fi_info` output.

4. **Version your iterations.** When optimizing, keep an attempt registry so
   the skill accumulates knowledge over time instead of repeating failures.

5. **Test the trigger description.** The `description` field in the frontmatter
   determines when Claude loads the skill. Make it specific enough to trigger
   on the right tasks but not so broad that it loads on every conversation.

### Registering Skills in Claude Code

Skills are registered in your Claude Code settings. Add them to the
`mcpServers` section or as project-level skill directories:

```json
{
  "permissions": {
    "allow": ["skill:*"]
  },
  "skills": {
    "directories": [
      "/path/to/your/skills"
    ]
  }
}
```

Or place skill files in your project's `.claude/skills/` directory and they
will be discovered automatically.

---

## 7. MCP Server Configuration Reference

Here is a representative configuration showing how MCP servers are registered
with Claude Code:

```json
{
  "mcpServers": {
    "zoekt-search": {
      "command": "node",
      "args": ["server.js"],
      "cwd": "/path/to/mcp-servers/zoekt-search",
      "env": {
        "ZOEKT_INDEX_DIR": "${HOME}/.zoekt",
        "ZOEKT_LISTEN": ":6070"
      }
    },
    "cplusplus-analysis": {
      "command": "python",
      "args": ["-m", "mcp_server.cpp_mcp_server"],
      "cwd": "/path/to/mcp-servers/cplusplus-analysis",
      "env": {
        "PYTHONPATH": "/path/to/mcp-servers/cplusplus-analysis"
      }
    },
    "nccl-log-parser": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "/path/to/mcp-servers/nccl-log-parser"
    },
    "k8s-gpu": {
      "command": "go-k8s-gpu-server",
      "args": ["--kubeconfig", "${HOME}/.kube/config"],
      "cwd": "/path/to/mcp-servers/k8s-gpu"
    }
  }
}
```

### Adding a New MCP Server

An MCP server is any process that speaks the Model Context Protocol over
stdio. The minimum implementation:

1. **Define tools** -- each tool has a name, description, and JSON schema for
   parameters.
2. **Handle requests** -- the server receives tool invocations and returns
   results.
3. **Register in settings** -- add the server to your Claude Code or Codex CLI
   configuration.

Frameworks: `fastmcp` (Python), `@modelcontextprotocol/sdk` (TypeScript),
or raw JSON-RPC over stdio in any language.

---

## Key Takeaways

- **Skills encode methodology, not just knowledge.** Ban lists, attempt
  registries, and ground truth injection prevent the agent from repeating
  known failures.
- **MCP servers provide semantic tool access.** Static analysis, log parsing,
  and K8s operations go far beyond what grep and file reading can achieve.
- **Multi-LLM consensus catches blind spots.** No single model has complete
  knowledge of HPC systems. Cross-validation with 3 models produces more
  complete analysis.
- **Parallel sub-agents reduce wall-clock time.** Independent investigations
  run simultaneously instead of sequentially.
- **This pattern is domain-agnostic.** Replace EFA/CUDA skills with skills
  for your domain (database optimization, compiler tuning, network security)
  and the same architecture applies.

---

## Further Reading

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [FastMCP Python Framework](https://github.com/jlowin/fastmcp)
- [Zoekt Code Search](https://github.com/sourcegraph/zoekt)

---

**Next module:** [Module 8 - Scaling to Production](../08-scaling-production/README.md)
