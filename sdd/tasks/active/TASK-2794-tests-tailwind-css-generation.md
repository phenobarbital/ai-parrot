# TASK-2794: Tests — generate_a2ui_css.py --check modes + vendor freshness check

**Feature**: FEAT-522 — Interactive-HTML Map Rendering + Tailwind CSS Coverage
**Spec**: `sdd/specs/interactive-html-map-tailwind.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2789, TASK-2790, TASK-2791
**Assigned-to**: unassigned

---

## Context

Spec §4 Unit Tests table lists 3 tests for Module 4:
`test_generate_a2ui_css_check_mode_clean`, `test_generate_a2ui_css_check_mode_stale`,
`test_generate_a2ui_css_vendor_check`. This task is the authoritative,
complete pytest implementation of these — TASK-2789's own Test Specification
section sketched illustrative placeholders; this task replaces those
placeholders with real, working tests.

## Scope

- Implement `test_generate_a2ui_css_check_mode_clean`: on a checkout where
  `interactive_html.py` and `design_system/tailwind.generated.css` are in sync
  (the normal, just-generated state), `scripts/generate_a2ui_css.py --check`
  exits 0.
- Implement `test_generate_a2ui_css_check_mode_stale`: using a TEMP COPY of the
  scanned source (do not mutate the real `interactive_html.py` on disk during
  the test — copy the relevant scan target to a temp location, or
  monkeypatch/parametrize the script's scan-target path if it's designed to
  accept one; if the script as built by TASK-2789 hardcodes the scan path with
  no override, that's a design gap to flag in the Completion Note rather than
  a reason to mutate the real source file mid-test-suite), simulate adding a
  new literal class string and assert `--check` exits 1.
- Implement `test_generate_a2ui_css_vendor_check`: simulate (via a temp
  directory / monkeypatched `VENDORED_ASSET_PATHS` from `_map_vendor.py`, or
  whatever mechanism TASK-2791 actually built for this sub-check) a missing
  vendored asset file and assert the freshness check (`--check`, or the
  distinct mechanism TASK-2791 added — read its Completion Note to know
  which) fails.
- Place these tests wherever TASK-2789's own scope note left this open (co-
  located with `scripts/` or under `packages/ai-parrot-visualizations/tests/`)
  — resolve this by checking what TASK-2789 actually did (its Completion Note)
  rather than guessing.

**NOT in scope**:
- Any change to `scripts/generate_a2ui_css.py`, `design_system/__init__.py`,
  or `.github/workflows/ci.yml` — this task only adds tests. Flag genuine gaps
  in the Completion Note.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/tests/test_generate_a2ui_css.py` (or the location TASK-2789 actually used — verify first) | CREATE or MODIFY | 3 tests for `generate_a2ui_css.py --check` behavior |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import subprocess
import sys
# Exact importable interface depends on how TASK-2789 built the script —
# read scripts/generate_a2ui_css.py in full FIRST (it exists by the time this
# task starts) before assuming a specific function-level API; if the script
# exposes its scan/check logic as importable functions (recommended, mirrors
# generate_tool_registry.py's own testable-function structure — verify that
# file's own test, if one exists, for the precedent), prefer importing and
# calling those directly over subprocess for faster/more precise tests;
# reserve subprocess-based invocation for a true end-to-end smoke test.
```

### Existing Signatures to Use
```python
# scripts/generate_tool_registry.py's OWN test file (if one exists in this
# repo — check `find . -iname "*test*generate_tool_registry*"` first) is the
# precedent for how a --check-mode script like this is typically tested here;
# mirror its structure if found.
```

### Does NOT Exist
- ~~A pre-existing test file for `generate_a2ui_css.py`~~ — this task creates
  the first one (TASK-2789's own Test Specification section only sketched
  placeholders, explicitly deferred to this task).

---

## Implementation Notes

### Pattern to Follow
```python
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # adjust to actual location


def test_generate_a2ui_css_check_mode_clean():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_a2ui_css.py"), "--check"],
        capture_output=True, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr.decode()
```

Prefer testing the script's internal functions directly (import + call) over
`subprocess.run` wherever TASK-2789 exposed them cleanly — faster, and gives
precise assertions on WHAT drifted, not just the exit code.

### Key Constraints
- Never mutate the real, committed `interactive_html.py` or
  `tailwind.generated.css` files as a side effect of running the test suite —
  use temp copies/monkeypatching for the "stale" scenarios.
- Tests must be able to run in CI (no interactive prompts, no reliance on a
  developer's local Tailwind CLI installation path — if the Tailwind CLI
  itself isn't available in the test environment, either skip the
  Tailwind-invocation-dependent assertions with a clear `pytest.mark.skipif`
  reason, or structure the tests to only exercise the AST-scan-and-diff logic
  (which doesn't need the CLI) — read TASK-2789's actual implementation to see
  which parts need the CLI present vs. not, and design around that boundary
  rather than assuming.

### References in Codebase
- `scripts/generate_tool_registry.py` and whatever test file (if any) already
  exists for it — the precedent to check first.
- `scripts/generate_a2ui_css.py` — TASK-2789's output, read in full before
  writing these tests.

---

## Acceptance Criteria

- [ ] All 3 tests from spec §4's Unit Tests table (Module 4 rows) exist and pass.
- [ ] Tests do not mutate the real, committed source files as a side effect.
- [ ] Tests run successfully in a CI-like environment (no interactive
  dependencies) — verify by running them via `pytest` directly, not just
  manually.
- [ ] No linting errors on the new test file.

---

## Test Specification

See Implementation Notes above — that IS this task's test scaffold.

---

## Agent Instructions

1. Read the spec at `sdd/specs/interactive-html-map-tailwind.spec.md` §4 Unit
   Tests table (Module 4 rows), §5 Acceptance Criteria.
2. **Check dependencies** — verify TASK-2789, TASK-2790, and TASK-2791 are all
   in `sdd/tasks/completed/` before starting; read TASK-2789 and TASK-2791's
   Completion Notes for the actual implementation shape (function names, test
   location) before writing these tests.
3. Update status in the per-spec index → `"in-progress"`.
4. Implement per scope.
5. Verify all acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update the per-spec index → `"done"`.
8. Fill in the Completion Note below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
