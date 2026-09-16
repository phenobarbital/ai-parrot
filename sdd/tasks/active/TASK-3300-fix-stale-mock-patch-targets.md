# TASK-3300: Fix stale `unittest.mock.patch` targets in handler/policy tests

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3297
**Assigned-to**: unassigned

---

## Context

Implements Module 8. Four test files patch names that two unrelated refactors
removed from module scope, so they fail with `AttributeError: <module ...> does
not have the attribute ...` — **regardless of whether any satellite is
installed** (this is why they were pulled out of Module 2's satellite-gap list
during the spec review):

1. `test_mediagen_handler.py`, `test_understanding_handler.py`,
   `test_understanding_integration.py` patch
   `parrot.handlers.<mediagen|understanding>.GoogleGenAIClient`. FEAT-523
   (TASK-2846, AC-3) made those handlers import `GoogleGenAIClient` **inside the
   method body** (`mediagen.py:90`, `understanding.py:213`) so core never
   imports a provider at module scope. `unittest.mock.patch` can only replace a
   module-level name → the patch target no longer exists.
2. `test_policy_rules_integration.py` patches
   `parrot.handlers.bots._EvalContext` at 2 sites (lines 230, 341).
   `bots.py` no longer binds `_EvalContext`; it delegates to
   `parrot.auth.eval_context.build_eval_context`, imported as
   `_core_build_eval_context` (`bots.py:16`, FEAT-446). `build_eval_context` is
   **async**, so its mock must be an `AsyncMock`.

---

## Scope

- Repoint the three handler tests' patch target from
  `parrot.handlers.<mediagen|understanding>.GoogleGenAIClient` to
  `parrot.clients.google.GoogleGenAIClient` (the SOURCE the lazy `from
  parrot.clients.google import GoogleGenAIClient` re-reads at call time — a
  function-local import sees a patched source attribute). Add a
  `pytest.importorskip("parrot.clients.google")` module guard so these skip in
  bare `test-core` and run in TASK-3297's job.
- In `test_policy_rules_integration.py`, change ONLY the 2 handler-level
  `patch('parrot.handlers.bots._EvalContext', MagicMock(...))` sites (lines
  230, 341) to `patch('parrot.handlers.bots._core_build_eval_context',
  AsyncMock(return_value=<eval_context>))`, assert it is awaited with the
  request, and keep the surrounding `_PBAC_AVAILABLE`/`_ResourceType` patches.
  **Leave the 2 `patch.object(_bots_abstract, '_EvalContext', ...)` sites
  (lines 149, 173) unchanged** — `parrot.bots.abstract._EvalContext` still
  exists and is called synchronously.

**NOT in scope**: any production code change (no import is restored to
accommodate a stale test); the `test-optional-integrations` job itself
(TASK-3297); other test modules. No authorization/handler behaviour assertion
is weakened — only the mock plumbing is corrected.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/handlers/test_mediagen_handler.py` | MODIFY | Patch target → `parrot.clients.google.GoogleGenAIClient`; add google importorskip |
| `tests/handlers/test_understanding_handler.py` | MODIFY | `HANDLER_PATH` → `parrot.clients.google.GoogleGenAIClient`; add google importorskip |
| `tests/handlers/test_understanding_integration.py` | MODIFY | `HANDLER_PATH` → `parrot.clients.google.GoogleGenAIClient`; add google importorskip |
| `tests/auth/test_policy_rules_integration.py` | MODIFY | 2 handler-level `_EvalContext` patches → `_core_build_eval_context` AsyncMock; abstract sites unchanged |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from unittest.mock import AsyncMock, MagicMock, patch  # AsyncMock needed for the async build_eval_context
# Patch TARGET for the handlers (the re-exporting source of the lazy import):
#   "parrot.clients.google.GoogleGenAIClient"
#   verified: packages/ai-parrot-client-google/src/parrot/clients/google/__init__.py:1,9
#   (`from .client import GoogleGenAIClient`; exported in __all__)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/mediagen.py:90    (inside method)
#   from parrot.clients.google import GoogleGenAIClient
# packages/ai-parrot-server/src/parrot/handlers/understanding.py:213 (inside method)
#   from parrot.clients.google import GoogleGenAIClient
# packages/ai-parrot-server/src/parrot/handlers/bots.py:16
#   from parrot.auth.eval_context import build_eval_context as _core_build_eval_context
# packages/ai-parrot/src/parrot/auth/eval_context.py:23
#   async def build_eval_context(request: web.Request) -> object | None   # ASYNC → AsyncMock
# packages/ai-parrot-server/src/parrot/handlers/bots.py:10-14
#   _ResourceType, _PBAC_AVAILABLE  STILL EXIST (from navigator_auth.abac...) — keep those patches

# The 4 patch sites in tests/auth/test_policy_rules_integration.py:
#   :149, :173  patch.object(_bots_abstract, '_EvalContext', ...)  → CORRECT, LEAVE UNCHANGED
#               (parrot.bots.abstract._EvalContext still exists: abstract.py:157)
#   :230, :341  patch('parrot.handlers.bots._EvalContext', ...)    → BROKEN, FIX THESE TWO
```

### Does NOT Exist
- ~~`parrot.handlers.mediagen.GoogleGenAIClient`,
  `parrot.handlers.understanding.GoogleGenAIClient`~~ — never bound at module
  scope (function-local import). Do NOT add a module-level import to "fix" this
  — that reintroduces the hard dependency FEAT-523 TASK-2846 removed. Fix the
  patch target.
