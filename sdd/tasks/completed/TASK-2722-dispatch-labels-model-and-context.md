# TASK-2722: `DispatchLabels` model + shared label ContextVar

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Layer 1" and §3 Module 1. This is the foundation task: every other
task in FEAT-496 imports what this one creates.

No dev-loop event today carries any identity of the work it belongs to — you
cannot tell from an event which `TASK-<NNN>`, which pool seat, or which agent
produced it. `DispatchLabels` is the value object that carries that identity,
and `_DISPATCH_LABELS_CTX` is how it reaches the single publish choke point in
each dispatcher without threading a parameter through ~40 internal call sites.

This task creates the model and the context plumbing **only**. It wires
nothing into any dispatcher — that is TASK-2724 through TASK-2728.

---

## Scope

- Add a `DispatchLabels` Pydantic model to
  `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`, exported
  from `parrot.flows.dev_loop.models`.
- Add `_DISPATCH_LABELS_CTX`, `bind_labels()` and `current_labels()` to
  `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py`,
  mirroring the existing `_SESSION_HOST_CTX` idiom in the same module.
- Add the optional `labels: Optional[DispatchLabels] = None` keyword to the
  `DevLoopCodeDispatcher` Protocol's `dispatch()` signature (`_shared.py:131`).
  **Protocol only** — concrete dispatchers are updated in later tasks.
- Write unit tests for the model's `as_payload()` and for ContextVar
  task-locality.

**NOT in scope**: `normalize_payload` (TASK-2723); any change to a concrete
dispatcher, to `session_state.py`, to `agent_pool.py`, or to any console HTML.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | add `DispatchLabels` near `DispatchEvent` (line 735) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` | MODIFY | export `DispatchLabels` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py` | MODIFY | `_DISPATCH_LABELS_CTX`, `bind_labels`, `current_labels`, Protocol kwarg |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_labels.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:19
from parrot.flows.dev_loop.models import DispatchEvent
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:20
from parrot.flows.dev_loop.session_state import SessionHost, action_from_dispatch_event
# stdlib, already imported at _shared.py:13
import contextvars
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py
_SESSION_HOST_CTX: "contextvars.ContextVar[Optional[SessionHost]]" = contextvars.ContextVar(
    "dev_loop_session_host", default=None
)                                                             # line 48-50

def _owning_node_id(node_id: str) -> str:                     # line 53
    return node_id.split(".", 1)[0]                           # line 74

def _apply_to_session_host(event: DispatchEvent) -> None:     # line 76
    host = _SESSION_HOST_CTX.get()                            # line 84

class DevLoopCodeDispatcher(Protocol):                        # line 128
    async def dispatch(                                       # line 131
        self,
        *,
        brief: BaseModel,
        profile: BaseModel,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,           # line 140
    ) -> T: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class DispatchEvent(BaseModel):                               # line 735
    kind: Literal["dispatch.queued", "dispatch.started",      # lines 745-754
                  "dispatch.message", "dispatch.tool_use",
                  "dispatch.tool_result", "dispatch.output_invalid",
                  "dispatch.failed", "dispatch.completed"]
    ts: float                                                 # line 755
    run_id: str                                               # line 756
    node_id: str                                              # line 757
    payload: Dict[str, Any]                                   # line 758

class WorkerSummary(BaseModel):                               # line 481
    worker_id: str   # "development.w1"                       # line 489
    agent: str       # "codex"                                # line 490
    model: str                                                # line 491
```

### Does NOT Exist

- ~~`parrot.flows.dev_loop.models.DispatchLabels`~~ — this task creates it.
- ~~`_DISPATCH_LABELS_CTX`~~ / ~~`bind_labels`~~ / ~~`current_labels`~~ —
  this task creates them. Only `_SESSION_HOST_CTX` and
  `_apply_to_session_host` exist in `_shared.py` today.
- ~~a shared dispatcher base class~~ — there is none; `DevLoopCodeDispatcher`
  is a `typing.Protocol`, not an ABC, so adding a defaulted kwarg to it does
  not break any implementer at runtime.
- ~~`DispatchEvent.labels`~~ — labels ride **inside** `payload`, not as a new
  envelope field. Do not add a field to `DispatchEvent`.

---

## Implementation Notes

### Pattern to Follow

`_shared.py:30-51` already carries a long docstring justifying the ContextVar
approach for `session_host`. Follow it exactly — same reasoning, same shape:

```python
_DISPATCH_LABELS_CTX: "contextvars.ContextVar[Optional[DispatchLabels]]" = (
    contextvars.ContextVar("dev_loop_dispatch_labels", default=None)
)


def bind_labels(labels: Optional[DispatchLabels]) -> "contextvars.Token":
    """Bind labels for the duration of one dispatch() call.

    Callers MUST reset the returned token in a ``finally:`` block, mirroring
    the ``_SESSION_HOST_CTX.set(...)`` / ``.reset(token)`` discipline at
    ``claude.py:211`` / ``:231`` / ``:456``.
    """
    return _DISPATCH_LABELS_CTX.set(labels)


