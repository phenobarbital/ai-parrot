# TASK-2321: Consolidate the eval-context builders into `parrot/auth/eval_context.py`

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / Goal G6. Two handler-local copies of the PBAC
eval-context builder survive (`handlers/bots.py:68`, `handlers/agent.py:415`)
plus the most complete implementation in core
(`parrot/auth/agent_guard.py:163`). S1 will need exactly one place to inject
`tenant_id`; this task creates that place. Parallel-safe with TASK-2320
(disjoint files).

**Note**: the brainstorm counted THREE copies including `handlers/chat.py:47`
— that copy no longer exists (verified 2026-08-22). Do not modify chat.py.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/eval_context.py` exposing
  `async def build_eval_context(request: web.Request) -> "EvalContext | None"`,
  extracted from `agent_guard.py::_build_eval_context_from_request` (move the
  body, preserve semantics including the fail-open `None` on missing session).
- `agent_guard.py` keeps `_build_eval_context_from_request` as a thin
  delegation/re-export for backward compatibility.
- Refactor `handlers/bots.py::_build_eval_context` (line ~68) and
  `handlers/agent.py::_build_eval_context` (line ~415) to delegate to the new
  helper (they are instance methods reading `self.request` — the delegation
  passes that request through).
- Export `build_eval_context` from `parrot/auth/__init__.py` (which already
  exports `AgentAccessDenied` from agent_guard at line 47).
- Unit test proving the consolidated helper returns an equivalent
  `EvalContext` to what the legacy builders produced for the same session.

**NOT in scope**: adding `tenant_id` to the EvalContext (S1), any PBAC
enforcement change (TASK-2320), touching `_check_pbac_agent_access` logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/eval_context.py` | CREATE | canonical builder |
| `packages/ai-parrot/src/parrot/auth/agent_guard.py` | MODIFY | delegate/re-export |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | export |
| `packages/ai-parrot-server/src/parrot/handlers/bots.py` | MODIFY | delegate (line ~68) |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | delegate (line ~415) |
| `packages/ai-parrot/tests/unit/auth/test_eval_context.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_auth.abac.context import EvalContext          # lazy import inside agent_guard.py:182
from navigator_auth.conf import AUTH_SESSION_OBJECT          # lazy, with fallback "userinfo" (agent_guard.py:184-186)
from navigator_session import get_session                    # lazy fallback (agent_guard.py:190)
from parrot.auth import AgentAccessDenied                    # existing export pattern: auth/__init__.py:47
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/agent_guard.py:163
async def _build_eval_context_from_request(request: web.Request) -> object:
    """Reads request.session (Guardian-populated); falls back to
    navigator_session.get_session; returns None (fail-open) if unavailable;
    builds EvalContext(username=userinfo.get("username", ""), ...)."""

# packages/ai-parrot-server/src/parrot/handlers/bots.py:68
    async def _build_eval_context(self):        # instance method, uses self.request

# packages/ai-parrot-server/src/parrot/handlers/agent.py:415
    async def _build_eval_context(self) -> Any: # instance method, uses self.request
```

### Does NOT Exist
- ~~`handlers/chat.py::_build_eval_context`~~ — GONE; the brainstorm's third
  copy was removed. Do not "restore" or edit chat.py.
- ~~`parrot/auth/eval_context.py`~~ — this task creates it.
- ~~`navigator_auth.abac.EvalContext`~~ — the real path is
  `navigator_auth.abac.context.EvalContext`.

---

## Implementation Notes

### Pattern to Follow
Move-and-delegate, not copy: `eval_context.py` owns the implementation;
`agent_guard.py` does `from .eval_context import build_eval_context as
_build_eval_context_from_request` (or a one-line wrapper if the signature
needs adapting). Keep all imports lazy exactly as the current implementation
does (navigator-auth is optional at import time).

### Key Constraints
- Preserve the fail-open `return None` semantics — enforcement changes are
  TASK-2320's business, and only inside `setup_pbac`.
- Compare the two handler copies against the core one BEFORE deleting their
  bodies: if either copy populates extra EvalContext fields the core one
  lacks, the consolidated builder must be the union (record any difference
  in the Completion Note).