- ~~`parrot.handlers.bots._EvalContext`~~ — removed; `bots.py` uses
  `_core_build_eval_context` (an alias for the async `build_eval_context`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "tests/handlers/test_mediagen_handler.py", "action": "MODIFY" },
    { "path": "tests/handlers/test_understanding_handler.py", "action": "MODIFY" },
    { "path": "tests/handlers/test_understanding_integration.py", "action": "MODIFY" },
    { "path": "tests/auth/test_policy_rules_integration.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/eval_context.py#build_eval_context"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- A function-local `from parrot.clients.google import GoogleGenAIClient`
  re-reads the attribute from `parrot.clients.google` every call, so patching
  `parrot.clients.google.GoogleGenAIClient` IS visible to it — that is why the
  source path is the correct target, not the handler module.
- `build_eval_context` is async → `AsyncMock`, and assert it was **awaited**
  with the request. Patching `parrot.auth.eval_context.build_eval_context` at
  its source would NOT replace `bots.py`'s already-bound `_core_build_eval_context`
  alias — patch the alias on `parrot.handlers.bots`.
- Policy-only tests must not become gated on Google — only the three handler
  tests get the google `importorskip`; the policy test is server/auth-scoped.

---

## Implementation Blueprint

### Steps (in order)
1. In the three handler tests, swap the patch target string and add the google
   guard — *why*: the source attribute is the correct, installed-only target.
2. In the policy test, fix the 2 handler-level sites with AsyncMock, leave the 2
   abstract sites alone — *why*: only `bots._EvalContext` was removed; the
   abstract one still exists and is sync.
3. Confirm each file skips (not errors) in bare core and passes with the deps
   installed — *why*: AC requires both.

### `tests/handlers/test_understanding_handler.py` (MODIFY) — representative handler fix
```python
# occurrences: 1 (verified: grep -c 'HANDLER_PATH = "parrot.handlers.understanding.GoogleGenAIClient"' tests/handlers/test_understanding_handler.py)
# REPLACE line 16 target and add a module-scope guard near the top imports:
import pytest

pytest.importorskip("parrot.clients.google")  # skip in bare test-core; runs in test-optional-integrations
HANDLER_PATH = "parrot.clients.google.GoogleGenAIClient"  # was parrot.handlers.understanding.GoogleGenAIClient
```
**Why**: patches the source the handler's lazy import resolves against; the
guard degrades bare core cleanly. Apply the same to
`test_understanding_integration.py` (line 21, identical `HANDLER_PATH`) and
`test_mediagen_handler.py` (line 34: `patch("parrot.handlers.mediagen.
GoogleGenAIClient")` → `patch("parrot.clients.google.GoogleGenAIClient")`).

### `tests/auth/test_policy_rules_integration.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c "patch('parrot.handlers.bots._EvalContext'" tests/auth/test_policy_rules_integration.py)
# Both occurrences (lines 230, 341) are inside a `with patch(...) , patch(...):`
# block that ALSO patches _PBAC_AVAILABLE and _ResourceType — keep those.
# REPLACE only the _EvalContext line in each block:
#     patch('parrot.handlers.bots._core_build_eval_context',
#           new=AsyncMock(return_value=_eval_context_stub)), \
# FILL IN: _eval_context_stub — a context object compatible with the existing
#   evaluator assertions in that test (read what the block asserts the PBAC
#   evaluation returns), and add `<mock>.assert_awaited()` with the request.
#   bounded by AC "use AsyncMock at _core_build_eval_context, assert awaited,
#   retain the filtering/authorization assertions".
# DO NOT touch lines 149, 173 (patch.object(_bots_abstract, '_EvalContext', ...)).
```
**Why**: `bots._EvalContext` was removed; `_core_build_eval_context` (async) is
the real delegation seam. AsyncMock + `assert_awaited` preserves the test's
authorization intent. The `_bots_abstract._EvalContext` sites are a different,
still-valid target and must stay MagicMock (sync).

### FILL IN checklist
- [ ] Three handler tests: patch target → `parrot.clients.google.GoogleGenAIClient` + google importorskip — bounded by Codebase Contract.
- [ ] Policy test: 2 handler-level sites → `_core_build_eval_context` AsyncMock with `assert_awaited`; `_eval_context_stub` compatible with existing assertions — bounded by AC.
- [ ] Verified lines 149/173 (`_bots_abstract._EvalContext`) left unchanged.

---

## Acceptance Criteria

- [ ] All four files pass under TASK-3297's `test-optional-integrations` job
      (Google client + server installed); the structured gate confirms no
      unexpected skips.
- [ ] All four skip (not `ERROR`) under bare `test-core`; the policy test's
      dependency-independent / `_bots_abstract` cases still execute where they
      don't require the server (guard server-dependent cases only).
- [ ] The two handler-level policy patches use `AsyncMock` at
      `_core_build_eval_context`, assert it was awaited with the request, and
      retain their filtering/authorization assertions.
- [ ] The two `_bots_abstract._EvalContext` patches remain synchronous MagicMock,
      unchanged.
- [ ] No production import is restored; no authorization/handler behaviour
      assertion is weakened. `ruff check` clean on all four files.

---

## Test Specification

These four files ARE the tests. Success = they collect+pass with the corrected
mock plumbing under the installed-dependency job, and skip cleanly in bare core,
with every behavioural assertion intact.

---

## Agent Instructions

Standard SDD flow. **Depends on TASK-3297** (its `test-optional-integrations`
job is where these run for real). Do NOT touch production handler/bots source —
this is a test-plumbing fix. Do NOT modify the two abstract-level patch sites.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
