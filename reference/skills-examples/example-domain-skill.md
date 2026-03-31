# Example: Domain-Specific Skill

> This is a sanitized reference example showing a domain-specific skill.
> The domain here is GPU performance optimization and multi-model API integration.
> Replace the domain content with your own expertise area.

---
name: gpu-optimization-methodology
description: Use when optimizing GPU kernel performance, when profiling shows unexpected bottlenecks, or when porting code to new GPU architectures
---

# GPU Optimization Methodology

## Overview

Optimization without measurement is guessing. Profile first, form hypotheses, change one variable, measure again.

**Core principle:** MEASURE before you THEORIZE. The bottleneck is rarely where you think it is.

## When to Use

- Starting any performance optimization campaign
- Profiling reveals unexpected bottlenecks
- Porting kernels to new GPU architectures
- Comparing two implementation approaches
- Setting realistic performance targets

## Ground Truth Checklist

Before optimizing, verify your platform constraints:

```
Platform Verification:
- [ ] GPU model and compute capability confirmed
- [ ] Memory bandwidth theoretical peak documented
- [ ] Compute throughput theoretical peak documented
- [ ] PCIe/NVLink bandwidth measured (not assumed)
- [ ] Known hardware limitations documented (e.g., cache coherence model)
```

**Why this matters:** LLMs frequently hallucinate hardware capabilities. Always verify claims against actual hardware specs and `deviceQuery` output.

## The Optimization Loop

### Step 1: Establish Baseline

```bash
# Profile the current implementation
nsys profile --stats=true ./my_application
ncu --set full -o baseline_report ./my_kernel

# Record key metrics
echo "Baseline: throughput=X GB/s, latency=Y ms, occupancy=Z%"
```

**Never skip this step.** Without a baseline, you cannot measure improvement.

### Step 2: Calculate Theoretical Ceiling

Before optimizing, determine the theoretical maximum:

| Metric | Formula | Example |
|--------|---------|---------|
| Memory bandwidth ceiling | HW peak * efficiency factor | 3.35 TB/s * 0.85 = 2.85 TB/s |
| Compute ceiling | FLOPs peak * utilization | 989 TFLOPS * 0.75 |
| Latency floor | Data size / bandwidth | 1 MB / 2.85 TB/s = 0.35 us |

**If your code already achieves 80%+ of theoretical ceiling, further optimization has diminishing returns.**

### Step 3: Identify Bottleneck

Profile output tells you what is actually slow:

| Bottleneck | Symptom | Typical Fix |
|-----------|---------|-------------|
| Memory bound | Low compute utilization, high memory throughput | Reduce data movement, improve locality |
| Compute bound | High occupancy, low memory throughput | Algorithm optimization, precision reduction |
| Latency bound | Low occupancy, low throughput | Increase parallelism, hide latency |
| Launch overhead | Kernel time << launch time | Kernel fusion, persistent kernels |

### Step 4: One Variable at a Time

```
Hypothesis: "Block size 256 -> 512 will improve occupancy from 50% to 75%"
Change: ONLY block size (nothing else)
Predict: "Expect throughput increase from X to ~1.5X"
Measure: Run benchmark with ONLY this change
Record: "Block 512: throughput=1.3X (predicted 1.5X), occupancy=68% (predicted 75%)"
Decide: Keep change? Try different value? Move to different bottleneck?
```

### Step 5: Record Everything

Maintain an experiment journal:

```yaml
experiments:
  - id: opt-001
    date: 2026-03-15
    hypothesis: "Vectorized loads (int4) will improve memory throughput"
    change: "Replace int32 loads with int4 vectorized loads in inner loop"
    baseline: "throughput=1.8 TB/s, latency=2.3ms"
    result: "throughput=2.4 TB/s, latency=1.7ms"
    verdict: confirmed
    notes: "33% improvement. Keep."

  - id: opt-002
    date: 2026-03-15
    hypothesis: "Shared memory tiling will reduce global memory reads"
    change: "Add 32x32 shared memory tile with __syncthreads"
    baseline: "throughput=2.4 TB/s (after opt-001)"
    result: "throughput=2.3 TB/s, latency=1.8ms"
    verdict: falsified
    notes: "Slight regression. Tile overhead > savings for this access pattern."
```

## Common Mistakes

| Mistake | Why It Fails | What To Do Instead |
|---------|-------------|-------------------|
| Optimize without profiling | Fix wrong bottleneck | Profile first with nsys/ncu |
| Change multiple things | Can't attribute improvement | One variable per experiment |
| Compare against wrong baseline | Misleading speedup numbers | Always compare against clean baseline |
| Ignore theoretical ceiling | Chase impossible gains | Calculate ceiling before optimizing |
| Assume LLM hardware claims | LLMs hallucinate specs | Verify on actual hardware |

## Multi-Model Validation Pattern

For complex optimization decisions, query multiple models:

```bash
# Query multiple frontier models in parallel
QUERY="Given this GPU kernel profile [attach profile],
what is the most impactful single optimization?"

./query-model.sh model-a "$QUERY" > /tmp/model-a.txt &
./query-model.sh model-b "$QUERY" > /tmp/model-b.txt &
./query-model.sh model-c "$QUERY" > /tmp/model-c.txt &
wait

# Compare recommendations
# If 2+ models agree on the same optimization -> strong signal
# If models disagree -> need more profiling data
```

**Always include ground truth in prompts to prevent hallucinations:**

```markdown
# GROUND TRUTH (verified on actual hardware)
- GPU: [model], compute capability [X.Y]
- Memory bandwidth measured: [X] TB/s (theoretical: [Y] TB/s)
- Current kernel occupancy: [Z]%
- Bottleneck per profiler: [memory/compute/latency] bound
```

## Quick Reference

| Phase | Action | Output |
|-------|--------|--------|
| Baseline | Profile current code | Metrics: throughput, latency, occupancy |
| Ceiling | Calculate theoretical max | "Best possible is X, we're at Y%" |
| Bottleneck | Analyze profile | "We are [memory/compute/latency] bound" |
| Optimize | One change, measure, record | Experiment journal entry |
| Validate | Compare against baseline | "Change gave X% improvement" |

## Real-World Impact

From optimization campaigns:
- Profiled-first approach: 3-5 targeted experiments to reach 80% of ceiling
- Guess-and-check approach: 15-20 experiments, often optimizing the wrong thing
- Time saved: 2-5x faster to reach same performance level