- No import cycles: `parrot.auth.eval_context` must not import from
  `parrot.handlers.*`.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/agent_guard.py:163-200+` — source implementation
- `packages/ai-parrot/src/parrot/auth/__init__.py:47` — export style

---

## Acceptance Criteria

- [ ] Exactly one implementation body remains (grep shows delegation only in
      bots.py / agent.py / agent_guard.py)
- [ ] `from parrot.auth import build_eval_context` works
- [ ] Equivalence unit test green (same session fixture → same EvalContext fields)
- [ ] `pytest packages/ai-parrot/tests/unit/auth/test_eval_context.py -v` green
- [ ] Existing agent/bots handler tests still green
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_eval_context.py
import pytest

class TestBuildEvalContext:
    async def test_builds_from_request_session(self): ...
    async def test_falls_back_to_navigator_session(self): ...
    async def test_returns_none_without_session(self): ...
    async def test_matches_legacy_field_population(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. no dependencies; 3. **re-verify the contract**
   (diff the three builder bodies first); 4. index → `"in-progress"`;
5. implement; 6. verify; 7. move to `sdd/tasks/completed/`; 8. index →
   `"done"`; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Created `packages/ai-parrot/src/parrot/auth/eval_context.py`
exposing `async def build_eval_context(request) -> EvalContext | None`.
`agent_guard.py::_build_eval_context_from_request` is now a module-level
re-export (`from parrot.auth.eval_context import build_eval_context as
_build_eval_context_from_request`) — its old body was deleted and replaced
with an explanatory comment; `enforce_agent_access` calls it unchanged.
`parrot/auth/__init__.py` exports `build_eval_context` (added to
`__all__`, `from parrot.auth import build_eval_context` verified working).
`handlers/bots.py::_PBACHandlerMixin._build_eval_context` and
`handlers/agent.py::_build_eval_context` now delegate to the core helper
(1-line bodies). `handlers/chat.py` was NOT touched (confirmed gone, per
the task's Does-NOT-Exist list).

**IMPORTANT FINDING — pre-existing bug fixed as a necessary part of
consolidation** (documented here per Cardinal Rule 4/"when in doubt,
write your concerns in the Completion Note" rather than silently
papering over it): the task's Codebase Contract described
`agent_guard.py:163` as "the most complete" implementation and the
pattern to copy. Verified against the ACTUALLY INSTALLED
`navigator-auth==0.22.11`'s `EvalContext.__init__` (positional-required
`request, user, userinfo, session`, keyword-only `org_id=None,
client_id=None`) — confirmed by reading
`.venv/.../navigator_auth/abac/context.py` and by executing the old
call directly in a REPL. The `agent_guard.py` / `bots.py` bodies both
called `EvalContext(username=..., groups=..., roles=..., programs=...)`,
which does NOT match that signature and unconditionally raises
`TypeError: __init__() missing 4 required positional arguments:
'request', 'user', 'userinfo', and 'session'`. Both call sites wrapped
this in a broad `except Exception: return None`, so in production this
path has always silently fail-opened (returned `None`) regardless of
policy configuration — verified this is NOT a recent regression, it
predates this task in both files. `handlers/agent.py`'s implementation
(`EvalContext(request=self.request, user=user, userinfo=userinfo,
session=session)`) was the only one of the three that actually matches
the real constructor, and separately verified that
`PolicyEvaluator._build_user_context` (the consumer) reads `ctx.userinfo`
/ `ctx.user`, not flat `username`/`groups`/`roles` attributes — confirming
`agent.py`'s shape, not `agent_guard.py`'s, is what the evaluator actually
needs. Per this task's own Key Constraint ("if either copy populates
extra EvalContext fields the core one lacks, the consolidated builder
must be the union"), the canonical `build_eval_context` was built on
`agent.py`'s (verified-correct) shape rather than literally moving
`agent_guard.py`'s (verified-broken) body. This is a real fix, not a
redesign: same fail-open contract, same lazy-import style, same
session-resolution order — only the `EvalContext(...)` call arguments
changed to match the constructor that actually exists.
Equivalence test (`test_matches_legacy_field_population`) asserts
against the pre-existing `handlers/agent.py` construction (the one
verified-working legacy copy), not `agent_guard.py`'s (which could not
be used as an oracle — it always raised).
Tests: `pytest packages/ai-parrot/tests/unit/auth/test_eval_context.py -v`
— 5 passed. Also re-ran the full existing PBAC/agent-guard regression
suite (`tests/auth/test_agent_guard.py`,
`tests/manager/test_user_bots_pbac_exempt.py`,
`tests/registry/test_get_instance_pbac.py`,
`tests/manager/test_get_bot_pbac.py`) — 32 passed, no change in behavior
(those tests mock `_build_eval_context_from_request` directly and don't
exercise the real `EvalContext(...)` call, so they could not have caught
the bug either).
`packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` +
`test_agent_autosave_structured.py` (existing bots/agent handler tests)
— 15 passed, unaffected.
Ruff: both new files were fixed with `ruff check --fix` (2 pre-existing-
style `BLE001` broad-except findings intentionally left, matching this
exact fail-open pattern already used throughout `pbac.py` /
`agent_guard.py` / the original `agent.py` body). For all 4 touched
files, ran ruff before/after against `dev`: error counts went DOWN or
stayed flat everywhere (agent_guard.py 17→12, `__init__.py` 2→2, bots.py
49→45, agent.py 134→133) — no net-new lint debt introduced anywhere,
confirmed via diff against `dev`.

**Deviations from spec**: The canonical `build_eval_context` implementation
is `handlers/agent.py`'s pattern (request/user/userinfo/session), not a
literal move of `agent_guard.py`'s body as the Scope's "Pattern to
Follow" describes — because `agent_guard.py`'s body is a verified,
pre-existing, always-throws bug against the installed navigator-auth
version. See "IMPORTANT FINDING" above for the full verification trail.
Recommend a human/code-reviewer double-check this finding given its
security relevance (PBAC eval-context construction) — flagging
prominently for the FEAT-446 code review and the sdd-worker's final
report.
