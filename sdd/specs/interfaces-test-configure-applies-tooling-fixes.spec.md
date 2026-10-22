---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [tests, configure, lifecycle, tech-debt, merge-gate]
---

# Feature Specification: Repair `test_configure_applies_tooling` (red since birth)

**Feature ID**: FEAT-727
**Date**: 2026-10-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.2.5

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

This spec drains one ledger fix group (`fixgroup:7f075cb7b7c4`, one issue:
`issue:487531e66e0b`).

`packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py::test_configure_calls_apply_tooling_specs_once`
has failed on every run since the commit that introduced it
(`bd32389e9e`, TASK-3655, 2026-09-23 — the only commit ever to touch the
file). It was committed by an engine-committed coder deliverable and
apparently never executed.

Two defects, both in the test's own setup — not in `AbstractBot`:

1. **Line 13 can never work.** `bot = AbstractBot.__new__(AbstractBot)`
   raises

   ```
   TypeError: Can't instantiate abstract class AbstractBot without an
   implementation for abstract methods 'ask', 'ask_stream', 'conversation',
   'invoke'
   ```

   `object.__new__` enforces `__abstractmethods__`, so routing through
   `__new__` does not dodge the ABC check. Those four abstract methods
   predate the test (TASK-398, the monorepo migration), so there is no
   version of the tree in which the line succeeded.

2. **Line 51 would fail next.** `bot.events = MagicMock()` assigns to
   `events`, which is a **read-only property** supplied by
   `EventEmitterMixin` (now
   `navigator_eventbus/lifecycle/mixin.py`); the registry is per-instance
   state stored in `_events_registry`. `configure()` reaches
   `self.events.emit_nowait(AgentConfiguredEvent(...))` near its end
   (`abstract.py:1775`), so the attribute matters for the test to complete.

The cost is not the one red test: the file is listed in the **Validation
Contract** of both `sdd/specs/double-configure-agents.spec.md` (FEAT-721)
and `sdd/specs/bots-agent-tech-debt.spec.md` (FEAT-726), so it reds the
merge-tier gate of every feature that inherits that target list, and
masks real regressions behind a known-red line.

Verified pre-existing during FEAT-726: the test fails identically against
the untouched base `packages/ai-parrot/src/parrot/bots/abstract.py`, so it
is unrelated to FEAT-726's changes. FEAT-726 responded by dropping the
file from its own `test_contract` and opening this issue; this feature
repairs the test itself.

### Goals

- `test_configure_calls_apply_tooling_specs_once` passes against
  `origin/dev`'s `AbstractBot`, keeping the behavior it was written to
  assert: `apply_tooling_specs()` is awaited exactly once, immediately
  after `configure_conversation_memory()`.
- The repaired fixture follows the one pattern already proven in this
  repository — `tests/bots/test_double_configure.py::_stub_bot` (FEAT-721)
  — instead of inventing a second way to build a configure-only bot shell.
- No production code changes: the defect is entirely in the test.

### Non-Goals (explicitly out of scope)

- Changing `AbstractBot.configure()` or anything else under
  `packages/ai-parrot/src/`.
- Extracting a shared `_stub_bot` helper for both test modules. The two
  modules assert different things (ordering vs. idempotency) and the
  duplication is 25 lines of attribute stubs; a shared fixture is a
  separate refactor with its own blast radius.
- Re-adding the file to FEAT-726's `test_contract` / spec Validation
  Contract. That index lives on FEAT-726's feature branch (PR #1781) and
  is not this feature's to edit.
- Auditing other tests committed by the same TASK-3655 deliverable.

---

## 2. Architectural Design

### Overview

The repair is a fixture rewrite inside one test file. The pattern is the
one `tests/bots/test_double_configure.py` already uses:

```python
class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs): return None
    async def ask_stream(self, *args, **kwargs): return None
    async def conversation(self, *args, **kwargs): return None
    async def invoke(self, *args, **kwargs): return None

bot = object.__new__(_ConfigureTestBot)   # no __init__, attributes stubbed by hand
```

`object.__new__` on a *concrete* subclass is legal; the four overrides
clear `__abstractmethods__`. `__init__` is deliberately skipped so the
test exercises `configure()` in isolation, with every collaborator it
touches replaced by a mock.

`configure()` is called with no `app`, so `resolved_app is None`: the
`tool_manager.set_server_param_source()` branch is skipped and
`_configure_count` is 1, so the idempotency early-return is not taken.
The remaining stubs keep every optional branch off (`_use_local_kb`,
`_use_vector`, `use_kb`, `warmup_on_configure`, `_prompt_builder`,
`_credentials`, `store`), leaving exactly the path the assertions cover.

### Component Diagram

