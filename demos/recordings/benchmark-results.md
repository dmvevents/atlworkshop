# Workshop Benchmark Results

## Qwen2.5-Coder-7B-Instruct on NVIDIA Dynamo (P4d.24xlarge)

**Hardware:** 1x NVIDIA A100 40GB (P4d.24xlarge)
**Backend:** vLLM via NVIDIA Dynamo v0.9.0
**Deployment:** DynamoGraphDeployment (Frontend + Worker)
**Benchmark Tool:** NVIDIA AIPerf (successor to GenAI-Perf)

### AIPerf Results (Concurrency=1)

| Metric | avg | min | max | p99 | p90 | p75 |
|--------|-----|-----|-----|-----|-----|-----|
| Time to First Token (ms) | 46.81 | 31.08 | 68.59 | 66.89 | 51.61 | 45.01 |
| Time to Second Token (ms) | 3.01 | 0.03 | 20.73 | 19.68 | 10.22 | 0.03 |
| Request Latency (ms) | 797.28 | 535.94 | 861.83 | 858.94 | 832.90 | 820.56 |
| Inter Token Latency (ms) | 12.36 | 12.16 | 12.61 | 12.61 | 12.59 | 12.30 |
| Output Token Throughput/User (tok/s) | 80.94 | 79.28 | 82.27 | 82.23 | 81.92 | 81.31 |
| Output Sequence Length (tokens) | 61.70 | 41.00 | 64.00 | 64.00 | 64.00 | 64.00 |
| Input Sequence Length (tokens) | 122.70 | 114.00 | 133.00 | 132.82 | 131.20 | 120.00 |
| Output Token Throughput (tok/s) | 77.04 | — | — | — | — | — |
| Request Throughput (req/s) | 1.25 | — | — | — | — | — |

### AIPerf Results (Concurrency=4)

| Metric | avg | min | max | p99 | p90 | p50 |
|--------|-----|-----|-----|-----|-----|-----|
| Time to First Token (ms) | 52.19 | 25.26 | 69.89 | 69.88 | 69.82 | 53.88 |
| Time to Second Token (ms) | 14.68 | 12.30 | 24.81 | 24.80 | 24.75 | 12.79 |
| Inter Token Latency (ms) | 12.97 | 12.69 | 13.42 | 13.39 | 13.28 | 12.93 |
| Output Token Throughput (tok/s) | 282.08 | — | — | — | — | — |
| Request Throughput (req/s) | 4.59 | — | — | — | — | — |

### Key Observations

- **TTFT (49ms):** Extremely fast time to first token
- **ITL (12.4ms):** Consistent inter-token latency (~80 tokens/sec per user)
- **Throughput scales linearly:** 76.8 → 283 tok/s at 4x concurrency (3.7x scaling)
- **Dynamo overhead is minimal:** Frontend adds <5ms to request routing

### Inference Quality Tests

**Test 1: Code Generation** - Generated correct async web scraper with aiohttp
**Test 2: Code Review** - Found the `/ vs //` integer division bug AND `pop(0)` inefficiency
**Test 3: First Response** - 145ms end-to-end from client

## Deployment Configuration

```yaml
apiVersion: nvidia.com/v1alpha1
kind: DynamoGraphDeployment
metadata:
  name: qwen-coder
spec:
  services:
    Frontend:
      componentType: frontend
      image: nvcr.io/nvidia/ai-dynamo/vllm-runtime:0.9.0
    QwenCoderWorker:
      componentType: worker
      image: nvcr.io/nvidia/ai-dynamo/vllm-runtime:0.9.0
      resources:
        limits:
          gpu: "1"
          memory: "80Gi"
      args:
        - --model Qwen/Qwen2.5-Coder-7B-Instruct
        - --max-model-len 8192
        - --gpu-memory-utilization 0.85
```

---

## SWE-bench Verified Leaderboard (Open-Source, March 2026)

### Top Open-Source Models for Software Engineering

| Rank | Model | SWE-bench Verified | Parameters | GPU Memory (BF16) |
|------|-------|--------------------|------------|-------------------|
| 1 | KAT-Dev | 62.4% | 32B | ~64GB |
| 2 | CoderForge-Preview | 59.4% | 32B | ~64GB |
| 3 | DeepSWE-Preview | 59.0% | 32.8B | ~66GB |
| 4 | Skywork-SWE-32B | 47.0% | 32B | ~64GB |
| 5 | Devstral-Small | 46.6% | 24B | ~48GB |

### Key Insight

**32B SWE-specialized models outperform 70B general models** on coding tasks.
Fine-tuning on software engineering data (code diffs, test generation, debugging)
produces better results than raw model size.

### Workshop Deployed Models

| Model | Purpose | Node | Status |
|-------|---------|------|--------|
| Qwen2.5-Coder-7B-Instruct | Fast coding assistant, general purpose | Node 2 | Running |
| Devstral-Small-2505 (24B) | SWE specialist, Mistral's coding model | Node 1 | Deploying |
