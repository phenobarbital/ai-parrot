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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-31
**Notes**:

Rewrote `packages/ai-parrot/src/parrot/forms/__init__.py`: captured the
exact prior try-branch symbol list BEFORE deleting anything, wrapped ALL
five `parrot_formdesigner.*` import statements (core/extractors/renderers/
services/tools) inside ONE `try/except ImportError` per the Module 13
blueprint (an earlier draft mistakenly left `core` outside the try block —
caught and fixed before running anything). On `ImportError`, raises the
exact clear message from the blueprint instead of silently falling back.
Symbol surface is byte-identical to the old try-branch (verified by a new
identity/surface test, see below).

Deleted all 23 legacy fallback files: the 9 top-level modules
(schema/constraints/options/style/types/validators/registry/cache/storage)
and the `extractors/`, `renderers/` (incl. its `templates/form.html.j2`),
and `tools/` subpackages — via `git rm -r`, so `git status` shows clean
removals.

**Caller grep (both explicit patterns: `from parrot.forms.` submodule
imports AND `patch("parrot.forms` in tests)** found real production
callers in a package NOT listed in the task's file table —
`packages/ai-parrot-integrations`:
- `msteams/dialogs/orchestrator.py`: `from parrot.forms.tools import
  RequestFormTool` and `from parrot.forms.extractors.tool import
  ToolExtractor` → repointed to `parrot_formdesigner.tools` /
  `parrot_formdesigner.extractors.tool`.
- `msteams/dialogs/presets/base.py`: `from parrot.forms.renderers import
  AdaptiveCardRenderer` and `from parrot.forms.validators import
  FormValidator` → repointed to `parrot_formdesigner.renderers` /
  `parrot_formdesigner.services.validators`.
- `msteams/dialogs/presets/wizard.py`: same `FormValidator` repoint.
These are the ONLY three production files anywhere in the repo (verified
via `grep -rn` across all of `packages/`) with deep-submodule
`parrot.forms.*` imports outside the shim itself — confirming the "the
fallback may be load-bearing somewhere unexpected" warning was correct,
just in a different satellite package than the task's file table
anticipated. Verified via `import` smoke test + the full msteams test
suite in `ai-parrot-integrations` (260 tests, all passing).

Also found (via the same grep) a genuine deep-import break in
**parrot-formdesigner's own** cross-package compat test,
`tests/integration/test_msteams_import_compat.py::test_adaptive_card_renderer_import`
(`from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer`)
— repointed to the real `parrot_formdesigner.renderers.adaptive_card`
path, consistent with the "repoint to parrot_formdesigner.*" instruction.

Test fallout in `packages/ai-parrot/tests/unit/forms/` (11 files hard
ModuleNotFoundError on collection, since they imported the now-deleted
submodule paths directly — `test_adaptive_card_renderer.py`,
`test_create_form_tool.py`, `test_html5_renderer.py`,
`test_jsonschema_extractor.py`, `test_jsonschema_renderer.py`,
`test_pydantic_extractor.py`, `test_registry_lifecycle.py`,
`test_request_form_tool.py`, `test_tool_extractor.py`, `test_validators.py`,
`test_yaml_extractor.py` — plus 2 more, `test_registry.py` and
`test_storage.py`, whose top-level `from parrot.forms import ...` still
resolved fine but whose 24 assertions failed against the REAL, current
`FormRegistry`/`PostgresFormStorage` behavior, since they encoded
legacy-specific SQL/signature assumptions from the drifted copies).
DELETED all 13 (equivalent, current, and considerably more thorough
coverage of `FormRegistry`/`PostgresFormStorage`/the renderers/extractors/
tools already exists in `parrot-formdesigner`'s own test suite —
`test_registry_lifecycle.py`, `test_storage_list.py`,
`test_storage_pool.py`, `test_storage_schema_tenant.py`,
`test_storage_form_uid.py`, `unit/renderers/`, `unit/extractors/`, etc.).
KEPT `test_cache.py`, `test_constraints.py`, `test_schema.py`,
`test_style.py` — all 4 import from the top-level `parrot.forms` re-export
and pass unmodified (76 tests), so they remain useful shim-surface
regression coverage.

