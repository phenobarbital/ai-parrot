# TASK-1842: Release gate — navigator-eventbus 0.1.0 final (tag + PyPI)

**Feature**: FEAT-319 — EventBus Consolidation
**Spec**: `sdd/specs/eventbus-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1839, TASK-1840, TASK-1841
**Assigned-to**: unassigned

> **REPO**: `navigator-eventbus` — work in `/home/jesuslara/proyectos/navigator-eventbus`.
> **HUMAN-GATED**: tagging and PyPI publishing are user-initiated actions —
> prepare everything, then hand off to Jesus for the actual `git tag` + publish.
> PyPI publication is irreversible per-version.

---

## Context

Spec §3 Module 3. ai-parrot (TASK-1843) must pin a published PyPI release, not a
git hash. Current published version is `0.1.0rc2`; this release ships M1
(envelope schema_version, TASK-1839/1840) and M2 (tri-state routing, TASK-1841)
as `0.1.0` final.

**Heads-up (verified 2026-07-20)**: the local navigator-eventbus checkout already
has uncommitted edits to `src/navigator_eventbus/version.py`
(`__version__ = "0.1.0"`), `.github/workflows/release.yml`, and `uv.lock` —
release prep is partially in progress. Coordinate with Jesus before touching
those files; do NOT revert or overwrite them.

---

## Scope

- Confirm `version.py` reads `__version__ = "0.1.0"` (already edited locally —
  verify, don't duplicate).
- Changelog entry for 0.1.0 covering:
  - envelope `schema_version` (new field, legacy→1 tolerance,
    `UnsupportedSchemaVersion` on unknown versions, new package-root exports);
  - HookManager tri-state `route_to_bus` — **flag explicitly as a latent
    behavior change**: any consumer that calls `set_event_bus` and relied on the
    implicit `route_to_bus=False` default will start routing hooks traffic to
    the bus; explicit `False` restores the old behavior.
- Full test suite green at the release commit.
- Hand off to Jesus: tag `0.1.0` + publish to PyPI (via the release workflow).
- Verify post-publish: `pip index versions navigator-eventbus` (or
  `pip install navigator-eventbus==0.1.0` in a scratch venv) resolves.

**NOT in scope**: any code change (TASK-1839/1840/1841); ai-parrot pin swap
(TASK-1843 — hard-gated on this task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/version.py` | VERIFY | `__version__ = "0.1.0"` (already edited locally) |
| `CHANGELOG.md` (or repo's changelog location) | MODIFY/CREATE | 0.1.0 entry per scope |
| git tag `0.1.0` + PyPI | ACTION (human-gated) | tag + publish via release workflow |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-20 against `navigator-eventbus@main` local checkout.

### Existing Signatures to Use
```python
# src/navigator_eventbus/version.py:7
__version__ = "0.1.0"   # already edited (uncommitted) in the local checkout

# pyproject.toml:7 — dynamic = ["version"]  (version read from version.py; see
# comment at pyproject.toml:91–92). Do NOT hardcode a version in pyproject.toml.
```

### Does NOT Exist
- ~~`navigator-eventbus==0.1.0` on PyPI~~ — current published is `0.1.0rc2`; this task publishes final.
- ~~a static `version =` field in pyproject.toml~~ — version is dynamic from `version.py`.

---

## Implementation Notes

### Key Constraints
- Publishing is irreversible per-version: if a defect is found post-publish,
  the remedy is `0.1.1` (and TASK-1843 pins `>=0.1.1,<0.2`) — never re-upload.
- The changelog behavior-change note is REQUIRED by spec §5 acceptance criteria.
- Check `.github/workflows/release.yml` (locally modified) for how the publish
  is triggered (tag push vs manual dispatch) and document the trigger in the
  Completion Note.

---

## Acceptance Criteria

- [ ] Version resolves as `0.1.0` (dynamic from `version.py`); no rc suffix.
- [ ] Changelog documents envelope versioning AND the routing behavior change.
- [ ] Full test suite green at the release commit (`pytest tests/ -v`).
- [ ] Tag `0.1.0` pushed and PyPI publish completed (by Jesus).
- [ ] `pip install navigator-eventbus==0.1.0` resolves from PyPI in a clean venv.

---

## Test Specification

```bash
# No new unit tests. Release verification:
cd /home/jesuslara/proyectos/navigator-eventbus
pytest tests/ -v                      # must be green at the release commit
python -c "from navigator_eventbus.version import __version__; assert __version__ == '0.1.0'"
# post-publish, in a scratch venv:
pip install navigator-eventbus==0.1.0 && python -c "
from navigator_eventbus import ENVELOPE_SCHEMA_VERSION, UnsupportedSchemaVersion
print('0.1.0 OK')"
```

---

## Agent Instructions

1. **Check dependencies** — TASK-1839, TASK-1840, TASK-1841 all in `sdd/tasks/completed/`.
2. **cd to `/home/jesuslara/proyectos/navigator-eventbus`**; coordinate with the
   uncommitted release-prep edits (do not revert them).
3. **Prepare** changelog + verify version; run the full suite.
4. **STOP and hand off** to Jesus for tag + publish — do NOT push tags or publish yourself.
5. After publish confirmation: run the post-publish verification, update index → `"done"`,
   move this file to `sdd/tasks/completed/`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
