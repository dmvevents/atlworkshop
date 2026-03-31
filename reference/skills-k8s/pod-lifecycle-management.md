---
name: pod-lifecycle-management
description: Use when deploying, monitoring, or debugging pods on Kubernetes. Covers kubectl apply, get, describe, logs, exec, delete workflows, iterative deploy cycles, log scanning, pod monitoring loops, and ConfigMap-based runtime patching.
---

# Pod Lifecycle Management

## Overview

Complete workflows for managing Kubernetes pods through their lifecycle: creation, monitoring, debugging, patching, and teardown. Derived from hundreds of real deploy-debug cycles on GPU training clusters.

## When to Use

- Deploying workloads and watching them come up
- Monitoring running pods (logs, status, GPU utilization)
- Debugging pods stuck in Pending, CrashLoopBackOff, or Error
- Running rapid edit-teardown-deploy iteration cycles
- Patching code inside running pods without image rebuilds
- Injecting configuration via ConfigMaps at runtime

## Core Deploy-Watch-Debug Cycle

```
EDIT YAML --> TEARDOWN old --> DEPLOY new --> WATCH status --> CHECK logs --> iterate
```

### Step 1: Deploy

```bash
kubectl apply -f manifests/my-workload.yaml
```

### Step 2: Watch Status

```bash
# Watch pod creation and scheduling
kubectl get pods -l app=my-workload -o wide -w

# Wait for ready state with timeout
kubectl wait --for=condition=Ready pod -l app=my-workload --timeout=300s

# Watch with timestamps
kubectl get pods -l app=my-workload -w | while read line; do
  echo "$(date +%H:%M:%S) $line"
done
```

### Step 3: Check Logs

```bash
POD=$(kubectl get pods -l app=my-workload -o jsonpath='{.items[0].metadata.name}')

# Tail recent logs
kubectl logs $POD --tail=50

# Stream logs in real time
kubectl logs -f $POD

# Filter for errors
kubectl logs $POD | grep -iE "error|warn|fail|timeout" | head -20

# Filter for progress indicators
kubectl logs $POD | grep -E "step|loss|iter|epoch" | tail -10

# Previous container logs (after a crash)
kubectl logs $POD --previous
```

### Step 4: Teardown for Redeployment

```bash
JOB_NAME=my-job
NS=default

# Delete the job (cascades to pods)
kubectl delete job $JOB_NAME -n $NS --ignore-not-found

# Force-delete orphaned pods stuck in Terminating
kubectl get pods -n $NS -l job-name=$JOB_NAME -o name | \
  xargs -r kubectl delete -n $NS --force --grace-period=0 2>/dev/null

# Wait for cleanup
kubectl wait --for=delete pod -l job-name=$JOB_NAME -n $NS --timeout=30s 2>/dev/null
```

## One-Command Redeploy Script

```bash
#!/bin/bash
# redeploy.sh <yaml-file> [job-name]
YAML=$1
JOB=${2:-$(grep -m1 'name:' $YAML | awk '{print $2}')}
NS=default

echo "=== Teardown ==="
kubectl delete job $JOB -n $NS --ignore-not-found
kubectl get pods -n $NS -l job-name=$JOB -o name | \
  xargs -r kubectl delete -n $NS --force --grace-period=0 2>/dev/null
sleep 3

echo "=== Deploy ==="
kubectl apply -f $YAML

echo "=== Waiting for pods ==="
for i in $(seq 1 30); do
  RUNNING=$(kubectl get pods -l job-name=$JOB -n $NS --no-headers 2>/dev/null | grep -c Running)
  TOTAL=$(kubectl get pods -l job-name=$JOB -n $NS --no-headers 2>/dev/null | wc -l)
  echo "  $RUNNING/$TOTAL running (${i}s)"
  [ "$RUNNING" -gt 0 ] && break
  sleep 2
done

echo "=== Pod Status ==="
kubectl get pods -l job-name=$JOB -n $NS -o wide

echo "=== First Logs ==="
POD=$(kubectl get pods -l job-name=$JOB -n $NS -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$POD" ]; then
  sleep 5
  kubectl logs $POD --tail=30 2>/dev/null
fi
```

