# TASK-1838: Verify public surface, close PR #393, document the breaking change & release coordination

**Feature**: FEAT-318 — Navigator Brokers Removal (`navigator-eventbus` phase 5)
**Spec**: `sdd/specs/navigator-brokers-removal.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1837
**Assigned-to**: unassigned

> **CROSS-REPO + external coordination**: changes land in
> `/home/jesuslara/proyectos/navigator` (branch `dev`) and on GitHub (PR #393).
> External consumers (Flowtask, FieldSync) live in their own repos and are only
> *coordinated*, not modified here.

---

## Context

Spec §3 Module 4. This closes out the removal: confirm no public surface still
references brokers, annotate/close PR
[navigator#393](https://github.com/phenobarbital/navigator/pull/393) (its fixes
already landed in `navigator-eventbus` via FEAT-316), and record the
breaking-change + coordinated-release requirement so downstream consumers migrate
in the same window.

---

## Scope

- Verify (should be a no-op) that `navigator/__init__.py` and any other public
  surface no longer reference `navigator.brokers` — already true at spec time.
- Add a migration / breaking-change note to the navigator repo's changelog (or
  equivalent) stating: `navigator.brokers.*` is removed; consumers must move to
  `navigator_eventbus.brokers.*`; no shim is provided.
- Record the coordinated-release requirement for the known external consumers:
  **Flowtask** and **FieldSync** (FieldSync must also drop its local PR #393
  shim) must migrate their imports before navigator ships this release.
- Annotate and close PR navigator#393, referencing the port (FEAT-316) + this
  removal so the fix is not perceived as dangling/unmerged.

**NOT in scope**:
- Migrating Flowtask/FieldSync code (their own repos / specs).
- Cutting the actual navigator release (owner decision — see Open Questions).
- Any code deletion (done in TASK-1837).

---

## Files to Create / Modify

> Paths relative to the **navigator** repo root; plus a GitHub action on PR #393.

| File / Target | Action | Description |
|---|---|---|
| `navigator/__init__.py` | VERIFY | confirm no `brokers` reference (expected no-op) |
| `CHANGELOG.md` (or repo's changelog convention) | MODIFY | breaking-change + migration note |
| PR navigator#393 (GitHub) | ANNOTATE/CLOSE | reference FEAT-316 port + FEAT-318 removal |

---

## Codebase Contract (Anti-Hallucination)

> Verified against the `navigator` repo (branch `dev`) on 2026-07-18.

### Verified facts
```
# navigator/__init__.py has NO 'broker' reference (grep confirmed) → verification is a no-op
# External consumers of navigator.brokers.* live OUTSIDE this repo:
#   - Flowtask   (separate repo)
#   - FieldSync  (separate repo; carries a local shim for PR #393 bug #1)
# PR #393 author: hacu9 — three fixes already ported into navigator-eventbus (FEAT-316)
```

### Does NOT Exist
- ~~a Flowtask/FieldSync directory inside the navigator repo~~ — they are external
  repos; do NOT attempt to edit them from here.
- ~~a broker re-export to verify-and-remove in `navigator/__init__.py`~~ — none;
  the check is expected to pass unchanged.

---

## Implementation Notes

### Verify-first
```bash
cd /home/jesuslara/proyectos/navigator
grep -niE "broker" navigator/__init__.py    # expected: no matches
ls CHANGELOG.md 2>/dev/null || echo "check repo's changelog convention"
```

### Key Constraints
- Do not touch external consumer repos from here — only document the coordination
  requirement.
- The changelog note must be explicit that there is **no shim** and name the
  replacement import path `navigator_eventbus.brokers.*`.
- PR #393 action requires GitHub access (`gh`); if unavailable, leave a clear
  note for the owner with the exact comment/close text to post.

### References
- Spec §7 Known Risks (external breakage by design; PR #393 provenance).
- Spec §8 Open Questions (release-coordination window owner).

---

## Acceptance Criteria

- [ ] `navigator/__init__.py` confirmed free of `brokers` references.
- [ ] A breaking-change/migration note exists in the navigator changelog naming
      the replacement (`navigator_eventbus.brokers.*`) and the no-shim decision.
- [ ] The note records the coordinated-release requirement for Flowtask and
      FieldSync (incl. FieldSync dropping its local #393 shim).
- [ ] PR navigator#393 is annotated/closed referencing FEAT-316 + FEAT-318 (or,
      if `gh` is unavailable, the exact text is handed to the owner).
- [ ] No changes to the ai-parrot repository.

---

## Test Specification

```bash
cd /home/jesuslara/proyectos/navigator
test -z "$(grep -niE 'broker' navigator/__init__.py)" && echo "PASS: no broker in __init__" || echo "REVIEW"
grep -qiE "navigator_eventbus\.brokers" CHANGELOG.md && echo "PASS: migration note present" || echo "FAIL: note missing"
```

---

## Agent Instructions

Standard SDD flow. This is the closing task — after it, run `/sdd-done FEAT-318`
in ai-parrot for the SDD bookkeeping (the navigator PR is opened separately in
that repo). Code/doc commits land in navigator; SDD state commit (index + this
file move) lands in ai-parrot on `dev`.

---

## Completion Note

**Completed by**: Claude (Opus 4.8) via `/sdd-start`
**Date**: 2026-07-20
**Notes**:
- **`navigator/__init__.py` verified free of `broker` references** (`git grep`) —
  no-op as expected.
- **CHANGELOG breaking-change note** added under a new `## [Unreleased]` section
  (Keep-a-Changelog format; exact release version is an open decision) in the
  navigator worktree (commit `558f8fb`). Covers: `navigator.brokers.*` removed,
  **no shim**, replacement path `navigator_eventbus.brokers.*`, the new
  `navigator-api[brokers]` extra + `aiormq` drop, and the coordinated-release
  requirement for **Flowtask** and **FieldSync** (FieldSync must drop its local
  PR #393 shim).
- **PR navigator#393 annotated + CLOSED** (verified `state: CLOSED`) with a
  "superseded — fixes ported to navigator-eventbus" comment crediting @hacu9 and
  referencing FEAT-316 (port) + FEAT-318 (removal). Done via `gh` authed as
  `phenobarbital`; **outward-facing action was explicitly approved by the user**
  before posting. PR base was `master`; closed as not-merged since the target
  code no longer exists here.

**Deviations from spec**: none.

**Follow-ups (owner, outside this task's scope)**:
- Cut the actual navigator release (open question — release-coordination window
  owner). The CHANGELOG entry is `[Unreleased]`; stamp it with the version at
  release time.
- Confirm Flowtask + FieldSync have migrated their imports before shipping.
- Run the full navigator `pytest` suite + `uv pip install -e .[brokers]` in
  navigator's own built venv/CI (deferred from TASK-1836/1837 — worktree is an
  unbuilt Cython tree).
