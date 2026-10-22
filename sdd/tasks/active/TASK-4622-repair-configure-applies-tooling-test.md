# TASK-4622: Repair the `test_configure_applies_tooling` bot fixture

**Feature**: FEAT-727 — Repair `test_configure_applies_tooling` (red since birth)
**Spec**: `sdd/specs/interfaces-test-configure-applies-tooling-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:487531e66e0b`

---

## Context

`packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py::test_configure_calls_apply_tooling_specs_once`
has never passed. `bd32389e9e` (TASK-3655, 2026-09-23) is the only commit that
has ever touched the file, and it committed it red:

```
TypeError: Can't instantiate abstract class AbstractBot without an
implementation for abstract methods 'ask', 'ask_stream', 'conversation', 'invoke'
```

`object.__new__` enforces `__abstractmethods__`, so line 13's
`AbstractBot.__new__(AbstractBot)` cannot work — and `AbstractBot` has carried
those four abstract methods since the monorepo migration (TASK-398), so no
past tree made it pass. Line 51 (`bot.events = MagicMock()`) is a second
defect waiting behind it: `events` is a **read-only property**
(`EventEmitterMixin`, no `fset`), and the per-instance registry is stored in
`_events_registry`.

Verified during FEAT-726 as pre-existing: the test fails identically against
the untouched `abstract.py`, so it is unrelated to FEAT-726's changes. The file
is listed in the Validation Contracts of FEAT-721 and FEAT-726, so it reds the
merge-tier gate of every feature that inherits that target list
(`issue:487531e66e0b`, severity minor).

## Scope

Repair the fixture inside the one test file so the assertions it was written
to make actually execute, using the pattern already proven in
`packages/ai-parrot/tests/bots/test_double_configure.py` (FEAT-721):

1. Add a module-private `_ConfigureTestBot(AbstractBot)` implementing `ask`,
   `ask_stream`, `conversation`, `invoke`.
2. Build the shell with `object.__new__(_ConfigureTestBot)` instead of
   `AbstractBot.__new__(AbstractBot)`.
3. Set `bot._events_registry = MagicMock()` instead of `bot.events = MagicMock()`.
4. Give `bot.tool_manager` a `MagicMock(_server_param_source=None)` (today it is
   `None`) and add `bot.sync_tools = MagicMock()`.
5. Keep both existing assertions byte-for-byte.

**NOT in scope**: any change under `packages/ai-parrot/src/` (the defect is
entirely in the test); extracting a shared `_stub_bot` helper across the two
test modules; adding new test cases or assertions; re-adding this file to
FEAT-726's `test_contract` (that index lives on PR #1781's branch); auditing
other tests from the same TASK-3655 deliverable.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py` | MODIFY | add concrete bot shell; fix the three attribute defects |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already present in the target file (line 7) — unchanged:
from parrot.bots.abstract import AbstractBot
# Already present (line 3) — unchanged, all three names stay in use:
from unittest.mock import AsyncMock, MagicMock, call
```

No new imports are needed.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:1575
async def configure(self, app=None) -> None

# AbstractBot.__abstractmethods__ == frozenset({'ask', 'ask_stream', 'conversation', 'invoke'})
# (verified: python -c "from parrot.bots.abstract import AbstractBot; print(sorted(AbstractBot.__abstractmethods__))")

# .venv/.../navigator_eventbus/lifecycle/mixin.py:98
@property
def events(self) -> EventRegistry       # fset is None -> assignment raises AttributeError
                                        # backing attribute: self._events_registry

# Pattern source — packages/ai-parrot/tests/bots/test_double_configure.py
# :12  class _ConfigureTestBot(AbstractBot):      (ask / ask_stream / conversation / invoke)
# :34      bot = object.__new__(_ConfigureTestBot)
# :47      bot.tool_manager = MagicMock(_server_param_source=None)
# :48      bot.sync_tools = MagicMock()
# :70      bot._events_registry = MagicMock()
```

Relevant `configure()` behavior (abstract.py, verified at 1575–1800):
- `app=None` ⇒ `resolved_app is None` ⇒ the
  `self.tool_manager._server_param_source` branch is **not** entered.
- `self._configure_count` becomes 1 ⇒ the idempotency early-return is **not** taken.
- `self.configure_conversation_memory()` then `await self.apply_tooling_specs()`
  are the first two pipeline steps — what the test asserts.
- `if self.tool_manager and hasattr(self._llm, "tool_manager"): self.sync_tools(self._llm)`
  — reachable once `tool_manager` is a MagicMock, hence stub `sync_tools`.
- `self.events.emit_nowait(AgentConfiguredEvent(...))` at `abstract.py:1775`.

### Does NOT Exist

- `packages/ai-parrot/tests/interfaces/conftest.py` — there is none; no shared
  fixture is available in that directory.
- Any shared `_stub_bot` / `_ConfigureTestBot` helper importable from a
  tests package: both names exist **only** in
  `packages/ai-parrot/tests/bots/test_double_configure.py` (verified:
  `grep -rln '_stub_bot\|_ConfigureTestBot' packages/ai-parrot/tests/`).
  Copy the pattern; do not import it.
- An `events` setter on `EventEmitterMixin` (`fset is None`) — do not try
  `bot.events = ...` in any form.
- `AbstractBot.__new__` override that bypasses the ABC check — there is none;
  `object.__new__` is the only path and it enforces `__abstractmethods__`.
- `AbstractBot.configure_skipped` / `configure_is_noop` — these are FEAT-726
  additions living on PR #1781's branch, NOT on `origin/dev`. Do not reference them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/tests/bots/test_double_configure.py#_ConfigureTestBot"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/tests/bots/test_double_configure.py:12-34 — copy this shape
class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None
    # ... ask_stream / conversation / invoke, same shape

bot = object.__new__(_ConfigureTestBot)   # __init__ deliberately skipped
```

