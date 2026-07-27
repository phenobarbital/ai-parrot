---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: EventBus Replacement Evaluation — Verify navigator-eventbus Integration and Remove Old Code

**Feature ID**: FEAT-381
**Date**: 2026-07-27
**Author**: Jesus (phenobarbital) + Claude
**Status**: approved
**Target version**: ai-parrot next minor
**Jira**: NAV-9267

> **Evaluation spec**: This feature performs a comprehensive correctness audit of the
> navigator-eventbus integration landed in FEAT-319 (eventbus-consolidation) and
> prior FEAT-316/317/318. Its goals are: confirm no old bus code survives, verify
> all import rewires are correct, ensure `ruff check .` and `pytest -q` pass
> cleanly against the current ai-parrot codebase.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-319 declared the navigator-eventbus consolidation complete. All tasks were
marked done and the migration guard tests pass. However, the codebase has grown
significantly since then (FEAT-374–380), and there is no post-facto verification
pass confirming:

1. **No old bus artifacts remain** — no residual imports of deleted modules
   (`parrot.core.events.bus`, `parrot.core.events.evb`, `parrot.core.hooks.base`,
   `parrot.core.hooks.models`), no stray `BusCore`/`EventEnvelope` definitions.
2. **Dependency pin is correct** — `pyproject.toml` correctly pins
   `navigator-eventbus>=0.2.1` (or better) from PyPI (not a git hash).
3. **All hook imports resolve from navigator_eventbus** — domain hooks
   (`parrot.core.hooks.*`) that import from `navigator_eventbus.hooks.*` do so
   correctly and without circular imports.
4. **Acceptance criteria green** — `ruff check .` (no eventbus-related lint
   errors introduced by the migration) and `pytest -q` (full suite green,
   including migration guard tests and hook tests).

### Goals

- G1: Audit all Python files under `packages/ai-parrot/src/` for residual
  references to deleted bus modules and confirm they are absent.
- G2: Verify `pyproject.toml` pins `navigator-eventbus` from PyPI at `>=0.2.1`
  with no git URL; confirm the `grpc` extra resolves.
- G3: Confirm all domain hook files under `parrot/core/hooks/` import
  `HookManager`, `BaseHook`, `HookEvent`, `HookType` from `navigator_eventbus`
  (or via the approved re-export shim in `parrot.core.hooks.__init__`).
- G4: Run `ruff check .` and `pytest -q`; if either fails with eventbus-related
  errors, fix them in this feature's single commit.
- G5: Update the migration guard test `test_no_internal_bus_copy` to also assert
  `navigator-eventbus` is installed from PyPI (not a VCS URL).

### Non-Goals (explicitly out of scope)

- New bus features or API changes — this is evaluation only.
- Changes to navigator-eventbus itself.
- Lifecycle extraction Phase 2 or broker-port work (separate specs).
- Broad ruff auto-fix of unrelated files (only fix eventbus-related violations
  if any are found; leave the rest for a dedicated lint-cleanup feature).

---

## 2. Architectural Design

### Overview

This is a read-heavy audit + targeted fix feature. Three small sequential tasks:

1. **Audit (T1)**: grep-based scan of all Python source under `packages/` for
   any reference to the deleted bus symbols and modules. Produce a concise
   findings report.
2. **Fix (T2)**: For each finding from T1, apply the minimal surgical fix
   (redirect import, delete dead code, update comment). Also fix any
   eventbus-related `ruff check` violations discovered during the audit.
3. **Guard test update + CI gate (T3)**: Add the PyPI-source assertion to
   `test_no_internal_bus_copy`; run `ruff check .` and `pytest -q`; confirm
   green; commit.

### Integration Points

