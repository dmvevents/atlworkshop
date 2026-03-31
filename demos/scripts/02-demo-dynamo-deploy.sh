#!/bin/bash
# =============================================================================
# 02-demo-dynamo-deploy.sh - Part 2: Deploy Dynamo on EKS
# Mastering Agentic Coding & GPUs Workshop
# =============================================================================
# Demonstrates deploying NVIDIA Dynamo for disaggregated LLM inference:
#   1. Install Dynamo operator via Helm (or apply CRDs)
#   2. Deploy etcd and NATS for service discovery and messaging
#   3. Deploy a model with disaggregated prefill/decode serving
#   4. Send a test inference request
#   5. Verify EFA activation in logs
#
# NOTE: This script uses placeholder values for model names and registry.
#       Replace all <TODO: ...> markers before running against a real cluster.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Configuration -- TODO: Replace placeholders before running
# ---------------------------------------------------------------------------
NAMESPACE="${WORKSHOP_NS:-workshop-agentic}"
DYNAMO_HELM_REPO="<TODO: DYNAMO_HELM_REPO_URL>"       # e.g., https://helm.ngc.nvidia.com/nvidia/dynamo
DYNAMO_CHART_VERSION="<TODO: CHART_VERSION>"            # e.g., 0.1.0
DYNAMO_IMAGE="<TODO: REGISTRY/IMAGE:TAG>"               # e.g., nvcr.io/nvidia/dynamo:latest
MODEL_NAME="<TODO: MODEL_NAME>"                         # e.g., meta-llama/Llama-3.1-8B-Instruct
NGC_API_KEY="<TODO: NGC_API_KEY>"                       # NEVER commit real keys
FRONTEND_PORT=8000
PREFILL_GPUS=1                                          # GPUs per prefill worker
DECODE_GPUS=1                                           # GPUs per decode worker
EFA_ADAPTERS=0                                          # Set >0 for multi-node EFA

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
step() {
    echo ""
    echo -e "${BOLD}${MAGENTA}--- Step $1: $2 ---${NC}"
    echo ""
}

run_show() {
    echo -e "${CYAN}\$ $*${NC}"
    eval "$@"
    echo ""
}

pause() {
    echo ""
    echo -e "${YELLOW}[Press ENTER to continue...]${NC}"
    read -r
}

wait_for_ready() {
    local label="$1"
    local timeout="${2:-180}"
    echo -e "${DIM}  Waiting up to ${timeout}s for pods with label '${label}' to be Ready...${NC}"
    kubectl wait pods -n "$NAMESPACE" -l "$label" \
        --for=condition=Ready --timeout="${timeout}s" 2>/dev/null || {
        echo -e "${YELLOW}  Pods not ready within ${timeout}s -- check: kubectl get pods -n ${NAMESPACE}${NC}"
        return 1
    }
    echo -e "  ${GREEN}Ready.${NC}"
}

check_placeholder() {
    local value="$1"
    local name="$2"
    if [[ "$value" == *"<TODO:"* ]]; then
        echo -e "${RED}ERROR: ${name} still contains a placeholder.${NC}"
        echo -e "       Edit this script and replace <TODO: ...> markers before running."
        return 1
    fi
}

header() {
    echo -e "${BOLD}============================================${NC}"
    echo -e "${BOLD}  Part 2: Deploy Dynamo on EKS${NC}"
    echo -e "${BOLD}  Disaggregated LLM Inference${NC}"
    echo -e "${BOLD}============================================${NC}"
    echo ""
    echo -e "  Namespace:  ${NAMESPACE}"
    echo -e "  Model:      ${MODEL_NAME}"
    echo -e "  Prefill:    ${PREFILL_GPUS} GPU(s)"
    echo -e "  Decode:     ${DECODE_GPUS} GPU(s)"
    echo -e "  EFA:        ${EFA_ADAPTERS} adapter(s)"
    echo ""
}

# ---------------------------------------------------------------------------
# Pre-flight: Check that namespace exists
# ---------------------------------------------------------------------------
header

echo -e "${BOLD}Pre-flight${NC}"
if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
    echo -e "  Creating namespace ${NAMESPACE}..."
    kubectl create namespace "$NAMESPACE"
