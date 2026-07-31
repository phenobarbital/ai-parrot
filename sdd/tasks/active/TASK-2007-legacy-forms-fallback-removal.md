# TASK-2007: Remove the drifted parrot.forms legacy fallback copies

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1996
**Assigned-to**: unassigned

---

## Context

Implements Module 13 of FEAT-393 (spec §3, blueprint §9). The
`parrot.forms` shim in ai-parrot falls back to drifted local copies (legacy
`FormField` lacks `post_depends`; legacy `FormSchema` lacks 8+ fields, no
`RenderWarning`). Resolved at spec time: DROP the fallback — re-export
`parrot_formdesigner` only, with a clear `ImportError` when absent.

---

## Scope

- Rewrite `packages/ai-parrot/src/parrot/forms/__init__.py`: same public
  symbol list, imports from `parrot_formdesigner.*` submodules only, wrapped
  in `try/except ImportError` that raises
  `ImportError("parrot.forms requires the 'parrot-formdesigner' package: pip install parrot-formdesigner")`.
- DELETE legacy copies: `parrot/forms/{schema,constraints,options,style,types,validators,registry,cache,storage}.py`
  and `parrot/forms/{extractors,renderers,tools}/`.
- Grep ai-parrot for `parrot.forms.<submodule>` imports (they bypass
  `__init__`) and repoint to `parrot_formdesigner.*`.
- Fix or delete `packages/ai-parrot/tests/unit/forms/` tests that exercised
  the deleted copies (e.g. `test_schema.py`, `test_validators.py`).
- Confirm ai-parrot's dependency metadata declares `parrot-formdesigner`
  (check `pyproject.toml` extras) — if absent, note it in the completion note
  for a human decision; do not restructure packaging.

**NOT in scope**: adding UID features to any legacy code (it is deleted, not
updated); packaging restructure.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | thin re-export + clear ImportError |
| `packages/ai-parrot/src/parrot/forms/schema.py` (+8 modules, 3 subpackages) | DELETE | drifted copies |
| ai-parrot files importing `parrot.forms.<submodule>` | MODIFY | repoint imports |
| `packages/ai-parrot/tests/unit/forms/` | MODIFY/DELETE | port or drop legacy-copy tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# TARGET imports (all verified to exist in parrot_formdesigner):
from parrot_formdesigner.core import ...        # schema/constraints/types symbols
from parrot_formdesigner.extractors import ...
from parrot_formdesigner.renderers import ...
from parrot_formdesigner.services import ...
from parrot_formdesigner.tools import ...
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/forms/__init__.py — current try/except shim:
#   "This module is a backward-compatible re-export shim..." — try branch imports
#   parrot_formdesigner.{core,extractors,renderers,services,tools}; except branch
#   falls back to local .schema/.constraints/.options/.style/.types/.validators/
#   .extractors.pydantic/.registry/.cache/.storage  (keep the SYMBOL LIST, drop the fallback)
# Legacy drift (why deletion, not update):
#   parrot/forms/schema.py — FormField :21-65 (field_id :47, NO post_depends);
#   FormSchema :150-175 (8 fields only, no iter_all_fields, no _validate_metadata);
#   RenderedForm :178-191 (no warnings); no RenderWarning, no FormType
```

### Does NOT Exist
- ~~deprecation warnings in the shim~~ — "No deprecation warnings per spec decision" (existing comment); the new ImportError replaces silent fallback, not a warning
- ~~`parrot.formdesigner` (dotted) namespace~~ — the real package module is `parrot_formdesigner` (underscore); TASK-554's plan text shows dotted paths but the shipped code uses `parrot_formdesigner` — follow the CODE
- ~~guaranteed test isolation~~ — memory/worktree gotcha: patching `parrot.forms.X` in tests does not patch `parrot_formdesigner.X`; repoint test patch targets too

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 13" blueprint.

### Key Constraints
- The re-export symbol list must be EXACTLY today's `__all__`/import surface —
  diff the current `__init__.py` try-branch; removing a symbol is a breaking
  change outside this task's scope.
- Search BOTH `from parrot.forms import` and `from parrot.forms.` patterns,
  plus `patch("parrot.forms` in tests.
- Run the FULL ai-parrot suite, not just forms tests — the fallback may be
  load-bearing somewhere unexpected.

---

## Acceptance Criteria

- [ ] `from parrot.forms import FormField` yields `parrot_formdesigner.core.schema.FormField` (identity check in test)
- [ ] Legacy module files deleted; `git status` shows removals only within `parrot/forms/`
- [ ] No ai-parrot source imports `parrot.forms.<deleted submodule>`
- [ ] `pytest packages/ai-parrot/tests/ -v` passes
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/forms/`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/forms/test_shim.py
def test_shim_reexports_formdesigner_classes():
    from parrot.forms import FormField
    from parrot_formdesigner.core.schema import FormField as Real
    assert FormField is Real

def test_shim_symbol_surface_unchanged(previous_symbol_list): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 13; verify TASK-1996 completed.
2. **Verify the contract**: read the current `__init__.py` in full to capture the exact symbol list BEFORE deleting anything.
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run BOTH package suites, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