## Pod Monitoring Loops

### Stream Logs From All Pods

```bash
#!/bin/bash
# stream-all-logs.sh <label-selector>
SELECTOR=${1:-app=my-workload}

PODS=$(kubectl get pods -l $SELECTOR -o jsonpath='{.items[*].metadata.name}')
for POD in $PODS; do
  kubectl logs -f $POD --prefix 2>&1 &
done
wait
```

### GPU Utilization Dashboard

```bash
#!/bin/bash
# gpu-dashboard.sh <label-selector> [interval]
SELECTOR=${1:-app=my-workload}
INTERVAL=${2:-30}

while true; do
  clear
  echo "=== GPU Dashboard === $(date +%H:%M:%S)"
  echo ""
  for POD in $(kubectl get pods -l $SELECTOR -o jsonpath='{.items[*].metadata.name}'); do
    NODE=$(kubectl get pod $POD -o jsonpath='{.spec.nodeName}')
    echo "--- $POD ($NODE) ---"
    kubectl exec $POD -- nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total \
      --format=csv,noheader 2>/dev/null || echo "  (unavailable)"
    echo ""
  done
  sleep $INTERVAL
done
```

### Training Stall Detector

```bash
#!/bin/bash
# stall-detector.sh <pod-name> [stall-threshold-seconds]
POD=$1
THRESHOLD=${2:-300}

while true; do
  CURRENT_LOG=$(kubectl logs $POD --tail=1 --timestamps 2>/dev/null)
  if [ -n "$CURRENT_LOG" ]; then
    LOG_TIME=$(echo "$CURRENT_LOG" | cut -d' ' -f1)
    LOG_EPOCH=$(date -d "$LOG_TIME" +%s 2>/dev/null || echo 0)
    NOW=$(date +%s)
    SILENCE=$((NOW - LOG_EPOCH))
    if [ $SILENCE -gt $THRESHOLD ]; then
      echo "ALERT: $POD silent for ${SILENCE}s (threshold: ${THRESHOLD}s)"
    fi
  fi
  sleep 30
done
```

### Comprehensive Health Check

```bash
#!/bin/bash
# health-check.sh <label-selector>
SELECTOR=$1

echo "=== Pod Status ==="
kubectl get pods -l $SELECTOR -o wide

echo ""
echo "--- Restart Count ---"
kubectl get pods -l $SELECTOR \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.restartCount}{end}{"\n"}{end}'

echo ""
echo "--- Recent Events ---"
kubectl get events --sort-by='.lastTimestamp' | grep "$(echo $SELECTOR | cut -d= -f2)" | tail -10

echo ""
echo "--- GPU Summary ---"
for POD in $(kubectl get pods -l $SELECTOR -o jsonpath='{.items[*].metadata.name}'); do
  GPU_COUNT=$(kubectl exec $POD -- nvidia-smi -L 2>/dev/null | wc -l)
  AVG_UTIL=$(kubectl exec $POD -- nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader 2>/dev/null | awk '{sum+=$1; n++} END {if(n>0) printf "%.0f", sum/n; else print "N/A"}')
  echo "  $POD: ${GPU_COUNT} GPUs, avg utilization ${AVG_UTIL}%"
done
```

## Live Pod Patching

When you need to iterate on fixes without rebuilding images.

### Copy Files Into a Running Pod

```bash
# Copy a fixed file into the pod
kubectl cp local_fixed_file.py $POD:/path/to/file.py -n $NS

# Copy from pod first to get baseline, edit locally, copy back
kubectl cp $POD:/path/to/file.py ./original.py -n $NS
# ... edit original.py ...
kubectl cp ./original.py $POD:/path/to/file.py -n $NS
```

