# Module 3: Deploying Coding Agents

**Duration:** 10 minutes
**Prerequisites:** Modules 1-2 (Agentic Coding Fundamentals, MCP Servers & Multi-LLM)

---

## 1. Coding Agent Landscape

The coding agent ecosystem has matured rapidly. Here is what is available today and when to reach for each tool.

| Agent | Strengths | Best For |
|-------|-----------|----------|
| **Claude Code** | Deep reasoning, agentic tool use, bash/file ops, git worktrees | Complex multi-file refactors, debugging, infrastructure |
| **OpenCode** | Open-source Claude Code alternative, local-first | Teams wanting full control over the agent runtime |
| **Codex CLI** | OpenAI reasoning models, sandbox execution | Architecture validation, code review cross-check |
| **Gemini CLI** | 1M token context window, Google ecosystem | Large-context analysis, UI/UX review, doc generation |
| **Cursor** | IDE-native, inline completions + chat | Rapid iteration inside an editor, autocomplete-heavy workflows |
| **oh-my-claudecode (OMC)** | Multi-agent orchestration layer on top of Claude Code | Parallel agent teams, autopilot mode, cross-model synthesis |

**Rule of thumb:** Use Claude Code when you need deep agentic reasoning with tool use. Use OMC when you need multiple agents coordinating on one codebase. Use Cursor when you want inline IDE assistance. Use Codex/Gemini CLI as secondary validators or specialist reviewers.

---

## 2. Deploying Claude Code for Teams

### Installation

```bash
# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Verify installation
claude --version
```

### Per-Project Configuration with CLAUDE.md

Every project should have a `.claude/CLAUDE.md` file. This is the instruction set that Claude Code reads at session start -- it shapes how the agent behaves for your specific codebase.

```bash
mkdir -p .claude
cat > .claude/CLAUDE.md << 'CLAUDEMD'
# Project Instructions

## Codebase
- Language: TypeScript + Python
- Test framework: pytest (backend), vitest (frontend)
- Always run tests before claiming work is complete

## Conventions
- Use absolute imports
- Prefer composition over inheritance
- Never commit .env files or credentials

## Build Commands
- Backend: `cd api && pip install -e . && pytest`
- Frontend: `cd web && npm install && npm test`
CLAUDEMD
```

### User-Level Configuration

Global instructions live at `~/.claude/CLAUDE.md` and apply to all projects. Use this for personal preferences:

```bash
cat > ~/.claude/CLAUDE.md << 'GLOBALMD'
# Global Instructions
- Be precise, technical, evidence-driven
- Minimal, reversible changes
- Verify before claiming completion
GLOBALMD
```

### Settings and Permissions

`~/.claude/settings.json` controls permissions and environment:

```json
{
  "permissions": {
    "allow": ["Bash(git *)", "Bash(npm test)", "Read", "Write", "Edit"],
    "deny": ["Bash(rm -rf /*)"]
  },
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

---

## 3. oh-my-claudecode: Multi-Agent Orchestration

[oh-my-claudecode (OMC)](https://github.com/Yeachan-Heo/oh-my-claudecode) is an orchestration layer that turns Claude Code into a multi-agent system. It adds team coordination, autopilot execution, skill learning, and cross-model synthesis -- all with zero configuration.

### Install OMC

```bash
# Inside a Claude Code session:
/plugin marketplace add https://github.com/Yeachan-Heo/oh-my-claudecode
/plugin install oh-my-claudecode

# Run setup
/setup
/omc-setup
```

### Orchestration Modes

| Mode | What It Does | When to Use |
|------|-------------|-------------|
| **Team** | Staged pipeline: plan, PRD, execute, verify, fix | Coordinated multi-agent work on shared task list |
| **Autopilot** | Single lead agent, autonomous end-to-end | Feature implementation with minimal oversight |
| **Ralph** | Persistent mode with verify/fix loops | Tasks that must fully complete (no partial results) |
| **Ultrawork** | Maximum parallelism, burst execution | Batch fixes/refactors across many files |

### Autopilot Example

```
autopilot: build a REST API for managing tasks with CRUD endpoints,
           SQLite storage, input validation, and comprehensive tests
```

OMC will autonomously: analyze requirements, plan the implementation, write code across multiple files, run tests, and fix failures -- all without further input.

### Team Mode (Recommended)

```bash
# Launch 3 executor agents to fix TypeScript errors
/team 3:executor "fix all TypeScript errors"
```

The team pipeline runs: `team-plan` (break down work) -> `team-prd` (define requirements) -> `team-exec` (parallel execution) -> `team-verify` (validate results) -> `team-fix` (loop on failures).

### tmux CLI Workers

OMC can spawn real CLI processes in tmux panes -- Claude, Codex, or Gemini:

```bash
omc team 2:codex "review auth module for security issues"
omc team 2:gemini "redesign UI components for accessibility"
omc team 1:claude "implement the payment flow"
omc team status auth-review
```

Workers spawn on demand and terminate when their task completes.

---

## 4. Parallel Agents and Worktree Isolation

When multiple agents modify the same codebase simultaneously, conflicts are inevitable. Git worktrees solve this by giving each agent an isolated copy of the repository.

### How Worktrees Work

```
main repo (~/project/)
  |
  +-- worktree-1 (~/project-wt-feature-a/)   <-- Agent 1
  +-- worktree-2 (~/project-wt-feature-b/)   <-- Agent 2
  +-- worktree-3 (~/project-wt-refactor/)     <-- Agent 3
