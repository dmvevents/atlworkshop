---
name: helm-deployment-patterns
description: Use when deploying applications via Helm charts on Kubernetes. Covers chart installation, values overrides, dry-run validation, rollback, upgrade patterns, and managing GPU workload Helm releases.
---

# Helm Deployment Patterns

## Overview

Patterns for deploying and managing Kubernetes workloads via Helm charts, with emphasis on GPU training infrastructure, operator installations, and iterative configuration tuning. Covers the full lifecycle from dry-run through rollback.

## When to Use

- Installing or upgrading Helm chart releases
- Overriding chart values for GPU workloads
- Performing dry-run validation before deployment
- Rolling back failed releases
- Managing multiple releases across namespaces
- Installing Kubernetes operators (GPU, monitoring, networking)

## Core Helm Workflow

```
ADD REPO --> INSPECT VALUES --> CUSTOMIZE --> DRY-RUN --> INSTALL --> VERIFY --> (UPGRADE/ROLLBACK)
```

## Phase 1: Repository and Chart Discovery

### Add and Update Repositories

```bash
# Add a chart repository
helm repo add my-charts https://charts.example.com
helm repo update

# Search for charts
helm search repo my-charts/
helm search repo gpu --versions

# Show chart information
helm show chart my-charts/training-operator
helm show readme my-charts/training-operator
```

### Inspect Default Values

```bash
# View all configurable values
helm show values my-charts/training-operator > default-values.yaml

# View values from a specific version
helm show values my-charts/training-operator --version 1.2.3
```

## Phase 2: Customize Values

### Values Override File

Create a `values-override.yaml` for your environment:

```yaml
# values-override.yaml
replicaCount: 2

image:
  repository: <registry>/my-training
  tag: v20260331
  pullPolicy: IfNotPresent

resources:
  limits:
    nvidia.com/gpu: 8
    memory: 900Gi
  requests:
    nvidia.com/gpu: 8
    memory: 800Gi
    cpu: 90

# GPU-specific settings
gpu:
  enabled: true
  count: 8

# Shared memory for NCCL
volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 256Gi

nodeSelector:
  node.kubernetes.io/instance-type: <gpu-instance-type>

tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule

# Environment variables
env:
  NCCL_DEBUG: "INFO"
  NCCL_TIMEOUT: "1800"
```

### Inline Value Overrides

```bash
# Override individual values on the command line
helm install my-release my-charts/app \
  --set image.tag=v2.0 \
  --set resources.limits.nvidia\.com/gpu=8 \
  --set nodeSelector.node\.kubernetes\.io/instance-type=<type>
```

### Multiple Value Files (Layered)

```bash
# Base + environment-specific overrides
helm install my-release my-charts/app \
  -f values-base.yaml \
  -f values-gpu.yaml \
  -f values-production.yaml
# Later files override earlier ones
```

## Phase 3: Dry-Run Validation

Always dry-run before deploying:

```bash
# Client-side dry-run (template rendering only)
helm install my-release my-charts/app \
  -f values-override.yaml \
  --dry-run \
  --debug

# Server-side dry-run (validates against cluster)
helm install my-release my-charts/app \
  -f values-override.yaml \
  --dry-run=server

# Save rendered manifests for review
helm template my-release my-charts/app \
  -f values-override.yaml > rendered-manifests.yaml

# Diff against existing release (requires helm-diff plugin)
helm diff upgrade my-release my-charts/app \
  -f values-override.yaml
```

### What to Check in Dry-Run Output

```bash
# Verify GPU resources are correct
grep -A5 "nvidia.com/gpu" rendered-manifests.yaml

# Verify node selector
grep -A3 "nodeSelector" rendered-manifests.yaml

# Verify volume mounts (shared memory, device paths)
grep -A10 "volumeMounts" rendered-manifests.yaml

# Verify environment variables
grep -A20 "env:" rendered-manifests.yaml
```

## Phase 4: Install

```bash
# Install with namespace creation
helm install my-release my-charts/app \
  --namespace ml-training \
  --create-namespace \
  -f values-override.yaml \
  --wait \
  --timeout 10m

# Install with atomic (auto-rollback on failure)
helm install my-release my-charts/app \
  --namespace ml-training \
  -f values-override.yaml \
  --atomic \
  --timeout 10m
```

### Verify Installation

```bash
# Check release status
helm status my-release -n ml-training

# List all releases
helm list -n ml-training

# Check pods created by the release
kubectl get pods -n ml-training -l app.kubernetes.io/instance=my-release

# Check events
kubectl get events -n ml-training --sort-by=.lastTimestamp | tail -20
```

