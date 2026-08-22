# TASK-2333: Validator branches for ten of the client's types

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §4
**Status**: pending · **Priority**: high · **Effort**: L · **Depends-on**: TASK-2332

## Context

Ten branches in `services/validators.py` (both the coercion switch around :425
and the validation switch around :519). `credit_card` is deliberately excluded —
it is TASK-2334, because it is a liability rather than a gap and must not be
written by whoever is working through a list of nine easy ones.

The shapes below were read from the controls, not from navigator-svelte's
2026-05 spec table: two of them are undocumented there and one other differs.

## Scope

| type | accepted value |
|---|---|
| `search` | `str` (the chosen option's value); `None` when cleared |
| `masked` | `str` |
| `color_picker` | `str`, lowercase hex |
| `emoji` | `str`, a single emoji |
| `cron` | `str`, a 5-part expression |
| `tree_select` | `list[str]` in multi mode; `str` in single |
| `signature_pad` | `str`, a PNG data URL |
| `image_dropzone` | `{name, type, size, dataUrl}` or a list of them |
| `multi_upload` | `list[{answer, blob_ref, display}]` |
| `ai_capture` | unconstrained JSON — the capture API's response |

`ai_capture` is deliberately unconstrained: the value is a third-party API's
response and we do not own its shape. Validate that it is JSON-serialisable and
stop. Inventing a schema for it would reject correct answers.

`cron` — validate the 5-field arity, not the semantics of each field. A full
cron parser is not a dependency this package should grow for one field type.

## Acceptance Criteria

- AC1 A value produced by each client control validates with no errors. One
  case per type, using the shape in the table.
- AC2 A clearly wrong value for each type produces an error (a dict where a
  string belongs, and the reverse).
- AC3 `ai_capture` accepts a nested object, a list and a scalar alike.
- AC4 `image_dropzone` accepts both the single and the list form.
- AC5 No existing branch changes behaviour — the pre-existing validator suite
  passes unchanged.

## Notes

`image_dropzone`'s `dataUrl` is inline base64 and the wrong carrier at photo
scale; the platform already has `blob_ref`. Accept the shape so schemas
validate. Changing the carrier is fieldsync FEAT-514 and must not be pre-empted.

### Completion Note

Added coercion branches (`_coerce_value`) and semantic checks
(`_validate_by_type`) for the ten types (search, masked, color_picker,
emoji, cron, tree_select, signature_pad, image_dropzone, multi_upload,
ai_capture) in `services/validators.py`. `credit_card` intentionally
excluded per this task's own scope — that's TASK-2334.

Design notes:
- Type-shape gates (string vs dict/list) raise `ValueError` in `_coerce_value`
  — same pattern as the existing SIGNATURE/AVAILABILITY/REST branches — so a
  dict where a string belongs (and vice versa) is a hard error (AC2).
- Deeper format checks (hex color, cron 5-field arity, PNG data-URL prefix,
  image_dropzone/multi_upload required keys) live in `_validate_by_type`,
  matching the existing LOCATION/AVAILABILITY split between coercion and
  semantic validation.
- `ai_capture` coercion only checks `json.dumps()` succeeds — deliberately
  no schema, per the task's explicit instruction not to invent one for a
  third-party API response (AC3).
- `cron` validates 5-space-separated-field arity only, not per-field
  semantics, per the task's explicit scope.

Tests: `tests/formdesigner/test_feat448_validator_branches.py`, 29 cases
covering AC1 (valid control values), AC2 (wrong-shape rejection per type),
AC3 (ai_capture accepts object/list/scalar, rejects non-JSON-serialisable),
AC4 (image_dropzone single + list form), and a spot-check of AC5 (TEXT and
LOCATION unaffected). Full `parrot-formdesigner` suite diffed against the
TASK-2332 baseline: identical failure set, no regressions.
