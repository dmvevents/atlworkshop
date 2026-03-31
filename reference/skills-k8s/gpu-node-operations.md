---
name: gpu-node-operations
description: Use when managing GPU nodes on Kubernetes, checking GPU availability, configuring device plugins, loading kernel modules, debugging node-level issues without SSH, managing disk pressure, or provisioning GPU nodegroups.
---

# GPU Node Operations

## Overview

Patterns for managing GPU-equipped Kubernetes nodes: checking GPU availability, loading kernel modules, debugging without SSH access, handling disk pressure, and configuring device plugins. These patterns apply to any Kubernetes cluster with GPU nodes.

## When to Use

- Nodes show no GPU resources in allocatable
- NVIDIA device plugin pods are crashing or missing
- Kernel modules need to be loaded on nodes (no SSH access)
- Disk pressure is evicting pods on GPU nodes
- Provisioning new GPU nodegroups with high-speed networking
- Diagnosing node-level issues from kubectl only

## Checking GPU Availability on Nodes

### GPU Allocation Status

```bash
# Check GPU resources across all nodes
kubectl describe nodes | grep -B2 -A3 "nvidia.com/gpu"

# Check allocatable vs allocated on a specific node
kubectl describe node <node-name> | grep -A20 "Allocated resources"

# List nodes with GPU capacity
kubectl get nodes -o custom-columns=\
  "NAME:.metadata.name,\
   GPU:.status.allocatable.nvidia\.com/gpu,\
   INSTANCE:.metadata.labels.node\.kubernetes\.io/instance-type"
```

### Verify GPUs Inside a Pod

```bash
# Check all GPUs are visible
kubectl exec <pod> -- nvidia-smi -L
# Should list all GPUs (e.g., 8 for a large GPU instance)

# Quick GPU count
kubectl exec <pod> -- nvidia-smi --query-gpu=count --format=csv,noheader

# GPU utilization and memory
kubectl exec <pod> -- nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv
```

## Node Shell Access Without SSH

Use `kubectl debug` to get a shell on any node:

```bash
# Interactive shell on a node
kubectl debug node/<node-name> -it --image=ubuntu -- chroot /host bash

# Run a single command on a node
kubectl debug node/<node-name> --image=ubuntu -- chroot /host <command>

# Check kernel modules on a node
kubectl debug node/<node-name> --image=ubuntu -- chroot /host bash -c \
  "lsmod | grep -E 'nvidia|gdrdrv|efa'"

# Check disk usage on a node
kubectl debug node/<node-name> --image=ubuntu -- chroot /host df -h

# IMPORTANT: Clean up debug pods after use
kubectl delete pod -l kubernetes.io/node-debugger
```

### Useful Node Shell Commands

```bash
# Inside the node shell (after chroot /host):
lsmod | grep nvidia          # NVIDIA kernel modules
nvidia-smi                   # GPU status from host
ls /dev/infiniband/           # RDMA/EFA devices
ls /dev/nvidia*               # GPU device nodes
cat /proc/modules | grep gpu  # Module details
df -h /var/lib/containerd     # Container storage usage
```

## Kernel Module Loading via DaemonSet

When `kubectl debug` cannot load kernel modules (missing `CAP_SYS_MODULE`), use a DaemonSet with `hostPID: true` and `privileged: true`:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: gpu-module-loader
spec:
  selector:
    matchLabels:
      app: gpu-module-loader
  template:
    metadata:
      labels:
        app: gpu-module-loader
    spec:
      hostPID: true
      nodeSelector:
        # Target only GPU nodes
        nvidia.com/gpu.present: "true"
      containers:
      - name: loader
        image: ubuntu:22.04
        command: ["/bin/bash", "-c"]
        args:
        - |
          # Load required kernel modules using host's modprobe
          for MODULE in gdrdrv nvidia_peermem; do
            if nsenter -t 1 -m -- lsmod | grep -q $MODULE; then
              echo "$MODULE: already loaded"
            else
              echo "Loading $MODULE..."
              nsenter -t 1 -m -- modprobe $MODULE || echo "WARN: Failed to load $MODULE"
            fi
          done
          # Show loaded modules
          nsenter -t 1 -m -- lsmod | grep -E "gdrdrv|nvidia|peermem"
          # Keep running so DaemonSet stays active
          sleep infinity
        securityContext:
          privileged: true
      tolerations:
      - operator: Exists
