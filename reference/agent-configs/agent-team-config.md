# Agent Team Configuration

> Patterns for configuring multi-agent teams with specialized roles.
> These patterns work with Claude Code's sub-agent and background agent capabilities.

## Overview

Multi-agent teams decompose complex work across specialized agents, each with
focused context and clear responsibilities. This avoids overloading a single
agent's context window and produces better results through specialization.

## Architecture Patterns

### Pattern 1: Coordinator + Specialists

```
                    Coordinator Agent
                    (orchestrates work)
                         |
            +------------+------------+
            |            |            |
       Researcher    Implementer   Reviewer
       (reads docs,  (writes code, (reviews diffs,
        searches)     runs tests)   catches issues)
```

The coordinator dispatches focused tasks and synthesizes results.
Specialists never see each other's full context.

### Pattern 2: Parallel Investigators

```
        Problem Statement
              |
    +---------+---------+
    |         |         |
  Agent A   Agent B   Agent C
  (area 1)  (area 2)  (area 3)
    |         |         |
    +---------+---------+
              |
        Synthesis
```

Use when a problem has multiple independent aspects that can be
investigated simultaneously.

### Pattern 3: Pipeline

```
  Analyzer --> Planner --> Implementer --> Tester --> Reviewer
```

Use when work flows through sequential stages, each building on
the previous stage's output.

## Agent Role Definitions

### Researcher Agent

**Purpose:** Gather information, search code, read documentation.

**Prompt template:**
```markdown
You are a research agent. Your task is to find specific information
and return structured findings.

## Task
[What to research]

## Scope
- Search in: [specific directories, files, or APIs]
- Focus on: [specific aspects]
- Ignore: [out-of-scope areas]

## Output Format
Return findings as:
1. Key facts (with file:line references)
2. Relevant code snippets
3. Open questions that need further investigation
```

**Best practices:**
- Give specific search scope (not "search everything")
- Ask for file:line references (verifiable)
- Request structured output for easy synthesis

### Implementer Agent

**Purpose:** Write code following a specific plan.

**Prompt template:**
```markdown
You are an implementation agent. Write code following the plan below.

## Plan
[Specific implementation steps from planning phase]

## Constraints
- Follow existing code patterns in [directory]
- Write tests for every new function
- Do not modify files outside [scope]

## Definition of Done
- [ ] All specified functions implemented
- [ ] Tests written and passing
- [ ] No linting errors
- [ ] Changes committed with descriptive message
```

**Best practices:**
- Provide a clear, specific plan (not vague requirements)
- Constrain scope explicitly
- Include definition of done

### Reviewer Agent

**Purpose:** Review code changes for correctness, style, and completeness.

**Prompt template:**
```markdown
You are a code review agent. Review the changes between commits.

## Review Scope
Base commit: [SHA]
Head commit: [SHA]

## What Was Implemented
[Brief description of intent]

## Review Checklist
- [ ] Logic correctness
- [ ] Error handling (edge cases, failure modes)
- [ ] Test coverage (are important paths tested?)
- [ ] Style consistency (matches existing codebase)
- [ ] Security (no hardcoded secrets, no injection vectors)
- [ ] Performance (no obvious N+1 queries, no unnecessary allocations)

## Output Format
Return:
- CRITICAL issues (must fix before merge)
- IMPORTANT issues (should fix before merge)
- MINOR suggestions (nice to have)
- Overall assessment: APPROVE / REQUEST CHANGES
```

**Best practices:**
- Give the reviewer fresh context (not your session history)
- Include what was supposed to be built
- Request structured severity levels

### Debugger Agent

**Purpose:** Investigate a specific failure and propose a fix.

**Prompt template:**
```markdown
You are a debugging agent. Investigate the following failure.

## Failure
[Error message, stack trace, or symptom description]

## Reproduction Steps
[How to trigger the failure]

## What Has Been Tried
[Previous hypotheses and their outcomes]

## Constraints
- Follow systematic debugging: read errors, reproduce, trace data flow
- Do NOT propose fixes until you've identified root cause
- If root cause unclear, propose diagnostic steps (not fixes)

## Output Format
1. Root cause analysis (what is actually wrong and why)
2. Evidence (specific file:line, log output, or test result)
3. Proposed fix (minimal, targeted)
4. Verification plan (how to confirm the fix works)
```

## Dispatch Patterns

### Using Claude Code Sub-agents

```
In Claude Code, use the Agent tool to dispatch sub-agents:

Agent(prompt="You are a research agent. Find all usages of
  the UserService class and document its public API.",
  run_in_background=true)

Agent(prompt="You are a review agent. Review the diff between
  abc123 and def456. Focus on error handling.",
  run_in_background=true)
```

