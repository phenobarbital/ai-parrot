# TASK-5050: Turn-local execution evidence for safe auto-retry (`retry_safety.py`) + shared needs-auth collector

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 "Execution evidence (M4)", AC-7. The chat may auto-resend a prompt after a connect **only**
when the server proves no tool body began in that turn. This task builds that proof: a ContextVar-scoped,
turn-local tracker that `ToolManager` and `AbstractTool.execute` feed, and that AgentTalk (TASK-5051) reads.

**Correction to the spec's boundary (record in the Completion Note).** The spec puts the "body started" mark in
`ToolManager._observed`. On dev that is too early: `_observed` wraps `tool.execute()`
(`manager.py:2186-2188`), and the credential gate that raises `CredentialRequired` runs *inside* `execute()`,
**before** the tool body (`abstract.py:1023-1046`, body at `:1053-1071`). Marking in `_observed` alone would flag
every broker auth failure as "body started", so `retry_safe` could never be true — the very case the feature
exists for. The tracker therefore records three things:

- `_observed` → `mark_dispatch()` always; plus `mark_body_started()` for plain function tools (their call *is* the body);
- `AbstractTool.execute` → `mark_pre_body_auth_failure()` right before raising `CredentialRequired` from the gate,
  and `mark_body_started()` right before the executor / `_execute` dispatch.

A tool that overrides `execute()` never reports either mark, so its dispatch stays unexplained and the turn is
unsafe — conservative by construction.

**Shared needs-auth collector.** TASK-5051 also needs the list of `AuthRequiredPayload`s raised during the turn, because
`AbstractClient._execute_tool` unwraps a `ToolResult` to `result.result` (`clients/base.py:1660-1667`) — an
`authorization_required` result reaches `AIMessage.tool_calls[*].result` as `None`, so the spec's
`_auth_required_from(ai_message)` cannot see it. FEAT-775 M5 / FEAT-776 M1 (Telegram/Teams connections, parallel
features) define exactly that collector, `parrot/auth/pending.py`, with the rule "whichever feature merges first
creates it; the second verifies the identical contract". This task creates it if it is still absent.

---

## Scope

- Step 1 gate on `parrot/auth/pending.py` (below).
- Create `parrot/auth/retry_safety.py`: `TurnExecutionTracker`, `track_turn()`, `current_turn_tracker()`.
- `ToolManager._observed`: new keyword `gated: bool = False`; mark dispatch (and body for non-gated calls) in **both**
  the observed and the unobserved branch; pass `gated=True` from the `_call_tool_execute` call site only.
- `AbstractTool.execute`: the two marks above.
- Create `parrot/auth/pending.py` (verbatim shared contract) and the one `record_auth_requirement(payload)` call in
  `ToolManager`'s needs-auth branch — unless the gate says it exists.
- Tests.

