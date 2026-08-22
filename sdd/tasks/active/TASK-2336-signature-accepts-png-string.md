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