| Component | Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/__init__.py` | verify | Must only reference `lifecycle`; no bus imports |
| `packages/ai-parrot/src/parrot/core/hooks/__init__.py` | verify | Re-exports must resolve via `navigator_eventbus` |
| `packages/ai-parrot/pyproject.toml` | verify/fix | `navigator-eventbus>=0.2.1` from PyPI |
| `packages/ai-parrot/tests/core/events/test_migration_guard.py` | extend | Add PyPI-source assertion |
| `packages/ai-parrot/src/parrot/core/hooks/*.py` (domain hooks) | verify | Import paths must be correct |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/core/events/bus/`~~ — deleted by FEAT-317; `test_no_internal_bus_copy` asserts this.
- ~~`parrot.core.events.evb`~~ — deleted by FEAT-317; migration guard asserts `ModuleNotFoundError`.
- ~~`parrot.core.hooks.base` / `parrot.core.hooks.models`~~ — same.
- ~~git URL for navigator-eventbus in pyproject.toml~~ — replaced by `>=0.2.1` in FEAT-319 M4.

---

## 3. Module Breakdown

### Task 1: Audit — grep for residual bus artifacts (ai-parrot, read-only)

- **Path**: `packages/ai-parrot/src/`, `packages/ai-parrot/tests/`
- **Responsibility**:
  - Grep for `parrot.core.events.bus`, `parrot.core.events.evb`,
    `parrot.core.hooks.base`, `parrot.core.hooks.models`, `BusCore`,
    `EventEnvelope` (local definition), `git+http` in pyproject.toml.
  - Verify `packages/ai-parrot/pyproject.toml` line for `navigator-eventbus`
    is a PyPI specifier, not a git URL.
  - Verify `parrot/core/hooks/__init__.py` re-exports resolve cleanly.
  - Produce a short findings list: each finding = file + line + symbol +
    recommended fix. If zero findings, confirm clean.
- **Depends on**: nothing.

### Task 2: Fix residual issues (ai-parrot, targeted edits)

- **Path**: any file flagged by Task 1
- **Responsibility**:
  - Apply each fix from the Task 1 findings list.
  - If `ruff check .` produces eventbus-related errors
    (F401 unused import of deleted symbol, E402 import order from rewire, etc.),
    fix those too.
  - Do NOT run `ruff --fix` globally — only touch the flagged files.
- **Depends on**: Task 1.
- **Skip condition**: if Task 1 finds zero issues, Task 2 is a no-op (note that
  in completion and skip to Task 3).

### Task 3: Guard test update + green gate

- **Path**: `packages/ai-parrot/tests/core/events/test_migration_guard.py`
- **Responsibility**:
  - Add an assertion to `test_no_internal_bus_copy` (or as a new test
    `test_navigator_eventbus_from_pypi`) that:
    ```python
    import importlib.metadata
    meta = importlib.metadata.metadata("navigator-eventbus")
    # direct_url is absent (PyPI install) or has no "vcs_info" key
    try:
        direct_url = importlib.metadata.packages_distributions()
        # or use importlib.metadata.PathDistribution
    except Exception:
        pass
    # simpler check: installed version matches semver, not a git hash
    version = importlib.metadata.version("navigator-eventbus")
    assert re.match(r'^\d+\.\d+\.\d+', version), f"Expected semver, got {version!r}"
    ```
  - Run `ruff check .` — must exit 0.
  - Run `pytest -q` — must exit 0.
  - Commit: `sdd: FEAT-381 eventbus replacement evaluation — audit clean, guard updated`.
- **Depends on**: Task 2.

---

## 4. Test Specification

### Tests to run (acceptance gate)

```bash
# Lint gate
ruff check .

# Full suite
pytest -q
```

### Specific tests expected to pass

| Test | File | Description |
|---|---|---|
| `test_deleted_modules_not_importable` | `test_migration_guard.py` | All 4 deleted modules → `ModuleNotFoundError` |
| `test_navigator_eventbus_smoke` | `test_migration_guard.py` | Package imports + round-trip |
| `test_typed_events_subclass` | `test_migration_guard.py` | Lifecycle events subclass pkg class |
| `test_no_internal_bus_copy` | `test_migration_guard.py` | Bus dir absent; no parrot.* BusCore |
| `test_facade_reexports` | `test_migration_guard.py` | Lifecycle + hooks facades resolve |
| `test_navigator_eventbus_from_pypi` (new) | `test_migration_guard.py` | Installed from PyPI (semver version) |
| All hook tests | `tests/core/hooks/` | Hook imports + behavior unchanged |

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Audit (T1) completes with zero residual old-bus symbols in `packages/ai-parrot/src/`.
- [ ] `packages/ai-parrot/pyproject.toml` contains `navigator-eventbus>=0.2.1` (or
  higher) with no git URL.
- [ ] `test_navigator_eventbus_from_pypi` added to `test_migration_guard.py` and passes.
- [ ] `ruff check .` exits 0 (from the repo root).
- [ ] `pytest -q` exits 0 (all tests pass, zero failures).
- [ ] Single commit on the feature branch: `sdd: FEAT-381 eventbus replacement evaluation`.

---

## 6. Worktree Strategy

- **Isolation**: per-spec worktree (`feat-381-eventbus-replacement-evaluation`).
- **Base**: `dev`.
- **Single commit** per the spec — no multi-task parallelism needed.
- Tasks T1→T2→T3 are sequential; T2 is conditional on T1 findings.

---

## 7. Open Questions

- None. This is a verification-and-fix spec; all architectural decisions were
  settled in FEAT-319 and prior.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | Jesus + Claude | Initial evaluation spec |
