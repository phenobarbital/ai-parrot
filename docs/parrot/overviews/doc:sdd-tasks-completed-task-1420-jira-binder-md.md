---
type: Wiki Overview
title: 'TASK-1420: `JiraToolkitBinder` + `FakeJiraClient` + `StaticResolver`'
id: doc:sdd-tasks-completed-task-1420-jira-binder-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Second `ToolkitBinder`, proving the pattern generalizes beyond databases.
  A real `JiraToolkit` runs
relates_to:
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.sandbox.state
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-1420: `JiraToolkitBinder` + `FakeJiraClient` + `StaticResolver`

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 4 (brainstorm §13.2, §13.7 step 6)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1419
**Assigned-to**: unassigned

---

## Context

Second `ToolkitBinder`, proving the pattern generalizes beyond databases. A real `JiraToolkit` runs
its tools against an in-memory `DictStateBackend` with **no real HTTP and no credential-resolver
network call**. This is the enterprise τ-bench-style target (Jira triage benchmark).

---

## Scope

- Add `JiraToolkitBinder(ToolkitBinder)` (in `state.py`), plus `FakeJiraClient` and `StaticResolver`
  (in `fakes.py`) backed by the `DictStateBackend`.
- The binder must make `JiraToolkit._pre_execute` resolve to the `FakeJiraClient` without touching the
  network. Resolve the spec §8 Open Question by picking ONE path:
  - (a) force a no-network auth mode and pre-seed `toolkit.jira = FakeJiraClient(backend)` plus a
    matching `_client_cache` entry, OR
  - (b) set `toolkit.credential_resolver = StaticResolver(test_token)` returning a token whose
    fingerprint matches a pre-seeded cached fake client.
  Read `JiraToolkit._pre_execute` (around line 866) to choose the lowest-friction path.
- `FakeJiraClient` implements only the Jira methods the triage benchmark exercises (e.g. search
  issues, assign, transition) translated into `DictStateBackend` ops on an `"issues"` collection.

**NOT in scope**: the benchmark dataset itself (TASK-1428), evaluator (TASK-1422).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/sandbox/state.py` | MODIFY | Add `JiraToolkitBinder` |
| `packages/ai-parrot/src/parrot/eval/sandbox/fakes.py` | MODIFY | Add `FakeJiraClient`, `StaticResolver` |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export `JiraToolkitBinder` |
| `packages/ai-parrot/tests/eval/test_jira_binder.py` | CREATE | Binder tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.eval.sandbox.state import ToolkitBinder, DictStateBackend   # TASK-1418/1419
from parrot_tools.jiratoolkit import JiraToolkit                         # ai-parrot-tools/.../jiratoolkit.py:630
```

### Existing Signatures to Use
```python
# parrot_tools/jiratoolkit.py
class JiraToolkit(AbstractToolkit):                       # line 630
    def __init__(self, ..., credential_resolver: Any = None, ...): ...  # line 700
    self.credential_resolver = credential_resolver       # line 766  ← swap for StaticResolver
    self.jira = ...                                       # line 772/781/926  ← pre-seed FakeJiraClient
    async def _pre_execute(self, tool_name, **kwargs): ...  # ~line 866 — resolves per-user client
    # _client_cache is keyed by user_key -> (client, token_hash)  (see ~line 926)
# Generic hook that calls _pre_execute before each tool:
# parrot/tools/toolkit.py — ToolkitTool._execute → toolkit._pre_execute(name, _permission_context=..., **kw)
```

### Does NOT Exist
- ~~A Jira test sandbox / `moto`-jira fixture~~ — none; hand-write `FakeJiraClient`.
- ~~`JiraToolkit.store` / `.backend`~~ — Jira state lives behind `self.jira` (the client).

---

## Implementation Notes

### Key Constraints
- **No real HTTP, no real `credential_resolver.resolve()` network call** — assert in tests.
- Match the `_pre_execute` token-fingerprint cache logic so the cached fake client is used (read the
  code around line 926 before implementing).
- `FakeJiraClient` scoped to the benchmark's operations only — not a full Jira API.

### References in Codebase
- `parrot_tools/jiratoolkit.py` — `_pre_execute`, `_client_cache`, `_init_jira_client`.
- TASK-1419 `DatabaseToolkitBinder` — mirror its binder structure.

---

## Acceptance Criteria

- [ ] `from parrot.eval import JiraToolkitBinder` resolves.
- [ ] After binding, a `JiraToolkit` tool call resolves through `_pre_execute` to `FakeJiraClient`
      with no network call (assert `credential_resolver.resolve` real network path not hit / patched).
- [ ] A Jira "assign" tool call mutates the `"issues"` collection in the backend.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_jira_binder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/sandbox/`

---

## Test Specification

```python
import pytest
from parrot.eval import DictStateBackend, JiraToolkitBinder

async def test_jira_binder_assign_mutates_backend():
    backend = DictStateBackend()
    await backend.reset({"issues": {"P-1": {"assignee": None}}})
    # build JiraToolkit, bind, invoke assign tool, assert backend updated + no network
    ...
```

---

## Agent Instructions

Standard SDD flow: read `_pre_execute` first to choose the no-network path, verify the contract, set
index `in-progress`, implement, run tests + ruff, move to `completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
