# Module 1: Agentic Coding Fundamentals

**Duration:** 15 minutes
**Prerequisites:** Terminal access, Claude Code CLI installed (`claude --version` >= 2.1.0)

---

## 1. What is Agentic Coding?

Traditional code assistants autocomplete lines. Agentic coding is fundamentally different: the AI operates as an **autonomous coding partner** that can plan, execute, verify, and iterate.

| Capability | Autocomplete | Agentic |
|-----------|-------------|---------|
| Scope | Single line/block | Entire features |
| Planning | None | Breaks work into tasks |
| Execution | Suggests text | Reads files, runs commands, edits code |
| Verification | None | Runs tests, checks builds, reviews output |
| Iteration | None | Retries on failure, adapts approach |
| Memory | Current file | Project context across sessions |

An agentic coding session looks like this:

```
You: "Add rate limiting to the /api/users endpoint"

Agent thinks:
  1. Read the existing route handler
  2. Check if a rate limiting library exists in package.json
  3. Plan the implementation (middleware approach vs per-route)
  4. Write failing tests for rate limit behavior
  5. Implement the middleware
  6. Run tests, verify they pass
  7. Check for edge cases
```

The agent is not waiting for you to tell it what file to open. It searches, reads, reasons, acts, and verifies -- autonomously.

---

## 2. Claude Code Architecture

Claude Code is a CLI-based agent harness. Here is how its components fit together:

```
~/.claude/CLAUDE.md          <-- Global instructions (your "operating system")
.claude/CLAUDE.md            <-- Project-specific instructions
.claude/settings.json        <-- Hooks, MCP servers, permissions
.claude/rules/               <-- Always-on guidelines
.claude/skills/              <-- Methodology workflows
.claude/commands/             <-- Custom slash commands
.claude/agents/              <-- Subagent definitions

Claude Code CLI (claude)
    |
    |-- Reads CLAUDE.md files (global + project)
    |-- Loads hooks from settings.json
    |-- Connects to MCP servers (tool providers)
    |-- Has built-in tools: Read, Write, Edit, Bash, Grep, Glob
    |-- Can spawn sub-agents via the Agent tool
    |-- Manages git operations natively
```

**Key design principle:** Configuration is just markdown and JSON files in your repository. No proprietary formats, no GUI configuration panels. Everything is version-controlled.

---

## 3. CLAUDE.md Deep Dive

CLAUDE.md is the single most important file in agentic coding. It transforms a general-purpose LLM into a specialized team member who knows your project, follows your standards, and respects your constraints.

Claude Code loads CLAUDE.md files in this order:

1. `~/.claude/CLAUDE.md` -- Global (all projects, all machines)
2. `.claude/CLAUDE.md` -- Project root (shared with team via git)
3. Any CLAUDE.md in subdirectories (scoped to that directory)

### Real-World CLAUDE.md Structure

Here is a production CLAUDE.md (adapted from a real HPC project):

````markdown
# CLAUDE.md

## Project Overview
HPC Agent Stack - toolkit for AI-assisted analysis of High-Performance
Computing codebases. Provides semantic code search, static analysis,
and MCP server integration for Claude Code.

## Setup & Commands
```bash
# Install dependencies
./setup.sh

# Index a codebase for search
./scripts/code-search/index-repos.sh /path/to/repo

# Start search servers
./scripts/code-search/start-zoekt.sh --background    # :6070

# Query external models
./scripts/multi-model/query-model.sh gemini-3-pro "prompt"
```

## Architecture
```
Claude Code Agent
    | MCP Protocol (JSON-RPC over stdio)
    |-- zoekt-search      - Fast trigram code search
    |-- semantic-scholar  - Academic paper search
    |-- codegraph-context - Semantic call graphs
    |-- efa-gpu-docs      - Domain knowledge base (47+ docs)
```

## Hard Rules
- NEVER expose services to 0.0.0.0/0 -- SSH tunnels only
- NEVER use sed on C/C++ files -- use Python or Edit tool
- NEVER skip pre-commit hooks (--no-verify)
- Always run tests before claiming work is done

## Build Hygiene
- `touch` sources + `rm -rf build dist *.egg-info` before rebuild
- Verify binary freshness: `strings *.so | grep marker`
- Restart K8s pods between test iterations (CUDA context pollution)
````

Notice the structure: **Overview** (what is this?), **Commands** (how to build/run), **Architecture** (how it fits together), **Hard Rules** (non-negotiable constraints), **Hygiene** (lessons learned).

---

## 4. Hands-on: Set Up Your First CLAUDE.md

Create a project CLAUDE.md that encodes your team's standards.

### Step 1: Create the directory structure

```bash
mkdir -p myproject/.claude
cd myproject
git init
```

### Step 2: Write your project CLAUDE.md

Create `.claude/CLAUDE.md`:

````markdown
# CLAUDE.md

