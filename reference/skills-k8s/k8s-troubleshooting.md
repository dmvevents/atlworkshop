---
name: k8s-troubleshooting
description: Use when pods fail to start, training hangs, performance is degraded, or workloads behave unexpectedly on Kubernetes. Covers Pending, CrashLoopBackOff, OOMKilled, ImagePullBackOff, DNS issues, training hangs, silent performance regressions, and systematic debugging methodology.
---

# Kubernetes Troubleshooting

## Overview

Systematic workflows for diagnosing Kubernetes workload failures, derived from hundreds of real debugging sessions across GPU training clusters. Covers the full spectrum from pod scheduling failures through runtime hangs.

## When to Use

- Pod stuck in Pending, Init, CrashLoopBackOff, or ImagePullBackOff
- Training stops making progress or communication stalls
- Performance is unexpectedly slow
- Pods are being evicted
- Init containers failing or timing out
- Cascading failures after cluster component restarts

## First Response: The Debugging Flowchart

```
Pod not running or misbehaving
  |
  +--> kubectl get events --sort-by=.lastTimestamp -n <ns>
  |      |
  |      +--> FailedScheduling?  --> Check node resources / affinity / taints
  |      +--> FailedMount?       --> Check PVC, secrets, configmaps
  |      +--> ImagePullBackOff?  --> Check registry auth, image tag, network
  |      +--> Webhook error?     --> Check cert-manager / webhook pods
  |
  +--> kubectl describe pod <pod> -n <ns>
  |      |
  |      +--> Init container waiting?  --> kubectl logs <pod> -c <init> -n <ns>
  |      +--> OOMKilled?               --> Check previous termination message
  |      +--> Evicted?                 --> Check node disk/memory pressure
  |
  +--> kubectl logs <pod> -n <ns> --previous
  |
  +--> kubectl describe node <node>   (check Allocatable vs Allocated)
```

## Phase-by-Phase Diagnosis

### Phase 1: Pending

The scheduler cannot place the pod on any node.

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `insufficient nvidia.com/gpu` | GPU requests exceed capacity | Scale node group or reduce request. GPU requests MUST equal limits. |
| `N node(s) had taints that the pod didn't tolerate` | Missing tolerations | Add toleration matching the node taint. |
| `N node(s) didn't match Pod's node affinity/selector` | Label mismatch | Verify labels exist with `kubectl get nodes --show-labels`. |
| Pod pending with no events | Quota exhausted or webhook blocking | Check `kubectl get resourcequotas` and webhook configurations. |

### Phase 2: Init Container Failures

Init containers run sequentially before app containers start.

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `Init:0/N` not progressing | First init container blocked | `kubectl logs <pod> -c <init-container-name>` |
| DNS resolution failure in init | CoreDNS not ready | Check CoreDNS pods. Verify `dnsPolicy` is set correctly. |
| Connection refused to dependency | Service not yet available | Add retry logic or init container that polls readiness. |
| Permission denied / RBAC errors | ServiceAccount lacks permissions | `kubectl auth can-i --as=system:serviceaccount:<ns>:<sa> <verb> <resource>` |

### Phase 3: CrashLoopBackOff

Container starts and exits repeatedly with increasing back-off delay.

| Symptom | Cause | Resolution |
|---------|-------|------------|
| OOMKilled (exit code 137) | Memory limit exceeded | Increase memory limit or fix memory leak. Check `lastState.terminated`. |
| Exit code 1 with config errors | Missing env vars or bad config | `kubectl logs <pod> --previous` to read the error. |
| Exit code 127 | Binary not found | Verify image entrypoint and tag. |
| Rapid restart loop | Liveness probe too aggressive | Increase `initialDelaySeconds` and `failureThreshold`. |

### Phase 4: ImagePullBackOff

Container runtime cannot pull the image.

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `401 Unauthorized` | Registry credentials expired | Re-authenticate with your container registry. |
| `manifest unknown` | Image tag does not exist | Verify exact tag exists in the registry. |
| `i/o timeout` | Network connectivity issue | Check VPC endpoints, NAT gateways, or proxy configuration. |

