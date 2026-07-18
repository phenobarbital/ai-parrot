# TASK-1836: Update navigator `pyproject.toml` — add `[brokers]` extra, drop `aiormq`

**Feature**: FEAT-318 — Navigator Brokers Removal (`navigator-eventbus` phase 5)
**Spec**: `sdd/specs/navigator-brokers-removal.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1835
**Assigned-to**: unassigned

> **CROSS-REPO**: changes land in `/home/jesuslara/proyectos/navigator` (branch
> `dev`), NOT ai-parrot.

---

## Context

Spec §3 Module 2. Once the examples no longer import `navigator.brokers.*`
(TASK-1835), navigator's dependency metadata is rewired: it gains an optional
extra `[brokers]` resolving to `navigator-eventbus[brokers]` (so example/consumer
usage opts in explicitly), and it drops the now-orphaned `aiormq` direct
dependency. `aiormq` was verified (2026-07-18) to be used **only** by
`navigator/brokers/` — removing it after TASK-1835 leaves the still-present but
soon-to-be-deleted `navigator/brokers/rabbitmq` as dead code with no live
importer, which is safe until TASK-1837 deletes it.

---

## Scope

- Add an optional extra `[brokers]` to navigator's `pyproject.toml` that pins
  `navigator-eventbus[brokers]` (version pin — see Open Question below).
- Remove the `aiormq>=6.8.1` direct dependency (navigator `pyproject.toml`
  line ~72, verified 2026-07-18).
- Remove the dead `aiormq.*` tooling override if present (navigator
  `pyproject.toml` line ~293 — likely a mypy overrides block entry).
- Do NOT touch `aioboto3` or `redis` — both are used outside `brokers/` and must
  remain (see Does NOT Exist / counter-anchors).

**NOT in scope**:
- Editing example files (TASK-1835).
- Deleting `navigator/brokers/` (TASK-1837).
- Version-pin final decision if FEAT-316 hasn't published yet — record it and use
  the editable/rc value available at implementation time.

---

## Files to Create / Modify

> Paths relative to the **navigator** repo root.

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | add extra `[brokers] = navigator-eventbus[brokers]`; remove `aiormq` dep (~line 72); remove `aiormq.*` override (~line 293) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against the `navigator` repo (branch `dev`) on 2026-07-18.

### Verified facts
```
navigator/pyproject.toml:72     "aiormq>=6.8.1",          # direct dependency (to REMOVE)
navigator/pyproject.toml:293    "aiormq.*",               # tooling override (to REMOVE)
# aiormq is imported ONLY under navigator/brokers/ (grep confirmed: 0 hits elsewhere)
# navigator has NO existing navigator-eventbus dependency (grep confirmed absent)
```

### Does NOT Exist / MUST NOT touch (counter-anchors)
- ~~`aiormq` usage outside `navigator/brokers/`~~ — none; safe to drop.
- **`aioboto3` — KEEP**: used at `navigator/utils/file/s3.py` (verified). Do NOT
  remove.
- **`redis` — KEEP**: used at `navigator/ext/redis/` and
  `navigator/background/tracker/redis.py` (verified). Do NOT remove.
- ~~an existing `[brokers]` extra in navigator pyproject~~ — does not exist; create it.

---

## Implementation Notes

### Verify-first
```bash
cd /home/jesuslara/proyectos/navigator
grep -nE "aiormq" pyproject.toml
grep -rlnE "aiormq" navigator/ | grep -v "navigator/brokers/"   # must be EMPTY
grep -rlnE "aioboto3" navigator/ | grep -v "navigator/brokers/" # must show utils/file/s3.py (KEEP)
```

### Key Constraints
- Follow the navigator repo's existing extras/formatting conventions.
- Match the `[brokers]` extra pin to whatever `navigator-eventbus` version
  FEAT-316 makes available (editable `0.1.0rc` vs a released version).
- Removing the mypy override for `aiormq` avoids a dead override entry.

### References
- Spec §7 External Dependencies table and Known Risks (`aiormq` override gotcha).

---

## Acceptance Criteria

- [ ] `pyproject.toml` no longer lists `aiormq` as a direct dependency.
- [ ] The `aiormq.*` tooling override is removed (no dangling override).
- [ ] `pyproject.toml` exposes an optional extra `[brokers]` resolving to
      `navigator-eventbus[brokers]`.
- [ ] `uv pip install -e .[brokers]` (in the navigator repo) succeeds and
      `python -c "import navigator_eventbus.brokers"` works afterward.
- [ ] `aioboto3` and `redis` remain present in `pyproject.toml`.
- [ ] No changes to the ai-parrot repository.

---

## Test Specification

```bash
cd /home/jesuslara/proyectos/navigator
grep -qE "aiormq" pyproject.toml && echo "FAIL: aiormq still present" || echo "PASS: aiormq removed"
grep -qE "aioboto3" pyproject.toml && echo "PASS: aioboto3 kept" || echo "FAIL: aioboto3 dropped"
uv pip install -e '.[brokers]' && python -c "import navigator_eventbus.brokers; print('extra OK')"
```

---

## Agent Instructions

Standard SDD flow. Verify the contract against the live `pyproject.toml` first
(line numbers may drift). Code commit lands in navigator; SDD state commit
(index + this file move) lands in ai-parrot on `dev`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
