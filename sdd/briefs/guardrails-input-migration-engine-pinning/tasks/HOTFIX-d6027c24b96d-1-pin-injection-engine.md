# HOTFIX-d6027c24b96d-1: Pin the injection engine in the INPUT-migration test harness

**Feature**: BRIEF-d6027c24b96d — Pin the injection engine in the INPUT-migration test harness
**Spec**: `sdd/briefs/guardrails-input-migration-engine-pinning.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d6027c24b96d`

---

## Context

8 tests in `packages/ai-parrot/tests/unit/test_guardrails_input_migration.py`
fail with `AttributeError: 'NoneType' object has no attribute 'detect_injection'`
on any machine with a cached ONNX graph, and pass where there is none.

`_patched_bot` (`:34`) patches `_get_shared_injection_detector`
(`prompt_injection.py:123`), which only the *pytector* construction branch
consults (`:548`). The ctor instead resolves through
`_resolve_injection_engine()` (`:617`), which prefers ONNX, and the ONNX branch
sets `self._pytector_detector = None` (`:730`, documented at `:724`). The patch
is therefore inert and the tests dereference `None`.

Full root cause, research and the rejected alternatives are in the brief.

---

## Scope

Pin the engine the harness builds its bot against, and share one helper for
doing so.

1. Add a shared `mock_pytector_engine` helper that wraps a mock detector as a
   resolved pytector engine.
2. In `_patched_bot`, patch `_resolve_injection_engine` to return it, so the
   guardrail's `_pytector_detector` is the mock the test already holds.
3. Assert the wiring took effect before returning the bot.
4. Point `test_guardrails_prompt_injection.py`'s local `_mock_pytector_engine`
   at the shared helper so there is exactly one definition.

**NOT in scope**:
- The 8 tests' bodies. Their
  `pi_guardrail._pytector_detector.detect_injection.return_value = (True, 0.99)`
  lines (8 occurrences, verified) stay **unchanged** — they start working again
  because the alias is populated. Rewriting them to drive `_injection_engine`
  is a larger refactor the brief's Q&A rejected.
- Parametrizing the seam tests over ONNX / pytector / regex engines (rejected:
  turns a single-file fix into a suite redesign).
- Production code under `src/`. Engine resolution is correct; only the test
  harness is wrong.
- The autouse `_reset_injection_engine_singleton` fixture
  (`tests/conftest.py:51`) — it already does its job; this task adds the
  per-suite pinning it was never meant to supply.

---

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `packages/ai-parrot/tests/_injection_test_helpers.py` | CREATE | shared `mock_pytector_engine()` helper |
| `packages/ai-parrot/tests/unit/test_guardrails_input_migration.py` | MODIFY | patch the resolver in `_patched_bot` + assert the wiring |
| `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` | MODIFY | re-point the local `_mock_pytector_engine` at the shared helper |

> **Deviation from the brief's Decision 1, deliberate and verified.** The Q&A
> chose `tests/conftest.py` as the helper's home. A `conftest.py` cannot host
> this one: `_patched_bot` is a module-level function, not a fixture, so it
> cannot consume a conftest fixture, and **no test in this repo imports
> `conftest` by name** (verified: `grep -rn '^from conftest import\|^import
> conftest' packages/ai-parrot/tests/` → no matches). The established idiom for
> a shared *callable* is a `tests/_<topic>_test_helpers.py` module imported
> directly — `from _crew_test_helpers import DummyAgent`
> (`tests/test_crew_final_regression.py:13` and 3 siblings), which works because
> `conftest.py:83-87` puts `TESTS_DIR` on `sys.path` for exactly this purpose.
> The decision's *intent* — one definition, no drifting copy, living with the
> rest of the injection test machinery — is preserved.

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev@2612a601e` (2026-10-22). Every anchor below re-checked
> with `test -e` + `sed -n '<line>p'`.

### Verified Imports
```python
from unittest.mock import MagicMock, patch   # already imported: test_guardrails_input_migration.py:20
from parrot.bots.basic import BasicBot        # already imported: :22
from parrot.bots.guardrails.builtin import prompt_injection as pi_module  # test_guardrails_prompt_injection.py:40
from _crew_test_helpers import DummyAgent     # the shared-helper import idiom: tests/test_crew_final_regression.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py
def _get_shared_injection_detector()                                         # line 123 — consulted ONLY at :548 (pytector branch)
def _resolve_injection_engine(force_reresolve: bool = False) -> _InjectionScoringEngine | None   # line 617
class _PytectorInjectionEngine(...)        # wraps a detector; ctor used as (detector, model_id=...) at test_guardrails_prompt_injection.py:47
class PromptInjectionGuardrail(Guardrail):
    def __init__(self, strict_mode=True, block_on_threat=False,
                 injection_probability_threshold=0.98, **kwargs)             # line 685-740
        # self._injection_engine = _resolve_injection_engine()               # line 727
        # self._pytector_detector = engine._detector if isinstance(..., _PytectorInjectionEngine) else None   # line 730
        # self._injection_detector = PromptInjectionDetector(...) if engine is None else self._pytector_detector  # lines 735-738

# packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py
def _mock_pytector_engine(detector)        # line 45 — returns pi_module._PytectorInjectionEngine(detector, model_id="mock-pytector")
@pytest.fixture def guardrail()            # line 51 — canonical "patch the resolver" usage

# packages/ai-parrot/tests/unit/test_guardrails_input_migration.py
def _patched_bot(**kwargs)                 # line 34-44 — returns (bot, mock_detector)
@pytest.fixture def bot()                  # line 74-77 — _patched_bot(injection_detection=True, strict_mode=True, block_on_threat=True)

# packages/ai-parrot/tests/conftest.py
@pytest.fixture(autouse=True) def _reset_injection_engine_singleton()        # line 51 — resets _RESOLVED_INJECTION_ENGINE per test
TESTS_DIR = Path(__file__).resolve().parent; sys.path.insert(0, str(TESTS_DIR))   # lines 85-87 — why `from _injection_test_helpers import ...` resolves
```

### Does NOT Exist
- ~~`_patched_bot` patching `_resolve_injection_engine`~~ — it does not today;
  that absence IS the bug (`grep -n "_resolve_injection_engine"
  test_guardrails_input_migration.py` → no matches).
- ~~`PromptInjectionGuardrail(injection_engine=...)`~~ — not a ctor kwarg;
  `**kwargs` swallows it silently. The engine comes only from the module-level
  resolver, so patching that function is the only lever.
- ~~`pi_module._PytectorInjectionEngine(detector)`~~ positionally alone — the
  existing call passes `model_id=` too (`test_guardrails_prompt_injection.py:47`);
  copy that call shape rather than guessing the signature.
- ~~`from conftest import _mock_pytector_engine`~~ — no test in this repo
  imports `conftest` by name; use the `_*_test_helpers.py` idiom.
- ~~`_get_shared_injection_detector` being dead~~ — it still exists (`:123`) and
  is still used at `:548`. Do NOT delete it; it is simply not on the path the
  ctor takes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/_injection_test_helpers.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_guardrails_input_migration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_resolve_injection_engine",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#PromptInjectionGuardrail.__init__",
    "sym:packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py#_mock_pytector_engine"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The 8 failing tests' bodies are untouched. If a change requires editing them,
  the approach is wrong — re-read the brief's Decisions.
- Keep `block_on_threat=True`'s behaviour intact: the `bot()` fixture (`:74`)
  relies on it for `on_error == "fail_closed"`.
- `_patched_bot` must keep returning `(bot, mock_detector)` — the `bot()` fixture
  discards the second element, but other call sites may not.
- The patch must be active during `BasicBot(...)` construction only (the engine
  is read in `__init__`); the existing `with patch(...)` block already has the
  right lifetime.
- Conventions: `.claude/rules/codebase-conventions.md` — type hints, Google-style
  docstrings, 120-col, `ruff check` clean.

### References in Codebase
- `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py:45-62` —
  the exact "patch the resolver, return a wrapped mock" pattern to copy.
- `packages/ai-parrot/tests/_crew_test_helpers.py` — shape and placement of a
  shared test-helper module in this repo.
- `packages/ai-parrot/tests/conftest.py:51-73` — why each test re-resolves the
  engine (and so why per-suite pinning is required, not optional).

---

## Implementation Blueprint

### Steps (in order)
1. Create `tests/_injection_test_helpers.py` with `mock_pytector_engine(detector)`
   — *why*: both suites need the same wrapper, and a single definition cannot
   drift; `conftest.py:85-87` already makes `tests/` importable.
2. In `_patched_bot`, add a `_resolve_injection_engine` patch returning that
   wrapper around the mock detector — *why*: it is the only lever that decides
   the backend, so this is what makes `_pytector_detector` the mock again.
3. Assert the wiring took effect before returning — *why*: a future resolution
   change then fails with one clear message instead of 8 `NoneType` reds.
4. Re-point `test_guardrails_prompt_injection.py`'s `_mock_pytector_engine` at
   the shared helper — *why*: leaving both means the copy this task was meant to
   prevent.
5. Run both Validation Commands — *why*: the first proves the 8 reds are green,
   the second proves the re-point broke nothing in the suite that owned it.

### `packages/ai-parrot/tests/_injection_test_helpers.py` (CREATE)
```python
"""Shared helpers for tests that must pin the injection-scoring engine.

`PromptInjectionGuardrail.__init__` resolves its engine through the
module-level `_resolve_injection_engine()`
(`bots/guardrails/builtin/prompt_injection.py:617`), whose precedence chain
prefers ONNX when a graph is cached. A suite that mocks a *detector* without
pinning the *engine* gets `_pytector_detector = None`
(`prompt_injection.py:730`) on exactly those machines — `issue:d6027c24b96d`.

Importable as `from _injection_test_helpers import mock_pytector_engine`
because `tests/conftest.py:85-87` puts this directory on `sys.path`.
"""
from typing import Any

