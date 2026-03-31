#!/usr/bin/env bash
# Quick smoke test for NemoClaw against the Dynamo endpoint.
# Usage:
#   ./test_nemoclaw.sh                    # uses port-forward
#   DYNAMO_ENDPOINT=http://host:port ./test_nemoclaw.sh   # custom endpoint
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If no endpoint set, start port-forward
if [[ -z "${DYNAMO_ENDPOINT:-}" ]]; then
    echo "[test] Starting port-forward to qwen-coder-frontend..."
    kubectl port-forward -n workshop svc/qwen-coder-frontend 8084:8000 &
    PF_PID=$!
    trap "kill $PF_PID 2>/dev/null || true" EXIT
    sleep 3
    export DYNAMO_ENDPOINT="http://localhost:8084"
fi

echo "[test] Endpoint: $DYNAMO_ENDPOINT"

# Test 1: Health check
echo ""
echo "=== Test 1: Health Check ==="
curl -s "${DYNAMO_ENDPOINT}/v1/models" | python3 -m json.tool

# Test 2: Single inference call
echo ""
echo "=== Test 2: Single Inference ==="
python3 -c "
import sys, os
os.environ['DYNAMO_ENDPOINT'] = '${DYNAMO_ENDPOINT}'
os.environ['DYNAMO_MODEL'] = 'Qwen/Qwen2.5-Coder-7B-Instruct'
sys.path.insert(0, '${SCRIPT_DIR}')
from nemoclaw_dynamo_agent import ask_nemoclaw, dynamo_health_check
ok, msg = dynamo_health_check()
print(f'Health: {\"OK\" if ok else \"FAIL\"} -- {msg}')
resp = ask_nemoclaw('Say hello and confirm you are NemoClaw running on Dynamo.')
print(f'Response: {resp}')
"

# Test 3: Latency
echo ""
echo "=== Test 3: Latency (3 calls) ==="
python3 -c "
import time, sys, os
os.environ['DYNAMO_ENDPOINT'] = '${DYNAMO_ENDPOINT}'
os.environ['DYNAMO_MODEL'] = 'Qwen/Qwen2.5-Coder-7B-Instruct'
sys.path.insert(0, '${SCRIPT_DIR}')
from nemoclaw_dynamo_agent import ask_nemoclaw
for i in range(3):
    start = time.time()
    resp = ask_nemoclaw(f'Test {i+1}: What is {i+2} * {i+3}?')
    elapsed = time.time() - start
    print(f'Call {i+1}: {elapsed:.2f}s -- {resp[:80]}')
"

echo ""
echo "=== All tests passed ==="