### Key Constraints

- `configure()` swallows errors from `apply_tooling_specs()` and
  `configure_kb()` into `self.logger.error(...)`, so a wrong stub degrades the
  test silently instead of failing it. The proof of the fix is that the test
  **passes** and the `TypeError` is gone — run it and read the `1 passed`.
- Do not weaken the assertions to make them pass. `sequence.mock_calls[:2] ==
  [call.memory(), call.apply()]` is the ordering guarantee this test exists for.
- The shared `.venv` is editable-installed against the main checkout; inside
  the worktree always run `PYTHONPATH=packages/ai-parrot/src python -m pytest …`.
  Never `uv sync` inside a worktree.

### References in Codebase

- `packages/ai-parrot/tests/bots/test_double_configure.py` — the fixture pattern.
- `packages/ai-parrot/src/parrot/bots/abstract.py:1575` — `configure()`.
- `sdd/specs/interfaces-test-configure-applies-tooling-fixes.spec.md` §2 — design.

---

## Implementation Blueprint

### Steps (in order)

1. Insert the `_ConfigureTestBot` class after the existing imports — because
   `object.__new__` refuses an ABC, and a concrete subclass is the only way to
   get an instance whose `configure()` is the real one.
2. Swap line 13's construction to `object.__new__(_ConfigureTestBot)` — because
   the subclass clears `__abstractmethods__` while `__init__` stays skipped, so
   the test still exercises `configure()` in isolation.
3. Replace `bot.tool_manager = None` with `MagicMock(_server_param_source=None)`
   and add `bot.sync_tools = MagicMock()` — because `configure()` reaches
   `sync_tools` when `tool_manager` is truthy, and the mock keeps the test
   valid if that branch starts being taken.
4. Replace `bot.events = MagicMock()` with `bot._events_registry = MagicMock()`
   — because `events` is a read-only property backed by that attribute.
5. Run the validation command and confirm `1 passed`, then `ruff check` the file.

### `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'from parrot.bots.abstract import AbstractBot' packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py)
# AFTER — insert below `from parrot.bots.abstract import AbstractBot` (verified: packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py:7)


class _ConfigureTestBot(AbstractBot):
    """Concrete shell used to exercise AbstractBot lifecycle behavior."""

    async def ask(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def ask_stream(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def conversation(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None

    async def invoke(self, *args, **kwargs):
        """Satisfy the AbstractBot contract for a lifecycle-only test."""
        return None
```

**Why**: `AbstractBot` is an ABC with four abstract methods; `object.__new__`
checks `__abstractmethods__`, so only a concrete subclass can be instantiated
at all. Mirrors `test_double_configure.py:12-28` so the repo has one pattern,
not two.

```python
# occurrences: 1 (verified: grep -c 'bot = AbstractBot.__new__(AbstractBot)' packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py)
# REPLACE `    bot = AbstractBot.__new__(AbstractBot)` (verified: packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py:13)
    bot = object.__new__(_ConfigureTestBot)
```

```python
# occurrences: 1 (verified: grep -c 'bot.tool_manager = None' packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py)
# REPLACE `    bot.tool_manager = None` (verified: packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py:29)
    bot.tool_manager = MagicMock(_server_param_source=None)
    bot.sync_tools = MagicMock()
```

```python
# occurrences: 1 (verified: grep -c 'bot.events = MagicMock()' packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py)
# REPLACE `    bot.events = MagicMock()` (verified: packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py:51)
    bot._events_registry = MagicMock()
```

**Why this shape**: each replacement removes one way the fixture contradicts
the class under test (ABC instantiation, a `None` tool manager that skips the
`sync_tools` branch, assignment to a read-only property). The test body,
including both assertions, is untouched — the whole point is that it finally
runs. What must NOT change: the two assertions, and nothing under
`packages/ai-parrot/src/`.

### FILL IN checklist

- [ ] none — every block above is complete; no judgement gaps remain.

---

## Acceptance Criteria

- [ ] `test_configure_calls_apply_tooling_specs_once` passes (1 passed) with
      `PYTHONPATH=packages/ai-parrot/src`.
- [ ] The file contains no `AbstractBot.__new__(` and no `bot.events =`
      assignment.
- [ ] Both original assertions are present and unmodified:
      `bot.apply_tooling_specs.assert_awaited_once_with()` and
      `sequence.mock_calls[:2] == [call.memory(), call.apply()]`.
- [ ] `git diff --name-only origin/dev...HEAD` shows no file under
      `packages/ai-parrot/src/`.
- [ ] `ruff check packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py`
      is clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q`
- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`

---

## Test Specification

No new test files. The task's deliverable *is* a working test:

```python
# packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py
# test_configure_calls_apply_tooling_specs_once
#   - asserts apply_tooling_specs() is awaited exactly once, with no arguments
#   - asserts the first two recorded calls are memory() then apply(), in order
```

`test_double_configure.py` is run alongside it to prove the borrowed pattern
still matches its source and that nothing in the shared `AbstractBot` path
regressed.

---

## Agent Instructions

1. Work inside the FEAT-727 worktree, never the main checkout.
2. Apply the four blueprint edits exactly; do not restructure the test.
3. Run both Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. `ruff check --fix` the changed file.
5. Commit only
   `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py`
   as `feat(interfaces-test-configure-applies-tooling-fixes): TASK-4622 — repair the configure fixture`.
6. Close with `scripts/sdd/close_task.sh TASK-4622 interfaces-test-configure-applies-tooling-fixes verified`.

---

## Completion Note

> Filled in when the task is closed.

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
