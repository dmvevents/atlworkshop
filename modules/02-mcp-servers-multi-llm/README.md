# Module 2: MCP Servers and Multi-LLM Orchestration

**Duration:** 15 minutes
**Prerequisites:** Module 1 completed, API keys for at least one provider (Google AI Studio or OpenAI)

---

## 1. MCP Server Architecture

The **Model Context Protocol (MCP)** is an open standard that lets AI agents connect to external tools and data sources. Think of it as USB for AI -- a standardized interface so any agent can use any tool.

### Core Concepts

```
Claude Code (Host)
    |
    |-- MCP Protocol (JSON-RPC 2.0)
    |
    |-- Transport Layer
    |   |-- stdio: Server runs as a child process, communicates via stdin/stdout
    |   |-- SSE:   Server runs as HTTP service, communicates via Server-Sent Events
    |
    |-- Primitives
        |-- Tools:     Functions the agent can call (search, query, deploy)
        |-- Resources: Data the agent can read (files, database records)
        |-- Prompts:   Pre-built prompt templates the server provides
```

### How It Works

1. Claude Code starts an MCP server as a child process (stdio transport)
2. The server advertises its available tools via the `tools/list` method
3. Claude Code sees these tools alongside its built-in ones (Read, Write, Bash, etc.)
4. When the agent decides to use a tool, it sends a `tools/call` request
5. The server executes the operation and returns the result

### Configuration

MCP servers are configured in `~/.claude.json` (global) or `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "my-search": {
      "command": "node",
      "args": ["/path/to/my-search-server/server.js"],
      "env": {
        "API_KEY": "your-key-here"
      }
    }
  }
}
```

Each server entry has:
- **command**: The executable to run
- **args**: Command-line arguments
- **env**: Environment variables passed to the server process

---

## 2. Building Your First MCP Server

Let us build a simple MCP server that provides code search functionality using grep as the backend.

### Step 1: Create the project

```bash
mkdir -p my-code-search-mcp
cd my-code-search-mcp
npm init -y
npm install @modelcontextprotocol/sdk
```

### Step 2: Write the server

Create `server.js`:

```javascript
#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { execSync } from "child_process";

// Create the MCP server
const server = new Server(
  { name: "code-search", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// Define available tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_code",
      description: "Search for patterns in source code files using regex",
      inputSchema: {
        type: "object",
        properties: {
          pattern: {
            type: "string",
            description: "Regex pattern to search for",
          },
          directory: {
            type: "string",
            description: "Directory to search in (default: current dir)",
          },
          file_type: {
            type: "string",
            description: "File extension filter, e.g. 'py', 'ts', 'go'",
          },
        },
        required: ["pattern"],
      },
    },
    {
      name: "list_files",
      description: "List files in a directory matching a glob pattern",
      inputSchema: {
        type: "object",
        properties: {
          directory: { type: "string", description: "Directory to list" },
          pattern: { type: "string", description: "Glob pattern (e.g. *.py)" },
        },
        required: ["directory"],
      },
    },
  ],
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "search_code": {
      const dir = args.directory || ".";
      const typeFilter = args.file_type
        ? `--include='*.${args.file_type}'`
        : "";
      try {
        const result = execSync(
          `grep -rn ${typeFilter} '${args.pattern}' '${dir}' | head -50`,
          { encoding: "utf-8", timeout: 10000 }
        );
        return {
          content: [{ type: "text", text: result || "No matches found." }],
        };
      } catch (e) {
        return {
          content: [
            { type: "text", text: e.stdout || "No matches found." },
          ],
        };
      }
    }

    case "list_files": {
      const pattern = args.pattern || "*";
      try {
        const result = execSync(
          `find '${args.directory}' -name '${pattern}' -type f | head -100`,
          { encoding: "utf-8", timeout: 10000 }
        );
        return {
          content: [{ type: "text", text: result || "No files found." }],
        };
      } catch (e) {
        return {
          content: [{ type: "text", text: "Error listing files: " + e.message }],
        };
      }
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

// Start the server with stdio transport
const transport = new StdioServerTransport();
await server.connect(transport);
```

### Step 3: Add to `package.json`

```json
{
  "name": "my-code-search-mcp",
  "version": "1.0.0",
  "type": "module",
  "bin": { "code-search-mcp": "server.js" }
}
```

