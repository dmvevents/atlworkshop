# Multi-Model Dispatch Configuration

> Pattern for querying multiple frontier LLMs from the command line
> and synthesizing their responses for higher-confidence answers.

## Overview

When a single model's analysis is insufficient -- complex debugging, architectural
decisions, or hardware-constrained systems -- dispatch the same question to 3-5
frontier models in parallel and synthesize their responses.

**Key insight:** Different models have different blind spots. Cross-model consensus
dramatically reduces hallucination risk.

## Architecture

```
                     +---> Model A (e.g., Gemini) ---> response-a.txt
                     |
query-model.sh ------+---> Model B (e.g., GPT)    ---> response-b.txt
                     |
                     +---> Model C (e.g., Claude)  ---> response-c.txt
                     |
                     +---> Model D (e.g., Codex)   ---> response-d.txt

All responses land in /tmp/results/
Synthesizer (you or an agent) reads all, finds consensus
```

## Setup

### 1. Create Environment File

Create `~/.env.local_deployment` with your API keys:

```bash
# Google Gemini (required for Gemini models)
# Get key from: https://aistudio.google.com/apikey
export GOOGLE_API_KEY="your-google-api-key-here"

# OpenAI (required for GPT and reasoning models)
# Get key from: https://platform.openai.com/api-keys
export OPENAI_API_KEY="your-openai-api-key-here"

# AWS Bedrock (required for Claude via Bedrock)
# Configure via: aws configure
export AWS_REGION="us-east-2"
export AWS_PROFILE="default"

# Optional: Groq (for fast inference + web search)
# Get key from: https://console.groq.com/keys
export GROQ_API_KEY="your-groq-api-key-here"
```

**SECURITY:** Never commit this file to git. Add to `.gitignore`:
```
.env.local_deployment
.env
*.key
```

### 2. Install the Query Script

Create `scripts/multi-model/query-model.sh`:

```bash
#!/bin/bash
# query-model.sh - Multi-model API query tool
# Usage:
#   ./query-model.sh <model> "Your prompt here"
#   ./query-model.sh <model> @/path/to/prompt-file.md
#   cat prompt.txt | ./query-model.sh <model> -

set -euo pipefail

# Load API keys
if [[ -f ~/.env.local_deployment ]]; then
    source ~/.env.local_deployment
fi

MODEL="${1:?Usage: query-model.sh <model> <prompt|-|@file>}"
shift

# Handle input: direct string, stdin (-), or file (@path)
PROMPT_FILE=$(mktemp /tmp/query-model-prompt.XXXXXX)
trap 'rm -f "$PROMPT_FILE"' EXIT

INPUT="$*"
if [[ "$INPUT" == "-" ]]; then
    cat > "$PROMPT_FILE"
elif [[ "$INPUT" == @* ]]; then
    cp "${INPUT:1}" "$PROMPT_FILE"
else
    printf '%s' "$INPUT" > "$PROMPT_FILE"
fi

MAX_TOKENS="${MAX_TOKENS:-32768}"

case "$MODEL" in
    gemini-pro)
        # Google Gemini Pro with thinking + search grounding
        [[ -z "${GOOGLE_API_KEY:-}" ]] && { echo "ERROR: GOOGLE_API_KEY not set" >&2; exit 1; }

        python3 -c "
import json, sys, urllib.request
prompt = open('$PROMPT_FILE').read()
payload = {
    'contents': [{'parts': [{'text': prompt}]}],
    'generationConfig': {'maxOutputTokens': int('$MAX_TOKENS')},
    'tools': [{'googleSearch': {}}]
}
data = json.dumps(payload).encode()
url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=${GOOGLE_API_KEY}'
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
resp = json.loads(urllib.request.urlopen(req, timeout=600).read())
parts = resp.get('candidates',[{}])[0].get('content',{}).get('parts',[])
for p in parts:
    if 'text' in p: print(p['text'])
"
        ;;

    gpt)
        # OpenAI GPT with reasoning
        [[ -z "${OPENAI_API_KEY:-}" ]] && { echo "ERROR: OPENAI_API_KEY not set" >&2; exit 1; }
        REASONING_EFFORT="${REASONING_EFFORT:-high}"

        python3 -c "
import json, sys, urllib.request
prompt = open('$PROMPT_FILE').read()
payload = {
    'model': 'gpt-4.1',
    'max_completion_tokens': int('$MAX_TOKENS'),
    'messages': [{'role': 'user', 'content': prompt}]
}
data = json.dumps(payload).encode()
req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=data,
    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ${OPENAI_API_KEY}'})
resp = json.loads(urllib.request.urlopen(req, timeout=600).read())
print(resp.get('choices',[{}])[0].get('message',{}).get('content',''))
"
        ;;

    claude)
        # Claude via AWS Bedrock
        python3 -c "
import boto3, json, sys
from botocore.config import Config
prompt = open('$PROMPT_FILE').read()
client = boto3.client('bedrock-runtime', region_name='${AWS_REGION:-us-east-2}',
    config=Config(read_timeout=600, retries={'max_attempts': 1}))
resp = client.converse(
    modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
    messages=[{'role': 'user', 'content': [{'text': prompt}]}],
    inferenceConfig={'maxTokens': int('$MAX_TOKENS')}
)
print(resp['output']['message']['content'][0]['text'])
"
        ;;

    *)
        echo "Unknown model: $MODEL" >&2
        echo "Available: gemini-pro, gpt, claude" >&2
        exit 1
        ;;
esac
```