Sub-agents run in isolated context and return results asynchronously.

### Using Background Agents (tmux)

```bash
# Start background agents in separate tmux sessions
tmux new-session -d -s researcher \
  "claude -p 'Research the authentication module. Document all endpoints,
   middleware, and token validation logic. Write findings to /tmp/auth-research.md'"

tmux new-session -d -s implementer \
  "claude -p 'Implement the rate limiting middleware following the plan
   in docs/plans/rate-limiting.md. Run tests after implementation.'"

# Monitor progress
tmux ls
tmux attach -t researcher
```

### Using Git Worktrees for Isolation

```bash
# Create isolated worktrees for parallel implementation
git worktree add ../feature-auth feature/auth
git worktree add ../feature-ratelimit feature/ratelimit

# Each agent works in its own worktree (no file conflicts)
cd ../feature-auth && claude -p "Implement auth changes..."
cd ../feature-ratelimit && claude -p "Implement rate limiting..."

# Merge results back
git worktree remove ../feature-auth
git worktree remove ../feature-ratelimit
```

## Team Configurations

### Small Team (3 agents) -- Feature Development

| Role | Agent | Focus |
|------|-------|-------|
| Planner | Agent 1 | Read requirements, create implementation plan |
| Implementer | Agent 2 | Execute plan, write code + tests |
| Reviewer | Agent 3 | Review diff, catch issues before merge |

### Medium Team (5 agents) -- Complex Feature

| Role | Agent | Focus |
|------|-------|-------|
| Researcher | Agent 1 | Explore codebase, document current state |
| Architect | Agent 2 | Design solution, create detailed plan |
| Implementer A | Agent 3 | Backend changes |
| Implementer B | Agent 4 | Frontend changes |
| Reviewer | Agent 5 | Review all changes, integration testing |

### Debug Team (3 agents) -- Production Issue

| Role | Agent | Focus |
|------|-------|-------|
| Investigator A | Agent 1 | Analyze logs and error traces |
| Investigator B | Agent 2 | Review recent code changes |
| Fixer | Agent 3 | Implement fix once root cause is identified |

## Best Practices

### Do

- **Give each agent a clear, scoped task** -- Focused agents produce better results
- **Provide all necessary context in the prompt** -- Agents don't share memory
- **Request structured output** -- Makes synthesis easier
- **Use git worktrees for parallel code changes** -- Prevents file conflicts
- **Review agent work before integrating** -- Agents can make systematic errors
- **Run full test suite after integration** -- Catch interaction bugs

### Don't

- **Don't let agents share files without coordination** -- Race conditions
- **Don't give agents vague tasks** -- "Fix everything" produces nothing useful
- **Don't skip review of agent output** -- Trust but verify
- **Don't dispatch dependent tasks in parallel** -- Wait for prerequisites
- **Don't overload a single agent** -- Split into focused sub-tasks instead

## Communication Between Agents

Agents communicate through artifacts, not direct messages:

```
Agent A writes findings to:  /tmp/research-findings.md
Agent B reads findings from: /tmp/research-findings.md
Agent B writes plan to:      docs/plans/implementation-plan.md
Agent C reads plan from:     docs/plans/implementation-plan.md
```

For Claude Code sub-agents, the parent agent receives results directly
and can pass relevant context to the next sub-agent.

## Example: End-to-End Feature Development

```bash
# Step 1: Research (background agent)
claude -p "Research how authentication works in this codebase.
  Document: endpoints, middleware chain, token format, error handling.
  Write findings to /tmp/auth-research.md"

# Step 2: Plan (after research completes)
claude -p "Read /tmp/auth-research.md. Create an implementation plan
  for adding OAuth2 support. Write plan to docs/plans/oauth2-plan.md"

# Step 3: Implement (after plan is approved)
claude -p "Execute the plan in docs/plans/oauth2-plan.md.
  Implement each task, write tests, commit after each task."

# Step 4: Review (after implementation)
claude -p "Review all commits since [base-sha]. Check against
  the plan in docs/plans/oauth2-plan.md. Report issues."
```

## Scaling Considerations

| Team Size | Coordination Overhead | When to Use |
|-----------|----------------------|-------------|
| 1 agent | None | Simple, focused tasks |
| 2-3 agents | Low | Standard features, debugging |
| 4-5 agents | Medium | Complex features, multi-component changes |
| 6+ agents | High (needs explicit coordination) | Large refactors, multi-service changes |

**Rule of thumb:** Start with fewer agents. Add more only when you can clearly
define independent work streams that don't share state.
