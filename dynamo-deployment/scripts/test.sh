#!/bin/bash
set -euo pipefail

# =============================================================================
# test.sh — Test the deployed Dynamo coding model
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

NAMESPACE="${NAMESPACE:-workshop}"
PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ -n "$result" ] && [ "$result" != "null" ]; then
        echo -e "  ${GREEN}PASS${NC}: $name"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC}: $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Dynamo Inference Tests ==="
echo ""

# Setup port-forward
kubectl port-forward -n "$NAMESPACE" svc/qwen-coder-frontend 8086:8000 &
PF=$!
sleep 3
URL="http://localhost:8086"

# Test 1: Models endpoint
MODEL_ID=$(curl -s "$URL/v1/models" 2>/dev/null | jq -r '.data[0].id' 2>/dev/null)
check "Models endpoint returns model" "$MODEL_ID"

# Test 2: Simple math
MATH=$(curl -s "$URL/v1/chat/completions" -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"What is 12*13? Just the number.\"}],\"max_tokens\":5,\"temperature\":0}" 2>/dev/null \
    | jq -r '.choices[0].message.content' 2>/dev/null)
check "Math (12*13=156): got '$MATH'" "$(echo "$MATH" | grep -o '156')"

# Test 3: Code generation
CODE=$(curl -s "$URL/v1/chat/completions" -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a Python function called fibonacci that returns the nth fibonacci number. Just code.\"}],\"max_tokens\":150,\"temperature\":0}" 2>/dev/null \
    | jq -r '.choices[0].message.content' 2>/dev/null)
check "Code generation (fibonacci)" "$(echo "$CODE" | grep -o 'def.*fibonacci')"

# Test 4: Streaming
STREAM=$(curl -s "$URL/v1/chat/completions" -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}],\"max_tokens\":10,\"stream\":true}" 2>/dev/null | head -3)
check "Streaming" "$(echo "$STREAM" | grep -o 'data:')"

# Test 5: Latency
START=$(date +%s%N)
curl -s "$URL/v1/chat/completions" -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL_ID\",\"messages\":[{\"role\":\"user\",\"content\":\"Hi\"}],\"max_tokens\":5}" > /dev/null 2>&1
END=$(date +%s%N)
LATENCY=$(( (END - START) / 1000000 ))
check "Latency < 500ms (got ${LATENCY}ms)" "$([ "$LATENCY" -lt 500 ] && echo "ok")"

kill $PF 2>/dev/null

echo ""
echo "Results: $PASS passed, $FAIL failed out of $((PASS + FAIL)) tests"
[ "$FAIL" -eq 0 ] && echo -e "${GREEN}ALL TESTS PASSED${NC}" || echo -e "${RED}SOME TESTS FAILED${NC}"
