# Module 6: Disaggregated Inference with NVIDIA Dynamo on EKS

**Duration:** 20 minutes
**Prerequisites:** Module 5 (GPU Foundations), kubectl access to an EKS cluster with GPU nodes
**Goal:** Understand disaggregated LLM inference, deploy NVIDIA Dynamo on EKS, and verify KV cache transfer over EFA RDMA.

---

## 1. What is Disaggregated Inference?

When you send a prompt to an LLM, inference happens in two distinct phases:

**Phase 1 -- Prefill:** Process the entire input prompt in parallel, computing the KV (Key-Value) cache. This is a large matrix multiplication across all input tokens. It is **compute-bound** -- more GPU FLOPS means faster prefill.

**Phase 2 -- Decode:** Generate output tokens one at a time. Each new token requires reading the entire KV cache to compute attention, but only produces a single token. This is **memory-bandwidth-bound** -- faster HBM means faster token generation.

```
Traditional (Unified) Inference:
  Both phases run on the same GPU, one after another.

  [Prompt In] --> |===PREFILL===|---decode---decode---decode--> [Tokens Out]
                  GPU is 100%     GPU is ~10%
                  utilized        utilized (waiting on memory)

Disaggregated Inference:
  Each phase runs on separate, optimized workers.

  [Prompt In] --> |===PREFILL===| --KV Cache Transfer--> |---decode---decode---| --> [Tokens Out]
                  Prefill Worker                          Decode Worker
                  (optimized for compute)                 (optimized for memory BW)
```

### Why Separate Them?

| Aspect | Unified | Disaggregated |
|---|---|---|
| GPU utilization | Low during decode (~10-30%) | Both workers optimized for their phase |
| Scaling | Prefill and decode scale together | Scale each independently based on load |
| Hardware | Same GPU config for both | Can tailor hardware per phase |
| Throughput | Limited by decode bottleneck | Prefill workers feed multiple decode workers |
| TTFT | Blocked if GPU is busy decoding | Prefill always available |

**The practical impact:** A system with 2 prefill workers and 6 decode workers can serve significantly more concurrent users than 8 unified workers, because you are not wasting compute-optimized hardware on memory-bandwidth-bound decode work.

**KV Cache Transfer:** The critical challenge is moving the KV cache from the prefill worker to the decode worker. For a 32B parameter model with 4K context, the KV cache can be ~500 MB. This transfer must be fast enough that it does not negate the benefits of disaggregation. RDMA over EFA achieves 50-100 GB/s, making the transfer nearly instantaneous.

---

## 2. NVIDIA Dynamo Architecture

[NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) is an open-source inference framework built specifically for disaggregated serving. It is inference-engine agnostic, supporting TensorRT-LLM, vLLM, and SGLang as backends.

### Core Components

```
                         +---------------------------+
                         |      Client Requests      |
                         |   (OpenAI-compatible API) |
                         +-------------+-------------+
                                       |
                                       v
                         +-------------+-------------+
                         |      Dynamo Frontend      |
                         |   (HTTP API, no GPU)      |
                         |   Routes requests          |
                         |   Manages sessions         |
                         +------+------------+-------+
                                |            |
                   +------------+            +------------+
                   |                                      |
                   v                                      v
         +---------+----------+               +-----------+---------+
         |  Prefill Worker    |               |   Decode Worker     |
         |                    |               |                     |
         |  - Processes prompt|    NIXL       |  - Generates tokens |
         |  - Generates KV    | KV Cache Xfer|  - Reads KV cache   |
         |  - Compute-bound   +-------------->+  - Memory-bound     |
         |                    |   RDMA/EFA    |                     |
         |  [8x H100 GPUs]   |               |  [8x H100 GPUs]    |
         +---+----------------+               +---+-----------------+
             |                                    |
             +----+-------------------------------+
                  |
         +--------+--------+    +--------+--------+
         |      etcd       |    |      NATS       |
         |  (service disc) |    |  (messaging)    |
         +-----------------+    +-----------------+
```

### How the Components Interact

