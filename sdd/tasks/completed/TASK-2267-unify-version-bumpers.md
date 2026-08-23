# TASK-2267: Unify the two version bumpers

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 4 (§8 Q4 answered: IN). Two independent implementations bump a
form version and they disagree:

- `api/_utils.py:61 _bump_version` increments the **last** component and
  accepts three-part versions (`1.2.3` → `1.2.4`);
- `services/form_version.py:85 _bump` uses `_SEMVER_RE` (`:66`), which
  matches only `^(\d+)\.(\d+)$`; anything else falls through
  `_parse_major_minor` to `(1, 0)` with a warning.

A single `1.2.3` row therefore sorts as `(1, 0)` and misorders the whole
history. No such row exists today — all 105 measured versions match
`^\d+\.\d+$` — which is exactly why this closes the door before it opens.

Independently mergeable; it does not block or depend on any other task in
this feature.

---

## Scope

- Collapse the two bumpers into one implementation with one documented
  grammar, used by both call sites.
- Decide and document what happens to a non-conforming input rather than
  degrading silently: reject it, or normalise it — not a `logger.warning`
  and `(1, 0)`.
- Tests proving both former call sites produce identical output.

**NOT in scope**: changing the `major.minor` format itself (spec §1
non-goal, reaffirmed by the submitter in §0.1 S1), and the SQL ordering
guard (TASK-2265 — that is the belt to this braces).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../api/_utils.py` | MODIFY | `_bump_version` delegates to the single implementation |
| `.../services/form_version.py` | MODIFY | the surviving `_bump` / `_parse_major_minor` grammar |
| `packages/parrot-formdesigner/tests/unit/test_form_version.py` | MODIFY | grammar-parity tests |

---

## Codebase Contract (Anti-Hallucination)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _bump_version(version: str) -> str: ...                    # line 61
#   "1.0" → "1.1" | "1" → "1.1" | "1.2.3" → "1.2.4"

# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)$")                     # line 66
def _parse_major_minor(version: str) -> tuple[int, int]: ...   # line 69  ← silent (1,0) fallback
def _bump(current: str, bump: str = "minor") -> str: ...       # line 85

# call sites of _bump_version
# api/handlers.py:1281   body["version"]   = _bump_version(existing.version)
# api/handlers.py:1357   merged["version"] = _bump_version(existing.version)
```

### Does NOT Exist
- ~~a CHECK constraint on `form_schemas.version`~~ — the column is a free
  `VARCHAR(50)`; nothing at the database level enforces the grammar

---

## Implementation Notes

### Key Constraints
- `_bump_version` is called on the editor's hot path (every save). Keep it
  cheap and total — a bump that raises on legacy input would break saving.
- `_bump(bump="major")` support must survive the merge.
- Whatever grammar wins, document it where the helper lives.

---

## Acceptance Criteria

- [ ] One implementation; the other delegates to it
- [ ] Both former call sites produce identical output for `1.0`, `1.9`, `1.14`
- [ ] Three-part input has one documented, tested behaviour — not a silent
      `(1, 0)` degradation
- [ ] `bump="major"` still works
- [ ] `pytest packages/parrot-formdesigner/tests/unit/ -v` passes

---

## Test Specification

```python
def test_bump_grammar_is_single():
    for v in ("1.0", "1.9", "1.14"):
        assert _bump_version(v) == _bump(v)

def test_three_component_input_has_one_documented_behaviour(): ...
def test_major_bump_survives(): ...
```

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: `services/form_version.py::_bump` is the surviving implementation
(per the task's own file-list wording); `api/_utils.py::_bump_version` now
delegates to it (`bump="minor"`, the only mode that call site ever used)
via a lazy import (matching this module's "no import-time side effects"
docstring and the same lazy-import style `handlers.py` already uses for
`FormVersionService`). Grammar: `major.minor` or `major.minor.patch`
increments the last present component (`bump="minor"`) or the major
component with the rest reset (`bump="major"`, drops any patch); anything
that doesn't even parse as `N.N` is NOT rejected — appended `.1` instead,
staying total (never raises) since `_bump_version` runs on the editor's
hot path. Also fixed `_parse_major_minor`'s fallback: it no longer
degrades an unparseable version to `(1, 0)` (which silently mis-sorted it
as the OLDEST version); it now returns a maximal sentinel
(`_UNPARSEABLE_SORT_KEY`) so it sorts LAST, matching the SQL ordering
guard's `NULLS LAST` semantics (Module 2). Verified against real call
sites: no other module in the tree references `_SEMVER_RE`,
`_parse_major_minor`'s old fallback value, or 3-part version behavior
besides the two bumpers and their own tests.
**Deviations from spec**: Rewrote the pre-existing
`test_parse_major_minor_invalid_falls_back` (this task's own listed test
file) — it asserted the exact `(1, 0)` degradation this task exists to
replace; left unmodified, it would fail as an expected consequence of
this change. Also added `test_parse_major_minor_three_part_ignores_patch`
and `test_non_conforming_input_is_total_not_raising`, beyond the task's
minimal Test Specification snippet, to cover the parsing-fallback change
the acceptance criteria call for ("not a silent (1, 0) degradation") and
the total/non-raising constraint explicitly called out in Key
Constraints.
