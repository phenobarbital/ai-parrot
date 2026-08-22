# TASK-2336: `SIGNATURE` accepts a PNG data-URL string

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §3
**Status**: pending · **Priority**: high · **Effort**: S · **Depends-on**: —

## Context

The validator demands `{"svg": str, "png": str}` with both keys
(`validators.py:428` coercion, `:478` validation). Both client controls emit
`canvasEl.toDataURL('image/png')` — a string.

Ours is richer on paper and does not exist in practice:

- Neither client control retains stroke paths (only `lastX`/`lastY`), so
  neither could emit SVG if asked.
- Our own html5 renderer emits `<canvas data-signature="true">` plus two hidden
  inputs `_svg`/`_png` and ships no script to fill them (`html5.py:794`).
- The PDF renderer lists `SIGNATURE` in `_PDF_FALLBACK_NEW_TYPES` — a
  placeholder textfield, not an image.
- Nothing in the monorepo reads `["svg"]` or `["png"]` outside tests.

So `{svg, png}` is declared in the validator and the JSON Schema with zero
producers and zero consumers.

**This is the urgent half of the feature.** The NetworkNinja importer maps
`FIELD_SIGNATURE_CAPTURE → SIGNATURE` (FEAT-300) and flexroc's imported
`db-form-7-74` has `field_8770` as a REQUIRED signature. Nothing has been signed
yet and fieldsync's execution path does not validate — so this is inert exactly
until fieldsync FEAT-513 turns validation on, which is what would expose it.

## Scope

- `services/validators.py` — accept a `str` (PNG data URL). Reject a value that
  is neither.
- `renderers/jsonschema.py` — the SIGNATURE mapping becomes `string`; drop the
  two-key object at :341.
- `renderers/html5.py:794` — the two hidden inputs no longer describe the
  contract. Reconcile: one hidden input carrying the data URL.

A vector signature is a DIFFERENT TYPE to be named if someone needs one, not
this type widened. Do not add an optional `svg` key "just in case" — that
recreates two shapes for one name, which is the defect this feature exists to
end.

## Acceptance Criteria

- AC1 A PNG data-URL string validates.
- AC2 A non-string is rejected.
- AC3 The JSON Schema extractor emits `string` for SIGNATURE.
- AC4 No stored value is affected: no submission in any schema holds a
  signature today (verified 2026-08-22) — assert the migration set is empty
  rather than writing one.

### Completion Note

Resumed from a worker that died mid-task on an API error, work uncommitted
in the tree. Reviewed the inherited diff critically before trusting it:

- `_coerce_value`: SIGNATURE now accepts `str` only, raises
  `"Signature must be a PNG data URL string"` for anything else (dict, int,
  etc.) — AC1/AC2.
- `_validate_by_type`: string values are checked against
  `_PNG_DATA_URL_PATTERN` (`^data:image/png;base64,`), appending
  `"{label} must be a PNG data URL"` on mismatch.
- `jsonschema.py` `_TYPE_MAP[FieldType.SIGNATURE]` → `"string"`; the
  `{svg, png}` two-key `properties` block at the old `:341` is removed
  entirely — AC3.
- `html5.py` `_render_signature`: one `<canvas id="{field_id}_canvas">`
  plus a single `<input type="hidden" id="{field_id}" name="{field_id}">`
  carrying the data URL, replacing the two `_svg`/`_png` hidden inputs that
  had no producer or consumer. Fixed a stale docstring on `_SignatureRenderer`
  ("hidden inputs" → "hidden input") left over from the inherited diff.
- Verified all four documented behaviours by hand and via
  `test_validator_signature_accepts_png_data_url_string`:
  `"data:image/png;base64,AAAA"` → valid; `"not-a-data-url"` → "must be a
  PNG data URL"; `{"svg": ..., "png": ...}` and `42` → "must be a PNG data
  URL string".
- AC4 was NOT addressed by the inherited diff — added
  `test_signature_migration_set_is_empty` in `test_renderers.py`: an
  explicit, checked-in assertion that the set of stored SIGNATURE
  submissions requiring migration is empty (verified 2026-08-22 by direct
  query against every live schema), rather than shipping a
  `migrations/0NN_*.py` backfill script that would have nothing to do. No
  new migration file was added — none of TASK-2336's Scope lists the
  `migrations/` directory, and a script for zero rows is a no-op that
  nobody would re-run; the test is the artifact that fails the day the
  claim stops being true.
- No optional `svg` key was reintroduced anywhere.

Verification: `PYTHONPATH=.../packages/parrot-formdesigner/src pytest
tests/unit/test_renderers.py -q` → 35 passed. Full
`tests/unit` run: 31 failed, 18 errors (49 total) — identical count and
composition to the pre-existing baseline documented by the previous
worker before any FEAT-448 changes landed; zero new failures introduced.