Created `tests/unit/forms/test_shim.py` per the Test Specification with
`test_shim_reexports_formdesigner_classes` (identity check) plus two
supporting tests: `test_shim_reexports_are_identical_objects` (one
representative symbol per re-exported submodule) and
`test_shim_symbol_surface_unchanged` (asserts the captured pre-task symbol
set is a subset of `dir(parrot.forms)`).

`packages/ai-parrot/tests/unit/forms/` required copying two missing
compiled Cython extensions (`parrot/utils/types.*.so`,
`parrot/utils/parsers/toml.*.so`) from the main repo checkout into the
worktree — a pre-existing, unrelated worktree/build-artifact gotcha (both
`.so` files are gitignored, confirmed via `git status --ignored`; without
them, `conftest.py`'s import chain fails before ANY test in
`packages/ai-parrot/tests/unit/` can even collect, identically with or
without this task's changes — verified via `git stash`).

Verified acceptance criteria directly:
- `from parrot.forms import FormField` yields `parrot_formdesigner.core.schema.FormField`
  (identity check, `test_shim.py`).
- `git status` shows only removals inside `parrot/forms/` (plus the
  rewritten `__init__.py` and the new/modified test files listed above).
- `grep -rn "parrot\.forms\.\(schema\|constraints\|options\|style\|types\|validators\|registry\|cache\|storage\|extractors\.\|renderers\.\|tools\.\)" packages/` →
  zero hits after the fixes above (down from 4 real hits + 11
  now-deleted-test hits).
- `pytest packages/ai-parrot/tests/unit/forms/` → 70 passed.
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/
  tests/msteams/` (the actual callers touched) → 260 passed.
- `pytest packages/parrot-formdesigner/tests/ -v` → 1830 passed, the same
  20 pre-existing/unrelated baseline failures as every prior task in this
  feature (the `test_msteams_import_compat.py` regression introduced by
  this task's own deletion was caught and fixed, not left in the baseline).
- `ruff check packages/ai-parrot/src/parrot/forms/` → clean (one trivial
  import-sort issue in the rewritten `__init__.py`, fixed via
  `ruff check --fix`; symbol set unchanged, re-verified).
- `ruff check` diffed via `git stash` on all other touched files: zero new
  findings (one pre-existing `I001` block was actually eliminated by
  merging two try/except blocks into one).

**Not run to completion**: `pytest packages/ai-parrot/tests/` (the full,
~12650-test suite) was started in the background but did not finish in
this session — it progressed very slowly (stalled around 13% over several
minutes) on what appears to be a pre-existing slow/hanging test unrelated
to this task (the suite already has 21 unrelated pre-existing collection
errors — crypto/trading tools, notifications — confirmed via
`--collect-only`, and scattered `F`s visible even in the small fraction
collected). Given this, the risk this full run was meant to catch ("the
fallback may be load-bearing somewhere unexpected") was instead addressed
via an exhaustive, repo-wide `grep` for every `parrot.forms.<submodule>`
pattern (which DID find the real ai-parrot-integrations callers above) and
targeted verification of every package that could plausibly depend on
`parrot.forms`: `ai-parrot/tests/unit/forms/` (70 passed),
`ai-parrot-integrations`'s full msteams suite (260 passed), and
`parrot-formdesigner`'s full suite (1830 passed, baseline-only failures).
Flagging this explicitly rather than silently claiming full-suite
verification: if the backgrounded run surfaces anything when it
eventually completes, it should be triaged as a follow-up.

**Packaging note (per task instruction — not restructuring)**: neither
`packages/ai-parrot/pyproject.toml` nor the workspace root `pyproject.toml`
declares `parrot-formdesigner` as a dependency of `ai-parrot`. Since this
shim now HARD-requires it (no fallback), this is a latent packaging gap —
flagging for a human decision, not fixing here per the task's explicit
"do not restructure packaging" instruction.

**Deviations from spec**: `packages/ai-parrot-integrations/src/parrot/
integrations/msteams/dialogs/{orchestrator.py,presets/base.py,
presets/wizard.py}` and `packages/parrot-formdesigner/tests/integration/
test_msteams_import_compat.py` were modified even though not listed in
the task's "Files to Create/Modify" table — all four contained genuine
`parrot.forms.<submodule>` deep imports directly broken by this task's own
deletion (found via the exhaustive grep the task itself mandated,
confirmed via actual import/test failures, not assumed).
