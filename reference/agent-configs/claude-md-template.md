# CLAUDE.md Template

> This template provides a comprehensive starting point for your project's CLAUDE.md.
> CLAUDE.md is the primary way to give Claude Code persistent instructions for your project.
> Place it at the root of your repository.

---

Copy everything below the line into your project's `CLAUDE.md` and customize.

---

# CLAUDE.md

## Project Overview

<!-- Brief description of what this project does, its tech stack, and architecture.
     Claude Code reads this at the start of every conversation. -->

[Project Name] is a [type of project] built with [tech stack].

**Architecture:**
- Frontend: [framework, language]
- Backend: [framework, language]
- Database: [type, name]
- Infrastructure: [cloud provider, deployment method]

**Key directories:**
```
src/           # Application source code
tests/         # Test suite
docs/          # Documentation
scripts/       # Build and utility scripts
config/        # Configuration files
```

## Development Workflow

### Build and Run

```bash
# Install dependencies
npm install  # or pip install -r requirements.txt, cargo build, etc.

# Run in development mode
npm run dev

# Build for production
npm run build
```

### Testing

```bash
# Run all tests
npm test

# Run specific test file
npm test -- path/to/test.test.ts

# Run with coverage
npm run test:coverage
```

### Linting and Formatting

```bash
# Lint
npm run lint

# Format
npm run format

# Type check
npm run typecheck
```

## Coding Standards

<!-- Project-specific conventions that Claude Code should follow -->

### Style
- [Language-specific style guide reference]
- Use [tabs/spaces, indent size]
- Max line length: [number]
- Import ordering: [convention]

### Naming Conventions
- Files: `kebab-case.ts`
- Components: `PascalCase`
- Functions: `camelCase`
- Constants: `UPPER_SNAKE_CASE`
- Database tables: `snake_case`

### Architecture Patterns
- [Pattern 1, e.g., "Use repository pattern for data access"]
- [Pattern 2, e.g., "All API endpoints return standard response envelope"]
- [Pattern 3, e.g., "Business logic lives in service layer, not controllers"]

### Error Handling
- [How errors should be handled in this project]
- [Error response format]
- [Logging conventions]

## Git Workflow

<!-- How this project uses git -->

- Branch naming: `feature/description`, `fix/description`, `chore/description`
- Commit messages: [Conventional Commits / project convention]
- PR process: [required reviews, CI checks]
- Main branch: `main` (protected, requires PR)

## Key Decisions and Constraints

<!-- Important architectural decisions, known limitations, or constraints
     that Claude Code should be aware of -->

- [Decision 1: "We use X instead of Y because..."]
- [Decision 2: "Never use Z in this codebase because..."]
- [Constraint 1: "Must support Node.js >= 18"]
- [Constraint 2: "All API responses must be < 500ms"]

## Environment Variables

<!-- Document required env vars WITHOUT including actual values -->

```bash
# Required
DATABASE_URL=        # PostgreSQL connection string
API_KEY=             # External service API key (get from team vault)
SESSION_SECRET=      # Random string for session encryption

# Optional
LOG_LEVEL=info       # debug, info, warn, error
CACHE_TTL=3600       # Cache duration in seconds
```

**NEVER commit `.env` files.** Use `.env.example` as a template.

## Debugging Guidelines

<!-- How to approach debugging in this project -->

1. **Check logs first:** `npm run logs` or check CloudWatch/Datadog
2. **Reproduce locally:** Use `npm run dev` with `LOG_LEVEL=debug`
3. **Common issues:**
   - [Issue 1: "If X happens, check Y"]
   - [Issue 2: "Z error usually means the database migration is pending"]

## Security Rules

<!-- Hard rules that must never be violated -->

- NEVER expose services to `0.0.0.0/0` except SSH (port 22)
- NEVER commit API keys, tokens, or passwords
- NEVER disable authentication in production code
- All user input must be validated and sanitized
- Use parameterized queries (never string concatenation for SQL)

## Performance Expectations

<!-- Performance budgets and optimization guidelines -->

- API response time: < 500ms p95
- Page load: < 3s on 3G
- Bundle size: < 200KB gzipped
- Database queries: < 100ms

## External Services and APIs

<!-- Services this project integrates with -->

| Service | Purpose | Docs |
|---------|---------|------|
| [Service 1] | [Purpose] | [URL] |
| [Service 2] | [Purpose] | [URL] |

## Operating Principles

<!-- Behavioral guidelines for Claude Code -->

- Be precise and evidence-driven. Verify before guessing.
- Make minimal, reversible changes. One variable per experiment.
- Always run tests before claiming something works.
- Search the codebase before creating new utilities -- avoid duplication.
- Follow existing patterns in the codebase.
- When unsure, ask rather than assume.

---

## Advanced: Skills Integration

<!-- If using Claude Code skills, reference them here -->

Skills are methodology documents that guide Claude Code's behavior.
Place them in `~/.claude/skills/` or reference project-specific ones.

**Project skills:**
- `skills/project-specific-skill/SKILL.md` -- [What it does]

**Recommended skills:**
- `systematic-debugging` -- Root cause investigation before fixes
- `test-driven-development` -- Write tests first, always
- `verification-before-completion` -- Run the command, read the output, THEN claim the result

## Advanced: Hooks

<!-- If using Claude Code hooks for automated behaviors -->

Hooks in `settings.json` run before/after tool use:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash(npm run build*)",
        "hooks": [{"type": "command", "command": "echo 'Building...'"}]
      }
    ]
  }
}
```

## Advanced: MCP Servers

<!-- If using MCP servers for extended capabilities -->

MCP servers configured in `.mcp.json` extend Claude Code with:
- Code search (Zoekt, OpenGrok)
- Database query access
- Kubernetes operations
- Custom domain-specific tools

See `reference/mcp-configs/mcp-server-example.json` for configuration examples.