```

**Key technique:** `nsenter -t 1 -m` enters PID 1's mount namespace (the host), allowing `modprobe` to work from a container.

### Persist Modules Across Reboots

```bash
nsenter -t 1 -m -- bash -c 'echo "gdrdrv" >> /etc/modules-load.d/gpu.conf'
```

### Verify Module Loading

```bash
# Check DaemonSet pods
kubectl get pods -l app=gpu-module-loader -o wide

# Verify from any privileged pod on the same node
kubectl exec <pod> -- cat /proc/modules | grep gdrdrv
```

## GPU Device Plugin Troubleshooting

When `nvidia.com/gpu` shows 0 or is missing from node allocatable resources:

### Check Device Plugin Status

```bash
# Check if NVIDIA device plugin DaemonSet is running
kubectl get ds -n kube-system | grep nvidia

# Check device plugin pod logs on the affected node
kubectl logs -n kube-system $(kubectl get pods -n kube-system -l app=nvidia-device-plugin \
  --field-selector spec.nodeName=<node-name> -o name) --tail=50

# Check for GPU device nodes on the host
kubectl debug node/<node-name> --image=ubuntu -- chroot /host ls -la /dev/nvidia*
```

### Manual GPU Access (When Device Plugin Is Broken)

If the device plugin is not functioning, use privileged pods with manual device setup:

```yaml
spec:
  containers:
  - name: trainer
    securityContext:
      privileged: true
    resources:
      limits:
        # Do NOT request nvidia.com/gpu when device plugin is broken
        memory: 900Gi
    volumeMounts:
    - name: nvidia-driver
      mountPath: /usr/lib64-host
      readOnly: true
    - name: dev
      mountPath: /dev
  volumes:
  - name: nvidia-driver
    hostPath:
      path: /usr/lib64
      type: Directory
  - name: dev
    hostPath:
      path: /dev
      type: Directory
```

With a startup script to create device nodes:

```bash
#!/bin/bash
# Create GPU device nodes if missing
for i in $(seq 0 7); do
  [ ! -e /dev/nvidia$i ] && mknod -m 666 /dev/nvidia$i c 195 $i || true
done
[ ! -e /dev/nvidiactl ] && mknod -m 666 /dev/nvidiactl c 195 255 || true
[ ! -e /dev/nvidia-uvm ] && mknod -m 666 /dev/nvidia-uvm c 510 0 || true

# Link host NVIDIA libraries
for lib in /usr/lib64-host/libnvidia*.so* /usr/lib64-host/libcuda*.so*; do
  [ -f "$lib" ] && ln -sf "$lib" /usr/local/lib/ || true
done
ldconfig

# Verify
nvidia-smi
python3 -c "import torch; print(torch.cuda.device_count())"
```

## Disk Pressure Management

GPU nodes with large container images frequently hit disk pressure, causing pod evictions.

### Detect Disk Pressure

```bash
# Check DiskPressure condition
kubectl get nodes -o custom-columns=\
  "NAME:.metadata.name,\
   DISK_PRESSURE:.status.conditions[?(@.type=='DiskPressure')].status"

