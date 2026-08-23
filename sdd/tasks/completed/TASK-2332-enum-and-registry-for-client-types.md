# TASK-2332: Enum values + control-registry entries for the client's 11 types

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §4, §5.1
**Status**: pending · **Priority**: high · **Effort**: M · **Depends-on**: —

## Context

Eleven types exist in navigator-svelte and not here, and because
`FormField.field_type` is a strict enum an unknown value does not invalidate the
field — it makes the whole `FormSchema` unparseable. This task removes that
cliff. Validation semantics come in TASK-2333/2334; here a schema must merely
PARSE.

`controls/builtin.py` is what `GET /api/v1/form-controls` serves, and
`FormDesignerConsole.svelte::fetchFieldControls()` builds the designer palette
from it — so a registry entry added here appears in the client palette with no
frontend change. That is the mechanism, and it is also the hazard: an entry
added before its validator branch exists offers a designer a type the server
will reject on submit. Land 2332 and 2333/2334 in the same release.

## Scope

`core/types.py` — add:

```
SEARCH, MASKED, COLOR_PICKER, EMOJI, CRON, TREE_SELECT, SIGNATURE_PAD,
CREDIT_CARD, IMAGE_DROPZONE, MULTI_UPLOAD, AI_CAPTURE
```

Values are the client's exact strings (`search`, `masked`, `color_picker`,
`emoji`, `cron`, `tree_select`, `signature_pad`, `credit_card`,
`image_dropzone`, `multi_upload`, `ai_capture`). A near-miss here is worse than
the current failure: the schema would parse into the wrong type.

`controls/builtin.py` — one `_BUILTIN_METADATA` entry each: `label`,
`description`, `category`, `icon`, `render_hint`, `supports_constraints`,
`is_container`, `supported_operators`, `supported_effects`,
`supported_operations`. Follow the neighbouring entries; do not invent new keys.

NOT in scope: validator branches (2333, 2334), renderer postures (2336),
`place` (2335).

## Acceptance Criteria

- AC1 `FormField(field_id=..., field_type=<t>, label=...)` constructs for all
  eleven. Parametrised, one case per type — today every one raises.
- AC2 A `FormSchema` containing all eleven at once parses.
- AC3 `GET /api/v1/form-controls` returns all eleven with a non-empty `label`
  and a `category` that already exists in the registry.
- AC4 The 33 pre-existing enum values are untouched — asserted by value, so a
  rename cannot pass.

## Notes

`multi_upload` emits `Array<{answer, blob_ref, display}>`, a LIST of REST
envelopes, while `_validate_rest_field` accepts a singular one. That is
fieldsync FEAT-514's stated blocker, already built on the client. Registering
the type here is a precondition for that feature — do not try to solve the
carrier here.

### Completion Note

Implemented as specified: 11 enum members added to `core/types.py` (client's
exact string values) and 11 `_BUILTIN_METADATA` entries added to
`controls/builtin.py` following the neighbouring entries' key shape (no new
keys invented). Added dedicated tests in
`tests/formdesigner/test_feat448_enum_and_registry.py` covering AC1-AC4
(FormField construction, FormSchema parsing, registry/label/category
presence, and the 33 pre-existing values by-value).

Verified inside the worktree with the shadowed venv
(`PYTHONPATH=.../parrot-formdesigner/src`), per the worker brief. Ran the
full `parrot-formdesigner` suite before and after: identical set of 37
pre-existing failures both before and after this change (diffed) — none of
which reference the eleven new types or the registry count; these are
pre-existing gaps (e.g. `pytest-aiohttp` not installed in this venv, and a
few hardcoded-count tests already stale from earlier features like FEAT-224
AUDIO). Not touched — out of scope for this task.

One pre-existing test, `tests/unit/test_controls_registry.py::test_controls_registry_has_all_new_types`,
hardcodes an expected total control count (32) and was already failing
before this task (verified against the pre-FEAT-448 code) since it never
accounted for FEAT-224's AUDIO addition. It fails harder now (44 vs 32) as
a direct, expected consequence of adding 11 registry entries. Left
unmodified per file-fidelity — not in this task's Scope — but flagged here
since a future task/PR reviewer should update that hardcoded count.
