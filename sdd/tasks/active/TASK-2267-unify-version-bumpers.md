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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
