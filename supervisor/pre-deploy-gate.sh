#!/bin/bash
# pre-deploy-gate.sh — CUCo L0/L1 evaluation gate before deployment
#
# Runs the CUCo cascaded-eval.py with --skip-deploy to perform:
#   L0: Parse check (balanced braces, includes, EVOLVE-BLOCK markers)
#   L1: Compile check (nvcc compilation)
#
# Returns 0 if the candidate passes both gates, 1 on failure.
# Can be called by the supervisor or by an agent before deploying kernel changes.
#
# Usage:
#   ./pre-deploy-gate.sh /path/to/candidate.cu
#   ./pre-deploy-gate.sh /path/to/candidate.cu --results-dir /tmp/gate-results
#   ./pre-deploy-gate.sh /path/to/candidate.cu --id my-variant-01
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUCO_EVAL="${SCRIPT_DIR}/../cuco-codesign/evaluation/cascaded-eval.py"
DEFAULT_RESULTS_DIR="${SCRIPT_DIR}/logs/gate-results"

usage() {
    echo "Usage: $0 <candidate.cu> [--results-dir DIR] [--id ID]"
    echo ""
    echo "Run CUCo L0 (parse) + L1 (compile) evaluation gate on a .cu candidate."
    echo ""
    echo "Arguments:"
    echo "  candidate.cu     Path to the CUDA kernel file to validate"
    echo "  --results-dir    Directory for evaluation results (default: ${DEFAULT_RESULTS_DIR})"
    echo "  --id             Candidate ID (auto-generated from content hash if omitted)"
    echo ""
    echo "Returns:"
    echo "  0  Candidate passes L0 + L1 (safe to deploy)"
    echo "  1  Candidate fails (error diagnostics printed to stderr)"
    exit 1
}

if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
fi

CANDIDATE="$1"
shift

# Parse optional arguments
RESULTS_DIR="$DEFAULT_RESULTS_DIR"
CANDIDATE_ID=""
while [ $# -gt 0 ]; do
    case "$1" in
        --results-dir)
            RESULTS_DIR="$2"
            shift 2
            ;;
        --id)
            CANDIDATE_ID="$2"
            shift 2
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage
            ;;
    esac
done

# Validate inputs
if [ ! -f "$CANDIDATE" ]; then
    echo "ERROR: Candidate file not found: $CANDIDATE" >&2
    exit 1
fi

if [ ! -f "$CUCO_EVAL" ]; then
    echo "ERROR: CUCo evaluator not found: $CUCO_EVAL" >&2
    echo "Expected at: cuco-codesign/evaluation/cascaded-eval.py" >&2
    exit 1
fi

# Ensure results directory exists
mkdir -p "$RESULTS_DIR"

# Build the evaluator command
CMD=(python3 "$CUCO_EVAL" "$CANDIDATE" --skip-deploy --results-dir "$RESULTS_DIR")
if [ -n "$CANDIDATE_ID" ]; then
    CMD+=(--id "$CANDIDATE_ID")
fi

echo "[PRE-DEPLOY-GATE] Evaluating: $CANDIDATE"
echo "[PRE-DEPLOY-GATE] Running L0 (parse) + L1 (compile) checks..."

# Run the evaluator and capture output
OUTPUT=$("${CMD[@]}" 2>&1) || true

# Parse the JSON result
PASSED=$(echo "$OUTPUT" | python3 -c "
import sys, json
try:
    # The evaluator prints JSON to stdout; find the JSON object
    lines = sys.stdin.read()
    # Find the JSON block (starts with '{')
    start = lines.find('{')
    if start == -1:
        print('false')
        sys.exit(0)
    data = json.loads(lines[start:])
    passed = data.get('passed', False)
    level = data.get('level_reached', 'unknown')
    error = data.get('error_message', '')
    diag = data.get('diagnostics', '')

    if passed:
        print('true')
    else:
        print('false')
        # Print diagnostics to stderr
        if error:
            print(f'  Level: {level}', file=sys.stderr)
            print(f'  Error: {error}', file=sys.stderr)
        if diag:
            print(f'  Diagnostics:', file=sys.stderr)
            for line in diag.split(chr(10)):
                print(f'    {line}', file=sys.stderr)
except Exception as e:
    print('false')
    print(f'  Parse error: {e}', file=sys.stderr)
" 2>&1)

# Extract pass/fail from first line
RESULT_LINE=$(echo "$PASSED" | head -1)
DIAG_LINES=$(echo "$PASSED" | tail -n +2)

if [ "$RESULT_LINE" = "true" ]; then
    echo "[PRE-DEPLOY-GATE] PASSED: L0 + L1 checks OK"
    exit 0
else
    echo "[PRE-DEPLOY-GATE] FAILED: Candidate did not pass pre-deploy gate" >&2
    if [ -n "$DIAG_LINES" ]; then
        echo "$DIAG_LINES" >&2
    fi
    # Also dump raw evaluator output for debugging
    echo "[PRE-DEPLOY-GATE] Raw evaluator output:" >&2
    echo "$OUTPUT" >&2
    exit 1
fi