### In-Pod Code Replacement (Python)

```bash
kubectl exec $POD -- bash -c '
  python3 -c "
c = open(\"/path/to/file.py\").read()
c = c.replace(\"broken_line\", \"fixed_line\")
open(\"/path/to/file.py\", \"w\").write(c)
print(\"Patched successfully\")
"'
```

### Patch All Pods in a Job

```bash
#!/bin/bash
# patch-all-pods.sh <label-selector> <patch-command>
SELECTOR=$1; shift
PATCH_CMD="$@"

for POD in $(kubectl get pods -l $SELECTOR -o jsonpath='{.items[*].metadata.name}'); do
  echo "=== Patching $POD ==="
  kubectl exec $POD -- bash -c "$PATCH_CMD"
done
```

### Safety: Always Backup Before Patching

```bash
kubectl exec $POD -- cp /path/to/file.py /path/to/file.py.bak.$(date +%s)
```

## ConfigMap Runtime Patching

Inject patches or config files into containers at runtime without rebuilding images.

### Create ConfigMap From Files

```bash
kubectl create configmap my-patches \
  --from-file=fix_worker.py=patches/fix_worker.py \
  --from-file=fix_config.py=patches/fix_config.py \
  --dry-run=client -o yaml > manifests/patches-configmap.yaml

kubectl apply -f manifests/patches-configmap.yaml
```

### Mount in Pod Spec

```yaml
volumes:
  - name: patches
    configMap:
      name: my-patches
containers:
  - volumeMounts:
      - name: patches
        mountPath: /opt/patches
        readOnly: true
    command: ["/bin/bash", "-c"]
    args:
      - |
        python3 /opt/patches/fix_worker.py
        python3 /opt/patches/fix_config.py
        exec python3 train.py
```

### Patch Script Best Practices

```python
#!/usr/bin/env python3
"""Each patch must be idempotent."""
target = '/path/to/target.py'
content = open(target).read()

if 'PATCH_V1_MARKER' in content:
    print('Already patched')
    exit(0)

content = content.replace('old_code', 'new_code # PATCH_V1_MARKER')
open(target, 'w').write(content)
print('PATCH_V1_MARKER: Applied')
```

## Config Persistence Warning

Pod-level file changes via `sed`, `echo >`, or manual edits are LOST when:
- Pod is evicted (DiskPressure, OOM, preemption)
- Pod is deleted and recreated
- Node restarts or StatefulSet is redeployed

**Prevention:**
1. Modify source and commit -- do not rely on pod-level edits
2. Use environment variables via ConfigMap or pod spec
3. Bake changes into the Docker image
4. Use ConfigMap mounts for runtime patches

## Iteration Tracking

### Version Your YAML Changes

```bash
git add manifests/my-workload.yaml
git commit -m "iter N: [what changed] - [result]"
```

### Keep an Iteration Log

```markdown
| # | Change | Result | Status |
|---|--------|--------|--------|
| 1 | Initial deploy | Pods pending | Failed |
| 2 | Add GPU limits | Running, timeout | Failed |
| 3 | Fix env vars | Working | Success |
```

### One Change Per Iteration

Change one thing at a time. If you change five things and it works, you do not know which one fixed it. If you change five things and it breaks, you do not know which one broke it.

## Avoiding Deployment Thrashing

Use the fastest method available for each type of change:

| Method | Time | When to Use |
|--------|------|-------------|
| `kubectl set env` | ~60s | Environment variable experiments |
| `kubectl patch configmap` | ~30s | Config file changes |
| `kubectl exec -- sed/python` | ~5s | One-line code tweaks |
| `kubectl delete + apply` | ~5 min | Schema changes |
| Docker rebuild + push + redeploy | ~15-30 min | Source code or library changes |

**Self-check:** If your ratio of kubectl ops to actual test results exceeds 5:1, stop and fix your experiment loop.