**NOT in scope**: AgentTalk wiring and the `retry_safe` flag on responses (TASK-5051); the UI guard (TASK-5055);
general tool idempotency (spec §2: not claimed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/retry_safety.py` | CREATE | turn tracker |
| `packages/ai-parrot/src/parrot/auth/pending.py` | CREATE | shared needs-auth collector (FEAT-775/776 contract) |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `_observed` marks; `gated=True` call site; `record_auth_requirement` |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | pre-body auth / body-start marks |
| `packages/ai-parrot/tests/auth/test_retry_safety.py` | CREATE | tracker + ToolManager/AbstractTool tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired   # verified: credentials.py:114, :128
from parrot.auth.exceptions import AuthorizationRequired                      # verified: exceptions.py:12
from parrot.tools.abstract import AbstractTool, ToolResult                    # verified: tools/manager.py:10
from parrot.tools.manager import ToolManager                                  # verified: tools/manager.py:290
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py
from ..auth.credentials import CredentialRequired      # :19
from ..auth.exceptions import AuthorizationRequired    # :20
class _Observation: __slots__ = ("executed",)          # :274 — per-dispatch FEAT-538 marker (keep untouched)
async def _call_tool_execute(tool, exec_kwargs, parameters, approved) -> Any   # :1724 (staticmethod-style helper)
async def _observed(self, observation, tool_name, call, *, sync: bool = False) -> Any   # :1735
#   observer = self._invocation_observer (:1771); `        if observer is None or observation is None:` (:1772)
#   → unobserved branch `return call() if sync else await call()` (:1773); observed branch :1775-1786
#   call sites: :2061, :2063 (full-result plain function), :2102, :2104 (plain function), :2186-2188 (_call_tool_execute)
#   needs-auth branch: `        except (AuthorizationRequired, CredentialRequired) as auth_exc:` (:2274) → payload (:2275-2279),
#   self.logger.info(...) (:2280-2284), `return ToolResult(... status="authorization_required" ...)` (:2285-2291)

# packages/ai-parrot/src/parrot/tools/abstract.py
async def execute(self, *args, **kwargs) -> ToolResult   # :916
#   credential gate: `                if self.credential_provider and _broker is not None:` (:1023);
#   `                    if isinstance(resolution, NeedsAuth):` (:1041) → `raise CredentialRequired(...)` (:1042-1046)
#   `                # ── Remote execution dispatch (executor=) ─────────────────────` (:1050) → executor / self._execute (:1053-1071)
async def run(self, *args, **kwargs)   # :1233 — direct body call, bypasses execute; leave unmarked (no dispatch → no false safety)
```

### Does NOT Exist
- ~~`parrot.auth.retry_safety`~~ — created here.
- ~~`parrot.auth.pending`~~ on `origin/dev` at task-writing time (2026-10-31) — FEAT-776 TASK-5016 plans it too (uncommitted then).
- ~~`ToolResult` reaching `AIMessage.tool_calls[*].result`~~ — the client stores `result.result` (`clients/base.py:1667`).
- ~~A "tool metadata says safe" flag~~ — never read tool metadata for safety (spec §3 M4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/retry_safety.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/auth/pending.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_retry_safety.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager._observed",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager._execute_tool_impl",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool.execute",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#AuthRequiredPayload"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The ContextVar holds a **mutable object**; `asyncio.gather` / `create_task` copy the context, so parallel tool
  calls in one turn update the same tracker and concurrent turns never share one. Never rebind the var inside a `mark_*`.
- Unbound tracker → every mark is a silent no-op (CLI, A2A, Telegram unaffected).
- Do not replace or reorder the FEAT-538 observer calls; the marks are additive.

---

## Implementation Blueprint

### Steps (in order)
1. **Gate**: `git fetch origin && git show origin/dev:packages/ai-parrot/src/parrot/auth/pending.py`. If it exists,
   remove the `pending.py` row from this task's Files table and Complexity Contract FIRST (commit that edit), verify
   it exposes `collect_auth_requirements()` and `record_auth_requirement(payload)`, and skip the pending blocks below.
   *why*: two collector modules violate FEAT-776 AC-14 and the complexity evaluator rejects a CREATE on an existing file.
2. Create `retry_safety.py` — *why*: one source of truth for the safety decision, shared by both response modes.
3. Edit `_observed` and its gated call site — *why*: every dispatch must be counted, observed or not.
4. Edit `AbstractTool.execute` — *why*: only it knows whether the gate failed before the body.
5. Create `pending.py` + the record call (unless step 1 skipped them).
6. Tests.

### `packages/ai-parrot/src/parrot/auth/retry_safety.py` (CREATE)
```python
"""Turn-local evidence that no tool body began, for server-authored ``retry_safe`` (FEAT-777 M4)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, List, Optional

_TURN: ContextVar[Optional["TurnExecutionTracker"]] = ContextVar("parrot_turn_execution", default=None)


@dataclass
class TurnExecutionTracker:
    """Counts dispatches and how each one ended before/after the tool body."""

    dispatches: int = 0
    bodies_started: int = 0
    pre_body_auth_failures: int = 0
    incomplete_reasons: List[str] = field(default_factory=list)

    def mark_dispatch(self) -> None:
        """A ToolManager dispatch reached the execution boundary."""
        self.dispatches += 1

    def mark_body_started(self) -> None:
        """A tool body (function, executor or ``_execute``) is about to run — permanently unsafe."""
        self.bodies_started += 1

    def mark_pre_body_auth_failure(self) -> None:
        """The credential gate refused before the body ran."""
        self.pre_body_auth_failures += 1

    def mark_incomplete(self, reason: str) -> None:
        """Evidence is not trustworthy (cancellation, unknown path, delegation)."""
        self.incomplete_reasons.append(reason)

    def retry_safe(self, *, auth_requirements: int, reported_tool_calls: int) -> bool:
        """True only for one outstanding auth requirement with every dispatch explained as a pre-body auth failure."""
        # FILL IN: return all of: not self.incomplete_reasons; self.bodies_started == 0; auth_requirements == 1;
        #          self.dispatches >= 1; self.dispatches == self.pre_body_auth_failures;
        #          reported_tool_calls == self.dispatches  — bounded by spec §3 M4 "Execution evidence", AC-7


@contextmanager
def track_turn() -> Iterator[TurnExecutionTracker]:
    """Bind a fresh tracker for one chat turn; always reset."""
    tracker = TurnExecutionTracker()
    token = _TURN.set(tracker)
    try:
        yield tracker
    finally:
        _TURN.reset(token)


def current_turn_tracker() -> Optional[TurnExecutionTracker]:
    """Return the tracker bound to this turn, or ``None`` outside a tracked turn."""
    return _TURN.get()


__all__ = ["TurnExecutionTracker", "track_turn", "current_turn_tracker"]
```

### `packages/ai-parrot/src/parrot/auth/pending.py` (CREATE — skip per Step 1)
```python
"""Request-scoped collector of tool needs-auth payloads (FEAT-775 M5 / FEAT-776 M1 / FEAT-777 M4)."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, List, Optional

from parrot.auth.credentials import AuthRequiredPayload

_PENDING_AUTH: ContextVar[Optional[List[AuthRequiredPayload]]] = ContextVar("parrot_pending_auth", default=None)


@contextmanager
def collect_auth_requirements() -> Iterator[List[AuthRequiredPayload]]:
    """Bind a fresh list for the current context; reset the ContextVar token on exit."""
    pending: List[AuthRequiredPayload] = []
    token = _PENDING_AUTH.set(pending)
    try:
        yield pending
    finally:
        _PENDING_AUTH.reset(token)


def record_auth_requirement(payload: AuthRequiredPayload) -> None:
    """Append ``payload`` when a collector is bound; otherwise do nothing."""
    pending = _PENDING_AUTH.get()
    if pending is not None:
        pending.append(payload)


__all__ = ["collect_auth_requirements", "record_auth_requirement"]
```
**Why verbatim**: this is the FEAT-775/776 contract (`sdd/specs/connections-msteams.spec.md` §2 "New Public Interfaces",
`sdd/tasks/active/TASK-5016-needs-auth-collector.md`). Do not add dedup or filtering.

### `packages/ai-parrot/src/parrot/tools/manager.py` (MODIFY)
```python
# imports — below `from ..auth.exceptions import AuthorizationRequired` (occurrences: 1; verified :20):
from ..auth.pending import record_auth_requirement
from ..auth.retry_safety import current_turn_tracker

# _observed signature (verified :1735-1742) — add the keyword:
        sync: bool = False,
        gated: bool = False,
# docstring Args: `gated: True when `call` runs AbstractTool.execute, which reports its own body/pre-body marks.`

# occurrences: 1 (verified: grep -c '        if observer is None or observation is None:' packages/ai-parrot/src/parrot/tools/manager.py)
# BEFORE — insert above `        if observer is None or observation is None:` (verified: manager.py:1772)
        tracker = current_turn_tracker()
        if tracker is not None:
            tracker.mark_dispatch()
            if not gated:
                tracker.mark_body_started()  # a plain function's call IS its body

# occurrences: 1 (verified: grep -c 'observation, tool_name, lambda: self._call_tool_execute(tool, exec_kwargs, parameters, approved)' …)
# CHANGE the call at :2186-2188 to:
                result = await self._observed(
                    observation,
                    tool_name,
                    lambda: self._call_tool_execute(tool, exec_kwargs, parameters, approved),
                    gated=True,
                )

# occurrences: 1 (verified: grep -c '        except (AuthorizationRequired, CredentialRequired) as auth_exc:' …)
# BEFORE `return ToolResult(` in that branch (verified :2285), after the logger.info call:
            record_auth_requirement(payload)
```

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '                    if isinstance(resolution, NeedsAuth):' packages/ai-parrot/src/parrot/tools/abstract.py)
# INSIDE that if, BEFORE `raise CredentialRequired(` (verified :1041-1042):
                        _turn = current_turn_tracker()
                        if _turn is not None:
                            _turn.mark_pre_body_auth_failure()

# occurrences: 1 (verified: grep -c '                # ── Remote execution dispatch (executor=) ─────────────────────' …abstract.py)
# BEFORE that comment line (verified :1050), same indentation as the `if self.credential_provider` block:
                _turn = current_turn_tracker()
                if _turn is not None:
                    _turn.mark_body_started()

# import: add near the other module imports (:19-30), lazily if a cycle appears (parrot.auth imports tools? verify):
from ..auth.retry_safety import current_turn_tracker
```
**Why**: `retry_safety.py` imports nothing from `parrot`, so a module-level import cannot create a cycle; keep it
module-level unless `python -c "import parrot.tools.abstract"` proves otherwise.

### `packages/ai-parrot/tests/auth/test_retry_safety.py` (CREATE)
```python
"""FEAT-777 M4: turn-local execution evidence."""
import asyncio

import pytest

from parrot.auth.pending import collect_auth_requirements
from parrot.auth.retry_safety import current_turn_tracker, track_turn


def test_unbound_tracker_is_noop() -> None:
    assert current_turn_tracker() is None


def test_single_pre_body_auth_failure_is_safe() -> None:
    """One dispatch, gate refused before body, one requirement → safe."""
    # FILL IN


def test_body_started_or_multiple_requirements_is_unsafe() -> None:
    """Any body start, two requirements, unexplained dispatch, or mark_incomplete → unsafe."""
    # FILL IN


@pytest.mark.asyncio
async def test_parallel_children_share_tracker_and_turns_are_isolated() -> None:
    """gather() children update one tracker; two concurrent track_turn() contexts never mix."""
    # FILL IN


@pytest.mark.asyncio
async def test_toolmanager_marks_and_records(monkeypatch) -> None:
    """A credential_provider tool whose broker returns NeedsAuth → 1 dispatch, 1 pre-body failure, 0 bodies,
    one payload collected; a plain @tool function → 1 body; the FEAT-538 observer still sees begin/finish."""
    # FILL IN: pattern: packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py (AbstractTool subclass + broker)
```

### FILL IN checklist
- [ ] `TurnExecutionTracker.retry_safe` — bounded by spec §3 M4, AC-7
- [ ] five tests — bounded by spec §4 `test_retry_safety_unknown_and_concurrent_paths` ("existing invocation observer retained")
- [ ] pending.py gate outcome recorded — bounded by FEAT-776 AC-14

---

## Acceptance Criteria

- [ ] Broker-gated auth failure with no body yields `retry_safe(...) is True` for one requirement; any body start makes it `False`.
- [ ] Both `_observed` branches (observer installed or not) count the dispatch; the FEAT-538 observer behaviour is unchanged.
- [ ] Exactly one `def collect_auth_requirements` under `packages/` (`grep -rn "def collect_auth_requirements" packages/`).
- [ ] `ruff check` clean on the four source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_retry_safety.py -q`
- `pytest packages/ai-parrot/tests/unit/test_tool_credential_seam.py -q`

---

## Test Specification

See `test_retry_safety.py` above; cases map to spec §4 `test_agenttalk_retry_safety` (tracker half) and
`test_retry_safety_unknown_and_concurrent_paths`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Run the Step 1 gate** (pending.py) first
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5050 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Record the boundary correction (marks in `AbstractTool.execute` as well as `_observed`) and the pending.py gate result.

**Deviations from spec**: execution boundary refined (see Context).
