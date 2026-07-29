# TASK-1843: ai-parrot — PyPI pin swap, bus-copy guard test, changelog note

**Feature**: FEAT-319 — EventBus Consolidation
**Spec**: `sdd/specs/eventbus-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1842
**Assigned-to**: unassigned

> **REPO**: `ai-parrot` (this checkout). Per spec Worktree Strategy: NO worktree —
> single-commit change on a short-lived branch from `dev` (or directly per
> Jesus's preference). HARD GATE: `navigator-eventbus==0.1.0` must be live on
> PyPI (TASK-1842) before starting.

---

## Context

Spec §3 Module 4. FEAT-317 migrated ai-parrot to `navigator_eventbus` but left
the dependency pinned to a git commit hash with a TODO. This task closes that
TODO: pin the published release, add the regression guard test the spec requires
(`test_no_internal_bus_copy`), and add the changelog entry Jesus approved for
the auto-routing behavior change.

---

## Scope

- `packages/ai-parrot/pyproject.toml` line 103–104: replace
  `"navigator-eventbus @ git+https://github.com/phenobarbital/navigator-eventbus.git@17b99c2…"`
  with `"navigator-eventbus>=0.1.0,<0.2"`; delete the TODO comment at line 103.
- Verify the `grpc` extra (`"navigator-eventbus[grpc]"`, ~line 419) resolves
  against the PyPI release (the extra exists in the published wheel).
- Add `test_no_internal_bus_copy` to
  `packages/ai-parrot/tests/core/events/test_migration_guard.py`: asserts
  (a) `packages/ai-parrot/src/parrot/core/events/bus/` does not exist on disk,
  and (b) no importable `parrot.*` module defines a class named `BusCore` or
  `EventEnvelope`.
- ai-parrot changelog entry: navigator-eventbus 0.1.0 introduces tri-state
  `route_to_bus` (auto-routes when a bus is attached) — latent for ai-parrot
  (zero call sites) but a behavior change for any deployment calling
  `set_event_bus`.
- Reinstall + full ai-parrot test suite green against the PyPI package
  (`source .venv/bin/activate && uv pip install …` — never bare pip).

**NOT in scope**: anything in the navigator-eventbus repo (TASK-1839..1842);
touching `forward_to_global`/`forward_to_bus` call sites (no change needed —
audit confirmed zero `route_to_bus` consumers).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | dep swap (line 103–104); verify grpc extra (~419) |
| `packages/ai-parrot/tests/core/events/test_migration_guard.py` | MODIFY | add `test_no_internal_bus_copy` |
| changelog (repo convention — locate `CHANGELOG*`/release notes; ask if absent) | MODIFY | auto-routing behavior note |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-20 against `ai-parrot@dev`.

### Verified Imports
```python
from navigator_eventbus import EventBus, EventEnvelope, Severity   # smoke-tested by existing guard
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml:103–104
#   "# TODO: switch to navigator-eventbus>=0.1.0 after PyPI publish (FEAT-317 close)"
#   "navigator-eventbus @ git+https://github.com/phenobarbital/navigator-eventbus.git@17b99c22faf44bcf92fdf299a6e9a021d678a970",
# packages/ai-parrot/pyproject.toml:~418–420
#   grpc = ["navigator-eventbus[grpc]"]

# packages/ai-parrot/tests/core/events/test_migration_guard.py — 4 existing tests:
#   test_deleted_modules_not_importable   (parametrized: parrot.core.events.bus,
#       parrot.core.events.evb, parrot.core.hooks.base, parrot.core.hooks.models)
#   test_navigator_eventbus_smoke
#   test_typed_events_subclass
#   test_facade_reexports
# → follow this file's style for the new test.
```

### Does NOT Exist
- ~~`parrot/core/events/bus/`, `parrot/core/events/evb.py`~~ — deleted (FEAT-317);
  the new test asserts this STAYS true (stale `__pycache__` may exist — assert on
  source dirs/importability, not on pycache absence).
- ~~`test_no_internal_bus_copy`~~ — this task creates it.
- ~~`set_event_bus`/`route_to_bus` call sites in ai-parrot~~ — zero; do not add opt-outs.

---

## Implementation Notes

### Pattern to Follow
```python
# test_no_internal_bus_copy — sketch (adapt to the guard file's existing style):
from pathlib import Path
import parrot

def test_no_internal_bus_copy():
    src_root = Path(parrot.__file__).parent
    assert not (src_root / "core" / "events" / "bus").exists()
    import navigator_eventbus
    from navigator_eventbus.envelope import EventEnvelope
    assert not EventEnvelope.__module__.startswith("parrot.")
```

### Key Constraints
- Environment rules: `source .venv/bin/activate` first; `uv pip install` only.
- The dep swap changes install resolution — reinstall before running the suite,
  and confirm the installed package is from PyPI, not the cached git build:
  `pip show navigator-eventbus` → version `0.1.0`, no git URL.
- One logical commit (dep + test + changelog) per spec §7.

---

## Acceptance Criteria

- [ ] `grep -n "navigator-eventbus" packages/ai-parrot/pyproject.toml` shows `>=0.1.0,<0.2` and NO git URL; TODO comment gone.
- [ ] `grpc` extra resolves against the PyPI wheel.
- [ ] `test_no_internal_bus_copy` passes and is in CI scope (same file as existing guard).
- [ ] Changelog entry documents the auto-routing behavior change.
- [ ] Full ai-parrot suite green with `navigator-eventbus==0.1.x` from PyPI.
- [ ] `ruff check` clean on touched files.

---

## Test Specification

```python
# extend packages/ai-parrot/tests/core/events/test_migration_guard.py
def test_no_internal_bus_copy():
    """FEAT-319 M4: internal bus copy must never come back."""
    # (a) directory absent — see Pattern to Follow
    # (b) parrot.* defines no BusCore/EventEnvelope class
```

```bash
source .venv/bin/activate
uv pip install "navigator-eventbus>=0.1.0,<0.2"
pytest packages/ai-parrot/tests/core/events/test_migration_guard.py -v
pytest packages/ai-parrot/tests/ -x -q   # full suite
```

---

## Agent Instructions

1. **Check dependencies** — TASK-1842 completed AND `navigator-eventbus==0.1.0` live on PyPI (verify with `pip index versions navigator-eventbus`).
2. **Verify the Codebase Contract** — re-check pyproject line numbers (file may have shifted).
3. **Update status** in `sdd/tasks/index/eventbus-consolidation.json` → `"in-progress"`.
4. **Implement** (dep swap → reinstall → guard test → changelog → full suite).
5. **Move this file** to `sdd/tasks/completed/`, set index status `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
