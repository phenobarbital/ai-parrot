---
name: codex-specifications
description: Create and refine specification files for Codex-driven implementation through CodeToolkit.
---

# Codex Specifications Skill

Use this skill when a user wants a bugfix or feature implemented from a
specification file, or when a Codex coding task needs a clear spec before
execution.

## Workflow

1. Read project instructions first: `AGENTS.md` and `.agent/CONTEXT.md` when present.
2. Check existing specs in `sdd/specs/` and proposals in `sdd/proposals/` for prior decisions.
3. Prefer the local SDD template and workflow:
   - Template: `sdd/templates/spec.md`
   - Workflow reference: `.claude/commands/sdd-spec.md`
4. Create or update a spec with frontmatter that Codex can consume:

```markdown
---
type: bugfix
repo: ai-parrot
test_command: pytest tests/ -q
files_in_scope:
  - packages/ai-parrot/src/parrot/
  - packages/ai-parrot/tests/
definition_of_done:
  - failing test added
  - bug fixed
  - all tests passing
---
```

5. Include a codebase contract with verified file paths, classes, and method signatures.
6. Keep implementation details precise enough for an autonomous coding provider:
   - Problem statement
   - Current behavior
   - Expected behavior
   - Files in scope
   - Constraints
   - Acceptance criteria
   - Validation command
   - Known risks
7. Call `code.implement_spec` only after the spec is explicit, scoped, and testable.

## Guardrails

- Do not re-open resolved SDD brainstorm questions.
- Do not invent imports, classes, or packages. Verify them in the repository.
- Do not ask Codex to make broad unrelated refactors.
- Do not omit a validation command when a relevant test target is known.
- Treat Codex output as a patch proposal until tests and review confirm it.

## Example

```python
await code_toolkit.implement_spec(
    spec_file="specs/bugfix-auth-timeout.md",
    repo_path="/workspace/project",
    test_command="pytest tests/auth -q",
)
```