```bash
chmod +x scripts/multi-model/query-model.sh
```

### 3. Create Parallel Dispatch Script

Create `scripts/multi-model/dispatch-all.sh`:

```bash
#!/bin/bash
# dispatch-all.sh - Query all configured models in parallel
# Usage: ./dispatch-all.sh "Your prompt" OR ./dispatch-all.sh @prompt.md

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULTS_DIR="/tmp/multi-llm-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULTS_DIR"

echo "Dispatching to all models..."
echo "Results directory: $RESULTS_DIR"

$SCRIPT_DIR/query-model.sh gemini-pro "$@" > "$RESULTS_DIR/gemini-pro.txt" 2>&1 &
$SCRIPT_DIR/query-model.sh gpt "$@" > "$RESULTS_DIR/gpt.txt" 2>&1 &
$SCRIPT_DIR/query-model.sh claude "$@" > "$RESULTS_DIR/claude.txt" 2>&1 &

wait
echo "All models complete. Results in: $RESULTS_DIR"
ls -lh "$RESULTS_DIR"
```

## Usage Patterns

### Basic: Single Model Query

```bash
./query-model.sh gemini-pro "What causes memory leaks in Python async generators?"
```

### From File (Large Prompts)

```bash
./query-model.sh gpt @/path/to/detailed-prompt.md
```

### From Stdin (Pipe)

```bash
cat code.py | ./query-model.sh claude -
```

### Parallel: All Models at Once

```bash
./dispatch-all.sh "Compare React Server Components vs Astro Islands for our use case"
```

### Multi-Round Consensus

```bash
# Round 1: Independent analysis
mkdir -p /tmp/consensus/r1
./query-model.sh gemini-pro @prompt.md > /tmp/consensus/r1/gemini.txt &
./query-model.sh gpt @prompt.md > /tmp/consensus/r1/gpt.txt &
./query-model.sh claude @prompt.md > /tmp/consensus/r1/claude.txt &
wait

# Round 2: Cross-model synthesis (each model sees all Round 1 responses)
cat prompt.md /tmp/consensus/r1/*.txt > /tmp/consensus/r2-prompt.md
# Add instruction: "Review all proposals above. Produce unified recommendation."
./dispatch-all.sh @/tmp/consensus/r2-prompt.md
```

## The 4-Layer Prompt Template

For debugging, structure prompts in 4 layers for best results:

```markdown
## LAYER A: IMMUTABLE FACTS (never change, always include)
[Verified platform/hardware constraints]
[Prevents model hallucinations about your specific environment]

## LAYER B: ATTEMPT REGISTRY (compact, append-only)
| Version | Hypothesis | Change | Result | Verdict |
|---------|-----------|--------|--------|---------|
| v1 | Timeout too short | Increased to 30s | Still fails | falsified |
| v2 | Race condition | Added mutex | Passes 90% | partial |

### BANLIST (never try again)
- [Approaches conclusively proven to fail, with WHY]

## LAYER C: CURRENT STATE (changes every iteration)
- Build info, current metrics, recent diffs, log excerpts

## LAYER D: FOCUSED QUESTION (narrow, implementable)
- Current hypothesis (one sentence)
- Specific question (leads to implementable fix)
- Constraints (must reference specific code, must not suggest banned approaches)
```

**Why this works:** Models weight early sections highest. Putting ground truth
first reduces hallucinations. The attempt registry prevents models from
suggesting things you've already tried.

## Consensus Decision Framework

| Consensus Level | Signal | Action |
|----------------|--------|--------|
| **Strong** (3/3 agree) | Same root cause, same fix | Implement immediately |
| **Moderate** (2/3 agree) | Similar direction, different details | Implement majority view, test carefully |
| **Weak** (all disagree) | Fundamental disagreement | Need more data. Profile/instrument first. |
| **Red flag** | All models make same wrong assumption | Your prompt is missing critical context |

## Cost Management

| Model | Approx Cost per 100K Input | Best For |
|-------|---------------------------|----------|
| Gemini Pro | $0.30-1.50 | Large context, code generation, web grounding |
| GPT | $1.00-5.00 | Architecture, reasoning, cross-validation |
| Claude (Bedrock) | $0.50-3.00 | Systematic analysis, careful reasoning |

**Cost optimization tips:**
- Start with 2 models for quick checks ($2-5)
- Use 3+ models only for critical decisions ($10-20)
- Set `MAX_TOKENS` appropriately (don't default to max)
- Reuse prompt files across rounds (save on prompt engineering time)
- Stop early if strong consensus reached in Round 1

## Security Reminders

- NEVER commit API keys to version control
- Use environment variable files excluded from git
- Rotate keys periodically
- Set spending limits on all API provider dashboards
- Review API usage weekly to catch unexpected costs
