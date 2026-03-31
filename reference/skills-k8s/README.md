# Kubernetes Skills Reference

Generalized Kubernetes skills for GPU workload management. These skills cover the full lifecycle of deploying, monitoring, debugging, and operating GPU training workloads on Kubernetes clusters.

## Skills Index

| Skill | File | Use When |
|-------|------|----------|
| Pod Lifecycle Management | [pod-lifecycle-management.md](pod-lifecycle-management.md) | Deploying, monitoring, debugging, or patching pods. Rapid edit-teardown-deploy cycles. Log streaming and GPU dashboards. ConfigMap-based runtime patching. |
| GPU Node Operations | [gpu-node-operations.md](gpu-node-operations.md) | Managing GPU nodes: checking GPU availability, loading kernel modules without SSH, fixing device plugin issues, handling disk pressure, building and pushing container images. |
| Distributed Training on K8s | [distributed-training-k8s.md](distributed-training-k8s.md) | Deploying multi-node GPU training with StatefulSets, headless services, rank computation, master IP discovery, RDMA device mounts, and torchrun configuration. |
| K8s Troubleshooting | [k8s-troubleshooting.md](k8s-troubleshooting.md) | Pods stuck in Pending/CrashLoopBackOff/ImagePullBackOff, training hangs, silent performance regressions, OOMKilled, DNS issues, and systematic debugging methodology. |
| Helm Deployment Patterns | [helm-deployment-patterns.md](helm-deployment-patterns.md) | Installing or upgrading Helm charts, values overrides for GPU workloads, dry-run validation, rollback, operator installations, and release management. |

## Quick Decision Guide

**"My pod will not start"**
Start with [k8s-troubleshooting.md](k8s-troubleshooting.md) -- it has a flowchart that covers Pending, CrashLoopBackOff, OOMKilled, ImagePullBackOff, and webhook failures.

**"I need to deploy multi-node training"**
Start with [distributed-training-k8s.md](distributed-training-k8s.md) -- it has complete StatefulSet templates, master IP discovery patterns, and torchrun configuration.

**"My training is running but slow or hanging"**
Start with [k8s-troubleshooting.md](k8s-troubleshooting.md) -- the training-specific section covers silent TCP fallback, NCCL timeouts, collective hangs, and A/B isolation methodology.

**"I need to iterate quickly on a fix"**
Start with [pod-lifecycle-management.md](pod-lifecycle-management.md) -- it covers the rapid redeploy cycle, live pod patching, ConfigMap injection, and deployment thrashing avoidance.

**"My GPU nodes are misbehaving"**
Start with [gpu-node-operations.md](gpu-node-operations.md) -- it covers kubectl debug for node access, kernel module loading, device plugin troubleshooting, and disk pressure management.

**"I need to install an operator or chart"**
Start with [helm-deployment-patterns.md](helm-deployment-patterns.md) -- it covers the full Helm lifecycle from repo add through rollback, with GPU-specific values patterns.

## Skill Frontmatter Format

Each skill uses this frontmatter format for integration with AI coding assistants:

```yaml
---
name: skill-name
description: Use when [trigger conditions describing when this skill is relevant]
---
```

The `description` field serves as a trigger -- when a user's task matches the described conditions, the skill content should be loaded for reference.

## Source

These skills are generalized from production patterns observed across GPU training clusters running on Kubernetes. Company-specific details, internal IPs, account IDs, and project names have been removed.
