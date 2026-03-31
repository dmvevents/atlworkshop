# Module 5: GPU Foundations for AI Engineers

**Duration:** 10 minutes
**Prerequisites:** Basic programming experience. No GPU experience required.
**Goal:** Build a working mental model of GPU computing, from hardware through Kubernetes, so the rest of this workshop makes sense.

---

## 1. Why GPUs for AI?

A CPU is like a single brilliant mathematician who can solve any problem, one step at a time.
A GPU is like a stadium full of 10,000 students, each doing simple arithmetic in parallel.

Modern AI is embarrassingly parallel -- matrix multiplications, attention computations, activation functions -- they all boil down to doing the same operation across millions of data points simultaneously.

**The numbers tell the story:**

| | CPU (x86, 96 cores) | GPU (H100, 16,896 cores) |
|---|---|---|
| Cores | 96 | 16,896 |
| FP16 Throughput | ~10 TFLOPS | ~1,979 TFLOPS |
| Memory Bandwidth | ~300 GB/s | ~3,350 GB/s |
| Best at | Serial logic, branching | Parallel math, throughput |

A single H100 delivers roughly 200x the floating-point throughput of a top-end server CPU for AI workloads.

**SIMT Execution Model:** GPUs use Single Instruction, Multiple Threads. Groups of 32 threads (called a "warp") execute the same instruction at the same time, each on different data. Think of it as 32 calculators pressing the same button simultaneously, but each calculator has a different number on its screen.

---

## 2. GPU Architecture Mental Model

You do not need to memorize GPU hardware to use GPUs effectively, but a rough mental model prevents confusion later.

```
GPU (e.g., H100)
+------------------------------------------------------------------+
|                                                                  |
|  +------------------+  +------------------+  +------------------+|
|  | SM 0             |  | SM 1             |  | SM ...           ||
|  |  Warp Scheduler  |  |  Warp Scheduler  |  |  Warp Scheduler  ||
|  |  32 threads/warp |  |  32 threads/warp |  |  32 threads/warp ||
|  |  [Registers]     |  |  [Registers]     |  |  [Registers]     ||
|  |  [Shared Memory] |  |  [Shared Memory] |  |  [Shared Memory] ||
|  +--------+---------+  +--------+---------+  +--------+---------+|
|           |                      |                      |        |
|           +----------+-----------+----------+-----------+        |
|                      |                      |                    |
|              +-------+------+       +-------+------+             |
|              |   L2 Cache   |       |   L2 Cache   |             |
|              |  (50 MB)     |       |              |             |
|              +-------+------+       +--------------+             |
|                      |                                           |
|              +-------+------+                                    |
|              |     HBM      |                                    |
|              |  (80 GB)     |                                    |
|              |  3,350 GB/s  |                                    |
|              +--------------+                                    |
+------------------------------------------------------------------+
```

**The memory hierarchy (fastest to slowest):**

| Level | Size | Latency | Analogy |
|---|---|---|---|
| Registers | ~256 KB/SM | ~1 cycle | Your hands (instant access) |
| Shared Memory | ~228 KB/SM | ~30 cycles | Your desk (shared with your team) |
| L2 Cache | ~50 MB | ~200 cycles | A bookshelf in the room |
| HBM (Global) | 80 GB | ~400 cycles | The library down the hall |

**Why this matters:** The biggest performance bottleneck in AI is not compute -- it is memory bandwidth. Moving data to and from the GPU dominates execution time. This is why H100 (3,350 GB/s HBM3) outperforms A100 (2,039 GB/s HBM2e) even for the same model.

**SMs (Streaming Multiprocessors)** are the building blocks. The H100 has 132 SMs. Each SM can run multiple warps concurrently, hiding memory latency by switching between warps while one waits for data.

---

## 3. CUDA Without Getting Lost

CUDA is NVIDIA's programming model for GPUs. Most AI engineers never write raw CUDA, but understanding the basics helps you reason about performance.

**Mental model:** Think of the GPU as a massively parallel for-loop.