### Phase 5: Eviction

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `The node was low on resource: ephemeral-storage` | Container images or logs filling disk | Increase root volume, add ephemeral-storage limits, clean images. |
| `The node was low on resource: memory` | Node memory exhausted | Reduce pod memory requests or add nodes. |

## Training-Specific Troubleshooting

### Triage Decision Tree

```
Training hung or slow
  |
  +--> Are logs still being produced?
  |    |
  |    +--> No --> Process hung or crashed
  |    |    +--> Pod Running? --> Deadlocked (get stack trace)
  |    |    +--> CrashLoopBackOff? --> Read previous logs
  |    |    +--> OOMKilled? --> Reduce batch/model size
  |    |
  |    +--> Yes --> Performance issue
  |         +--> Completely stalled at specific step? --> Collective hang
  |         +--> Running but slow? --> Check transport type
```

### Silent Performance Regression (Most Common)

Training runs but 3-4x slower than expected because the communication library silently fell back to TCP sockets instead of RDMA.

**Detection:**
```bash
# Check transport type in logs
kubectl logs <pod> | grep "via NET/"
# GOOD: "via NET/Libfabric/0/GDRDMA"
# BAD:  "via NET/Socket/0"
```

**Fix:** Ensure the network plugin environment variable is set and the plugin library path is in `LD_LIBRARY_PATH`.

### NCCL Timeout

```bash
# Symptom: "NCCL WARN Timeout waiting for connect"

# Check all pods are running and on different nodes
kubectl get pods -l app=training -o wide

# Check master IP reachability
kubectl exec <pod> -- ping -c 1 <master_ip>

# Check rendezvous port
kubectl exec <pod> -- nc -zv <master_ip> 29500
```

**Common fixes:**
- Increase timeout (e.g., `NCCL_TIMEOUT=1800`)
- Verify master IP discovery worked
- Check security groups allow traffic between nodes
- Ensure `hostNetwork: true` is set

### Collective Operation Hang

Training starts successfully but hangs during an AllReduce, Broadcast, or AlltoAll operation.

**Common causes:**
- Hardcoded algorithm selection that is wrong for the topology
- Shared memory too small for intra-node communication
- Not all ranks executing the same collective operations
- Gradient accumulation mismatch across ranks

**Diagnostic approach:**
```bash
# Get Python stack traces from hung process
kubectl exec <pod> -- pip install py-spy 2>/dev/null
kubectl exec <pod> -- py-spy dump --pid $(kubectl exec <pod> -- pgrep -f train)
```

## Systematic Debugging Methodology

### Step 1: Identify the Symptom (0-5 min)

```bash
# Pod status
kubectl get pods -l app=my-workload -o wide

# Recent logs from all pods
for pod in $(kubectl get pods -l app=my-workload -o name); do
  echo "=== $pod ==="
  kubectl logs $pod --tail=50
done

# Events sorted by time
kubectl get events --sort-by=.lastTimestamp -n <namespace> | tail -20
```

### Step 2: Classify the Problem (5-15 min)

| Observation | Classification | Next Action |
|------------|----------------|-------------|
| `via NET/Socket` | TCP fallback | Fix network plugin configuration |
| `Timeout waiting` | Network issue | Check connectivity between nodes |
| Hang after init complete | Collective hang | Check algorithm settings |
| `OOMKilled` | Memory issue | Increase limits or reduce workload |
| `Could not find` plugin | Missing library | Fix LD_LIBRARY_PATH |
| No logs at all | Crash on startup | Check image, volumes, entrypoint |

### Step 3: Isolate with A/B Testing (15-60 min)

```bash
# Test 1: Single node (eliminates networking)
# Reduce replicas to 1 and verify training works

# Test 2: Known-good container image (eliminates software)
# Deploy with a reference/upstream image

# Test 3: Benchmark tool (eliminates application code)
# Run nccl-tests or similar benchmarks

# Test 4: Environment diff (find the configuration difference)
kubectl exec <working-pod> -- printenv | sort > /tmp/working.env
kubectl exec <broken-pod> -- printenv | sort > /tmp/broken.env
diff /tmp/working.env /tmp/broken.env
```

### Step 4: Fix and Verify

