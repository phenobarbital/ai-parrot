# TASK-3907: Bound the merge-tier sweep with `pytest-timeout` so a hung test fails loudly

**Feature**: FEAT-617 — Unpoison `packages/ai-parrot/tests` collection (merge-gate unblock)
**Spec**: `sdd/specs/manager-test-bot-cleanup-lifecycle-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`issue:c3c59277ef77` has two halves. The collection errors are TASK-3903/3904/3905.
This task covers the second half: a run that **stalls** rather than fails.

The reported stall was ~40% through `packages/ai-parrot-integrations/tests` with zero
log growth for 3+ minutes, and once cost the sdd-coder gate a SIGTERM at its 600s
budget. When a test hangs, the gate learns nothing: it cannot say *which* test hung,
only that the whole sweep timed out.

**Important — this ships as a precaution, not a repair** (spec §8 Q1, resolved
2026-10-01):
- A full bounded run of `packages/ai-parrot-integrations/tests/` on `dev` @ `883fe4480`
  **completed in 260.8s** (30 failed, 2257 passed, 67 skipped) — no stall.
- The specific hang was separately filed as `issue:1dbb2aac09ba` (major, open) naming
  `test_oauth2_integration.py::TestHandleWebAppDataRoutes::test_handle_web_app_data_routes_to_strategy`.
  Under that issue's **exact** documented repro
  (`-m 'not e2e and not real_llm and not integration'`) the test now **passes in 1.93s**.
- So there is no live hang to fix here. What is missing is the *guard*: `pytest-timeout`
  is **not installed**, so nothing bounds a future hang.

**Do not attempt to fix a hanging test in this task** — none reproduces, and the named
one belongs to `issue:1dbb2aac09ba`, which is not in this feature's scope.

`discovered_from: issue:c3c59277ef77`

## Scope

Add `pytest-timeout` as a dev dependency and give `scripts/sdd/select_tests.py` an
opt-in `--timeout` flag that injects a per-test timeout into each planned pytest
invocation when the sweep runs.

**Scoped to the sweep invocation only** (spec §8 Q2, decided by the user 2026-10-01):
the timeout must **not** go into `[tool.pytest.ini_options]`. A global default would
flake legitimately slow suites — the voice/browser tests run for minutes by design.

**NOT in scope**:
- Fixing any individual hanging test (`issue:1dbb2aac09ba` owns the one known candidate).
- A global/default timeout in shared pytest config — explicitly rejected.
- Changing tier selection, scoring, escalation or cap logic (spec §1 Non-Goals).
- The collection-error tasks (TASK-3903/3904/3905) or the guard (TASK-3906).

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `pyproject.toml` | MODIFY | add `pytest-timeout` to the `dev` dependency group |
| `scripts/sdd/select_tests.py` | MODIFY | add `--timeout`; inject into each invocation's argv |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import argparse      # verified: scripts/sdd/select_tests.py:10
import shlex         # verified: scripts/sdd/select_tests.py:11
import subprocess    # verified: scripts/sdd/select_tests.py:12
from pathlib import Path   # verified: scripts/sdd/select_tests.py:14
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py
def _build_parser() -> argparse.ArgumentParser:                    # line 29
    parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))  # line 31
    parser.add_argument("--base", default="origin/dev")            # line 32
    parser.add_argument("--task-file", action="append", default=[], type=Path)  # line 33
    parser.add_argument("--worktree", type=Path, default=Path.cwd())            # line 34
    parser.add_argument("--run", action="store_true")              # line 35
    parser.add_argument("--json", action="store_true")             # line 36
    return parser                                                  # line 37

def main(argv: list[str] | None = None) -> int:                    # line 40
    ...
    for invocation in plan.invocations:                            # line 88
        result = subprocess.run(list(invocation.argv), cwd=worktree)   # line 89  <- NO timeout today
```
`invocation.argv` is a sequence of pytest CLI tokens; `shlex.join(invocation.argv)` is
how the plan is printed (line 77).

```toml
# pyproject.toml
[dependency-groups]        # line 60
dev = [                    # line 61
    "pytest>=7.2.2",       # line 62
    "pytest-asyncio==1.4.0",   # line 63
    "pytest-xdist==3.3.1",     # line 64
    "pytest-assume==2.4.3",    # line 65
    "pytest-mock==3.15.1",     # line 66
    ...
    "pytest-aiohttp>=1.1.0",   # line 73
]
[tool.pytest.ini_options]  # line 234  <- MUST NOT gain a timeout (Q2)
```

