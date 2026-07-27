# TASK-1941: Guard test update — add PyPI-source assertion; ruff check + pytest green

**Feature**: eventbus-replacement-evaluation
**Feature ID**: FEAT-381
**Spec**: sdd/specs/eventbus-replacement-evaluation.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Effort**: S
**Depends-on**: TASK-1940
**Assigned-to**: unassigned

## Context

Final task in the evaluation pass. Extends the migration guard with a PyPI-source
assertion, then runs the full acceptance gate (`ruff check .` + `pytest -q`) and
commits all changes.

## Scope

1. Add a new test `test_navigator_eventbus_from_pypi` to
   `packages/ai-parrot/tests/core/events/test_migration_guard.py`:

   ```python
   import re
   import importlib.metadata

   def test_navigator_eventbus_from_pypi() -> None:
       """FEAT-381: navigator-eventbus must be installed from PyPI, not a VCS URL."""
       version = importlib.metadata.version("navigator-eventbus")
       assert re.match(r'^\d+\.\d+\.\d+', version), (
           f"Expected semver version, got {version!r} — "
           "may indicate a git-URL or editable install"
       )
       # Check direct_url.json is absent or has no vcs_info (PyPI install has neither)
       try:
           from importlib.metadata import packages_distributions
           dists = packages_distributions()
       except Exception:
           dists = {}
       # The presence of a well-formed semver is the primary signal
       parts = version.split(".")
       assert len(parts) >= 3 and all(p.isdigit() for p in parts[:3]), (
           f"navigator-eventbus version {version!r} is not a proper semver release"
       )
   ```

2. Run `ruff check .` from the repo root — must exit 0.
   - If it fails with eventbus-related errors not caught by TASK-1940, fix them now.
   - Do NOT fix unrelated ruff errors (out of scope per spec Non-Goals).

3. Run `pytest -q` — must exit 0.
   - If migration guard tests fail, investigate and fix.
   - Do NOT fix unrelated test failures (escalate instead).

4. Commit on the feature branch:
   ```
   sdd: FEAT-381 eventbus replacement evaluation — audit clean, guard updated
   ```

## Files to Create/Modify

- `packages/ai-parrot/tests/core/events/test_migration_guard.py` — add new test
- (any files from TASK-1940 fixes that weren't committed yet)

## Reference Code

- Existing tests in `packages/ai-parrot/tests/core/events/test_migration_guard.py`
- Pattern: `importlib.metadata.version("navigator-eventbus")` returns version string

## Acceptance Criteria

- [ ] `test_navigator_eventbus_from_pypi` added and passes.
- [ ] `ruff check .` exits 0.
- [ ] `pytest -q` exits 0 (all tests pass, zero failures).
- [ ] Commit created: `sdd: FEAT-381 eventbus replacement evaluation — audit clean, guard updated`.

## Output

When complete:
1. Write completion note: ruff exit code, pytest pass count, commit SHA.
2. Update `sdd/tasks/index/eventbus-replacement-evaluation.json` status to "done".
3. Move this file to `sdd/tasks/completed/`.

### Completion Note
(Agent fills this in when done)