## Phase 5: Upgrade

```bash
# Upgrade with new values
helm upgrade my-release my-charts/app \
  --namespace ml-training \
  -f values-override.yaml \
  --wait \
  --timeout 10m

# Upgrade with reuse of existing values + overrides
helm upgrade my-release my-charts/app \
  --namespace ml-training \
  --reuse-values \
  --set image.tag=v2.1

# Upgrade with atomic rollback on failure
helm upgrade my-release my-charts/app \
  --namespace ml-training \
  -f values-override.yaml \
  --atomic \
  --timeout 10m
```

### Check Upgrade History

```bash
# View release history
helm history my-release -n ml-training

# See what changed between revisions
helm get values my-release -n ml-training --revision 1 > rev1-values.yaml
helm get values my-release -n ml-training --revision 2 > rev2-values.yaml
diff rev1-values.yaml rev2-values.yaml
```

## Phase 6: Rollback

```bash
# Rollback to previous revision
helm rollback my-release -n ml-training

# Rollback to specific revision
helm rollback my-release 3 -n ml-training

# Rollback with wait for pods
helm rollback my-release -n ml-training --wait --timeout 5m
```

## Common Operator Installations

### GPU Device Plugin / Operator

```bash
# Example: NVIDIA GPU Operator
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace \
  --set driver.enabled=true \
  --set toolkit.enabled=true \
  --set devicePlugin.enabled=true \
  --wait --timeout 15m
```

### Monitoring Stack

```bash
# Prometheus + Grafana
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f values-monitoring.yaml \
  --wait --timeout 10m
```

### Training Operator (Kubeflow)

```bash
# PyTorchJob / TFJob support
helm repo add kubeflow https://kubeflow.github.io/training-operator
helm repo update

helm install training-operator kubeflow/training-operator \
  --namespace kubeflow \
  --create-namespace \
  --wait
```

## Helm Values Patterns for GPU Workloads

### Shared Memory and Device Mounts

```yaml
# values-gpu.yaml
extraVolumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 256Gi
  - name: dev-infiniband
    hostPath:
      path: /dev/infiniband

extraVolumeMounts:
  - name: dshm
    mountPath: /dev/shm
  - name: dev-infiniband
    mountPath: /dev/infiniband
```

### Host Networking for RDMA

```yaml
hostNetwork: true
dnsPolicy: ClusterFirstWithHostNet
```

### Pod Anti-Affinity for Multi-Node

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: training
      topologyKey: kubernetes.io/hostname
```

## Troubleshooting Helm

### Release Stuck in Pending-Install

```bash
# Check for failed hooks
kubectl get jobs -n <namespace> | grep hook

# Force delete the release
helm uninstall my-release -n <namespace> --no-hooks

# Or delete the stuck secret
kubectl delete secret -n <namespace> -l name=my-release,owner=helm,status=pending-install
```

### Values Not Taking Effect

```bash
# Check actual values applied
helm get values my-release -n <namespace>

# Check computed (merged) values
helm get values my-release -n <namespace> --all

# Common causes:
# 1. --reuse-values with conflicting -f override
# 2. Chart version changed the values schema
# 3. Values file has wrong indentation
```

### Upgrade Fails With Immutable Field Error

```bash
# Some fields (like selector labels) are immutable
# Solution: Uninstall and reinstall
helm uninstall my-release -n <namespace>
helm install my-release my-charts/app -f values-override.yaml -n <namespace>

# Or delete the specific resource and let Helm recreate it
kubectl delete statefulset <name> -n <namespace> --cascade=orphan
helm upgrade my-release my-charts/app -f values-override.yaml -n <namespace>
```

## Useful Helm Plugins

```bash
# helm-diff: Show changes before upgrade
helm plugin install https://github.com/databus23/helm-diff
helm diff upgrade my-release my-charts/app -f values.yaml

# helm-secrets: Manage encrypted values files
helm plugin install https://github.com/jkroepke/helm-secrets

# helm-whatup: Check for chart updates
helm plugin install https://github.com/fabmation-gmbh/helm-whatup
```

## Best Practices

1. **Always use values files** instead of `--set` for reproducibility
2. **Version control your values files** alongside your manifests
3. **Use `--atomic`** for production deployments (auto-rollback on failure)
4. **Dry-run before every install/upgrade** to catch configuration errors
5. **Pin chart versions** in production (`--version 1.2.3`)
6. **Use namespaces** to isolate releases
7. **Check release history** before debugging (it may be a rollback issue)
8. **Template and review** rendered manifests for GPU resource correctness