from parrot.bots.guardrails.builtin import prompt_injection as pi_module


def mock_pytector_engine(detector: Any) -> Any:
    """Wrap *detector* as a resolved pytector engine.

    Args:
        detector: Usually a `MagicMock` whose `detect_injection` returns a
            `(bool, float)` tuple.

    Returns:
        A `_PytectorInjectionEngine` the guardrail ctor will unwrap back into
        `self._pytector_detector`, so a test can keep driving the mock it
        already holds.
    """
    return pi_module._PytectorInjectionEngine(detector, model_id="mock-pytector")
```
**Why this shape**: a verbatim lift of `test_guardrails_prompt_injection.py:45-47`
(including the `model_id=` kwarg — do not drop it), moved so both suites share
one definition. Public name (no leading underscore) because it is now imported
across modules.

### `packages/ai-parrot/tests/unit/test_guardrails_input_migration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _patched_bot(\*\*kwargs):' packages/ai-parrot/tests/unit/test_guardrails_input_migration.py)
# REPLACE the whole function body at `def _patched_bot(**kwargs):` (verified: :34-44)
def _patched_bot(**kwargs):
    """Construct a BasicBot with a pinned, mocked injection engine.

    Patches `_resolve_injection_engine` — not just the detector factory —
    because the ctor reads the engine from there and prefers ONNX, which
    leaves `_pytector_detector` as None on any box with a cached graph
    (`issue:d6027c24b96d`).
    """
    mock_detector = MagicMock()
    mock_detector.detect_injection.return_value = (False, 0.0)
    with patch(
        "parrot.bots.guardrails.builtin.prompt_injection._resolve_injection_engine",
        return_value=mock_pytector_engine(mock_detector),
    ):
        # FILL IN: keep or drop the existing `_get_shared_injection_detector`
        # patch — bounded by: it is inert for engine selection (it is read only
        # at prompt_injection.py:548), so keep it ONLY if a test still needs the
        # shared-detector factory stubbed; otherwise drop it as misleading.
        bot = BasicBot(name="TestBot", **kwargs)

    # Guard (brief Decision 2): fail loudly if the patch ever goes inert again.
    pi_guardrail = next(
        (
            g for g in bot._guardrail_pipelines[GuardrailStage.INPUT]._guardrails
            if g.name == "prompt_injection"
        ),
        None,
    )
    # FILL IN: assert the wiring took effect — bounded by AC-3: when
    # `injection_detection` is enabled the guardrail must be present AND
    # `pi_guardrail._pytector_detector is mock_detector`; when it is disabled
    # (`_patched_bot()` with no injection kwargs) there is no such guardrail,
    # so the assertion must not fire. Message must name issue:d6027c24b96d.
    return bot, mock_detector