```bash
# After applying fix, verify:

# 1. Training process started
kubectl logs <pod> | grep "Init COMPLETE"

# 2. Communication working
kubectl logs <pod> | grep "via NET/" | head -5

# 3. Training progressing
kubectl logs <pod> | grep -E "loss|step|iter" | tail -5

# 4. No errors
kubectl logs <pod> | grep -ciE "error|warn|timeout"
```

## Key Diagnostic Commands

```bash
# Events sorted by time (always check first)
kubectl get events --sort-by=.lastTimestamp -n <namespace>

# Full pod description with events
kubectl describe pod <pod-name> -n <namespace>

# Init container logs
kubectl logs <pod-name> -c <init-container-name> -n <namespace>

# Previous container logs (after crash)
kubectl logs <pod-name> --previous -n <namespace>

# Termination message for OOM analysis
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'

# Node resource usage vs allocatable
kubectl describe node <node> | grep -A20 "Allocated resources"

# All pods in bad state across cluster
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded

# GPU allocation on nodes
kubectl describe nodes | grep -B2 -A3 "nvidia.com/gpu"

# Check all environment variables in a pod
kubectl exec <pod> -- printenv | sort
```

## GPU-Specific Issues

### Ephemeral Storage Pressure

Large ML framework container images (10-30GB) fill the root disk quickly on GPU nodes.

**Detection:**
```bash
kubectl describe node <node> | grep -i "ephemeral\|DiskPressure"
```

**Resolution:**
- Increase root volume size in node launch template (200-500GB)
- Add `ephemeral-storage` requests/limits to pod specs
- Clean build artifacts during pod execution

### GPU Resource Requests Must Equal Limits

Kubernetes does not support GPU overcommit:
```yaml
resources:
  limits:
    nvidia.com/gpu: 8
  requests:
    nvidia.com/gpu: 8   # MUST match limits
```

### CNI IP Allocation Delays

Large GPU instances have most ENIs reserved for high-speed networking. Pod IP allocation can take 2-5 minutes on newly launched nodes.

**Detection:**
```bash
kubectl describe pod <pod> | grep -i "failed to assign an IP"
```

**Resolution:**
- Enable prefix delegation in the VPC CNI
- Set warm IP targets on the CNI DaemonSet
- Allow 2-5 minutes for ENI warm-up on large instances

## Webhook Cascading Failures

When a webhook pod (e.g., cert-manager) is not running, any resource that triggers it will fail with timeout errors, creating cascading failures.

**Detection:**
```bash
kubectl get events -A | grep -i "webhook\|cert-manager"
```

**Resolution:**
1. Identify and restart the failing webhook pods first
2. Wait for readiness checks to pass
3. Retry blocked pod creations

## Environment Variable Audit Script

```bash
#!/bin/bash
# audit-pod-config.sh <pod-name> [namespace]
POD=$1
NS=${2:-default}

echo "=== Configuration Audit for $POD ==="
echo ""

# Check critical variables
for VAR in NCCL_DEBUG NCCL_TIMEOUT MASTER_ADDR WORLD_SIZE NODE_RANK; do
  VAL=$(kubectl exec $POD -n $NS -- printenv $VAR 2>/dev/null)
  if [ -z "$VAL" ]; then
    echo "MISSING: $VAR"
  else
    echo "OK: $VAR=$VAL"
  fi
done

echo ""

# Check GPU count
GPU_COUNT=$(kubectl exec $POD -n $NS -- nvidia-smi -L 2>/dev/null | wc -l)
echo "GPUs: $GPU_COUNT"

# Check RDMA devices
RDMA_COUNT=$(kubectl exec $POD -n $NS -- ls /dev/infiniband/ 2>/dev/null | wc -l)
echo "RDMA devices: $RDMA_COUNT"
```

## Red Herrings (Do Not Waste Time On)

Based on real debugging sessions:

1. **Library version warnings** -- If the library loads and works, version warnings are usually noise.
2. **Optional feature warnings** -- GDRCopy, hugepages, and similar features produce warnings when unavailable but are not required.
3. **Module loading order** -- Kernel modules are host-level. If devices show up in the pod, modules are working.
4. **Documentation version mismatches** -- Test with a known-good reference image before investigating version issues.