1. **Frontend** receives an inference request via OpenAI-compatible HTTP API
2. **Frontend** routes the request to an available **Prefill Worker**
3. **Prefill Worker** processes the prompt, generates the KV cache
4. **Prefill Worker** transfers the KV cache to a **Decode Worker** via NIXL (RDMA)
5. **Decode Worker** generates tokens one at a time, streaming them back to the client
6. **etcd** handles service discovery -- workers register themselves on startup
7. **NATS** handles internal messaging between components

### NIXL: The KV Cache Transfer Engine

**NIXL (NVIDIA Inference Xfer Library)** is purpose-built for large bulk transfers of KV cache data between GPUs. It supports two backends:

| Backend | Transport | When to Use |
|---|---|---|
| **LIBFABRIC** | AWS EFA (SRD/RDMA) | AWS instances with EFA (P5, P4d) |
| **UCX** | InfiniBand, RoCE, TCP | On-premises or non-EFA environments |

On AWS with EFA, NIXL uses the LIBFABRIC backend, which calls libfabric's `fi_write` to perform RDMA writes directly from GPU memory to GPU memory -- zero CPU copies, zero kernel transitions.

### DynamoGraphDeployment (DGD) CRD

Dynamo uses a custom Kubernetes resource called **DynamoGraphDeployment** to describe the inference graph:

```yaml
apiVersion: dynamo.nvidia.com/v1alpha1
kind: DynamoGraphDeployment
metadata:
  name: disagg-llm
spec:
  graph:
    frontend:
      replicas: 1
      resources:
        requests:
          cpu: "4"
          memory: "16Gi"
    prefill:
      replicas: 1
      resources:
        requests:
          nvidia.com/gpu: 8
          memory: "128Gi"
          vpc.amazonaws.com/efa: 32
    decode:
      replicas: 1
      resources:
        requests:
          nvidia.com/gpu: 8
          memory: "128Gi"
          vpc.amazonaws.com/efa: 32
```

### Backend Support

| Backend | Disaggregated Serving | KV-Aware Routing | SLA Planner | Multimodal |
|---|:---:|:---:|:---:|:---:|
| **TensorRT-LLM** | Yes | Yes | Yes | Yes |
| **vLLM** | Yes | Yes | Yes | Yes |
| **SGLang** | Yes | Yes | Yes | Yes |

### Component Versions (Dynamo v0.9.0)

| Component | Version |
|---|---|
| Dynamo | v0.9.0 |
| NIXL | 0.9.0 |
| TRT-LLM | 1.3.0rc1 / 1.3.0rc3 |
| vLLM | 0.14.1 |
| CUDA | 13.1 |
| EFA / libfabric | 2.3.1amzn3.0 |

---

## 3. Deploying on EKS with EFA

### Prerequisites

Before deploying Dynamo, your EKS cluster needs:

| Requirement | Why |
|---|---|
| P5.48xlarge (or P4d) nodes | H100 GPUs + EFA NICs |
| EFA device plugin | Exposes `vpc.amazonaws.com/efa` as a schedulable resource |
| GDRCopy DaemonSet | Enables low-latency GPU memory copies for RDMA registration |
| NVIDIA GPU Operator | Exposes `nvidia.com/gpu` and installs drivers |
| kubectl + Helm configured | Deployment tooling |
| HuggingFace token | Model download access |

**Verify EFA devices are available on your nodes:**

```bash
kubectl get nodes -o json | \
  jq '.items[] | {name: .metadata.name, efa: .status.allocatable["vpc.amazonaws.com/efa"]}'
```

Expected output for P5.48xlarge:
```json
{ "name": "ip-10-1-0-174", "efa": "32" }
```

### Step 1: Deploy Infrastructure (etcd + NATS)

Dynamo requires etcd for service discovery and NATS for inter-component messaging.

```bash
# Add the Dynamo Helm repo
helm repo add dynamo https://helm.ngc.nvidia.com/nvidia/dynamo
helm repo update

# Deploy etcd
helm install etcd dynamo/etcd \
  --namespace dynamo-system \
  --create-namespace

# Deploy NATS
helm install nats dynamo/nats \
  --namespace dynamo-system
```