```
**Why**: the mock detector is created *before* the patch so it can be wrapped
into the engine; `GuardrailStage` is already imported (`:28`). The guard is
conditional because `_patched_bot` is also called without injection kwargs —
check the real call sites before writing the assertion.

### `packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _mock_pytector_engine(detector):' packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py)
# REPLACE the local helper at `def _mock_pytector_engine(detector):` (verified: :45-47)
from _injection_test_helpers import mock_pytector_engine  # shared test infrastructure

# Backwards-compatible alias: 14+ TestEngineResolution/TestWarmup tests and the
# `guardrail` fixture call `_mock_pytector_engine(...)` by that name.
_mock_pytector_engine = mock_pytector_engine
```
**Why**: an alias keeps every existing call site in this file working with a
2-line change instead of renaming ~15 uses. Put the import with the other
top-of-file imports (`:33-43`), matching
`tests/test_crew_final_regression.py:13`'s commented-import style.

### FILL IN checklist
- [ ] `test_guardrails_input_migration.py::_patched_bot` — keep or drop the now-inert `_get_shared_injection_detector` patch; bounded by its only read site (`prompt_injection.py:548`)
- [ ] `test_guardrails_input_migration.py::_patched_bot` — the guard assertion, including the no-injection-kwargs call path; bounded by AC-3

---

## Acceptance Criteria

- [ ] **AC-1** All 8 previously-failing tests pass:
      `pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`
      is fully green **on this machine** (which has a cached ONNX graph — the
      environment that exposed the bug).
- [ ] **AC-2** Green regardless of backend: the suite also passes with the ONNX
      path unavailable, e.g.
      `PARROT_INJECTION_ONNX_DIR=/nonexistent pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`.
- [ ] **AC-3** The guard works: temporarily making the patch inert (e.g. pointing
      it back at `_get_shared_injection_detector`) fails with a message naming
      `issue:d6027c24b96d`, **not** `AttributeError: 'NoneType'`.
- [ ] **AC-4** The 8 `pi_guardrail._pytector_detector.detect_injection` lines are
      byte-identical to before (`git diff` shows no change on those 8 lines).
- [ ] **AC-5** One definition only: `grep -rn "_PytectorInjectionEngine(" packages/ai-parrot/tests/`
      matches only `_injection_test_helpers.py`.
- [ ] **AC-6** `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`
      still passes (49 tests at brief time) — the re-point broke nothing.
- [ ] **AC-7** `ruff check` clean on all 3 changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_input_migration.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py -q`

---

## Test Specification

This task's deliverable *is* test infrastructure; its proof is the 8 existing
tests going green without their bodies changing, plus AC-2's
backend-independence run and AC-3's guard check. No new test cases are required.

Run with `PYTHONPATH=packages/ai-parrot/src` from inside the worktree, and copy
`packages/ai-parrot/src/parrot/utils/types.cpython-312-*.so` plus
`parrot/utils/parsers/toml.cpython-312-*.so` in from the main checkout first —
they are build artifacts that exist only there, and `import parrot.utils` fails
without them.

---

## Agent Instructions

When you pick up this task:

1. **Work in this brief's worktree** —
   `.claude/worktrees/fix-d6027c24b96d-guardrails-input-migration-engine-pinning`
   (branch `fix-d6027c24b96d-guardrails-input-migration-engine-pinning`), never on `dev`.
2. **Read the brief** at `sdd/briefs/guardrails-input-migration-engine-pinning.brief.md`.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run each blueprint `grep -c` and use the
   fresh line numbers. A count of `0` means the anchor moved: report the drift,
   do not invent an attachment point.
5. **Confirm the failure first**: run Validation Command 1 and see the 8 reds
   before changing anything. If they are already green, your environment lacks a
   cached ONNX graph — say so and stop, because you cannot prove AC-1 here.