```
test_configure_calls_apply_tooling_specs_once
  └── object.__new__(_ConfigureTestBot)        # concrete AbstractBot shell
        ├── sequence = MagicMock()             # call-order recorder
        │     ├── .memory  → bot.configure_conversation_memory
        │     └── .apply   → bot.apply_tooling_specs (AsyncMock)
        ├── bot._events_registry = MagicMock() # self.events property backing store
        ├── bot.tool_manager    = MagicMock(_server_param_source=None)
        └── bot.sync_tools      = MagicMock()
              ⇓
        await bot.configure()                  # app=None → no server-param wiring
              ⇓
        assert apply awaited once, after memory
```

### Integration Points

| Touched | How |
|---|---|
| `parrot.bots.abstract.AbstractBot` | imported and subclassed by the test only; unchanged |
| `navigator_eventbus.lifecycle.mixin.EventEmitterMixin` | its `events` property reads `_events_registry`, which the fixture now sets |
| `tests/bots/test_double_configure.py` | pattern source; not modified |

### Data Models

None.

### New Public Interfaces

None. `_ConfigureTestBot` is a module-private test helper.

---

## 3. Module Breakdown

### Module 1: Repair the `test_configure_applies_tooling` fixture

**File**: `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py`

- Add a module-private `_ConfigureTestBot(AbstractBot)` implementing the
  four abstract methods (`ask`, `ask_stream`, `conversation`, `invoke`)
  with Google-style docstrings, mirroring
  `tests/bots/test_double_configure.py:12-28`.
- Replace `AbstractBot.__new__(AbstractBot)` with
  `object.__new__(_ConfigureTestBot)`.
- Replace `bot.events = MagicMock()` with
  `bot._events_registry = MagicMock()`.
- Give `bot.tool_manager` a `MagicMock(_server_param_source=None)` and add
  `bot.sync_tools = MagicMock()`, so the test still passes if a later
  change makes `configure()` reach the `sync_tools` / server-param
  branches it skips today.
- Keep both existing assertions verbatim — the awaited-once check and the
  `sequence.mock_calls[:2] == [call.memory(), call.apply()]` ordering
  check. The point of the fix is that these assertions finally *run*.

**NOT in scope**: new test cases, new assertions, touching any other file.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_configure_calls_apply_tooling_specs_once` | M1 | existing test, now actually executing: `apply_tooling_specs` awaited once with no args, immediately after `configure_conversation_memory` |

### Integration Tests

None — this is a unit-level fixture repair.

### Validation Contract

tests:
- packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py
markers: none

### Test Data / Fixtures

```python
# Reuse, do not re-invent:
#   packages/ai-parrot/tests/bots/test_double_configure.py — _ConfigureTestBot
#   shell + _stub_bot attribute list (FEAT-721)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `PYTHONPATH=packages/ai-parrot/src python -m pytest
      packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py`
      passes (1 passed) in the feature worktree.
- [ ] The file contains no `AbstractBot.__new__(AbstractBot)` and no
      assignment to `bot.events`.
- [ ] The two original assertions are unchanged in meaning: a single
      awaited `apply_tooling_specs()` and the `memory` → `apply` order.
- [ ] `git diff --name-only origin/dev...HEAD` lists exactly
      `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py`
      plus SDD state files — no `packages/ai-parrot/src/` change.
- [ ] `ruff check` is clean on the changed file.

---

## 6. Affected Files

| File | Change |
|---|---|
| `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py` | rewrite the bot fixture (concrete shell, `_events_registry`, mock `tool_manager`/`sync_tools`) |

---

## 7. Implementation Notes

- The shared `.venv` is editable-installed against the **main checkout**, so
  a bare `pytest` inside the worktree imports the wrong branch. Always
  prefix with `PYTHONPATH=packages/ai-parrot/src`. Never `uv sync` inside
  a worktree.
- `self.events` is a property; only `_events_registry` is assignable. A
  `MagicMock()` there satisfies `self.events.emit_nowait(...)` because the
  property returns the stored registry when one is present.
- `configure()` is wrapped in `try/except/finally` and swallows errors from
  `apply_tooling_specs` and `configure_kb` by logging them, so a broken
  stub would silently weaken the test rather than fail it. Confirm the
  test fails when the fixture is wrong by checking the pre-fix `TypeError`
  is gone and the assertions genuinely execute.
- FEAT-726 (PR #1781) touches `abstract.py:configure()` on its own branch.
  This test asserts the memory → tooling order, which FEAT-726 preserves,
  so the two do not conflict; this feature bases on `origin/dev` and does
  not wait on that PR.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

- [ ] None.

---

## 9. Design Research Cross-Check

> Status: skipped (ledger-driven fix lane — `/sdd-fix` routes a verified
> fix group straight to a spec; the single issue is itself a verified
> finding from FEAT-726's implementation).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Jesus Lara | Initial draft from `fixgroup:7f075cb7b7c4` (issue `487531e66e0b`) |
