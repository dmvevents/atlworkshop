# HPC Agent Stack Configuration

Configuration files for the full agent toolkit: MCP servers, multi-model gateways, code search, RAG, and Claude Code integration.

## Quick Setup (5 minutes)

```bash
# 1. Copy and fill in API keys
cp .env.example .env
nano .env  # Add your keys (see "Getting API Keys" below)
source .env

# 2. Copy MCP server config into Claude Code
#    Replace <HPC_STACK_ROOT> with your actual install path
sed "s|<HPC_STACK_ROOT>|$(pwd)/..|g" claude-settings.json > /tmp/mcp-config.json
# Then merge into ~/.claude/settings.json or ~/.claude.json
```

## Getting API Keys

| Service | Free Tier | Where to Get Key |
|---------|-----------|-----------------|
| **Google Gemini** | Yes (free tier generous) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **OpenAI** | No ($5 minimum) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Tavily** | Yes (1000/month) | [tavily.com](https://tavily.com) |
| **Semantic Scholar** | Yes (unlimited) | [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api) |
| **OpenRouter** | No (pay-per-use) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **GitHub** | Yes (free for public repos) | [github.com/settings/tokens](https://github.com/settings/tokens) |
| **RAGFlow** | Self-hosted (free) | Auto-generated on setup |
| **LiteLLM** | Self-hosted (free) | Auto-generated on setup |
| **AWS Bedrock** | Pay-per-use (IAM auth) | Use IAM role on EC2 (no key needed) |

**Minimum to get started:** Google Gemini key (free) + OpenAI key ($5). Everything else is optional.

---

## Files in This Directory

### `.env.example` -- API Keys Template

Environment variables for all services. Copy to `.env` and fill in your keys.

```bash
cp .env.example .env
source .env
```

### `claude-settings.json` -- MCP Server Configuration

Configures 15 MCP servers for Claude Code. Each server gives Claude a new capability:

| MCP Server | What It Does | Install | Port |
|------------|-------------|---------|------|
| **zoekt-search** | Trigram code search across repositories (instant grep over millions of lines) | `go install github.com/sourcegraph/zoekt/cmd/...@latest` | 6070 |
| **opengrok-search** | Symbol cross-reference (go-to-definition, find-references across repos) | [Docker](https://github.com/oracle/opengrok) | 8080 |
| **ragflow-query** | RAG over your documents (upload PDFs, docs, code -- ask questions) | `docker-compose -f ragflow-compose.yml up -d` | 9380 |
| **tavily-search** | AI-optimized web search (better than Google for technical queries) | API key only (no install) | API |
| **semantic-scholar** | Search 200M+ academic papers by topic, author, citation | API key only (optional) | API |
| **codegraph-context** | Call chain analysis (who calls what, data flow through functions) | Node.js (included) | stdio |
| **openrouter-gateway** | Access 300+ LLM models via single API (Gemini, GPT, Claude, Llama, etc.) | API key only | API |
| **litellm-proxy** | Self-hosted multi-model gateway with cost tracking and routing | `pip install litellm` | 4000 |
| **efa-gpu-docs** | Knowledge base of 47+ EFA/NCCL/GPU documents (searchable RAG) | Python (included) | stdio |
| **github** | GitHub operations (issues, PRs, code search, file read) | `brew install github/gh/gh-mcp-server` | stdio |
| **kubernetes** | Kubernetes operations (pods, deployments, logs, exec) | `npm install -g kubernetes-mcp-server` | stdio |
| **cplusplus-analysis** | C++ AST analysis via libclang (type checking, symbol resolution) | Python + libclang | stdio |
| **k8s-gpu** | NVIDIA GPU introspection for K8s (device status, memory, utilization) | Node.js (included) | stdio |
| **nccl-log-parser** | Parse NCCL debug logs (collective operations, ring topology, errors) | Python (included) | stdio |
| **context7** | Real-time library documentation (latest docs for any npm/pip package) | `npx` (auto-install) | stdio |

**How to use:** After configuring, Claude Code automatically discovers and uses these tools when relevant. Ask "search the codebase for X" and zoekt-search activates. Ask "what does this function call?" and codegraph-context activates.

### `litellm-config.yaml` -- Multi-Model Gateway

Routes requests to 10+ models across Google, OpenAI, and AWS Bedrock through a single endpoint.

```bash
# Install
pip install litellm

# Start (runs on port 4000)
litellm --config config/litellm-config.yaml --port 4000

# Test
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemini-3-pro", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Models available through LiteLLM:**

| Model Alias | Provider | Best For |
|------------|----------|----------|
| `gemini-3-pro` | Google | Code generation, 1M context analysis |
| `gemini-3-flash` | Google | Fast classification, summarization |
| `gemini-2.5-pro` | Google | Strong reasoning, long context |
| `gpt-5.2` | OpenAI | Frontier reasoning |
| `gpt-5` | OpenAI | SWE-bench 74.4% |
| `o3` | OpenAI | Complex reasoning chains |
| `o3-pro` | OpenAI | Highest-quality reasoning |
| `gpt-4.1` | OpenAI | Fast, capable general model |
| `o4-mini` | OpenAI | Cost-effective reasoning |
| `claude-sonnet` | AWS Bedrock | Deep analysis (IAM auth) |

### `ragflow-compose.yml` -- RAG Document Server

Self-hosted RAG server for searching your own documents.

```bash
# Start RAGFlow
docker-compose -f ragflow-compose.yml up -d

# Open web UI
open http://localhost:9380

# Upload documents (PDF, Markdown, code files)
# Then ask questions via the MCP server
```

**Use cases:**
- Upload API documentation and ask "How do I configure X?"
- Upload architecture docs and ask "What component handles Y?"
- Upload research papers and ask "What are the tradeoffs of Z?"

### `zoekt-config.yaml` -- Code Search Engine

Trigram-based code search (like grep, but instant over millions of lines).

```bash
# Install Zoekt
go install github.com/sourcegraph/zoekt/cmd/zoekt-webserver@latest
go install github.com/sourcegraph/zoekt/cmd/zoekt-git-index@latest

# Index a repository
zoekt-git-index -index ~/.zoekt /path/to/your/repo

# Start the web server (port 6070)
zoekt-webserver -index ~/.zoekt -listen :6070

# Test
curl "http://localhost:6070/api/search?q=def+main"
```

**Configuration options in `zoekt-config.yaml`:**
- Branches to index (main, develop, feature branches)
- File size limits (skip binaries, minified files)
- Exclude patterns (node_modules, vendor, __pycache__)
- Ctags symbol indexing (go-to-definition for C/C++/Python/Rust/Go/Java)
- Incremental indexing (only re-index changed files)

---

## Multi-Model Query Script

The `query-model.sh` script lets you query any model from the command line:

```bash
# Set path (adjust to your install)
Q=/path/to/hpc-agent-stack/scripts/multi-model/query-model.sh

# Query individual models
$Q gemini-3-pro "Explain the visitor pattern in C++"
$Q gpt-5.4 "Find bugs in this code: $(cat myfile.py)"
$Q claude-think "Debug this NCCL hang: $(cat nccl.log)"

# Pipe file content
cat architecture.md | $Q gemini-3-pro -

# Run parallel consensus (same question to 3 models)
$Q gpt-5.4 "question" > /tmp/gpt.txt &
$Q gemini-3-pro "question" > /tmp/gemini.txt &
$Q claude-think "question" > /tmp/claude.txt &
wait
# Compare the three answers
```

---

## Installation Order (Recommended)

### Phase 1: Essentials (10 minutes)
1. Get a Google Gemini API key (free) and OpenAI key ($5)
2. Copy `.env.example` to `.env`, add keys
3. Configure `claude-settings.json` with your paths
4. You now have: multi-model queries, web search, academic search

### Phase 2: Code Search (15 minutes)
5. Install Zoekt (`go install`)
6. Index your repositories
7. Start Zoekt server on port 6070
8. You now have: instant code search across all repos

### Phase 3: Self-Hosted Services (20 minutes)
9. Start LiteLLM proxy (`pip install litellm && litellm --config ...`)
10. Start RAGFlow (`docker-compose up -d`)
11. Upload documents to RAGFlow
12. You now have: unified model gateway + document RAG

### Phase 4: K8s & GitHub Integration (5 minutes)
13. Install GitHub MCP server
14. Install Kubernetes MCP server
15. You now have: full GitHub + K8s integration from Claude Code

---

## Architecture

```
Your Terminal
    |
    v
Claude Code CLI
    |
    +---> MCP Servers (stdio) ─────────────────────────────────┐
    |       |                                                   |
    |       +-- zoekt-search ─────── Zoekt Server (:6070)       |
    |       +-- opengrok-search ──── OpenGrok (:8080)           |
    |       +-- ragflow-query ────── RAGFlow (:9380)            |
    |       +-- tavily-search ────── Tavily API (cloud)         |
    |       +-- semantic-scholar ─── S2 API (cloud)             |
    |       +-- openrouter-gateway── OpenRouter API (cloud)     |
    |       +-- litellm-proxy ────── LiteLLM Proxy (:4000)     |
    |       +-- github ───────────── GitHub API (cloud)         |
    |       +-- kubernetes ───────── kubectl (local)            |
    |       +-- cplusplus-analysis── libclang (local)           |
    |       +-- nccl-log-parser ──── Python (local)             |
    |       +-- k8s-gpu ──────────── kubectl (local)            |
    |       +-- context7 ─────────── Upstash API (cloud)        |
    |       +-- codegraph-context ── Node.js (local)            |
    |       +-- efa-gpu-docs ─────── FastMCP + 47 docs (local)  |
    |                                                           |
    +---> Multi-Model Query Script ────────────────────────────┘
            |
            +-- gemini-3-pro (Google)
            +-- gpt-5.4 (OpenAI)
            +-- claude-think (AWS Bedrock)
            +-- o3, o4-mini, codex-5.4 (OpenAI)
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| MCP server not loading | Check path in `claude-settings.json` -- must be absolute |
| "API key not found" | Run `source .env` before starting Claude Code |
| Zoekt returns no results | Run `zoekt-git-index` to index your repos first |
| LiteLLM won't start | Check port 4000 isn't in use: `lsof -i :4000` |
| RAGFlow slow to start | First startup downloads models -- wait 2-3 minutes |
| GitHub MCP fails | Generate a PAT with `repo` scope at github.com/settings/tokens |
| K8s MCP fails | Ensure `kubectl` is configured: `kubectl cluster-info` |

## Links

| Resource | URL |
|----------|-----|
| Claude Code Docs | [docs.anthropic.com/en/docs/claude-code](https://docs.anthropic.com/en/docs/claude-code) |
| MCP Protocol Spec | [modelcontextprotocol.io](https://modelcontextprotocol.io) |
| Zoekt | [github.com/sourcegraph/zoekt](https://github.com/sourcegraph/zoekt) |
| LiteLLM | [github.com/BerriAI/litellm](https://github.com/BerriAI/litellm) |
| RAGFlow | [github.com/infiniflow/ragflow](https://github.com/infiniflow/ragflow) |
| OpenGrok | [github.com/oracle/opengrok](https://github.com/oracle/opengrok) |
| Tavily | [tavily.com](https://tavily.com) |
| Semantic Scholar API | [api.semanticscholar.org](https://api.semanticscholar.org) |
| OpenRouter | [openrouter.ai](https://openrouter.ai) |
| GitHub MCP Server | [github.com/github/github-mcp-server](https://github.com/github/github-mcp-server) |
| Kubernetes MCP | [github.com/manusa/kubernetes-mcp-server](https://github.com/manusa/kubernetes-mcp-server) |
| Context7 | [github.com/upstash/context7](https://github.com/upstash/context7) |
