---
name: distributed-training-k8s
description: Use when deploying multi-node GPU training on Kubernetes. Covers StatefulSets, headless services, rank computation, master IP discovery, anti-affinity scheduling, high-speed networking device mounts, torchrun configuration, and topology discovery.
---

# Distributed Training on Kubernetes

## Overview

Deploying multi-node distributed GPU training on Kubernetes requires coordinating pod scheduling, network device allocation, rank assignment, and synchronized training launches. This skill covers proven patterns for StatefulSet-based deployments with high-speed inter-node networking.

## When to Use

- Deploying multi-node training jobs (2+ nodes)
- Computing NODE_RANK and MASTER_ADDR from pod metadata
- Configuring StatefulSets with headless services for pod discovery
- Mounting RDMA/high-speed networking devices into containers
- Launching torchrun or similar distributed launchers across pods
- Building preflight checks that fail fast if infrastructure is missing

## Master IP Discovery Patterns

### Pattern 1: StatefulSet + Headless Service (Recommended)

StatefulSet pods have deterministic names (`<name>-0`, `<name>-1`, ...) and DNS entries via headless services.

```bash
#!/bin/bash
# entrypoint.sh - Compute topology from pod identity

# Extract rank from StatefulSet ordinal
HOSTNAME=$(hostname)
NODE_RANK=${HOSTNAME##*-}  # "training-2" -> "2"

# Headless service provides DNS for pod-0 as master
MASTER_ADDR="${STATEFULSET_NAME}-0.${HEADLESS_SERVICE}.${NAMESPACE}.svc.cluster.local"
MASTER_PORT=${MASTER_PORT:-29500}
WORLD_SIZE=${WORLD_SIZE:-2}
NPROC_PER_NODE=${NPROC_PER_NODE:-8}

export NODE_RANK MASTER_ADDR MASTER_PORT WORLD_SIZE NPROC_PER_NODE
```

### Pattern 2: Init Container with Kubernetes API

Query the K8s API for pod IPs. Requires RBAC permissions.

