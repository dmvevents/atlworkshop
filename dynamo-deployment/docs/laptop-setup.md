# Running the Workshop on a Laptop (Docker Desktop + Kubernetes)

You don't need a cloud GPU cluster to follow along. This guide covers running
the workshop demos on a laptop with Docker Desktop and its built-in Kubernetes.

## What You Can Run Locally

| Component | Laptop (CPU) | Laptop (GPU) | Cloud (EKS) |
|-----------|-------------|-------------|-------------|
| Claude Code + Skills | Yes | Yes | Yes |
| MCP Servers | Yes | Yes | Yes |
| Multi-LLM Dispatch | Yes | Yes | Yes |
| OpenCode | Yes | Yes | Yes |
| Manager/Supervisor | Yes | Yes | Yes |
| Dynamo (CPU inference) | Yes (slow) | Yes (fast) | Yes |
| Dynamo (GPU inference) | No | Yes (NVIDIA GPU) | Yes |
| EFA/RDMA Networking | No | No | Yes (P5/P4d) |
| Disaggregated Inference | No | Limited | Yes |

**Bottom line:** Modules 1-4 and 9 (agentic coding) work fully on a laptop.
Modules 5-8 (GPU compute) work best on cloud but can be demoed locally with
CPU inference or a single NVIDIA GPU.

---

## Step 1: Install Docker Desktop

### macOS

```bash
# Option A: Homebrew
brew install --cask docker

# Option B: Download from docker.com
# https://www.docker.com/products/docker-desktop/
```

### Windows

1. Download Docker Desktop from https://www.docker.com/products/docker-desktop/
2. Install with WSL 2 backend (recommended)
3. Restart your computer

### Linux

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Or use the convenience script
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

### Verify

```bash
docker version
docker run hello-world
```

---

## Step 2: Enable Kubernetes in Docker Desktop

1. Open Docker Desktop
2. Go to **Settings** (gear icon)
3. Click **Kubernetes** in the left sidebar
4. Check **Enable Kubernetes**
5. Click **Apply & Restart**
6. Wait 2-3 minutes for Kubernetes to start

### Verify

```bash
kubectl cluster-info
# Should show: Kubernetes control plane is running at https://kubernetes.docker.internal:6443

kubectl get nodes
# Should show: docker-desktop   Ready   control-plane   ...
```

---

## Step 3: Install Workshop Tools

```bash
# Claude Code
npm install -g @anthropic-ai/claude-code

# OpenCode
curl -fsSL https://opencode.ai/install | bash

# Helm
brew install helm      # macOS
# or: curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Claude Code Router (optional)
npm install -g @musistudio/claude-code-router
```

---

## Step 4: Deploy a Model (CPU or GPU)

### Option A: CPU Inference (Any Laptop, Slow but Works)

Use vLLM with a small model in CPU mode:

```bash
# Create namespace
kubectl create namespace workshop

# Deploy a small model using standard vLLM (CPU mode)
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coding-model
  namespace: workshop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: coding-model
  template:
    metadata:
      labels:
        app: coding-model
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        ports:
        - containerPort: 8000
        command:
        - python3
        - -m
        - vllm.entrypoints.openai.api_server
        - --model=Qwen/Qwen2.5-Coder-1.5B-Instruct
        - --max-model-len=2048
        - --dtype=float32
        - --device=cpu
        - --port=8000
        resources:
          requests:
            cpu: "4"
            memory: "8Gi"
          limits:
            cpu: "8"
            memory: "16Gi"
---
apiVersion: v1
kind: Service
metadata:
  name: coding-model-svc
  namespace: workshop
spec:
  type: ClusterIP
  selector:
    app: coding-model
  ports:
  - port: 8000
    targetPort: 8000
EOF
```

> **Note:** CPU inference with the 1.5B model is slow (~2-5 tokens/sec) but
> functional for demos. Use it to show the API works.

### Option B: GPU Inference (NVIDIA GPU Laptop)

If you have an NVIDIA GPU (RTX 3060+, 6GB+ VRAM):

1. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
2. Enable GPU support in Docker Desktop (Settings > Resources > GPU)

```bash
# Verify GPU access
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi

# Deploy with GPU
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: coding-model
  namespace: workshop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: coding-model
  template:
    metadata:
      labels:
        app: coding-model
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        ports:
        - containerPort: 8000
        command:
        - python3
        - -m
        - vllm.entrypoints.openai.api_server
        - --model=Qwen/Qwen2.5-Coder-7B-Instruct
        - --max-model-len=4096
        - --gpu-memory-utilization=0.85
        - --dtype=auto
        - --port=8000
        resources:
          limits:
            nvidia.com/gpu: "1"
---
apiVersion: v1
kind: Service
metadata:
  name: coding-model-svc
  namespace: workshop
spec:
  type: ClusterIP
  selector:
    app: coding-model
  ports:
  - port: 8000
    targetPort: 8000
EOF
```

### Option C: Ollama (Simplest, No Kubernetes)

Skip Kubernetes entirely and just run Ollama:

```bash
# Install Ollama
brew install ollama    # macOS
# or: curl -fsSL https://ollama.ai/install.sh | sh  # Linux

# Pull a coding model
ollama pull qwen2.5-coder:7b

# Start serving (OpenAI-compatible API on port 11434)
ollama serve &

# Test
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "Write hello world in Go"}]
  }'
```

Then point OpenCode or Claude Code Router at `http://localhost:11434/v1`.

---

## Step 5: Access Your Model

```bash
# Port-forward (K8s deployments)
kubectl port-forward -n workshop svc/coding-model-svc 8000:8000

# Test
curl http://localhost:8000/v1/models
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    "messages": [{"role": "user", "content": "Write a fibonacci function in Python"}],
    "max_tokens": 200
  }'
```

---

## Resource Requirements

### Minimum (CPU-only, follow along)

| Resource | Requirement |
|----------|-------------|
| CPU | 4+ cores |
| RAM | 16 GB |
| Disk | 20 GB free |
| Docker Desktop | Latest |
| Node.js | 18+ |

### Recommended (GPU inference)

| Resource | Requirement |
|----------|-------------|
| CPU | 8+ cores |
| RAM | 32 GB |
| GPU | NVIDIA RTX 3060+ (6GB+ VRAM) |
| Disk | 50 GB free |
| Docker Desktop | Latest with GPU support |
| NVIDIA Driver | 535+ |

---

## Docker Desktop Resource Allocation

Docker Desktop limits resources by default. Increase them:

1. **Settings > Resources > Advanced**
2. Set **CPUs** to at least 4 (8 recommended)
3. Set **Memory** to at least 12 GB (16 recommended)
4. Set **Disk** to at least 40 GB
5. Click **Apply & Restart**

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Kubernetes not starting" | Reset Kubernetes in Docker Desktop settings |
| "Cannot pull image" | Check Docker Desktop has internet access and enough disk |
| "Pod stuck in Pending" | Increase Docker Desktop resource limits |
| "OOMKilled" | Use smaller model (1.5B) or increase memory limit |
| "No GPU detected" | Install NVIDIA Container Toolkit, enable GPU in Docker settings |
| "vLLM crashes on CPU" | Add `--device=cpu --dtype=float32`, use 1.5B model |
| "Slow inference" | Expected on CPU. Use GPU or Ollama for better performance |
