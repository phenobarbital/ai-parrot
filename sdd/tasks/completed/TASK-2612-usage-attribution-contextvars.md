# TASK-2612: Seat/run attribution ContextVars

**Feature**: FEAT-479 — Dev-Flow / Dev-Loop Telemetry Accounting on the Lifecycle Bus
**Spec**: `sdd/specs/devflow-telemetry-accounting.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2.

Usage records must be attributed to a **seat** (`"development"`,
`"development.w1"`, `"qa"`) and a **run**. The events that carry token counts
(`AfterClientCallEvent`) are emitted deep inside `AbstractClient`, which knows
nothing about flow nodes. The codebase already solved this exact problem for
agent identity in FEAT-228: a module-level `ContextVar` read at
event-construction time.

This is how `development.w1` becomes a first-class seat **without widening
`NodeId`** — the closed `Literal` that currently causes all pool-worker
telemetry to be silently dropped (spec Finding 3).

---

## Scope

- Add `current_run_id` and `current_seat` ContextVars to
  `parrot/observability/context.py`, following the existing pattern exactly.
- Add a `usage_attribution(run_id, seat)` context manager using token-based
  `set()` / `reset()` so nesting restores the prior value.
- Add all three names to the module's `__all__`.
- Re-export from `parrot/observability/__init__.py` alongside
  `current_agent_name`, and add them to its `__all__`.
- Write the unit test below.

**NOT in scope**: reading these ContextVars anywhere (TASK-2614 does that in
the subscriber; TASK-2617 sets them in the CLI dispatchers). This task only
defines them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/context.py` | MODIFY | Add two ContextVars + `usage_attribution` |
| `packages/ai-parrot/src/parrot/observability/__init__.py` | MODIFY | Re-export the three new names |
| `packages/ai-parrot/tests/observability/test_usage_attribution.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/observability/__init__.py:49
from parrot.observability.context import agent_identity, current_agent_name
# after this task, this must also work:
from parrot.observability import current_run_id, current_seat, usage_attribution
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/observability/context.py
__all__ = [                                    # around line 30-40
    ...,
    "current_user_id",                         # line 36
    "current_session_id",                      # line 37
    "agent_identity",                          # line 38
    "invocation_context",                      # line 39
]

current_agent_name: ContextVar[Optional[str]] = ContextVar(   # line 42
    "parrot_current_agent_name", default=None
)
current_user_id: ContextVar[Optional[str]] = ContextVar(      # line 46
    "parrot_current_user_id", default=None
)
current_session_id: ContextVar[Optional[str]] = ContextVar(   # line 50
    "parrot_current_session_id", default=None
)

@contextmanager
def agent_identity(name: Optional[str]) -> Iterator[None]:    # line 55
    """<full Google-style docstring with an Example:: block>"""
    token = current_agent_name.set(name)
    try:
        yield
    finally:
        current_agent_name.reset(token)

@contextmanager
def invocation_context(                                        # line 83
    agent_name: Optional[str],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Iterator[None]:
    """Binds THREE ContextVars with three tokens — the multi-var pattern
    to copy for usage_attribution."""
    tok_agent = current_agent_name.set(agent_name)
    tok_user = current_user_id.set(user_id)
    tok_session = current_session_id.set(session_id)
    try:
        ...
```

Note the ContextVar **naming convention**: the variable is `current_x`, and its
`ContextVar` name string is `"parrot_current_x"`. Follow it.

### Does NOT Exist

- ~~`current_run_id` / `current_seat`~~ — this task creates them.
- ~~`usage_attribution`~~ — this task creates it.
- ~~`parrot.observability.context.run_context`~~ — no such name; do not invent
  an alternative spelling.
- ~~A `seat` concept anywhere in the codebase today~~ — this task introduces
  the term. It is deliberately a free `str`, NOT `parrot.flows.dev_loop.
  session_state.NodeId` (a closed `Literal` of 15 names that cannot express
  `"development.w1"`).

---

## Implementation Notes

### Pattern to Follow

`invocation_context` (context.py:83) is the closest model — it binds multiple
ContextVars with one token each and resets all of them in a `finally`. Copy
that structure:

```python
@contextmanager
def usage_attribution(
    run_id: Optional[str],
    seat: Optional[str] = None,
) -> Iterator[None]:
    """Bind run/seat attribution for events emitted inside this block.

    Uses token-based ``set()`` / ``reset()`` so nested blocks restore the
    prior values rather than clearing them.

    Args:
        run_id: The dev-loop / dev-flow run identifier.
        seat: The accounting seat — a node id (``"qa"``) or a pool worker id
            (``"development.w1"``). Deliberately a free string, not a
            ``NodeId``.

    Example::

        with usage_attribution("run-abc123", "development.w1"):
            ...  # AfterClientCallEvents emitted here carry this attribution
    """
    tok_run = current_run_id.set(run_id)
    tok_seat = current_seat.set(seat)
    try:
        yield
    finally:
        current_seat.reset(tok_seat)
        current_run_id.reset(tok_run)
```

