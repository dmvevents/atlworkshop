# Skill Template

> Use this template when creating new skills for Claude Code.
> Each section has annotations explaining its purpose.
> Delete the annotations (lines starting with ">") when writing your actual skill.

## File Location

```
~/.claude/skills/your-skill-name/
  SKILL.md              # Main skill file (required)
  supporting-file.*     # Only if needed (scripts, heavy reference)
```

> Skills live in `~/.claude/skills/` for Claude Code.
> Use a flat namespace -- all skills in one searchable directory.

---

## SKILL.md Content

```markdown
---
name: your-skill-name
description: Use when [specific triggering conditions and symptoms]
---
```

> **FRONTMATTER (required):**
> - `name`: Letters, numbers, and hyphens only. No special characters.
> - `description`: Max 1024 characters total. Start with "Use when..."
>   Describe ONLY when to trigger -- NOT what the skill does.
>   Write in third person. Include specific symptoms and situations.
>
> CRITICAL: Do NOT summarize the skill's workflow in the description.
> If you put process steps in the description, the agent may follow
> the description shortcut instead of reading the full skill.
>
> BAD:  "Use when debugging -- traces root cause, checks logs, proposes fix"
> GOOD: "Use when encountering any bug, test failure, or unexpected behavior"

```markdown
# Your Skill Name

## Overview

[What is this? Core principle in 1-2 sentences.]
```

> Keep this concise. The overview should answer:
> "What is this skill and why does it matter?"

```markdown
## When to Use

[Bullet list with SYMPTOMS and use cases]
[When NOT to use]
```

> Include concrete triggers: error messages, symptoms, situations.
> Also include when NOT to use -- prevents misapplication.
> Optional: small flowchart IF the decision is non-obvious.

```markdown
## The Iron Law (optional, for discipline-enforcing skills)

[One-line rule that cannot be violated]
```

> Use this for skills that enforce discipline (TDD, debugging process).
> State the rule clearly and absolutely. Add "No exceptions" sections
> that explicitly close loopholes agents might find.

```markdown
## Core Pattern / Process

[The main content of the skill]
[For techniques: step-by-step with code examples]
[For patterns: before/after comparison]
[For reference: organized lookup tables]
```

> This is the meat of the skill. Structure depends on type:
>
> **Technique skill** (how-to):
>   - Numbered steps with code examples
>   - One excellent example beats many mediocre ones
>   - Choose the most relevant language for your domain
>
> **Pattern skill** (mental model):
>   - Before/after comparison showing the pattern in action
>   - When to apply and when NOT to apply
>
> **Reference skill** (documentation):
>   - Organized tables and lookup sections
>   - Move heavy reference (100+ lines) to separate files
>
> **Discipline skill** (process enforcement):
>   - Phases with gates between them
>   - Explicit rationalization table (see below)
>   - Red flags list for self-checking

```markdown
## Quick Reference

[Table or bullets for scanning common operations]
```

> Make this scannable. Agents should be able to find what they need
> without reading the entire skill.

```markdown
## Common Mistakes

[What goes wrong + how to fix it]
```

> Include real mistakes you've encountered. Be specific:
> BAD:  "Don't make mistakes"
> GOOD: "Changing multiple variables at once makes it impossible to
>        attribute improvement. Change ONE variable per experiment."

```markdown
## Common Rationalizations (for discipline-enforcing skills)

| Excuse | Reality |
|--------|---------|
| "Too simple to need this" | Simple things break too. Process is fast for simple cases. |
| "No time for process" | Systematic is faster than thrashing. |
| "Just this once" | First skip sets the pattern. Do it right from the start. |
```

> Build this table from actual testing. When you test the skill with
> a sub-agent under pressure, document every rationalization they use
> and add an explicit counter to this table.

```markdown
## Red Flags - STOP and Follow Process

- [List of thoughts that indicate you're about to violate the skill]

**All of these mean: STOP. Return to the beginning.**
```

> These are self-check triggers. When the agent catches itself
> thinking one of these things, it should stop and re-engage
> with the skill's process.

```markdown
## Real-World Impact (optional)

[Concrete results showing the value of this approach]
```

> Include measurable outcomes when available.
> "Systematic approach: 15-30 min. Random fixes: 2-3 hours."

---

## Skill Types Reference

| Type | Examples | Test With |
|------|----------|-----------|
| **Technique** | Condition-based waiting, root-cause tracing | Application scenarios: can agent apply it? |
| **Pattern** | Flatten-with-flags, test invariants | Recognition: does agent know when to use it? |
| **Reference** | API docs, command guides | Retrieval: can agent find the right info? |
| **Discipline** | TDD, systematic debugging | Pressure scenarios: does agent comply under stress? |

## Search Optimization Tips

Future Claude instances need to FIND your skill. Optimize for discovery:

1. **Rich description** -- Include symptoms, error messages, situations
2. **Keyword coverage** -- Use words the agent would search for
3. **Descriptive naming** -- Verb-first, active voice (e.g., `condition-based-waiting`)
4. **Token efficiency** -- Target under 500 words for most skills
5. **Cross-references** -- Link to related skills by name (not file path)

## Testing Your Skill

Skills should be tested like code:

1. **RED:** Run a scenario WITHOUT the skill. Document baseline behavior.
2. **GREEN:** Run the SAME scenario WITH the skill. Agent should now comply.
3. **REFACTOR:** Find loopholes. Close them. Re-test.

For discipline-enforcing skills, test under pressure:
- Time pressure: "We need this fixed NOW"
- Sunk cost: "I already spent 3 hours on this approach"
- Authority: "The tech lead says just ship it"
- Exhaustion: "This is the 5th thing we've tried"