fi
kubectl label namespace "$NAMESPACE" workshop=mastering-agentic-coding --overwrite >/dev/null 2>&1 || true
echo -e "  ${GREEN}Namespace '${NAMESPACE}' ready.${NC}"

pause

# ==========================================================================
# Step 1: Install Dynamo Operator via Helm
# ==========================================================================
step 1 "Install Dynamo Operator"

echo -e "${DIM}  The Dynamo operator manages DynamoGraphDeployment CRDs that orchestrate${NC}"
echo -e "${DIM}  disaggregated serving components (frontend, prefill, decode workers).${NC}"
echo ""

# TODO: Uncomment and fill in real Helm repo details
# check_placeholder "$DYNAMO_HELM_REPO" "DYNAMO_HELM_REPO"

echo -e "${YELLOW}  [DRY-RUN] The following commands would install the Dynamo operator:${NC}"
echo ""
echo -e "${CYAN}  # Add the Dynamo Helm repository${NC}"
echo -e "${CYAN}  helm repo add dynamo ${DYNAMO_HELM_REPO}${NC}"
echo -e "${CYAN}  helm repo update${NC}"
echo ""
echo -e "${CYAN}  # Install the operator${NC}"
echo -e "${CYAN}  helm install dynamo-operator dynamo/dynamo-operator \\${NC}"
echo -e "${CYAN}    --namespace ${NAMESPACE} \\${NC}"
echo -e "${CYAN}    --version ${DYNAMO_CHART_VERSION} \\${NC}"
echo -e "${CYAN}    --set image.pullPolicy=Always \\${NC}"
echo -e "${CYAN}    --wait --timeout 120s${NC}"
echo ""

# Alternative: Apply CRDs directly
echo -e "${DIM}  Alternative -- apply CRDs directly:${NC}"
echo -e "${CYAN}  kubectl apply -f demos/manifests/dynamo-workshop.yaml -n ${NAMESPACE}${NC}"

pause

# ==========================================================================
# Step 2: Deploy etcd and NATS
# ==========================================================================
step 2 "Deploy etcd and NATS"

echo -e "${DIM}  etcd: Service discovery -- workers register themselves, frontend finds them.${NC}"
echo -e "${DIM}  NATS: Message bus -- routes inference requests between components.${NC}"
echo ""

# Deploy etcd (stateless for workshop -- NOT production-ready)
echo -e "  Deploying etcd (stateless, workshop-only)..."
cat <<'ETCD_EOF' | kubectl apply -n "$NAMESPACE" -f -
apiVersion: v1
kind: Service
metadata:
  name: dynamo-etcd
  labels:
    app: etcd
    component: workshop
spec:
  type: ClusterIP
  ports:
    - name: client
      port: 2379
      targetPort: 2379
    - name: peer
      port: 2380
      targetPort: 2380
  selector:
    app: etcd
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dynamo-etcd
  labels:
    app: etcd
    component: workshop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: etcd
  template:
    metadata:
      labels:
        app: etcd
        component: workshop
    spec:
      containers:
      - name: etcd
        image: quay.io/coreos/etcd:v3.5.17
        env:
        - name: ETCD_NAME
          value: "etcd-0"
        - name: ETCD_DATA_DIR
          value: "/etcd-data"
        - name: ETCD_LISTEN_CLIENT_URLS
          value: "http://0.0.0.0:2379"
        - name: ETCD_ADVERTISE_CLIENT_URLS
          value: "http://dynamo-etcd:2379"
        - name: ETCD_LISTEN_PEER_URLS
          value: "http://0.0.0.0:2380"
        - name: ETCD_INITIAL_ADVERTISE_PEER_URLS
          value: "http://etcd-0:2380"
        - name: ETCD_INITIAL_CLUSTER
          value: "etcd-0=http://etcd-0:2380"
        - name: ETCD_INITIAL_CLUSTER_STATE
          value: "new"
        ports:
        - containerPort: 2379
          name: client
        - containerPort: 2380
          name: peer
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /health
            port: 2379
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: data
          mountPath: /etcd-data
      volumes:
      - name: data
        emptyDir: {}