6. **Implement** from the blueprint; complete both `# FILL IN:` markers.
7. **Verify** every acceptance criterion, AC-2 and AC-3 included.
8. **Commit the code** — stage only the 3 files this task lists (never `git add .` / `-A`).
9. **Close out** with `/sdd-done d6027c24b96d`, which opens the PR against `dev`
   and closes `issue:d6027c24b96d` by the two-key rule.

A brief closes in place: there is no `active/` → `completed/` move, and no
`close_task.sh` run.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Code session (interactive, `/sdd-brief` → manual implementation)
**Date**: 2026-10-22
**Notes**: Implemented in commit `c7ad8795e`.

- **New** `packages/ai-parrot/tests/_injection_test_helpers.py` —
  `mock_pytector_engine(detector)`, the single definition of the wrapper.
- **`_patched_bot`** now patches `_resolve_injection_engine` (returning the
  wrapped mock) instead of `_get_shared_injection_detector`, and asserts
  `_pytector_detector is mock_detector` before returning.
- **`test_guardrails_prompt_injection.py`** keeps `_mock_pytector_engine` as a
  one-line alias of the shared helper, so its ~15 call sites are unchanged.

**Both `FILL IN` markers resolved by evidence, not preference:**

1. *Keep or drop the `_get_shared_injection_detector` patch?* **Dropped.**
   `grep -rn` over `packages/ai-parrot/src/` (excluding `build/`) shows exactly
   one runtime call site, `prompt_injection.py:548`, inside the pytector branch
   of the resolution chain — which patching the resolver bypasses entirely. The
   patch was therefore dead, and leaving a dead patch in place is precisely the
   trap this issue was about.
2. *Guard on the no-injection-kwargs path?* **Made conditional.**
   `_patched_bot` has exactly one call site today (`:76`,
   `injection_detection=True`), but the helper takes `**kwargs`, so the guard
   asserts only when the INPUT pipeline actually carries a `prompt_injection`
   guardrail (`.get(...)` + `getattr(..., "_guardrails", ())`).

**Acceptance criteria — all 7 verified:**

| AC | Evidence |
|---|---|
| AC-1 | `test_guardrails_input_migration.py` 15/15 green on this box (which has the cached ONNX graph that exposed the bug); was 8 failed / 7 passed before |
| AC-2 | Also 15/15 with `PARROT_INJECTION_ONNX_DIR=/nonexistent-onnx-dir HF_HOME=<empty> HF_HUB_OFFLINE=1` |
| AC-3 | Repointing the patch back at `_get_shared_injection_detector` fails with `AssertionError: injection-engine patch went inert: … (see issue:d6027c24b96d)`, not `AttributeError: 'NoneType'`; file restored afterwards |
| AC-4 | `git diff -U0 | grep` for the 8 `detect_injection.return_value = (True, 0.99)` lines → no `+`/`-` hits; all 8 byte-identical |
| AC-5 | `grep -rn "_PytectorInjectionEngine(" packages/ai-parrot/tests/` → only `_injection_test_helpers.py:31` |
| AC-6 | `test_guardrails_prompt_injection.py` 42/42 still green (57 combined) |
| AC-7 | `ruff check` clean on all 3 files |

**Side benefit worth noting**: the suite went from **72s to 5.6s**, because it
no longer resolves and loads a real ONNX graph on every test.

**Deviations from brief**: one, already recorded in this task's "Files to
Create / Modify" note — the brief's Q&A chose `tests/conftest.py` as the shared
helper's home, and the helper went to `tests/_injection_test_helpers.py`
instead. `_patched_bot` is a module-level function and cannot consume a
conftest fixture, and no test in this repo imports `conftest` by name;
`_<topic>_test_helpers.py` + `conftest.py:85-87`'s `sys.path` entry is the
established idiom (`from _crew_test_helpers import DummyAgent`). Intent of the
decision — one definition, no drifting copy — is preserved.

**Note for the reviewer**: this brief and FEAT-714's PR #1759 both modify
`packages/ai-parrot/tests/unit/test_guardrails_prompt_injection.py` (that PR
adds a `GuardrailPipeline` import and a `TestMultiThreatAggregation` class near
the same import block). Expect a small, mechanical conflict in whichever merges
second.