```
CPU version:
    for (int i = 0; i < 1000000; i++) {
        output[i] = input[i] * 2.0;
    }

GPU version (conceptually):
    // All 1,000,000 iterations run simultaneously
    __global__ void doubleIt(float* input, float* output) {
        int i = blockIdx.x * blockDim.x + threadIdx.x;
        output[i] = input[i] * 2.0;
    }

    // Launch: 1000 blocks x 1024 threads = 1,024,000 threads
    doubleIt<<<1000, 1024>>>(d_input, d_output);
```

**The kernel launch syntax** `<<<blocks, threads>>>` tells the GPU how to organize the work:
- **threads per block:** Usually 128 or 256 (must be a multiple of 32 for warp alignment)
- **blocks:** Enough to cover all your data. Blocks are distributed across SMs.

**Memory management in 30 seconds:**

```c
// Allocate on GPU
float* d_data;
cudaMalloc(&d_data, size);

// Copy CPU -> GPU
cudaMemcpy(d_data, h_data, size, cudaMemcpyHostToDevice);

// Launch kernel (runs on GPU)
myKernel<<<blocks, threads>>>(d_data);

// Copy GPU -> CPU
cudaMemcpy(h_data, d_data, size, cudaMemcpyDeviceToHost);
```

**Practical advice for AI engineers:**

1. **Start with PyTorch** -- `torch.cuda.is_available()`, `.to("cuda")`, and you are running on GPU.
2. **Custom ops next** -- If you need custom GPU code, use `torch.utils.cpp_extension` to write C++/CUDA extensions that integrate with PyTorch.
3. **Raw CUDA last** -- Only when you need maximum control (custom kernels for inference, MoE dispatch, etc.).

Most of the time, frameworks like PyTorch, vLLM, and TensorRT-LLM handle GPU programming for you. Your job is to understand *why* things are fast or slow.

---

## 4. GPU + Kubernetes

Running GPUs in Kubernetes requires a few extra pieces beyond standard container orchestration.

**The GPU device plugin** exposes GPUs as schedulable resources:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-workload
spec:
  containers:
  - name: inference
    image: my-inference-server:latest
    resources:
      requests:
        nvidia.com/gpu: 1       # Request 1 GPU
      limits:
        nvidia.com/gpu: 1       # Limit to 1 GPU
```

**How scheduling works:**

```
+--Node 1 (p5.48xlarge)---+    +--Node 2 (p5.48xlarge)---+
| 8x H100 GPUs            |    | 8x H100 GPUs            |
| nvidia.com/gpu: 8       |    | nvidia.com/gpu: 8       |
|                          |    |                          |
| [Pod A: 4 GPUs]          |    | [Pod C: 8 GPUs]          |
| [Pod B: 4 GPUs]          |    |                          |
+--------------------------+    +--------------------------+
```

**GPU sharing strategies:**

| Strategy | How it works | Best for |
|---|---|---|
| **Exclusive** (default) | 1 GPU = 1 pod | Training, inference |
| **Time-slicing** | Multiple pods share a GPU by time-division | Dev/test, light workloads |
| **MIG** (Multi-Instance GPU) | Hardware-partitioned GPU slices (A100/H100) | Guaranteed isolation |
| **MPS** (Multi-Process Service) | Concurrent kernel execution | Multiple small models |

For production AI inference, exclusive GPU access is almost always correct. MIG is useful when you need to run multiple small models on a single GPU with hardware isolation.

---

## 5. EFA and RDMA Networking

When your model is too large for one GPU (and most LLMs are), GPUs on different machines need to communicate. This is where networking becomes critical.

**AWS Elastic Fabric Adapter (EFA)** is a custom network interface built for HPC and AI workloads.

```
Traditional Networking (TCP/IP):
  GPU -> CPU -> Kernel -> NIC -> Network -> NIC -> Kernel -> CPU -> GPU
  Latency: ~100+ microseconds, CPU overhead at every hop

GPUDirect RDMA over EFA:
  GPU -> NIC -> Network -> NIC -> GPU
  Latency: ~5-10 microseconds, zero CPU involvement