### Does NOT Exist
- ~~`pytest_timeout`~~ — not installed; `python -c "import pytest_timeout"` raises `ModuleNotFoundError` (verified)
- ~~a `--timeout` option on `select_tests.py`~~ — this task adds it
- ~~a `timeout=` argument on the `subprocess.run` at line 89~~ — absent today
- ~~`timeout` in `[tool.pytest.ini_options]`~~ — absent, and must stay absent (Q2)
- ~~`invocation.timeout`~~ — not a field on the invocation model

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    { "path": "pyproject.toml", "action": "MODIFY" },
    { "path": "scripts/sdd/select_tests.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#_build_parser",
    "sym:scripts/sdd/select_tests.py#main"
  ]
}
```

## Implementation Notes

### Pattern to Follow
Match the existing `_build_parser()` argument style exactly (plain `add_argument`, no
subparsers). Keep `--timeout` **opt-in with a default of `None`** so existing callers
behave identically.

### Key Constraints
- **Per-test**, not wall-clock. `pytest-timeout`'s `--timeout=N` fails the *individual*
  hung test and prints its stack, which is the entire point — a `subprocess.run(timeout=)`
  wall-clock kill reproduces today's uninformative SIGTERM.
- `--timeout` must affect **only** `--run` invocations. Printed plans may include the
  flag so the printed command matches what runs, but no shared config changes.
- `uv add` for the dependency (never `pip`), declared in `pyproject.toml`.
- This task edits a dependency manifest → it is **exclusive** (no concurrent tasks).

### References in Codebase
- `scripts/sdd/select_tests.py:88-89` — the unbounded run loop
- `sdd/specs/merge-tier-validation-cost.spec.md` (FEAT-604) — prior work on this sweep's cost
- `issue:1dbb2aac09ba` — the known (now non-reproducing) hang candidate

## Implementation Blueprint

### Steps (in order)
1. Add `pytest-timeout` to the `dev` dependency group via `uv add --group dev pytest-timeout`
   — because the plugin must exist before `--timeout=N` is a valid pytest flag.
2. Add the `--timeout` option to `_build_parser()`, defaulting to `None` so every
   existing caller is unaffected.
3. Inject `--timeout=<N>` into each invocation's argv when the flag is set, so the
   printed plan and the executed command stay identical.
4. Verify a deliberately-hung test is reported **by name** rather than stalling.

### `pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'pytest-aiohttp>=1.1.0' pyproject.toml)
# AFTER — insert below `    "pytest-aiohttp>=1.1.0",` (verified: pyproject.toml:73)
    "pytest-timeout>=2.3",
```
**Why**: FEAT-617 M3 — bounds a hung test in the merge-tier sweep so the gate names the
offender instead of dying on its own budget. Added to the `dev` group (not a runtime
dependency) because it is only ever used by test invocations. Prefer
`uv add --group dev 'pytest-timeout>=2.3'` so `uv.lock` is updated consistently; edit the
TOML by hand only if that command is unavailable.

### `scripts/sdd/select_tests.py` (MODIFY — parser)
```python
# occurrences: 1 (verified: grep -c 'parser.add_argument("--json", action="store_true")' scripts/sdd/select_tests.py)
# AFTER — insert below `    parser.add_argument("--json", action="store_true")` (verified: scripts/sdd/select_tests.py:36)
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-test timeout (pytest-timeout) applied to every planned invocation. "
            "FEAT-617: bounds a hung test so the sweep names it instead of stalling. "
            "Opt-in — omitted by default, and deliberately NOT a shared pytest config "
            "default, so slow suites do not flake for developers."
        ),
    )
```
**Why**: default `None` keeps every existing caller byte-identical. `type=int` rejects a
malformed value at parse time rather than passing garbage to pytest.

### `scripts/sdd/select_tests.py` (MODIFY — argv injection)
```python
# occurrences: 1 (verified: grep -c 'for invocation in plan.invocations:' scripts/sdd/select_tests.py)
# NOTE: this anchor appears TWICE in the file (the print loop at :76 and the run loop
# at :88). Disambiguate with surrounding context — the RUN loop is the one immediately
# followed by `result = subprocess.run(...)`:
#
#     for invocation in plan.invocations:
#         result = subprocess.run(list(invocation.argv), cwd=worktree)
#
# MODIFY that run loop (verified: scripts/sdd/select_tests.py:88-89):
    for invocation in plan.invocations:
        argv = list(invocation.argv)
        # FILL IN: when args.timeout is not None, append f"--timeout={args.timeout}" to
        # argv — do NOT mutate invocation.argv itself, other code reads it. Bounded by
        # AC-2 (default behaviour unchanged) and AC-3 (flag reaches the subprocess).
        result = subprocess.run(argv, cwd=worktree)