def current_labels() -> Optional[DispatchLabels]:
    """Return the labels bound by the active dispatch() call, if any."""
    return _DISPATCH_LABELS_CTX.get()
```

### Model shape (spec §2 "Data Models")

```python
class DispatchLabels(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = ""        # "TASK-1857" | "RESOLVE_MERGE_CONFLICT"
    task_title: str = ""
    task_file: str = ""      # "sdd/tasks/active/TASK-1857-<slug>.md"
    seat: str = ""           # "development.w1" | "development.resolver"
    agent: str = ""          # "claude-code" | "codex" | "gemini" | ...
    model: str = ""
    subagent: str = ""       # "sdd-worker" | "sdd-qa" | "sdd-secondopinion"
    judge_id: str = ""
    attempt: int = 1

    def as_payload(self) -> Dict[str, Any]:
        """Non-empty fields only — never pads a payload with blanks."""
```

### Key Constraints

- Every field defaults, so a dispatch without labels publishes exactly what it
  publishes today.
- `as_payload()` omits empty strings and omits `attempt` when it is `1`, so an
  unlabelled or default dispatch adds **zero** keys.
- `as_payload()` must never raise.
- Google-style docstrings + full type hints (project rule).
- Do **not** add `task_file` handling logic here — the "only on
  queued/started" policy (spec §7 payload-growth risk) is enforced by
  TASK-2723's normalizer, not by the model.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/_shared.py:30-99` — the ContextVar pattern and its rationale.
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:481-495` — `WorkerSummary`, the closest existing "identity of a seat" model.

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.models import DispatchLabels` works.
- [ ] `from parrot.flows.dev_loop.dispatchers._shared import bind_labels, current_labels` works.
- [ ] `DispatchLabels().as_payload() == {}` — an all-default instance adds no keys.
- [ ] `DispatchLabels` is frozen (mutation raises).
- [ ] `DevLoopCodeDispatcher.dispatch` declares `labels: Optional[DispatchLabels] = None`.
- [ ] Two concurrent `asyncio.Task`s never observe each other's bound labels.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatch_labels.py -v`
- [ ] Existing suite still green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_dispatch_labels.py
import asyncio
import pytest

from parrot.flows.dev_loop.models import DispatchLabels
from parrot.flows.dev_loop.dispatchers._shared import (
    bind_labels, current_labels, _DISPATCH_LABELS_CTX,
)


class TestDispatchLabels:
    def test_empty_labels_add_no_keys(self):
        assert DispatchLabels().as_payload() == {}

    def test_as_payload_omits_empty_fields(self):
        p = DispatchLabels(task_id="TASK-1857", seat="development.w1").as_payload()
        assert p == {"task_id": "TASK-1857", "seat": "development.w1"}

    def test_as_payload_includes_attempt_only_when_gt_one(self):
        assert "attempt" not in DispatchLabels(attempt=1).as_payload()
        assert DispatchLabels(attempt=2).as_payload()["attempt"] == 2

    def test_frozen(self):
        with pytest.raises(Exception):
            DispatchLabels().task_id = "nope"


class TestLabelContext:
    def test_current_labels_defaults_to_none(self):
        assert current_labels() is None

    def test_bind_and_reset(self):
        token = bind_labels(DispatchLabels(task_id="TASK-1"))
        try:
            assert current_labels().task_id == "TASK-1"
        finally:
            _DISPATCH_LABELS_CTX.reset(token)
        assert current_labels() is None

    async def test_labels_are_task_local(self):
        """Two concurrent tasks must never see each other's labels — the
        safety property the whole ContextVar approach rests on."""
        seen = {}

        async def seat(name):
            token = bind_labels(DispatchLabels(seat=name))
            try:
                await asyncio.sleep(0)          # force interleaving
                seen[name] = current_labels().seat
            finally:
                _DISPATCH_LABELS_CTX.reset(token)

        await asyncio.gather(seat("development.w1"), seat("development.w2"))
        assert seen == {"development.w1": "development.w1",
                        "development.w2": "development.w2"}
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/dev-loop-dispatch-event-legibility.spec.md` (§2 Layer 1, §3 Module 1, §6 Codebase Contract).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `_shared.py:48` and `:131` still look as listed before editing.
4. **Update status** in `sdd/tasks/index/dev-loop-dispatch-event-legibility.json` → `"in-progress"`.
5. **Implement** the model + context plumbing. Wire nothing into a dispatcher.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Added `DispatchLabels` to `models/base.py` (frozen, all-default
fields, `as_payload()` omitting empty/default values), exported from
`parrot.flows.dev_loop.models`. Added `_DISPATCH_LABELS_CTX`, `bind_labels()`,
`current_labels()` to `dispatchers/_shared.py`, mirroring `_SESSION_HOST_CTX`
exactly. Added `labels: Optional[DispatchLabels] = None` to the
`DevLoopCodeDispatcher` Protocol's `dispatch()` signature. 7 new unit tests
pass; full `dev_loop` suite still green (pre-existing 3 failures in
`test_recovery_lifecycle.py` confirmed unrelated via `git stash` diff).

**Deviations from spec**: none