```

**EFA by the numbers (P5.48xlarge):**

| Spec | Value |
|---|---|
| EFA NICs per node | 32 |
| Bandwidth per NIC | 100 Gbps |
| Total bandwidth per node | 3,200 Gbps (400 GB/s) |
| Protocol | SRD (Scalable Reliable Datagram) |
| Multipath routing | Up to 64 simultaneous paths |
| CPU involvement | Zero (kernel bypass) |

**SRD Protocol:** AWS built a custom transport protocol that combines the scalability of Unreliable Datagram (no per-connection state) with the reliability of connected transports. It uses multipath routing across up to 64 paths simultaneously, with hardware-accelerated congestion control on the Nitro card.

**GPUDirect RDMA: The Key Technology**

Without GPUDirect RDMA, data must be copied from GPU memory to CPU memory before the NIC can send it. With GPUDirect RDMA, the NIC reads directly from GPU memory:

```
Without GPUDirect RDMA:
  GPU Memory --cudaMemcpy--> CPU Memory --send()--> NIC
  Two copies, CPU involved, high latency

With GPUDirect RDMA:
  GPU Memory --DMA--> NIC --SRD--> Remote NIC --DMA--> Remote GPU Memory
  Zero copies, zero CPU, low latency
```

This matters enormously for:
- **Distributed training:** Gradient synchronization (AllReduce) across nodes
- **MoE models:** Token routing between expert GPUs on different nodes
- **Disaggregated inference:** KV cache transfer from prefill to decode workers

---

## 6. Matching Workloads to Compute

Not every AI workload needs GPUs, and not every GPU workload needs the biggest instance.

**When you need GPUs:**

| Workload | GPUs needed? | Why? |
|---|---|---|
| LLM inference (7B) | 1 GPU | Fits in one GPU's memory |
| LLM inference (70B) | 2-8 GPUs | Model parallelism needed |
| LLM inference (405B+) | 16+ GPUs | Multi-node tensor parallelism |
| Fine-tuning (7B) | 1-2 GPUs | Gradients + optimizer states |
| Pre-training (any) | 100s-1000s of GPUs | Data + model parallelism |
| Agentic workflows | 0 GPUs (usually) | CPU-bound API orchestration |
| RAG pipelines | 0-1 GPU | Embedding model, mostly CPU |

**Instance selection guide:**

| Instance | GPU | GPU Memory | EFA | Best for |
|---|---|---|---|---|
| **g5** | A10G (1-8) | 24 GB each | No | Small inference, dev/test |
| **p4d.24xlarge** | A100 x8 | 40 GB each | 4x 100 Gbps | Training, medium inference |
| **p5.48xlarge** | H100 x8 | 80 GB each | 32x 100 Gbps | Large-scale training, disaggregated inference |
| **p5en.48xlarge** | H200 x8 | 141 GB each | 32x 100 Gbps | Memory-hungry models, long context |

**The key tradeoff:** Training is compute-bound (more FLOPS = faster). Inference is usually memory-bandwidth-bound (faster memory = more tokens/sec). The H200's biggest advantage over the H100 is not more FLOPS -- it is 76% more HBM capacity and 43% more memory bandwidth.

**Rule of thumb:** Start with the smallest GPU that fits your model in memory. Scale up if throughput is insufficient. Scale out (more nodes) only when necessary, because inter-node communication adds latency.

---

## Key Takeaways

1. GPUs are massively parallel processors. AI workloads map naturally to this architecture.
2. Memory bandwidth, not compute, is usually the bottleneck for inference.
3. The memory hierarchy (registers to HBM) determines performance -- keep data close to compute.
4. Kubernetes schedules GPUs as resources. Use exclusive access for production AI.
5. EFA with GPUDirect RDMA enables GPU-to-GPU communication across nodes without CPU involvement.
6. Match instance type to workload: bigger is not always better.

---

## Further Reading

- [NVIDIA CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/)
- [NVIDIA H100 Architecture Whitepaper](https://resources.nvidia.com/en-us-tensor-core)
- [AWS EFA Documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa.html)
- [SRD Protocol Paper (IEEE Micro 2020)](https://ieeexplore.ieee.org/document/9167399)
- [Kubernetes GPU Scheduling](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/)

---

**Next:** [Module 6 - Disaggregated Inference with NVIDIA Dynamo on EKS](../06-dynamo-inference-eks/README.md)