```
**Why**: building a local `argv` list keeps the plan object immutable, so the printed
plan (line 77) and any JSON output stay consistent. Appending rather than prepending is
safe: pytest accepts options after positional targets.

### FILL IN checklist
- [ ] argv injection conditional on `args.timeout is not None`
- [ ] Decide whether the printed plan also shows `--timeout` (keep print and run identical if so)
- [ ] Confirm `[tool.pytest.ini_options]` (pyproject.toml:234) gained **no** timeout key

## Acceptance Criteria

- [ ] **AC-1** `python -c "import pytest_timeout"` succeeds after `uv sync`
- [ ] **AC-2** `select_tests.py` **without** `--timeout` produces byte-identical argv to before this change
- [ ] **AC-3** `select_tests.py --timeout 60 --run` passes `--timeout=60` to each pytest subprocess
- [ ] **AC-4** A deliberately-hung test under `--timeout=5` **fails and is named**, rather than stalling (demonstrate; record output in the Completion Note)
- [ ] **AC-5** `[tool.pytest.ini_options]` contains **no** timeout key — the default is not global (spec Q2)
- [ ] **AC-6** `pytest-timeout` is in the `dev` dependency group, not runtime deps
- [ ] **AC-7** `ruff check` clean on `scripts/sdd/select_tests.py`
- [ ] **AC-8** Existing `select_tests` tests still pass

## Validation Commands
- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q -k timeout`

## Test Specification

| Test | Asserts |
|---|---|
| existing `test_select_tests.py` suite | unchanged behaviour without `--timeout` (AC-2) |
| new: `--timeout` absent | argv contains no `--timeout` token |
| new: `--timeout 60` | every planned invocation's argv ends with `--timeout=60` |
| manual (AC-4) | a `time.sleep(30)` test under `--timeout=5` fails by name within ~5s |

Add the two new cases to `tests/sdd_scripts/test_select_tests.py` alongside the
existing coverage; do not create a parallel test module.

## Agent Instructions

1. **Do not fix a hanging test.** None reproduces on current `dev`; the one known
   candidate belongs to `issue:1dbb2aac09ba`, outside this feature.
2. Use `uv add --group dev` — never `pip`, never `requirements.txt`.
3. Do **not** add a timeout to `[tool.pytest.ini_options]`; the user explicitly chose
   sweep-only scope. A global default would flake the voice/browser suites.
4. AC-4 needs a real demonstration — write a throwaway hanging test, run it under
   `--timeout=5`, paste the output into the Completion Note, then delete it.
5. This task is **exclusive**: it edits `pyproject.toml` (a dependency manifest) and
   touching `uv.lock` concurrently with another task would corrupt the shared venv.
6. Never run `uv sync` inside a worktree — it repoints the shared venv's `.pth`
   (`.claude/rules/worktree-management.md`). Declare the dependency; let the main-checkout
   operator install it if the sandbox blocks installation.

## Completion Note

**Completed by**: Claude Opus 5 (/sdd-fix issue:c3c59277ef77)
**Date**: 2026-10-01
**Verification**: verified — 10 passed; AC-4 demonstrated live.

`pytest-timeout>=2.3` declared in the `dev` group via `uv add --no-sync` (pyproject +
uv.lock committed, shared venv untouched by the worktree), and
`scripts/sdd/select_tests.py` gained an opt-in `--timeout SECONDS` that appends
`--timeout=N` to each planned invocation's argv under `--run`. A local argv list is
built so `invocation.argv` stays unmodified for the printed plan. Two new tests in
`tests/sdd_scripts/test_select_tests.py`; **10 passed** (2 under `-k timeout`).

A first version of the test helper monkeypatched `subprocess.run` wholesale and broke
`test_scope`'s internal `git diff`; it now intercepts only pytest argvs and delegates
everything else to the real `subprocess.run`.

**AC-4 demonstrated** (the user installed pytest-timeout 2.4.0 into the shared venv;
`worktree-management.md` reserves that for the main-checkout operator). A throwaway
module with `time.sleep(600)` plus one passing test:

```
# without --timeout, capped externally at 20s:
#   killed by SIGKILL, exit 137 — stalled, no information about which test
#
# with --timeout=5:
F.                                                                       [100%]
    def test_this_one_hangs():
>       time.sleep(600)
E       Failed: Timeout (>5.0s) from pytest-timeout.
=========================== short test summary info ============================
FAILED test_feat617_hang_demo.py::test_this_one_hangs - Failed: Timeout (>5.0...
1 failed, 1 passed in 5.17s
```

The offender is **named**, the suite **continues**, and the sibling test still passes —
exactly the behaviour change the merge gate needed. The throwaway module was deleted
after the run (it never entered the repo; it lived in the session scratchpad).

**AC-5 confirmed**: `pyproject.toml` has no timeout key outside the dependency
declaration — the default is sweep-only per the user's Q2 decision, so slow
voice/browser suites cannot start flaking for developers.

**Context**: this ships as a precaution, not a repair. The hang in
`issue:c3c59277ef77` does not reproduce (full integrations run completes in 260.8s),
and the separately-filed `issue:1dbb2aac09ba` names a test that now passes in 1.93s
under its own documented repro — that issue looks already fixed and is a candidate for
closure by its owner.

**AC status**: AC-1 ✅ (pytest_timeout 2.4.0 imports; `--timeout` registered),
AC-2 ✅, AC-3 ✅, AC-4 ✅ (above), AC-5 ✅, AC-6 ✅, AC-7 ✅ ruff clean, AC-8 ✅.