Verify both are running:

```bash
kubectl get pods -n dynamo-system
```

```
NAME                    READY   STATUS    RESTARTS   AGE
etcd-0                  1/1     Running   0          60s
nats-0                  1/1     Running   0          45s
```

### Step 2: Install the Dynamo Operator

The Dynamo operator watches for DynamoGraphDeployment resources and manages the worker pods.

```bash
helm install dynamo-operator dynamo/dynamo-operator \
  --namespace dynamo-system
```

### Step 3: Create Model Configuration

Create a ConfigMap with your model and inference settings:

```yaml
# dynamo-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dynamo-model-config
  namespace: dynamo-inference
data:
  MODEL_ID: "meta-llama/Llama-3.1-8B-Instruct"
  TENSOR_PARALLEL_SIZE: "8"
  MAX_MODEL_LEN: "4096"
  NIXL_BACKEND: "LIBFABRIC"
  FI_PROVIDER: "efa"
  FI_EFA_USE_DEVICE_RDMA: "1"
  FI_HMEM_DISABLE_P2P: "1"
```

```bash
kubectl create namespace dynamo-inference
kubectl apply -f dynamo-config.yaml
```

### Step 4: Deploy Single-Node Disaggregated Inference

Start with both prefill and decode on the same node to verify the pipeline works before adding cross-node complexity:

```yaml
# dynamo-single-node.yaml
apiVersion: dynamo.nvidia.com/v1alpha1
kind: DynamoGraphDeployment
metadata:
  name: llm-disagg
  namespace: dynamo-inference
spec:
  graph:
    frontend:
      replicas: 1
      containers:
      - name: frontend
        resources:
          requests:
            cpu: "4"
            memory: "16Gi"
    prefill:
      replicas: 1
      containers:
      - name: prefill
        envFrom:
        - configMapRef:
            name: dynamo-model-config
        resources:
          requests:
            nvidia.com/gpu: 8
            memory: "128Gi"
    decode:
      replicas: 1
      containers:
      - name: decode
        envFrom:
        - configMapRef:
            name: dynamo-model-config
        resources:
          requests:
            nvidia.com/gpu: 8
            memory: "128Gi"
```

```bash
kubectl apply -f dynamo-single-node.yaml
```

### Step 5: Cross-Node with NIXL LIBFABRIC over EFA RDMA

For cross-node operation, add EFA device requests so NIXL can use RDMA for KV cache transfer:

```yaml
# dynamo-cross-node.yaml
apiVersion: dynamo.nvidia.com/v1alpha1
kind: DynamoGraphDeployment
metadata:
  name: llm-disagg-efa
  namespace: dynamo-inference
spec:
  graph:
    frontend:
      replicas: 1
      containers:
      - name: frontend
        resources:
          requests:
            cpu: "4"
            memory: "16Gi"
    prefill:
      replicas: 1
      containers:
      - name: prefill
        envFrom:
        - configMapRef:
            name: dynamo-model-config
        resources:
          requests:
            nvidia.com/gpu: 8
            memory: "128Gi"
            vpc.amazonaws.com/efa: 32
          limits:
            nvidia.com/gpu: 8
            memory: "128Gi"
            vpc.amazonaws.com/efa: 32
    decode:
      replicas: 1
      containers:
      - name: decode
        envFrom:
        - configMapRef:
            name: dynamo-model-config
        resources:
          requests:
            nvidia.com/gpu: 8
            memory: "128Gi"
            vpc.amazonaws.com/efa: 32
          limits:
            nvidia.com/gpu: 8
            memory: "128Gi"
            vpc.amazonaws.com/efa: 32
```

The key difference: `vpc.amazonaws.com/efa: 32` requests all 32 EFA devices on P5.48xlarge, enabling NIXL to use RDMA for KV cache transfer between nodes.

```bash
kubectl apply -f dynamo-cross-node.yaml
```

---

## 4. KV Cache Transfer Deep Dive

### NIXL LIBFABRIC vs UCX