```

Each worktree shares the same `.git` history but has its own working directory and branch. Agents never step on each other.

### Launch a Worktree-Isolated Session

```bash
# Claude Code natively supports worktree isolation
claude --worktree feature-auth "implement JWT authentication with refresh tokens"

# The agent works in an isolated copy, returns changes as a branch
# Merge when ready:
git merge feature-auth
```

### Running Parallel Background Agents

```bash
# Named session for resumability
claude --name "api-refactor" --continue

# Non-interactive background execution
claude -p --print "analyze this file for security issues" < src/auth.py

# Multiple agents in parallel (different terminals or tmux panes)
tmux new-session -d -s agent1 'claude --worktree feat-a "implement user registration"'
tmux new-session -d -s agent2 'claude --worktree feat-b "implement password reset"'
tmux new-session -d -s agent3 'claude --worktree feat-c "add rate limiting middleware"'
```

---

## 5. Agent Teams

Agent Teams are persistent multi-agent groups with shared context and inter-agent communication via mailbox. Enable them with:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Team Concepts

- **Shared Task List:** All agents in a team see the same task queue
- **Mailbox Communication:** Agents send messages to each other via `SendMessage`
- **Specialization:** Each agent can have a different role (architect, implementer, tester)
- **Hooks:** Events like task completion trigger notifications to other agents

### Team Workflow Example

```
Architect Agent          Implementer Agent         Tester Agent
      |                        |                        |
  analyze spec           wait for plan            wait for code
      |                        |                        |
  send plan ----msg----->  receive plan                 |
      |                   write code                    |
      |                        |                        |
      |                   send code ------msg-----> receive code
      |                        |                   run tests
      |                        |                        |
      |                   <---msg--- send test results  |
      |                   fix bugs                      |
```

### Important Limitation

Agent Teams operate within a single Claude Code session context. They do not share state across separate terminal sessions or tmux windows. For cross-session coordination, use explicit file-based state (lock files, shared config).

---

## 6. Hands-On: Launch a Parallel Agent Workflow

**Goal:** Watch OMC brainstorm, plan, and implement a feature using sub-agents.

### Step 1: Set Up a Test Project

```bash
mkdir -p /tmp/agent-demo && cd /tmp/agent-demo
git init
cat > package.json << 'EOF'
{
  "name": "agent-demo",
  "version": "1.0.0",
  "scripts": { "test": "node test.js" }
}
EOF
git add -A && git commit -m "initial"
```

### Step 2: Launch Claude Code with OMC

```bash
claude
```

Inside the session:

```
# Option A: Autopilot mode (single agent, autonomous)
autopilot: build a URL shortener with in-memory storage,
           Express server, and tests

# Option B: Team mode (multiple agents coordinating)
/team 2:executor "build a URL shortener: one agent handles
the Express server and routes, the other writes tests"
```

### Step 3: Observe the Workflow

Watch the agent:
1. **Brainstorm** -- analyze requirements, identify components
2. **Plan** -- break work into tasks, assign to sub-agents
3. **Implement** -- write code across multiple files in parallel
4. **Verify** -- run tests, check for errors
5. **Fix** -- loop on failures until tests pass

### Step 4: Deep Interview (Alternative Start)

If requirements are vague, start with Socratic questioning:

```
/deep-interview "I want some kind of link management tool"
```

OMC will ask clarifying questions across weighted dimensions (scope, constraints, users, integrations) before any code is written.

---

## 7. Safety and Security

Coding agents write and execute code on your machine. Security is not optional.

### Permission Controls

```json
{
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(npm test)",
      "Bash(python -m pytest)",
      "Read",
      "Write",
      "Edit"
    ],
    "deny": [
      "Bash(curl * | bash)",
      "Bash(rm -rf /*)",
      "Bash(chmod 777 *)"
    ]
  }
}
```

### Credential Protection

- **Never** put API keys, tokens, or passwords in CLAUDE.md or committed files
- Use `.env` files excluded via `.gitignore`
- Use environment variables or secrets managers
- Instruct agents explicitly in CLAUDE.md:

```markdown
## Security Rules
- NEVER commit .env files or any file containing credentials
- NEVER expose services to 0.0.0.0/0 in security groups
- NEVER run `curl ... | bash` or download and execute remote scripts
- Use SSH tunnels for any service access, not public endpoints
```

### Network Security

- Agents should never open ports to the public internet
- Use SSH tunnels for accessing deployed services: `ssh -L <port>:localhost:<port> user@host`
- Restrict security group ingress to SSH (port 22) only

### Code Review

- Always review agent-generated code before merging to main
- Use `git diff` to inspect changes before committing
- Run your test suite -- agents can introduce subtle bugs
- Pay special attention to: dependency additions, permission changes, network calls

### Sandbox Execution

- Consider running agents in containers or VMs for untrusted tasks
- Use read-only filesystem mounts where possible
- Limit network access for agents working on sensitive codebases

---

## Key Takeaways

1. **CLAUDE.md is your control plane** -- it shapes agent behavior per-project and per-user
2. **OMC adds orchestration** -- team mode, autopilot, and cross-model synthesis on top of Claude Code
3. **Worktrees prevent conflicts** -- multiple agents work in parallel without stepping on each other
4. **Security is explicit** -- permissions, credential protection, and network rules must be configured deliberately
5. **Start simple, scale up** -- begin with single-agent Claude Code, add OMC when you need coordination

---

**Next:** [Module 4 - OpenClaw & WhatsApp Integration](../04-openclaw-whatsapp-integration/README.md)
