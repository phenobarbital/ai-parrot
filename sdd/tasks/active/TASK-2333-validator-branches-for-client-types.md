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