# Check disk usage on a node
kubectl debug node/<node-name> --image=ubuntu -- chroot /host df -h /
```

### Prevention

1. **Set ephemeral-storage limits on pods** to prevent surprise evictions:
   ```yaml
   resources:
     limits:
       ephemeral-storage: "50Gi"
     requests:
       ephemeral-storage: "20Gi"
   ```

2. **Increase root volume size** in the node launch template (200-500GB recommended for GPU workloads).

3. **Relocate containerd storage** to a larger volume if root disk is small:
   ```bash
   # In node bootstrap script (before kubelet starts):
   LARGE_DISK="/mnt/data"
   mkdir -p "$LARGE_DISK/containerd/data"
   systemctl stop containerd
   cp -a /var/lib/containerd/* "$LARGE_DISK/containerd/data/" 2>/dev/null || true
   rm -rf /var/lib/containerd
   ln -sf "$LARGE_DISK/containerd/data" /var/lib/containerd
   systemctl start containerd
   ```

4. **Clean up during pod execution** to prevent ephemeral storage exhaustion:
   ```bash
   # Clean build artifacts and pip cache
   rm -rf /tmp/pip-* build/ dist/ *.egg-info
   ```

## GPU Resource Requests

### GPU Requests Must Equal Limits

Kubernetes does not support overcommit for extended resources like GPUs. Requests must equal limits:

```yaml
resources:
  limits:
    nvidia.com/gpu: 8    # This is both the request and limit
  requests:
    nvidia.com/gpu: 8    # MUST match limits
```

### Node Selectors and Tolerations for GPU Nodes

```yaml
spec:
  nodeSelector:
    # Select by instance type
    node.kubernetes.io/instance-type: <gpu-instance-type>
    # Or by GPU presence
    nvidia.com/gpu.present: "true"

  tolerations:
  # Tolerate GPU node taints
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

## Container Image Management for GPU Workloads

### Build Workflow

```bash
# 1. Authenticate to your container registry
# 2. Build with GPU support
IMAGE_TAG="v$(date +%Y%m%d-%H%M%S)"
docker build -t my-training:${IMAGE_TAG} -f Dockerfile .

# 3. Verify locally
docker run --rm my-training:${IMAGE_TAG} \
  python -c "import torch; print(f'PyTorch {torch.__version__}')"

# 4. Tag and push
docker tag my-training:${IMAGE_TAG} <registry>/my-training:${IMAGE_TAG}
docker push <registry>/my-training:${IMAGE_TAG}

# 5. Deploy
kubectl apply -f manifests/training-job.yaml
```

### Multi-Stage Dockerfile Pattern

```dockerfile
# Stage 1: Build dependencies
FROM nvidia/cuda:12.8.0-devel-ubuntu22.04 AS builder
RUN pip install --no-cache-dir torch==2.8.0

# Stage 2: Runtime (smaller image)
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04
COPY --from=builder /usr/local/lib/python3.10 /usr/local/lib/python3.10

# Set defaults for distributed training
ENV NCCL_DEBUG=WARN
```

### Image Verification Script

```bash
#!/bin/bash
# verify-image.sh <image:tag>
IMAGE=$1
PASS=0; FAIL=0

check() {
  local desc=$1; shift
  if docker run --rm $IMAGE bash -c "$@" >/dev/null 2>&1; then
    echo "PASS: $desc"; PASS=$((PASS+1))
  else
    echo "FAIL: $desc"; FAIL=$((FAIL+1))
  fi
}

check "Python imports" "python -c 'import torch'"
check "CUDA available" "python -c 'import torch; assert torch.cuda.is_available()'" 2>/dev/null || true

echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ] && echo "Image READY" || echo "Image NOT ready"
```

## Common Module Reference

| Module | Purpose | Required For |
|--------|---------|-------------|
| `nvidia` | NVIDIA GPU driver | All GPU workloads |
| `gdrdrv` | GDRCopy GPU-CPU DMA | GPUDirect RDMA |
| `nvidia_peermem` | GPU Direct RDMA (generic) | InfiniBand RDMA |
| `efa_nv_peermem` | GPU Direct RDMA over EFA | AWS EFA RDMA |

## Verification Checklist

```bash
# Node-level checks
kubectl describe node <node> | grep -A5 "Allocatable"  # GPU count
kubectl debug node/<node> --image=ubuntu -- chroot /host nvidia-smi  # Driver
kubectl debug node/<node> --image=ubuntu -- chroot /host lsmod | grep nvidia  # Modules
kubectl debug node/<node> --image=ubuntu -- chroot /host df -h /  # Disk

# Pod-level checks
kubectl exec <pod> -- nvidia-smi -L                    # GPUs visible
kubectl exec <pod> -- nvidia-smi --query-gpu=memory.free --format=csv  # Memory
```