## Project Overview
A REST API built with Node.js/Express serving a React frontend.
Database: PostgreSQL via Prisma ORM.

## Commands
```bash
# Development
npm run dev          # Start dev server (port 3000)
npm run test         # Run test suite (Jest)
npm run test:watch   # Watch mode
npm run lint         # ESLint + Prettier
npm run db:migrate   # Run Prisma migrations
npm run db:seed      # Seed development data
```

## Coding Standards
- TypeScript strict mode -- no `any` types
- All API endpoints must have request/response validation (Zod)
- Error responses follow RFC 7807 (Problem Details)
- Database queries go through the repository pattern, never raw SQL in routes

## Testing Requirements
- Every new endpoint needs integration tests
- Every new utility function needs unit tests
- Test-Driven Development: write the failing test FIRST
- Minimum 80% coverage on changed files

## Security Rules
- NEVER commit .env files or API keys
- NEVER disable CORS in production config
- All user input must be validated before database queries
- Authentication middleware on every route except /health and /auth/*

## Git Workflow
- Branch naming: feature/*, fix/*, chore/*
- Commit messages: conventional commits (feat:, fix:, docs:, test:)
- Always rebase on main before merging
- PRs require passing CI + 1 approval
````

### Step 3: Add a global CLAUDE.md for personal preferences

Create `~/.claude/CLAUDE.md`:

```markdown
# Global Instructions

## My Preferences
- Use verbose variable names over abbreviations
- Prefer functional patterns (map, filter, reduce) over loops
- Always add JSDoc/TSDoc comments on exported functions
- Use early returns to reduce nesting

## Session Protocol
- On session start, run `git status` and check current branch
- Before any destructive operation, confirm with me
- After completing a task, run the test suite automatically
```

### Step 4: Verify it works

```bash
cd myproject
claude
# Ask: "Show me what instructions you're following"
```

Claude Code will read both CLAUDE.md files and follow them throughout the session.

---

## 5. Skills System

Skills are structured methodology documents that teach the agent **how to work**, not just what to build. Two major skills systems exist:

### Superpowers (by Jesse Vincent)

Superpowers provides a complete development workflow that activates automatically:

| Phase | Skill | What Happens |
|-------|-------|-------------|
| 1 | **brainstorming** | Agent asks questions, explores alternatives, produces a design document |
| 2 | **using-git-worktrees** | Creates an isolated branch and workspace |
| 3 | **writing-plans** | Breaks work into 2-5 minute tasks with exact file paths and code |
| 4 | **subagent-driven-development** | Dispatches a fresh sub-agent per task with two-stage review |
| 5 | **test-driven-development** | Enforces RED-GREEN-REFACTOR. Deletes code written before tests |
| 6 | **requesting-code-review** | Reviews against the plan, reports issues by severity |
| 7 | **finishing-a-development-branch** | Verifies tests, presents merge/PR/keep/discard options |

Install Superpowers:

```bash
# Via Claude Code plugin marketplace
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

### Everything Claude Code (ECC)

ECC provides 116+ skills, 28 agents, and 59 commands:

```bash
# Install
/plugin marketplace add affaan-m/everything-claude-code
/plugin install everything-claude-code@everything-claude-code

# Use skills via slash commands
/plan "Add user authentication with OAuth"
/tdd                           # Enforce test-driven development
/code-review                   # Review changes for quality
/build-fix                     # Fix build errors
/security-scan                 # Run security audit
```

### Writing Your Own Skill

Skills are just markdown files in `.claude/skills/`:

```bash
mkdir -p .claude/skills/api-design
```

Create `.claude/skills/api-design/SKILL.md`:

```markdown
---
name: api-design
description: REST API design patterns for this project
trigger: creating or modifying API endpoints
---

# API Design Skill

## When to Activate
- Creating new API endpoints
- Modifying request/response schemas
- Adding middleware

## Workflow
1. Check existing endpoints in `src/routes/` for consistency
2. Define the Zod schema for request validation FIRST
3. Write the integration test (request -> expected response)
4. Implement the route handler
5. Add to the OpenAPI spec in `docs/api.yaml`
6. Run `npm run test` to verify

## Patterns
- Use `asyncHandler()` wrapper on all route handlers
- Return `{ data, meta }` for collections (with pagination)
- Return `{ data }` for single resources
- Return `{ error }` for errors (RFC 7807)

## Anti-patterns (NEVER do these)
- Raw SQL in route handlers (use repository pattern)
- Swallowing errors with empty catch blocks
- Returning 200 for error conditions
```

---

## 6. Hooks

Hooks are automated actions that fire on specific events during a Claude Code session. They are defined in `.claude/settings.json` and execute shell commands.

### Hook Events

| Event | When It Fires | Use For |
|-------|--------------|---------|
| `PreToolUse` | Before any tool runs | Block dangerous commands, validate inputs |
| `PostToolUse` | After any tool runs | Auto-format, lint checks, notifications |
| `Stop` | When agent finishes a response | Session summaries, learning extraction |
| `SessionStart` | When a new session begins | Load context, check environment |
| `SessionEnd` | When a session ends | Save state, cleanup |

### Example: Block `--no-verify` on Git Commits

This hook prevents the agent from bypassing pre-commit hooks:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "if echo \"$TOOL_INPUT\" | grep -q '\\-\\-no-verify'; then echo 'BLOCKED: --no-verify is not allowed' >&2; exit 2; fi"
          }
        ],
        "description": "Block git hook-bypass flag"
      }
    ]
  }
}
```

Exit codes matter:
- **Exit 0**: Proceed normally
- **Exit 1**: Show warning but proceed
- **Exit 2**: BLOCK the tool call entirely

### Example: Auto-Format After File Edits

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "if [[ \"$TOOL_INPUT\" =~ \\.(ts|tsx|js|jsx)$ ]]; then npx prettier --write \"$TOOL_INPUT\" 2>/dev/null; fi"
          }
        ],
        "description": "Auto-format TypeScript/JavaScript files after editing"
      }
    ]
  }
}
```

### Example: Session Start Context Loading

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo \"Session started at $(date). Branch: $(git branch --show-current 2>/dev/null || echo 'not a git repo')\""
          }
        ],
        "description": "Log session start with git context"
      }
    ]
  }
}
```

### Production Hook Configuration (from Everything Claude Code)

A real production hook setup includes layers of protection:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "npx block-no-verify@1.1.2"}],
        "description": "Block git hook-bypass flag"
      },
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "node scripts/hooks/pre-bash-tmux-reminder.js"}],
        "description": "Remind to use tmux for long-running commands"
      },
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "node scripts/hooks/pre-bash-git-push-reminder.js"}],
        "description": "Review before git push"
      },
      {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "node scripts/hooks/suggest-compact.js"}],
        "description": "Suggest context compaction at logical intervals"
      }
    ],
    "Stop": [
      {
        "hooks": [{"type": "command", "command": "node scripts/hooks/session-end.js", "timeout": 10}],
        "description": "Extract patterns from session for continuous learning"
      }
    ]
  }
}
```

---

## 7. Version Control Integration

Claude Code has deep git integration. The agent can manage branches, commits, and PRs natively.

### How the Agent Interacts with Git

```bash
# The agent can do all of this autonomously:
git status                    # Check working state
git diff                      # Review changes
git log --oneline -10         # Understand recent history
git checkout -b feature/x     # Create feature branches
git add specific-file.ts      # Stage specific files (not -A)
git commit -m "feat: ..."     # Commit with conventional messages
gh pr create --title "..."    # Create pull requests via gh CLI
```

### Branch Management with Git Worktrees

For parallel development, use git worktrees to isolate work:

```bash
# Create an isolated worktree for a feature
git worktree add ../myproject-auth feature/auth

# The agent works in the worktree without affecting main
cd ../myproject-auth
# ... make changes ...

# When done, merge or create PR
git worktree remove ../myproject-auth
```

The Superpowers `using-git-worktrees` skill automates this:

```
Agent:
  1. Creates worktree on new branch
  2. Runs project setup (npm install, etc.)
  3. Verifies clean test baseline
  4. Does all work in the worktree
  5. Merges or creates PR when done
  6. Cleans up the worktree
```

### PR Creation Pattern

The agent follows a structured PR workflow:

```
1. git status + git diff           -- Understand what changed
2. git log main..HEAD              -- See all commits on this branch
3. Draft title + description       -- Summarize the "why"
4. gh pr create --title "..." \
     --body "## Summary ..."       -- Create the PR with details
5. Return the PR URL               -- Hand off to human reviewer
```

### Safety Guardrails

Claude Code's built-in safety rules for git:

- **Prefer `git add <specific-file>`** over `git add -A` (avoids committing secrets)
- **Never amend commits** unless explicitly asked (prevents losing history)
- **Never force push** to main/master (warns if requested)
- **Never skip hooks** (`--no-verify`) unless explicitly asked
- **New commits over amends** when pre-commit hooks fail

---

## Summary

| Concept | What It Does | Where It Lives |
|---------|-------------|----------------|
| CLAUDE.md | Persistent instructions | `.claude/CLAUDE.md` or `~/.claude/CLAUDE.md` |
| Skills | Methodology workflows | `.claude/skills/*/SKILL.md` |
| Hooks | Automated triggers | `.claude/settings.json` |
| Rules | Always-on guidelines | `.claude/rules/*.md` |
| Commands | Slash command shortcuts | `.claude/commands/*.md` |
| Agents | Specialized sub-agents | `.claude/agents/*.md` |

**Next module:** [Module 2: MCP Servers and Multi-LLM Orchestration](../02-mcp-servers-multi-llm/README.md) -- connect external tools and multiple AI models to your agent.