| Aspect | LIBFABRIC (EFA) | UCX |
|---|---|---|
| Transport | AWS SRD over EFA | InfiniBand, RoCE, or TCP |
| Best environment | AWS P5/P4d with EFA | On-premises with InfiniBand |
| GPU memory access | GPUDirect RDMA via DMA-BUF | GPUDirect RDMA via verbs |
| CPU involvement | Zero (kernel bypass) | Zero (kernel bypass) |
| Multi-path | Up to 64 paths (SRD) | Depends on fabric config |

**Environment variables for LIBFABRIC backend:**

```bash
NIXL_BACKEND=LIBFABRIC          # Select LIBFABRIC for KV cache transfer
FI_PROVIDER=efa                  # Use the EFA provider in libfabric
FI_EFA_USE_DEVICE_RDMA=1         # Enable GPUDirect RDMA (GPU memory -> NIC)
FI_HMEM_DISABLE_P2P=1            # Required for multi-GPU RDMA registration
```

**Environment variables for UCX backend (alternative):**

```bash
NIXL_BACKEND=UCX
UCX_TLS=tcp,srd,cuda_copy,cuda_ipc,sm,self
UCX_IB_GPU_DIRECT_RDMA=yes
```

### The 128Gi Memory Requirement

Worker pods on P5.48xlarge require **at least 128Gi of memory**. With less (e.g., 64Gi), the pod is OOMKilled during NIXL initialization.

**Why:** When NIXL initializes the LIBFABRIC backend, it enumerates all 32 EFA devices on P5.48xlarge. For each device, it allocates queue pairs and memory registrations. This per-device overhead, multiplied by 32 NICs, requires substantial host memory.

```
NIXL LIBFABRIC Initialization on P5.48xlarge:
  32 EFA devices x (queue pairs + memory registrations + buffers) = ~80-100 GB
  + Model weights in GPU memory (host-side page tables)
  + CUDA context overhead
  = 128Gi minimum to avoid OOMKill
```

If you see pods OOMKilled during startup, check your memory requests first.

### Verifying EFA Activation

After deploying cross-node, verify that NIXL is actually using EFA RDMA by checking the pod logs for the libfabric handshake:

```bash
# Check prefill worker logs for NIXL initialization
kubectl logs -n dynamo-inference -l component=prefill | grep -i "nixl\|libfabric\|efa"
```

**What to look for:**

```
NIXL: Initializing LIBFABRIC backend
NIXL: Found 32 EFA devices
NIXL: libfabric provider: efa
NIXL: GPUDirect RDMA: enabled
NIXL: KV cache transfer ready
```

**If you see TCP fallback instead:**

```
NIXL: WARNING: Falling back to TCP transport
```

This means EFA is not properly configured. Check:
1. EFA device plugin is running (`kubectl get ds -n kube-system | grep efa`)
2. Pods requested `vpc.amazonaws.com/efa` resources
3. Security group allows SRD traffic (self-referencing egress rule required)
4. `FI_PROVIDER=efa` is set in the environment

**Check EFA hardware counters from inside a worker pod:**

```bash
kubectl exec -n dynamo-inference <prefill-pod> -- \
  cat /sys/class/infiniband/rdmap0s6/ports/1/hw_counters/rdma_read_bytes
```

Non-zero and increasing values confirm RDMA data is flowing through EFA.

---

## 5. Hands-on: Deploy and Query

### Deploy Dynamo

Follow Steps 1-4 from Section 3 above. Once all pods are running:

```bash
kubectl get pods -n dynamo-inference
```

```
NAME                        READY   STATUS    RESTARTS   AGE
llm-disagg-frontend-xxx     1/1     Running   0          5m
llm-disagg-prefill-xxx      1/1     Running   0          5m
llm-disagg-decode-xxx       1/1     Running   0          5m
```

### Port-Forward to the Frontend

```bash
kubectl port-forward -n dynamo-inference svc/llm-disagg-frontend 8000:8000
```

### Send an Inference Request

Dynamo exposes an OpenAI-compatible API:

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [
      {"role": "user", "content": "Explain disaggregated inference in one paragraph."}
    ],
    "max_tokens": 256,
    "stream": true
  }'