### Step 4: Register with Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "code-search": {
      "command": "node",
      "args": ["/absolute/path/to/my-code-search-mcp/server.js"]
    }
  }
}
```

### Step 5: Test it

```bash
# Test with the MCP Inspector
npx @anthropic-ai/mcp-inspector node server.js

# Or start Claude Code and the tool appears automatically
claude
# Ask: "Search for all TODO comments in the src directory"
```

---

## 3. The HPC Agent Stack MCP Ecosystem

A production agent stack uses multiple MCP servers working together. Here is the configuration from a real 14-server deployment:

### MCP Server Configuration (`~/.claude.json`)

```json
{
  "mcpServers": {
    "zoekt-search": {
      "command": "node",
      "args": ["/path/to/mcp-servers/zoekt-search/server.js"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    },
    "opengrok-search": {
      "command": "node",
      "args": ["/path/to/mcp-servers/opengrok-search/server.js"],
      "env": { "OPENGROK_URL": "http://localhost:8080" }
    },
    "semantic-scholar": {
      "command": "node",
      "args": ["/path/to/mcp-servers/semantic-scholar/server.js"],
      "env": { "S2_API_KEY": "" }
    },
    "tavily-search": {
      "command": "node",
      "args": ["/path/to/mcp-servers/tavily-search/server.js"],
      "env": { "TAVILY_API_KEY": "tvly-YOUR_KEY_HERE" }
    },
    "codegraph-context": {
      "command": "node",
      "args": ["/path/to/mcp-servers/codegraph-context/server.js"],
      "env": {
        "CGC_WORKSPACE": "/path/to/your/codebase/src",
        "CGC_DB_PATH": "/home/user/.codegraph"
      }
    },
    "ragflow-query": {
      "command": "node",
      "args": ["/path/to/mcp-servers/ragflow-query/server.js"],
      "env": {
        "RAGFLOW_URL": "http://localhost:9380",
        "RAGFLOW_API_KEY": "YOUR_RAGFLOW_KEY"
      }
    },
    "openrouter-gateway": {
      "command": "node",
      "args": ["/path/to/mcp-servers/openrouter-gateway/server.js"],
      "env": {
        "OPENROUTER_API_KEY": "sk-or-YOUR_KEY_HERE",
        "OPENROUTER_DEFAULT_MODEL": "google/gemini-2.5-pro"
      }
    },
    "litellm-proxy": {
      "command": "node",
      "args": ["/path/to/mcp-servers/litellm-proxy/server.js"],
      "env": {
        "LITELLM_PROXY_URL": "http://localhost:4000",
        "LITELLM_API_KEY": "YOUR_KEY",
        "LITELLM_DEFAULT_MODEL": "gemini/gemini-3-pro-preview"
      }
    },
    "efa-gpu-docs": {
      "command": "python3",
      "args": ["/path/to/mcp-servers/efa-gpu-docs/server.py"],
      "env": {}
    }
  }
}
```

### What Each Server Provides

| Server | Tools | Backend | Purpose |
|--------|-------|---------|---------|
| **zoekt-search** | `search_code`, `list_repos` | Zoekt trigram index | Fast regex code search across repos |
| **opengrok-search** | `get_xref`, `search_symbol` | OpenGrok | Symbol cross-reference and definition lookup |
| **semantic-scholar** | `search_papers`, `get_citations` | Semantic Scholar API | Find academic papers and citation graphs |
| **tavily-search** | `search`, `search_github` | Tavily API | Web search and GitHub code search |
| **codegraph-context** | `get_call_chain`, `get_callers` | Local AST analysis | Function call graphs and dependency chains |
| **ragflow-query** | `query_docs` | RAGFlow + vector DB | RAG over internal documentation |
| **openrouter-gateway** | `chat`, `route_task` | OpenRouter API | Access 300+ LLMs via single key |
| **litellm-proxy** | `chat`, `batch_complete` | Self-hosted LiteLLM | Unified gateway to Google/OpenAI/Bedrock |
| **efa-gpu-docs** | `search_gpu_docs`, `read_gpu_doc` | Local markdown files | Domain-specific knowledge base (47+ docs) |

### Context Window Warning

Each MCP tool description consumes tokens from your context window. With 14 servers, you could lose 30-50% of your 200K context to tool descriptions alone.

**Best practice:** Disable servers you are not using in the current project:

```json
{
  "disabledMcpServers": ["ragflow-query", "opengrok-search", "efa-gpu-docs"]
}
```

Rule of thumb: Keep under 10 MCP servers and under 80 total tools active.

---

## 4. Multi-LLM Orchestration

Why query multiple models? Because no single model is best at everything.

### Model Strengths

| Model | Provider | Strength | Best For |
|-------|----------|----------|----------|
| **Gemini 3 Pro** | Google | 1M+ context, search grounding, thinking | Large codebase analysis, research |
| **GPT-5.4** | OpenAI | Strong reasoning, code generation | Implementation, structured analysis |
| **Codex 5.4** | OpenAI | Code-specialized reasoning | Code review, refactoring |
| **Claude Opus 4.6** | AWS Bedrock | Extended thinking, deep reasoning | Architecture, complex debugging |
| **Gemini 3 Flash** | Google | Fast, cheap | Classification, summarization |

### When to Use Multiple Models

| Scenario | Why Multi-Model Helps |
|----------|----------------------|
| **Debugging platform issues** | Models hallucinate about hardware capabilities. Cross-validate. |
| **Security review** | Different models catch different vulnerability classes. |
| **Architecture decisions** | Get diverse perspectives before committing. |
| **Verifying a fix** | The model that wrote the fix is biased. Ask another to review it. |

### The Consensus Pattern

Send the same prompt to 3+ models. Compare answers. Where they agree, you have high confidence. Where they disagree, you found the areas that need human judgment.

```
Prompt: "Is EFA SRD guaranteed to deliver RDMA writes in order?"

Gemini 3 Pro:  "No, SRD does not guarantee ordering."     <-- CORRECT
GPT-5.4:       "Yes, RDMA writes are ordered."              <-- WRONG
Claude Opus:   "No, SRD is unordered. Use fences."          <-- CORRECT

Consensus: 2/3 say no. Verified against docs: NO ordering.
```

Without consensus, you might have trusted the wrong model and built on a false assumption.

---

## 5. Hands-on: Multi-Model Dispatch

The `query-model.sh` script provides direct API access to frontier models from the command line.

### Setup

```bash
# Clone the agent toolkit (or use the workshop copy)
cd /path/to/agent-toolkit

# Configure API keys
cp config/.env.example ~/.env.local_deployment
```

Edit `~/.env.local_deployment`:

```bash
# Get from https://aistudio.google.com/apikey
GOOGLE_API_KEY=AIza...your-key-here

# Get from https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-...your-key-here

# AWS Bedrock (for Claude models) -- uses default AWS credentials
AWS_REGION=us-east-2
```

### Query Individual Models

```bash
Q=./scripts/multi-model/query-model.sh

# Google Gemini 3 Pro (thinking + search grounding)
$Q gemini-3-pro "Explain the visitor pattern in Go with a code example"

# OpenAI GPT-5.4 (reasoning mode)
$Q gpt-5.4 "Review this function for bugs: $(cat myfile.py)"

# Claude Opus 4.6 with extended thinking
$Q claude-think "Design a rate limiter that handles distributed deployments"

# Read prompt from file (avoids shell escaping issues)
$Q gemini-3-pro @analysis-prompt.md

# Pipe large content via stdin
cat entire-codebase.txt | $Q gemini-3-pro -

# Control output length
MAX_TOKENS=65536 $Q gpt-5.4 "Generate a comprehensive test suite for..."
```

### Compare Models Side-by-Side

```bash
Q=./scripts/multi-model/query-model.sh
PROMPT="What are the tradeoffs between gRPC and REST for internal microservice communication?"

# Run three models in parallel
$Q gemini-3-pro "$PROMPT" > /tmp/gemini.txt &
$Q gpt-5.4 "$PROMPT" > /tmp/gpt.txt &
$Q claude-think "$PROMPT" > /tmp/claude.txt &
wait

# Compare the results
echo "=== GEMINI 3 PRO ===" && head -20 /tmp/gemini.txt
echo "=== GPT-5.4 ===" && head -20 /tmp/gpt.txt
echo "=== CLAUDE OPUS ===" && head -20 /tmp/claude.txt
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_TOKENS` | 32768 | Maximum output tokens |
| `REASONING_EFFORT` | high | GPT-5.4 reasoning: low / medium / high |
| `ENABLE_SEARCH` | 1 (Gemini) | Enable Google Search grounding |
| `ENABLE_THINKING` | 1 (pro models) | Enable extended thinking for Gemini |
| `THINKING_EFFORT` | max | Claude thinking effort level |

---

## 6. Building a Consensus Pipeline

The `dispatch-all.sh` script automates the parallel multi-model pattern.

### Basic Usage

```bash
# Send to all 4 models: gemini-3-pro, gpt-5.4, codex-5.4, claude-1m
./scripts/multi-model/dispatch-all.sh "Review this code for correctness: $(cat patch.diff)"

# Output:
# Dispatching to 4 models (prompt: 2847 bytes)...
# Output dir: /tmp/multi-llm-20260331-143022
#
#   gemini-3-pro: 45 lines
#   gpt-5.4: 38 lines
#   codex-5.4: 52 lines
#   claude-1m: 41 lines
#
# Results saved to: /tmp/multi-llm-20260331-143022/
```

### Reading Results

```bash
# Each model's response is a separate markdown file
cat /tmp/multi-llm-20260331-143022/gemini-3-pro.md
cat /tmp/multi-llm-20260331-143022/gpt-5.4.md
cat /tmp/multi-llm-20260331-143022/codex-5.4.md
cat /tmp/multi-llm-20260331-143022/claude-1m.md

# The original prompt is saved for reference
cat /tmp/multi-llm-20260331-143022/PROMPT.md
```

### The 4-Layer Debug Prompt

When asking models for help debugging, structure your prompt to reduce hallucinations:

```markdown
## Layer A: Immutable Facts (Verified Platform Constraints)
- AWS P5.48xlarge with 32 EFA interfaces
- EFA SRD does NOT guarantee message ordering
- Same-node EFA loopback is silently dropped

## Layer B: Attempt Registry (What Has Been Tried)
| Attempt | Result | Verdict |
|---------|--------|---------|
| Added __threadfence_system | No change | FAILED |
| Switched to volatile loads | Data still stale | FAILED |

**BANLIST (proven failures, do NOT suggest):**
- __threadfence_system for cross-NIC visibility
- volatile alone for RDMA-written memory

## Layer C: Current State
- Build: commit abc123, image tag v74-clean
- Metric: 0 bytes received on rank 1 (rank 0 sends 4096 bytes)
- Relevant log: `[WARN] fi_cq_read returned -FI_EAGAIN`

## Layer D: Focused Question
Why does rank 1 read all zeros from the RDMA buffer
despite rank 0's fi_writemsg completing successfully?
Suggest ONE specific diagnostic step.
```

This structure (from the agent-toolkit's `templates/debug-prompt-template.md`) prevents models from suggesting things you have already tried, and grounds them in verified facts.

### Synthesizing with a Consensus Agent

After collecting multi-model responses, use a consensus agent to synthesize:

```bash
# Collect all responses into one file
RESULTS_DIR=/tmp/multi-llm-20260331-143022
{
  echo "# Multi-Model Responses"
  echo ""
  for f in "$RESULTS_DIR"/*.md; do
    model=$(basename "$f" .md)
    [ "$model" = "PROMPT" ] && continue
    echo "## $model"
    cat "$f"
    echo ""
  done
} > /tmp/consensus-input.md

# Ask Claude to synthesize
Q=./scripts/multi-model/query-model.sh
$Q claude-think "$(cat <<'EOF'
You are a consensus synthesizer. Below are responses from 4 different AI models
to the same question. Your job:

1. Identify points of AGREEMENT (high confidence)
2. Identify points of DISAGREEMENT (needs human judgment)
3. Flag any claims that contradict known facts
4. Produce a single unified recommendation

$(cat /tmp/consensus-input.md)
EOF
)"
```

---

## 7. MCP Server for Your Domain

Use this template to build domain-specific MCP servers for your team.

### Template: Domain Knowledge MCP Server

```javascript
#!/usr/bin/env node
// domain-knowledge-mcp/server.js
// An MCP server that provides domain-specific knowledge to your agent

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { readFileSync, readdirSync } from "fs";
import { join } from "path";

const DOCS_DIR = process.env.DOCS_DIR || "./docs";

const server = new Server(
  { name: "domain-knowledge", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// Tool definitions
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_docs",
      description: "Search domain knowledge base by keyword",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
          max_results: {
            type: "number",
            description: "Max results (default 5)",
          },
        },
        required: ["query"],
      },
    },
    {
      name: "read_doc",
      description: "Read a specific document by name",
      inputSchema: {
        type: "object",
        properties: {
          name: { type: "string", description: "Document filename" },
        },
        required: ["name"],
      },
    },
    {
      name: "list_docs",
      description: "List all available documents in the knowledge base",
      inputSchema: { type: "object", properties: {} },
    },
  ],
}));

// Tool implementations
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "list_docs": {
      const files = readdirSync(DOCS_DIR).filter((f) => f.endsWith(".md"));
      return {
        content: [
          {
            type: "text",
            text: `Available documents (${files.length}):\n${files.map((f) => `  - ${f}`).join("\n")}`,
          },
        ],
      };
    }

    case "read_doc": {
      try {
        const content = readFileSync(join(DOCS_DIR, args.name), "utf-8");
        return { content: [{ type: "text", text: content }] };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Document not found: ${args.name}` }],
        };
      }
    }

    case "search_docs": {
      const maxResults = args.max_results || 5;
      const query = args.query.toLowerCase();
      const files = readdirSync(DOCS_DIR).filter((f) => f.endsWith(".md"));
      const results = [];

      for (const file of files) {
        const content = readFileSync(join(DOCS_DIR, file), "utf-8");
        const lines = content.split("\n");
        const matches = lines.filter((l) =>
          l.toLowerCase().includes(query)
        );
        if (matches.length > 0) {
          results.push({
            file,
            matches: matches.length,
            preview: matches.slice(0, 3).join("\n"),
          });
        }
      }

      results.sort((a, b) => b.matches - a.matches);
      const top = results.slice(0, maxResults);

      const text = top.length
        ? top
            .map(
              (r) =>
                `### ${r.file} (${r.matches} matches)\n${r.preview}`
            )
            .join("\n\n")
        : "No matches found.";

      return { content: [{ type: "text", text }] };
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
```

### Adapting the Template

1. **API Documentation Server**: Replace file reads with calls to your API documentation system
2. **Database Schema Server**: Query `information_schema` and expose table/column metadata
3. **Monitoring Server**: Connect to Prometheus/Grafana and expose metric queries
4. **CI/CD Server**: Wrap your Jenkins/GitHub Actions API to show build status and logs
5. **Runbook Server**: Serve operational runbooks so the agent can follow your team's incident procedures

### Register Your Server

```json
{
  "mcpServers": {
    "my-domain-knowledge": {
      "command": "node",
      "args": ["/path/to/domain-knowledge-mcp/server.js"],
      "env": {
        "DOCS_DIR": "/path/to/your/knowledge-base"
      }
    }
  }
}
```

### Test with MCP Inspector

```bash
# Interactive testing tool from Anthropic
npx @anthropic-ai/mcp-inspector node server.js

# In the inspector:
# 1. Click "List Tools" to see your tool definitions
# 2. Click a tool and fill in parameters
# 3. Verify the response format
```

---

## Summary

| Concept | What It Does | Key File |
|---------|-------------|----------|
| MCP Protocol | Standardized tool interface for AI agents | `~/.claude.json` |
| stdio Transport | Server runs as child process (most common) | `server.js` |
| `query-model.sh` | Query any frontier model from CLI | `scripts/multi-model/query-model.sh` |
| `dispatch-all.sh` | Parallel 4-model dispatch | `scripts/multi-model/dispatch-all.sh` |
| Consensus Pattern | Cross-validate across models | Synthesize disagreements |
| 4-Layer Prompt | Structured debug prompts | `templates/debug-prompt-template.md` |
| Domain MCP Server | Custom tools for your team | Template above |

### Key Takeaways

1. **MCP servers are just Node.js (or Python) scripts** that read JSON from stdin and write JSON to stdout. No complex infrastructure needed.
2. **Multi-model dispatch saves you from single-model blind spots.** Models hallucinate about different things -- consensus catches errors.
3. **Keep MCP server count under 10** to preserve your context window for actual work.
4. **The 4-layer debug prompt** (Facts, Attempts, State, Question) dramatically reduces hallucinations when querying external models.
5. **Always sanitize API keys** -- use environment variables, never hardcode them in configuration files checked into git.

**Next module:** [Module 3: Deploying Coding Agents](../03-deploying-coding-agents/README.md) -- tmux sessions, autonomous loops, and production agent workflows.
