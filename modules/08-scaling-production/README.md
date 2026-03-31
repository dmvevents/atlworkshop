# Module 8: Scaling to Production

**Duration:** 5 minutes (wrap-up)
**Format:** Instructor-led discussion

---

## 1. From Experiment to Production

The journey from a working prototype to a production deployment follows a
predictable path. Each stage introduces new constraints:

```
Local Dev          Single GPU         Multi-GPU          Multi-Node         Production
+-----------+     +-----------+     +-------------+    +--------------+   +---------------+
| Laptop    | --> | 1x A100   | --> | 8x H100     | --> | 2+ nodes    | --> | Auto-scaling  |
| CPU only  |     | p3.2xl    |     | p5.48xl     |    | EFA RDMA    |   | Monitoring    |
| Prototype |     | Validate  |     | Parallelize |    | Distribute  |   | Cost controls |
+-----------+     +-----------+     +-------------+    +--------------+   +---------------+

  Concerns:        Does it run      Data parallel?     NCCL transport?    SLA, uptime,
  "Does it work?"  on GPU at all?   Tensor parallel?   EFA vs TCP?        cost per token
```

**Key lesson:** Most failures happen at stage boundaries. A model that trains
on 1 GPU may deadlock at 8 GPUs (NCCL topology). A job that runs on 8 GPUs
may hang at 2 nodes (TCP fallback instead of EFA). Test each transition
explicitly.

---

## 2. Matching Workloads to Architecture

Not every workload needs GPUs, and not every GPU workload needs the same
architecture:

| Workload | Compute Profile | Architecture | AWS Instance | Key Constraint |
|----------|----------------|--------------|-------------|----------------|
| **Coding agents** | CPU-bound, I/O-heavy | Horizontal scale, fast disk | c7i, m7i | Tokens/sec from LLM API, not local GPU |
| **LLM inference** | GPU-bound, memory-bound | Disaggregated prefill/decode (Dynamo) | p5.48xlarge, inf2 | KV cache size, first-token latency |
| **Training** | GPU-bound, network-bound | Tight-coupled multi-node | p5.48xlarge + EFA | Interconnect bandwidth (3.2 Tbps EFA) |
| **Agent + GPU hybrid** | Mixed CPU + GPU | Agents orchestrate GPU jobs | CPU fleet + GPU pool | Agent dispatches to GPU; does not hold GPU idle |

### The NemoClaw Pattern (Agent + GPU Hybrid)

The highest-leverage architecture for production AI systems:

```
  Coding Agent (CPU)                    GPU Cluster
  +-------------------+                +------------------+
  | Claude Code       |  -- submit --> | Training Job     |
  | Plans experiments |                | Runs on 8x H100  |
  | Reads results     |  <-- results - | Returns metrics   |
  | Iterates          |                +------------------+
  +-------------------+
        |
        +-- submit --> Dynamo (Inference)
        +-- submit --> Evaluation Pipeline
```

The agent runs on cheap CPU instances and only claims GPU resources when
running compute. This avoids the common anti-pattern of an agent holding
a $32/hr GPU instance idle while waiting for human input.

---

## 3. Cost Optimization

| Strategy | When to Use | Savings |
|----------|------------|---------|
| **Spot instances** | Experiments, fault-tolerant training with checkpointing | 60-90% vs on-demand |
| **Reserved / Savings Plans** | Steady-state production inference | 30-60% vs on-demand |
| **Right-sizing** | Inference that does not need 8x H100 | Variable -- avoid paying for idle GPUs |
| **Disaggregated inference** | High-throughput serving (Dynamo) | 2-4x better GPU utilization via prefill/decode split |
| **Agent orchestration** | Any workflow with idle-wait periods | Agents on CPU, GPUs only when computing |

**Rule of thumb:** If your GPU utilization is below 70%, you are either
over-provisioned or your architecture has idle-wait bottlenecks that an
agent orchestration pattern can eliminate.

---

## 4. Key Takeaways from the Workshop

**Agentic Coding (Modules 1-4):**
- Claude Code, Codex CLI, and Amazon Q operate as agentic coding systems
  that plan, execute, and verify code changes autonomously
- MCP servers extend agent capabilities with domain-specific tools
- Multi-LLM consensus (querying 3+ models) catches blind spots that any
  single model misses
- Markdown skills encode expert methodology as version-controlled documents
  that prevent known failure patterns

**GPU Infrastructure (Modules 5-6):**
- GPU architecture (SMs, tensor cores, memory hierarchy) determines what
  optimizations are possible
- NVIDIA Dynamo disaggregates prefill and decode for 2-4x better inference
  throughput
- EFA RDMA on P5.48xlarge provides 3.2 Tbps interconnect for distributed
  training -- but requires correct NCCL plugin configuration

**Putting It Together (Modules 7-8):**
- The HPC Agent Stack demonstrates skills + MCP servers + multi-LLM
  consensus applied to real kernel optimization (340us to 221us, 35% reduction)
- Match workloads to architecture: not everything needs GPUs, and agents
  should orchestrate GPU resources rather than hold them idle
- Production readiness = monitoring + cost controls + fault tolerance,
  not just "it works on my cluster"

---

## 5. Resources

### Workshop Projects

| Project | URL |
|---------|-----|
| NVIDIA Dynamo | https://github.com/ai-dynamo/dynamo |
| NVIDIA NIXL | https://github.com/ai-dynamo/nixl |
| NeMo Agent Toolkit | https://github.com/NVIDIA/NeMo-Agent-Toolkit |
| Model Context Protocol | https://modelcontextprotocol.io/ |
| Claude Code | https://docs.anthropic.com/en/docs/claude-code |
| OpenAI Codex CLI | https://github.com/openai/codex |
| Amazon Q Developer | https://aws.amazon.com/q/developer/ |

### AWS GPU References

| Resource | URL |
|----------|-----|
| EC2 P5 Instances | https://aws.amazon.com/ec2/instance-types/p5/ |
| Elastic Fabric Adapter | https://aws.amazon.com/hpc/efa/ |
| EKS GPU Best Practices | https://docs.aws.amazon.com/eks/latest/best-practices/gpu.html |
| SageMaker HyperPod | https://aws.amazon.com/sagemaker/hyperpod/ |

### Frameworks and Libraries

| Resource | URL |
|----------|-----|
| FastMCP (Python MCP framework) | https://github.com/jlowin/fastmcp |
| Zoekt Code Search | https://github.com/sourcegraph/zoekt |
| vLLM | https://github.com/vllm-project/vllm |
| Ray | https://github.com/ray-project/ray |

---

## 6. What's Next

**Immediate next steps:**
- Try building a skill for your own domain (use the template from Module 7)
- Set up one MCP server (Zoekt for code search is the fastest win)
- Run a multi-LLM consensus query on a real problem you are facing

**Advanced topics for deeper exploration:**
- Autonomous agent loops with checkpoint-based recovery
- Agent teams with inter-agent communication for complex workflows
- Custom NCCL plugins for domain-specific collective operations
- GPU fault injection and resilience testing with NVRx
- Worktree isolation for parallel agent experiments on the same codebase

**Community:**
- MCP Server Registry: https://github.com/modelcontextprotocol/servers
- Claude Code Discord and GitHub Discussions
- NVIDIA Developer Forums (Dynamo, NeMo, NCCL)

---

**Thank you for attending Mastering Agentic Coding & GPUs.**

Back to: [Module 7 - HPC Kernel Optimization](../07-hpc-kernel-optimization/README.md)