```

### Verify Disaggregation is Working

Check that the request actually went through separate prefill and decode workers:

```bash
# Check prefill worker received the prompt
kubectl logs -n dynamo-inference -l component=prefill --tail=20 | grep "prefill_request"

# Check decode worker received the KV cache and is generating tokens
kubectl logs -n dynamo-inference -l component=decode --tail=20 | grep "decode_request"

# Check NIXL transfer occurred
kubectl logs -n dynamo-inference -l component=prefill --tail=50 | grep "nixl.*transfer"
```

You should see the prefill worker logging the prompt processing, a NIXL KV cache transfer event, and then the decode worker logging token generation.

### Streaming Response Test

```bash
# Use curl with streaming to watch tokens arrive in real time
curl -N http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [
      {"role": "user", "content": "Write a haiku about GPU computing."}
    ],
    "max_tokens": 50,
    "stream": true
  }' 2>/dev/null | while read -r line; do
    echo "$line"
  done
```

---

## 6. Performance

### Key Metrics

| Metric | What it Measures | Target |
|---|---|---|
| **TTFT** (Time to First Token) | Prompt processing + KV transfer + first decode step | < 500 ms for 4K context |
| **ITL** (Inter-Token Latency) | Time between consecutive output tokens | < 30 ms |
| **KV Transfer Latency** | NIXL RDMA transfer from prefill to decode | < 10 ms for 500 MB cache |
| **Throughput** | Tokens generated per second across all requests | Workload-dependent |

### Benchmarking with NVIDIA AIPerf

AIPerf is NVIDIA's official benchmarking tool for LLM inference (successor to GenAI-Perf).
It comes pre-installed in Dynamo containers at `/opt/dynamo/venv/bin/aiperf`.

```bash
# Run from inside a Dynamo frontend pod
kubectl exec -n workshop <frontend-pod> -- \
  /opt/dynamo/venv/bin/aiperf profile \
  -m "Qwen/Qwen2.5-Coder-7B-Instruct" \
  --endpoint-type chat \
  --streaming \
  -u "http://localhost:8000" \
  --concurrency 4 \
  --request-count 20 \
  --synthetic-input-tokens-mean 128 \
  --output-tokens-mean 64 \
  --use-legacy-max-tokens \
  --artifact-dir /tmp/aiperf-results
```

**Workshop benchmark results (A100 40GB, Qwen2.5-Coder-7B):**

| Metric | Concurrency=1 | Concurrency=4 |
|--------|---------------|---------------|
| TTFT (avg) | 46.81 ms | 52.19 ms |
| ITL (avg) | 12.36 ms | 12.97 ms |
| Throughput | 77 tok/s | 282 tok/s |
| Req/s | 1.25 | 4.59 |

### Benchmarking with curl Timing

```bash
# Measure TTFT (time to first byte ~ time to first token for streaming)
curl -o /dev/null -s -w "TTFT: %{time_starttransfer}s\nTotal: %{time_total}s\n" \
  http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/Llama-3.1-8B-Instruct",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 1,
    "stream": true
  }'
```

### Cross-Node Latency: LIBFABRIC vs UCX vs TCP

The KV cache transfer backend dramatically affects performance:

```
KV Cache Transfer Latency (500 MB, P5.48xlarge):

  LIBFABRIC (EFA RDMA):  ~5-8 ms    ========
  UCX (EFA):             ~8-12 ms   ============
  TCP (fallback):        ~50-100 ms ====================================================

  Note: TCP fallback means EFA is not activated. This is the most common
  misconfiguration and has a 10x performance impact on TTFT.
```

### Monitoring EFA Throughput During Inference

While running inference requests, monitor EFA RDMA traffic in real time:

```bash
# On the prefill worker pod, watch RDMA write bytes
kubectl exec -n dynamo-inference <prefill-pod> -- bash -c '
  PREV=0
  while true; do
    CURR=$(cat /sys/class/infiniband/rdmap0s6/ports/1/hw_counters/rdma_write_bytes 2>/dev/null || echo 0)
    DIFF=$((CURR - PREV))
    if [ $DIFF -gt 0 ]; then
      echo "RDMA write throughput: $((DIFF / 1048576)) MB since last check"
    fi
    PREV=$CURR
    sleep 1
  done