ETCD_EOF
echo -e "  ${GREEN}etcd deployed.${NC}"

# Deploy NATS
echo -e "  Deploying NATS..."
cat <<'NATS_EOF' | kubectl apply -n "$NAMESPACE" -f -
apiVersion: v1
kind: Service
metadata:
  name: dynamo-nats
  labels:
    app: nats
    component: workshop
spec:
  type: ClusterIP
  ports:
    - name: client
      port: 4222
      targetPort: 4222
    - name: monitoring
      port: 8222
      targetPort: 8222
  selector:
    app: nats
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dynamo-nats
  labels:
    app: nats
    component: workshop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nats
  template:
    metadata:
      labels:
        app: nats
        component: workshop
    spec:
      containers:
      - name: nats
        image: nats:2.10-alpine
        args: ["-js", "-m", "8222"]
        ports:
        - containerPort: 4222
          name: client
        - containerPort: 8222
          name: monitoring
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8222
          initialDelaySeconds: 5
          periodSeconds: 5
NATS_EOF
echo -e "  ${GREEN}NATS deployed.${NC}"

echo ""
echo -e "  Checking deployment status..."
run_show kubectl get pods -n "$NAMESPACE" -l "component=workshop"

pause

# ==========================================================================
# Step 3: Deploy Model with Disaggregated Serving
# ==========================================================================
step 3 "Deploy Disaggregated Model (Prefill + Decode)"

echo -e "${DIM}  Dynamo splits inference into two phases:${NC}"
echo -e "${DIM}    - Prefill: processes the full input prompt (compute-heavy)${NC}"
echo -e "${DIM}    - Decode: generates tokens one-by-one (memory-bandwidth-bound)${NC}"
echo -e "${DIM}  NIXL transfers the KV cache between prefill and decode workers.${NC}"
echo ""

MANIFEST_DIR="$(cd "$DEMO_DIR/../manifests" && pwd)"

echo -e "${YELLOW}  [DRY-RUN] The following would deploy the model:${NC}"
echo ""
echo -e "${CYAN}  kubectl apply -f ${MANIFEST_DIR}/dynamo-workshop.yaml -n ${NAMESPACE}${NC}"
echo ""
echo -e "  This manifest creates:"
echo -e "    - ConfigMap with model configuration and environment"
echo -e "    - Frontend Service (ClusterIP, port ${FRONTEND_PORT})"
echo -e "    - Frontend Deployment (no GPU)"
echo -e "    - Prefill Worker Deployment (${PREFILL_GPUS} GPU)"
echo -e "    - Decode Worker Deployment (${DECODE_GPUS} GPU)"
echo ""

echo -e "${DIM}  Key environment variables for disaggregated serving:${NC}"
echo -e "    DYN_ROUTER_MODE=kv              # KV-cache-aware routing"
echo -e "    BACKEND_MODULE=dynamo.trtllm    # TensorRT-LLM backend"
echo -e "    DYNAMO_ETCD_ENDPOINTS=dynamo-etcd:2379"
echo -e "    DYNAMO_NATS_URL=nats://dynamo-nats:4222"
echo ""

if [[ "$EFA_ADAPTERS" -gt 0 ]]; then
    echo -e "${DIM}  EFA configuration (for multi-node KV cache transfer):${NC}"
    echo -e "    vpc.amazonaws.com/efa: \"${EFA_ADAPTERS}\""
    echo -e "    FI_EFA_USE_DEVICE_RDMA=1"
    echo -e "    FI_PROVIDER=efa"
    echo -e "    NIXL_LIBFABRIC_MAX_RAILS=8"
fi

pause

# ==========================================================================
# Step 4: Send Test Inference Request
# ==========================================================================
step 4 "Send Test Inference Request"

