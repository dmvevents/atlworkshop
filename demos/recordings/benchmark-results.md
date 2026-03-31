# Workshop Benchmark Results

## Qwen2.5-Coder-7B-Instruct on NVIDIA Dynamo (P4d.24xlarge)

**Hardware:** 1x NVIDIA A100 40GB (P4d.24xlarge)
**Backend:** vLLM via NVIDIA Dynamo v0.9.0
**Deployment:** DynamoGraphDeployment (Frontend + Worker)

### GenAI-Perf Results (Concurrency=1)

| Metric | avg | min | max | p99 | p90 | p75 |
|--------|-----|-----|-----|-----|-----|-----|
| Time To First Token (ms) | 49.36 | 42.54 | 75.80 | 73.96 | 57.36 | 50.61 |
| Time To Second Token (ms) | 2.57 | 0.00 | 13.72 | 12.83 | 4.87 | 3.37 |
| Request Latency (ms) | 822.14 | 734.19 | 884.13 | 882.17 | 864.51 | 837.00 |
| Inter Token Latency (ms) | 12.40 | 12.20 | 12.87 | 12.86 | 12.83 | 12.47 |
| Output Token Throughput/User (tok/s) | 80.65 | 77.72 | 81.97 | 81.97 | 81.96 | 81.57 |
| Output Sequence Length (tokens) | 63.30 | 57.00 | 64.00 | 64.00 | 64.00 | 64.00 |
| Input Sequence Length (tokens) | 131.00 | 114.00 | 140.00 | 139.91 | 139.10 | 137.00 |
| Output Token Throughput (tok/s) | 76.80 | — | — | — | — | — |
| Request Throughput (req/s) | 1.21 | — | — | — | — | — |

### GenAI-Perf Results (Concurrency=4)

| Metric | avg | min | max | p99 | p90 | p75 |
|--------|-----|-----|-----|-----|-----|-----|
| Time To First Token (ms) | 60.18 | 19.43 | 99.25 | 99.21 | 88.28 | 72.02 |
| Inter Token Latency (ms) | 12.87 | 12.49 | 13.38 | 13.37 | 13.23 | 12.91 |
| Output Token Throughput (tok/s) | 283.00 | — | — | — | — | — |
| Request Throughput (req/s) | 4.61 | — | — | — | — | — |

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