'
```

### Common Performance Issues

| Symptom | Likely Cause | Fix |
|---|---|---|
| High TTFT, low ITL | KV cache transfer is slow | Verify EFA is active, not TCP fallback |
| OOMKilled on startup | Memory request too low | Set memory to 128Gi for P5 workers |
| Pods stuck in Pending | Insufficient GPU or EFA resources | Check node allocatable resources |
| NIXL timeout errors | Security group blocks SRD | Add self-referencing egress rule |
| Slow first request | Model loading on first inference | Use model pre-loading or warm-up |

---

## Architecture Summary

```
+--EKS Cluster------------------------------------------------------------------+
|                                                                                |
|  +--dynamo-system namespace--+    +--dynamo-inference namespace--------------+ |
|  |                           |    |                                          | |
|  |  [etcd]  [NATS]           |    |  [Frontend Pod]                          | |
|  |  Service  Internal        |    |   Port 8000 (OpenAI API)                 | |
|  |  Discovery Messaging      |    |   No GPU needed                          | |
|  |                           |    |                                          | |
|  +---------------------------+    |  +--Node 1 (P5.48xlarge)-------------+   | |
|                                   |  | [Prefill Worker Pod]              |   | |
|                                   |  |  8x H100 GPUs                     |   | |
|                                   |  |  32x EFA NICs                     |   | |
|                                   |  |  128Gi memory                     |   | |
|                                   |  |  NIXL LIBFABRIC backend           |   | |
|                                   |  +--+-----------------------------+--+   | |
|                                   |     |    NIXL KV Cache Transfer    |      | |
|                                   |     |    (RDMA over EFA, ~5ms)     |      | |
|                                   |  +--+-----------------------------+--+   | |
|                                   |  | [Decode Worker Pod]               |   | |
|  +--Dynamo Operator---------+    |  |  8x H100 GPUs                     |   | |
|  |  Watches DGD resources   |    |  |  32x EFA NICs                     |   | |
|  |  Manages worker pods     |    |  |  128Gi memory                     |   | |
|  |  Handles scaling         |    |  |  NIXL LIBFABRIC backend           |   | |
|  +---------------------------+    |  +-----------------------------------+   | |
|                                   |                                          | |
|                                   +------------------------------------------+ |
+--------------------------------------------------------------------------------+
```

---

## Key Takeaways

1. **Disaggregated inference** separates compute-bound prefill from memory-bound decode, enabling independent scaling and better GPU utilization.
2. **NVIDIA Dynamo** orchestrates the inference graph with a frontend, prefill workers, and decode workers connected via NIXL.
3. **NIXL LIBFABRIC** over EFA provides 5-8 ms KV cache transfer using GPUDirect RDMA -- critical for making disaggregation practical.
4. **128Gi memory** is required for worker pods on P5.48xlarge due to NIXL enumerating all 32 EFA devices.
5. **Always verify EFA activation** in logs. TCP fallback causes 10x worse TTFT and is the most common misconfiguration.
6. **The DynamoGraphDeployment CRD** is the Kubernetes-native way to declare inference topologies.

---

## Further Reading

- [NVIDIA Dynamo GitHub](https://github.com/ai-dynamo/dynamo)
- [NIXL GitHub](https://github.com/ai-dynamo/nixl)
- [Dynamo Documentation](https://docs.nvidia.com/dynamo/latest/index.html)
- [AWS EFA User Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa.html)
- [SRD Protocol (IEEE Micro 2020)](https://ieeexplore.ieee.org/document/9167399)
- [Disaggregated LLM Serving (Splitwise Paper)](https://arxiv.org/abs/2311.18677)

---

**Previous:** [Module 5 - GPU Foundations](../05-gpu-foundations/README.md)
**Next:** [Module 7 - HPC Kernel Optimization](../07-hpc-kernel-optimization/README.md)