```yaml
# RBAC setup
apiVersion: v1
kind: ServiceAccount
metadata:
  name: training-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: training-pod-reader
subjects:
- kind: ServiceAccount
  name: training-sa
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

```yaml
initContainers:
- name: discover-master
  image: curlimages/curl:latest
  command: ["/bin/sh", "-c"]
  args:
  - |
    TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
    NAMESPACE=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)
    API_SERVER="https://kubernetes.default.svc"

    while true; do
      PODS=$(curl -sk -H "Authorization: Bearer $TOKEN" \
        "$API_SERVER/api/v1/namespaces/$NAMESPACE/pods?labelSelector=app=training")
      READY=$(echo "$PODS" | grep -c '"podIP"')
      if [ "$READY" -ge 2 ]; then
        MASTER_IP=$(echo "$PODS" | grep '"podIP"' | head -1 | \
          grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')
        echo "$MASTER_IP" > /discovery/master_ip
        break
      fi
      sleep 2
    done
```

### Pattern 3: Headless Service DNS (Simple)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: training-svc
spec:
  clusterIP: None
  selector:
    app: training
  ports:
  - port: 29500
    name: rendezvous
```

```bash
MASTER_ADDR=$(getent hosts training-svc | awk '{print $1}' | head -1)
```

**Warning:** DNS resolution can be unreliable with `hostNetwork: true`. Prefer StatefulSet ordinal DNS or init container patterns.

## Complete StatefulSet Template

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: training
  namespace: ml-training
spec:
  serviceName: training-headless
  replicas: 2
  selector:
    matchLabels:
      app: training
  template:
    metadata:
      labels:
        app: training
    spec:
      # Required for RDMA/high-speed networking
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet

      # One pod per physical node
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                app: training
            topologyKey: kubernetes.io/hostname

      # Target GPU nodes
      nodeSelector:
        node.kubernetes.io/instance-type: <gpu-instance-type>

      containers:
      - name: trainer
        image: <registry>/training:latest
        command: ["/bin/bash", "-c"]
        args:
        - |
          # Compute rank from StatefulSet ordinal
          NODE_RANK=${HOSTNAME##*-}
          MASTER_ADDR="training-0.training-headless.ml-training.svc.cluster.local"

          # Launch distributed training
          torchrun \
            --nnodes=$WORLD_SIZE \
            --nproc_per_node=$NPROC_PER_NODE \
            --node_rank=$NODE_RANK \
            --master_addr=$MASTER_ADDR \
            --master_port=29500 \
            train.py

        env:
        - name: WORLD_SIZE
          value: "2"
        - name: NPROC_PER_NODE
          value: "8"
        - name: NCCL_TIMEOUT
          value: "1800"
        # Debug logging (set to WARN for production)
        - name: NCCL_DEBUG
          value: "INFO"

        resources:
          limits:
            nvidia.com/gpu: 8
            # High-speed networking devices (adjust count for your instance type)
            # vpc.amazonaws.com/efa: 32    # AWS EFA
            # rdma/hca: 8                  # InfiniBand
            memory: 1000Gi
          requests:
            nvidia.com/gpu: 8
            memory: 800Gi
            cpu: 90

        volumeMounts:
        # Shared memory for NCCL/collective communication
        - name: dshm
          mountPath: /dev/shm
        # RDMA devices (if applicable)
        - name: dev-infiniband
          mountPath: /dev/infiniband

      volumes:
      - name: dshm
        emptyDir:
          medium: Memory
          sizeLimit: 256Gi
      - name: dev-infiniband
        hostPath:
          path: /dev/infiniband

---
# Headless service for DNS-based pod discovery
apiVersion: v1
kind: Service
metadata:
  name: training-headless
  namespace: ml-training
spec:
  clusterIP: None
  selector:
    app: training
  ports:
  - port: 29500
    name: rendezvous
```

## Pod Scheduling

### Anti-Affinity (Required)

Ensure each pod lands on a different physical node:

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: training
      topologyKey: kubernetes.io/hostname
```

### Node Selection

```yaml
# By instance type
nodeSelector:
  node.kubernetes.io/instance-type: <gpu-instance-type>

# By GPU presence
nodeSelector:
  nvidia.com/gpu.present: "true"
```

## Volume Mounts (Required)

```yaml
volumeMounts:
  # Shared memory for NCCL inter-GPU communication
  - name: dshm
    mountPath: /dev/shm
  # RDMA devices (InfiniBand/EFA)
  - name: dev-infiniband
    mountPath: /dev/infiniband
  # GDRCopy device (optional, for GPU Direct RDMA)
  - name: gdrdrv
    mountPath: /dev/gdrdrv

volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 256Gi    # Large for collective communication
  - name: dev-infiniband
    hostPath:
      path: /dev/infiniband
  - name: gdrdrv
    hostPath:
      path: /dev/gdrdrv
      type: CharDevice
```

## torchrun Configuration

### Key Parameters

| Parameter | Purpose | Typical Value |
|-----------|---------|---------------|
| `--nproc_per_node` | GPUs per node | 8 |
| `--nnodes` | Total nodes | 2+ |
| `--node_rank` | This node's rank (0-indexed) | Computed from hostname |
| `--master_addr` | Master node IP or DNS | Discovered via headless service |
| `--master_port` | Rendezvous port | 29500 |

### Launch Script

```bash
#!/bin/bash
MASTER_ADDR="${STATEFULSET}-0.${HEADLESS_SVC}.${NAMESPACE}.svc.cluster.local"
NODE_RANK=${HOSTNAME##*-}

torchrun \
  --nproc_per_node=$NPROC_PER_NODE \
  --nnodes=$WORLD_SIZE \
  --node_rank=$NODE_RANK \
  --master_addr=$MASTER_ADDR \
  --master_port=${MASTER_PORT:-29500} \
  train.py "$@"
```

### Detect torchrun vs Direct Launch

```python
import os

def is_torchrun():
    """Detect if running under torchrun."""
    return 'RANK' in os.environ and 'WORLD_SIZE' in os.environ

if is_torchrun():
    rank = int(os.environ['RANK'])
    world_size = int(os.environ['WORLD_SIZE'])
else:
    # Direct launch: spawn processes manually
    torch.multiprocessing.spawn(main, nprocs=nproc_per_node)
```

## Preflight Check Script

Run before training to fail fast if infrastructure is missing:

```bash
#!/bin/bash
set -e
echo "=== Distributed Training Preflight ==="

# 1. Check GPUs
GPU_COUNT=$(nvidia-smi -L 2>/dev/null | wc -l)
if [ "$GPU_COUNT" -lt "$NPROC_PER_NODE" ]; then
  echo "FAIL: Only $GPU_COUNT GPUs found, need $NPROC_PER_NODE"
  exit 1
fi
echo "OK: $GPU_COUNT GPUs available"

# 2. Check RDMA devices (if applicable)
if [ -d /dev/infiniband ]; then
  RDMA_COUNT=$(ls /dev/infiniband/ | wc -l)
  echo "OK: $RDMA_COUNT RDMA devices"
else
  echo "WARN: /dev/infiniband not mounted (RDMA unavailable)"
fi

# 3. Check shared memory
SHM_SIZE=$(df -BG /dev/shm | tail -1 | awk '{print $2}' | tr -d 'G')
if [ "$SHM_SIZE" -lt 10 ]; then
  echo "WARN: /dev/shm only ${SHM_SIZE}GB (recommend 64GB+)"
fi
echo "OK: /dev/shm is ${SHM_SIZE}GB"

# 4. Check master connectivity (non-rank-0 only)
if [ "$NODE_RANK" != "0" ] && [ -n "$MASTER_ADDR" ]; then
  if ! timeout 10 bash -c "echo > /dev/tcp/$MASTER_ADDR/${MASTER_PORT:-29500}" 2>/dev/null; then
    echo "WARN: Cannot reach master at $MASTER_ADDR:${MASTER_PORT:-29500}"
  else
    echo "OK: Master reachable at $MASTER_ADDR:${MASTER_PORT:-29500}"
  fi
fi

echo "=== Preflight PASSED ==="
```

## Environment Variables for NCCL

```yaml
env:
  # NCCL configuration
  - name: NCCL_TIMEOUT
    value: "1800"          # 30 min timeout for large models
  - name: NCCL_DEBUG
    value: "INFO"          # Use WARN in production
  - name: NCCL_DEBUG_SUBSYS
    value: "INIT,NET"      # Subsystems to log

  # DO NOT hardcode these unless you know why:
  # NCCL_ALGO    -- can cause hangs if wrong for your topology
  # NCCL_PROTO   -- let NCCL auto-select
```

## Verification Checklist

```bash
# 1. Pods on different nodes
kubectl get pods -l app=training -o wide
# Verify NODE column shows different hostnames

# 2. All GPUs visible
kubectl exec training-0 -- nvidia-smi -L
# Should show expected GPU count

# 3. RDMA devices mounted (if applicable)
kubectl exec training-0 -- ls /dev/infiniband/ | wc -l

# 4. NCCL initialization complete
kubectl logs training-0 | grep "Init COMPLETE"

# 5. Training producing output
kubectl logs training-0 | grep -E "loss|step|iter" | tail -5
```

## Common Failures

| Failure | Symptom | Fix |
|---------|---------|-----|
| Pods on same node | Anti-affinity not configured | Add `requiredDuringSchedulingIgnoredDuringExecution` |
| DNS resolution failure | Master address not found | Use init container IP discovery with hostNetwork |
| NCCL timeout during init | `Timeout waiting for connect` | Increase NCCL_TIMEOUT, check master IP, check security groups |
| RDMA devices not visible | Empty `/dev/infiniband/` | Add RDMA device resource requests and hostPath volume |
| Shared memory too small | CUDA IPC errors | Increase dshm emptyDir sizeLimit |
| Rank mismatch | AlltoAll or AllReduce hangs | Verify NODE_RANK extraction from hostname |
| Wrong transport | Training 3-4x slower than expected | Check logs for `via NET/Socket` vs `via NET/...GDRDMA` |

## Job Template (Alternative to StatefulSet)

For one-shot training runs, use a Job with indexed completions:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: training-job
spec:
  parallelism: 2
  completions: 2
  completionMode: Indexed
  backoffLimit: 3
  template:
    metadata:
      labels:
        job-name: training-job
    spec:
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      restartPolicy: OnFailure

      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchLabels:
                job-name: training-job
            topologyKey: kubernetes.io/hostname

      containers:
      - name: trainer
        image: <registry>/training:latest
        env:
        - name: NCCL_TIMEOUT
          value: "1800"
        resources:
          limits:
            nvidia.com/gpu: 8
            memory: 1000Gi
          requests:
            nvidia.com/gpu: 8
            memory: 800Gi
            cpu: 90
        volumeMounts:
        - name: dshm
          mountPath: /dev/shm

      volumes:
      - name: dshm
        emptyDir:
          medium: Memory
          sizeLimit: 256Gi
```

## Process Cleanup Between Runs

Zombie training processes consume GPU memory:

```bash
kubectl exec $POD -- bash -c '
  pkill -9 -f torchrun || true
  pkill -9 -f train.py || true
  sleep 2
  nvidia-smi --query-gpu=memory.free --format=csv,noheader
'
```
