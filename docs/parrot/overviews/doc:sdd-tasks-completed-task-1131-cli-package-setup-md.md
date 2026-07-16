---
type: Wiki Overview
title: 'TASK-1131: CLI Package Setup & Dependency Addition'
id: doc:sdd-tasks-completed-task-1131-cli-package-setup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: at `packages/ai-parrot/src/parrot/cli.py` (lines 34-40)
relates_to:
- concept: mod:parrot.autonomous.cli
  rel: mentions
- concept: mod:parrot.cli
  rel: mentions
- concept: mod:parrot.cli.agent_repl
  rel: mentions
- concept: mod:parrot.cli.repl
  rel: mentions
- concept: mod:parrot.install.cli
  rel: mentions
- concept: mod:parrot.install.conf
  rel: mentions
- concept: mod:parrot.mcp.cli
  rel: mentions
- concept: mod:parrot.setup.cli
  rel: mentions
---

# TASK-1131: CLI Package Setup & Dependency Addition

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for the CLI agent REPL feature.  Creates the `parrot/cli/`
> subpackage, adds the `prompt_toolkit` dependency, and registers the `agent`
> subcommand in the existing Click LazyGroup.  All subsequent tasks depend on
> this package structure being in place.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/__init__.py` (empty or minimal exports)
- Add `prompt_toolkit>=3.0` to `packages/ai-parrot/pyproject.toml` dependencies
- Register `"agent": "parrot.cli.agent_repl"` in the LazyGroup subcommands dict
  at `packages/ai-parrot/src/parrot/cli.py` (lines 34-40)
- Create a stub `packages/ai-parrot/src/parrot/cli/agent_repl.py` with a minimal
  Click command that prints "Not yet implemented" (so the import resolves)

**NOT in scope**: actual REPL logic, agent loading, rendering, commands

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/__init__.py` | CREATE | Package init |
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | CREATE | Stub Click command |
| `packages/ai-parrot/src/parrot/cli.py` | MODIFY | Add `agent` to LazyGroup dict |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `prompt_toolkit>=3.0` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.cli import cli  # verified: parrot/cli.py:28
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli.py
class LazyGroup(click.Group):  # line 10
    ...

@click.group(cls=LazyGroup)
def cli():  # line 28
    ...
# Registered subcommands (lines 34-40):
#   "setup": "parrot.setup.cli",
#   "conf": "parrot.install.conf",
#   "install": "parrot.install.cli",
#   "mcp": "parrot.mcp.cli",
#   "autonomous": "parrot.autonomous.cli",
```

### Does NOT Exist
- ~~`parrot.cli.agent`~~ — no existing `agent` subcommand (this task creates it)
- ~~`parrot.cli.repl`~~ — no existing `cli/` subpackage (this task creates it)
- ~~`prompt_toolkit`~~ — NOT currently in deps (this task adds it)

---

## Implementation Notes

### Pattern to Follow
```python
# Existing pattern in cli.py lines 34-40 — add one more entry:
lazy_subcommands = {
    "setup": "parrot.setup.cli",
    "conf": "parrot.install.conf",
    "install": "parrot.install.cli",
    "mcp": "parrot.mcp.cli",
    "autonomous": "parrot.autonomous.cli",
    "agent": "parrot.cli.agent_repl",   # NEW
}
```

### Key Constraints
- The stub command must be importable as `parrot.cli.agent_repl` with a `cli`
  function (Click command) so the LazyGroup import works.
- Add `prompt_toolkit>=3.0` in the same dependency section as `click>=8.1.7`
  and `rich>=13.0`.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/cli/__init__.py` exists
- [ ] `packages/ai-parrot/src/parrot/cli/agent_repl.py` exists with a Click command
- [ ] `parrot agent` runs without import errors (prints stub message)
- [ ] `prompt_toolkit>=3.0` is in `pyproject.toml` dependencies
- [ ] `"agent"` entry in LazyGroup subcommands dict at `cli.py`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/`

---

## Test Specification

```python
# No dedicated test file for this task — verification is import-level:
# python -c "from parrot.cli.agent_repl import cli; print('OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` for full context
2. **Read `packages/ai-parrot/src/parrot/cli.py`** to see the LazyGroup pattern
3. **Read `packages/ai-parrot/pyproject.toml`** to find the dependency section
4. **Create the `cli/` subpackage** with `__init__.py`
5. **Create the stub** `agent_repl.py` with a Click command
6. **Add the LazyGroup entry** in `cli.py`
7. **Add `prompt_toolkit>=3.0`** to pyproject.toml
8. **Verify** the import works

---

## Completion Note

Completed 2026-05-13. Created `parrot/cli/` subpackage by converting `cli.py`
into `cli/__init__.py` (rename + content preserved + LazyGroup registration added),
created stub `cli/agent_repl.py` with `agent` Click command (matching LazyGroup
`getattr(mod, cmd_name)` pattern — key "agent" requires function named `agent`),
and added `prompt_toolkit>=3.0` to `pyproject.toml`. Import verified:
`from parrot.cli.agent_repl import agent` works correctly. All linting passed.