echo -e "${DIM}  Once the frontend is running, send an OpenAI-compatible request.${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Port-forward and send request:${NC}"
echo ""
echo -e "${CYAN}  # Port-forward the frontend service${NC}"
echo -e "${CYAN}  kubectl port-forward -n ${NAMESPACE} svc/dynamo-frontend ${FRONTEND_PORT}:${FRONTEND_PORT} &${NC}"
echo ""
echo -e "${CYAN}  # Send an inference request (OpenAI-compatible API)${NC}"
echo -e "${CYAN}  curl -s http://localhost:${FRONTEND_PORT}/v1/chat/completions \\${NC}"
echo -e "${CYAN}    -H 'Content-Type: application/json' \\${NC}"
echo -e "${CYAN}    -d '{${NC}"
echo -e "${CYAN}      \"model\": \"${MODEL_NAME}\",${NC}"
echo -e "${CYAN}      \"messages\": [{\"role\": \"user\", \"content\": \"Hello, what is EFA?\"}],${NC}"
echo -e "${CYAN}      \"max_tokens\": 128,${NC}"
echo -e "${CYAN}      \"stream\": false${NC}"
echo -e "${CYAN}    }'${NC}"
echo ""

echo -e "${DIM}  Expected response (mock):${NC}"
echo '  {
    "id": "chatcmpl-workshop-001",
    "object": "chat.completion",
    "choices": [{
      "message": {
        "role": "assistant",
        "content": "EFA (Elastic Fabric Adapter) is a network interface for Amazon EC2 instances that enables high-performance inter-node communication using the Scalable Reliable Datagram (SRD) protocol..."
      },
      "finish_reason": "stop"
    }]
  }'

pause

# ==========================================================================
# Step 5: Verify EFA Activation in Logs
# ==========================================================================
step 5 "Verify EFA Activation in Logs"

echo -e "${DIM}  After deploying with EFA, verify that NIXL/libfabric is using EFA correctly.${NC}"
echo ""

echo -e "${YELLOW}  [DRY-RUN] Check EFA logs on a worker pod:${NC}"
echo ""
echo -e "${CYAN}  # Get the prefill worker pod name${NC}"
echo -e "${CYAN}  PREFILL_POD=\$(kubectl get pods -n ${NAMESPACE} -l component=prefill -o name | head -1)${NC}"
echo ""
echo -e "${CYAN}  # Check for EFA provider initialization${NC}"
echo -e "${CYAN}  kubectl logs -n ${NAMESPACE} \$PREFILL_POD | grep -i 'efa\\|libfabric\\|nixl\\|rdma'${NC}"
echo ""

echo -e "${DIM}  Expected EFA activation log lines:${NC}"
echo -e "  ${GREEN}  [libfabric] Using provider: efa${NC}"
echo -e "  ${GREEN}  [NIXL] Registered 8 EFA rails${NC}"
echo -e "  ${GREEN}  [NIXL] GPU Direct RDMA: enabled${NC}"
echo -e "  ${GREEN}  [NIXL] KV cache transfer: prefill -> decode via RDMA${NC}"
echo ""

echo -e "${DIM}  Also check EFA hardware counters on the node:${NC}"
echo -e "${CYAN}  kubectl exec -n ${NAMESPACE} \$PREFILL_POD -- \\${NC}"
echo -e "${CYAN}    cat /sys/class/infiniband/rdmap0s6/ports/1/hw_counters/rdma_read_resp_bytes${NC}"
echo ""
echo -e "${DIM}  Non-zero rdma_read_resp_bytes confirms EFA RDMA is active.${NC}"

pause

# ==========================================================================
# Summary
# ==========================================================================
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  Part 2 Complete: Dynamo on EKS${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo -e "  What we deployed:"
echo -e "    1. ${BOLD}etcd${NC}     -- service discovery for Dynamo components"
echo -e "    2. ${BOLD}NATS${NC}     -- message bus for request routing"
echo -e "    3. ${BOLD}Frontend${NC} -- OpenAI-compatible API endpoint"
echo -e "    4. ${BOLD}Prefill${NC}  -- prompt processing worker (GPU)"
echo -e "    5. ${BOLD}Decode${NC}   -- token generation worker (GPU)"
echo ""
echo -e "  Architecture: Frontend -> KV Router -> Prefill/Decode via NIXL"
echo ""
echo -e "  Next: ${CYAN}03-demo-openclaw.sh${NC} -- Deploy OpenClaw Gateway"
echo ""