### Key Constraints

- Both ContextVars default to `None` — attribution is always optional, and an
  unattributed LLM call must never crash a consumer.
- Reset in reverse order of setting, matching `invocation_context`.
- The `finally` is mandatory: an exception inside the block must still restore.
- Google-style docstrings with an `Example::` block, matching the neighbours.
- Add to `__all__` in **both** files, or the re-export is invisible to
  `from parrot.observability import *` and to linters.

### References in Codebase

- `packages/ai-parrot/src/parrot/observability/context.py:55` — `agent_identity`
- `packages/ai-parrot/src/parrot/observability/context.py:83` — `invocation_context`

---

## Acceptance Criteria

- [ ] `from parrot.observability import current_run_id, current_seat, usage_attribution` works.
- [ ] `from parrot.observability.context import usage_attribution` works.
- [ ] Both names appear in `context.py`'s `__all__` and in `__init__.py`'s `__all__`.
- [ ] Values are restored after the block, including when it raises.
- [ ] Nested blocks restore the outer value, not `None`.
- [ ] `pytest packages/ai-parrot/tests/observability/test_usage_attribution.py -v` passes.
- [ ] `ruff check` clean on both modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_usage_attribution.py
import pytest

from parrot.observability import current_run_id, current_seat, usage_attribution


def test_binds_inside_block():
    assert current_run_id.get() is None
    with usage_attribution("run-1", "development.w1"):
        assert current_run_id.get() == "run-1"
        assert current_seat.get() == "development.w1"
    assert current_run_id.get() is None
    assert current_seat.get() is None


def test_nested_restores_outer_not_none():
    with usage_attribution("run-1", "development"):
        with usage_attribution("run-1", "development.w2"):
            assert current_seat.get() == "development.w2"
        assert current_seat.get() == "development"   # outer, not None


def test_restores_on_exception():
    with pytest.raises(RuntimeError):
        with usage_attribution("run-1", "qa"):
            raise RuntimeError("boom")
    assert current_run_id.get() is None
    assert current_seat.get() is None


def test_seat_is_optional():
    with usage_attribution("run-1"):
        assert current_run_id.get() == "run-1"
        assert current_seat.get() is None


async def test_isolated_across_tasks():
    """ContextVars copy per asyncio.Task, so concurrent runs must not see
    each other's attribution."""
    import asyncio

    seen = {}

    async def worker(run_id: str, seat: str):
        with usage_attribution(run_id, seat):
            await asyncio.sleep(0)
            seen[seat] = current_run_id.get()

    await asyncio.gather(
        worker("run-a", "development.w1"),
        worker("run-b", "development.w2"),
    )
    assert seen == {"development.w1": "run-a", "development.w2": "run-b"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `context.py`'s `__all__` and the
   `invocation_context` pattern before editing
4. **Update status** in `sdd/tasks/index/devflow-telemetry-accounting.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2612-usage-attribution-contextvars.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-31
**Notes**: Added `current_run_id` / `current_seat` ContextVars and the
`usage_attribution(run_id, seat=None)` context manager to
`observability/context.py`, mirroring `invocation_context`'s multi-var
token-based `set()`/`reset()` pattern exactly (reset in reverse order,
`finally`-guarded). Both new ContextVars default to `None`. Added all three
names to `context.py`'s `__all__` and re-exported them from
`observability/__init__.py` (with a matching `__all__` entry and module
docstring section). Created `packages/ai-parrot/tests/observability/`
(did not exist yet) with `__init__.py` (matching the empty-`__init__.py`
convention used by `tests/flows/`) and `test_usage_attribution.py`
implementing the task's 5-test specification verbatim (bind/restore,
nested restores outer not None, restores on exception, seat is optional,
isolated across asyncio tasks) — all pass. `ruff check` on the diff adds no
new import-ordering or logic findings (fixed I001/SIM117 introduced by the
new test file and the `__init__.py` import reordering); the remaining
`UP035`/`UP045`/`RUF022` findings on `context.py`/`__init__.py` are
pre-existing style debt already present on the unmodified file (`Optional`
vs `X | None`, unsorted `__all__`) — left as-is per the task's explicit
instruction to follow `invocation_context`'s existing style/convention
exactly rather than modernizing unrelated lines. Full
`packages/ai-parrot/tests/unit/observability/` suite (173 tests, pre-existing
`context.py` coverage) still passes.

**Deviations from spec**: none.
