---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Proposal: FormField Content-Type

**Date**: 2026-09-01
**Author**: jesuslarag@gmail.com (with sdd-ideation)
**Status**: draft

## Origin

> "in parrot-formbuilder, the answer of any question in `FormSubmission.data`
> is `dict[str, Any]`, the value type depends on the `FieldType` of the field
> and passes through `_coerce_value()` but we don't have:
> - content-type explicitly by answer — e.g. we are expecting markdown, YAML or
>   a JSON object
> - `TEXT_AREA` is always plain `str`, with no distinction between YAML or markdown
> - no blobs/binary inline: when `FileEnvelope` is used it is the only shape with
>   `blob_ref`; there is no way currently for `TEXT_AREA` to carry a blob (base64)
>
> My suggestion: `content_type` as a field property (schema-side):
> ```python
> class FormField(BaseModel):
>     ...
>     content_type: str | None = None  # "text/markdown", "application/json", "text/yaml"
>     # None → inferred from FieldType (str, int, etc.), backward compatible
> ```
> With this the consumer knows how to interpret the value. For the voice-note
> case, if `FormField` has `accept_content_types` we can accept `"text/plain"`
> and `"application/json"` with a structured JSON containing the answer + the
> path/base64 of the voice note."

The request targets the schema-side gap: field values in `FormSubmission.data`
carry no declared content type, so renderers and consumers must guess encoding
from `FieldType` alone — which is ambiguous (a `TEXT_AREA` could be Markdown,
YAML, or plain prose). The secondary motivation is the audio renderer scenario
where a voice note must be stored alongside the transcribed text answer.

## Scope

### What Changes

- **`FormField`** (`core/schema.py`): add two new optional fields —
  - `content_type: str | None = None` — declares the primary MIME type of the
    expected answer (e.g. `"text/markdown"`, `"text/yaml"`, `"application/json"`).
    `None` means "inferred from `FieldType`" (backward-compatible default).
  - `accept_content_types: list[str] | None = None` — declares additional MIME
    types the field can accept (order-significant; first entry is preferred).
    `None` means single-type acceptance inferred from `content_type`/`FieldType`.
    When set, the validator enforces that the submitted value's shape matches one
    of the declared types.

- **`FormValidator._coerce_value()`** (`services/validators.py`):
  `content_type` is **not** used for eager parsing inside the validator —
  parsing responsibility belongs to the consumer (*resolved: leave parsing
  to the consumer*). The only change to `_coerce_value()` is a dict
  pass-through: when `field.accept_content_types` is set and the submission
  is a `dict` (e.g. a `VoiceAnswerEnvelope` payload), the validator accepts
  it without coercing to `str`. The `content_type` and `accept_content_types`
  values are surfaced as annotation only (present in the `FormField` schema
  that the consumer already reads).

- **Renderers** — all three existing renderers emit `content_type` and
  `accept_content_types` when present (*resolved: all existing renderers, JSON
  Schema renderer is prioritary*):
  - `renderers/jsonschema.py` — primary; first to ship.
  - `renderers/audio.py` — reads `accept_content_types` to decide submission
    shape (`VoiceAnswerEnvelope` vs plain string).
  - `renderers/xforms.py` — emits the metadata in the `bind` element when a
    natural XForms mapping exists (removed from Non-Goals in v1).

### What's New

- **`VoiceAnswerEnvelope`** (new model, `core/voice_answer.py` or similar):
  a lightweight Pydantic model representing the dual payload submitted when a
  voice note drives a `TEXT_AREA` or similar field:
  ```python
  class VoiceAnswerEnvelope(BaseModel):
      answer: str          # Transcription / text answer
      blob_ref: str | None = None   # Server-side voice note reference
      data_url: str | None = None   # Inline base64 audio (small notes only)
  ```
  This is the concrete JSON shape submitted when `accept_content_types`
  contains `"application/json"` alongside `"text/plain"`.  
  Its MIME type from the consumer's perspective is `"application/json"`.

- **Validator pass-through for `accept_content_types`**: when the submitted value
  is a `dict` and `"application/json"` is in `accept_content_types`, the
  validator passes the dict through unchanged (no eager Pydantic coercion to
  `VoiceAnswerEnvelope` — the consumer is responsible for parsing/validation).
  MIME-type mismatch enforcement is **advisory-only in v1** (*resolved:
  advisory-only; hard enforcement is a follow-up for build validators*).

### What's Untouched (Non-Goals)

- `FileEnvelope` and the `UPLOAD_FIELD_TYPES` blob pipeline (FILE, IMAGE,
  IMAGE_DROPZONE, MULTI_UPLOAD) — they already have their own content-type
  negotiation inside `FileEnvelope.content_type`. This proposal does not
  alter upload-field coercion.
- `FieldType` enum — no new values added; `content_type` is orthogonal to
  `field_type`.
- `FormSubmission.data` outer shape — the value for a field is still keyed by
  `field_id`; the content shifts from `str` to `str | dict` for fields
  that declare `"application/json"` as an accepted type.
- XForms renderer full enforcement — `renderers/xforms.py` emits
  `content_type`/`accept_content_types` metadata in v1 (moved to in-scope;
  see What Changes above). Hard MIME-type validation at submission time
  remains a non-goal for v1.
- Server-side audio recording/storage pipeline — `VoiceAnswerEnvelope.blob_ref`
  is expected to be pre-populated by the audio-renderer session before
  submission; this proposal only defines the schema and the validator pass-
  through. Storage itself remains the audio renderer's responsibility.

## Rationale

`TEXT_AREA` today collapses every text-like answer to a plain Python `str`
(see `_coerce_value()` line 516-527 in `services/validators.py`). A consumer
that needs to render Markdown must guess; one that needs to parse YAML must
guess. Declaring `content_type` on the field schema makes the contract
explicit at definition time and is backward-compatible (default `None`).

The `accept_content_types` list addresses the audio-renderer use-case cleanly
without a new `FieldType`: a `TEXT_AREA` that may be answered by voice carries
`accept_content_types=["text/plain", "application/json"]`. The audio renderer
submits a `VoiceAnswerEnvelope` dict when a voice note is present, and a plain
string when it is not. The validator and consumers check `accept_content_types`
to know which shape to expect — no field-type proliferation, no hidden magic.

This approach follows the same pattern already established by `FileEnvelope`
for upload fields (FEAT-460): a typed envelope that coexists with the field's
base `FieldType`.

## Impact

| Area | Change |
|---|---|
| `core/schema.py` — `FormField` | Add `content_type`, `accept_content_types` fields |
| `core/voice_answer.py` (new) | Define `VoiceAnswerEnvelope` |
| `services/validators.py` — `_coerce_value()` | JSON/YAML parse branch for `content_type`; dict pass-through for `accept_content_types` |
| `renderers/jsonschema.py` | Emit `content_type`/`accept_content_types` in JSON Schema output (prioritary) |
| `renderers/audio.py` | Read `accept_content_types` to decide submission shape (`VoiceAnswerEnvelope` vs plain `str`) |
| `renderers/xforms.py` | Emit `content_type`/`accept_content_types` in XForms `bind` element (v1, all renderers in-scope) |
| `tools/field_helpers.py` | Update `_FIELD_SCHEMA_SNIPPETS` examples for `TEXT_AREA` with `content_type` |
| Tests | New unit tests for `_coerce_value()` with `content_type`; VoiceAnswerEnvelope round-trip |

**Backward compatibility**: `content_type=None` and `accept_content_types=None`
replicate today's behavior exactly. Existing `FormSchema` documents that omit
these fields deserialize without error (`model_config = ConfigDict(extra="forbid")`
is preserved; the new fields have defaults).

**Migration**: none required for stored schemas. Consumer code that reads
`FormSubmission.data[field_id]` should guard with `isinstance(value, dict)` for
fields that declare `"application/json"` acceptance — a pattern already needed
for `FileEnvelope` fields.

## Code Context

- **`FormField` model** — `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` lines 65–168.  
  The field currently ends at `meta: dict[str, Any] | None = None` (line 123).
  `model_config = ConfigDict(extra="forbid")` means the two new fields must be
  declared explicitly (line 104).

- **`_coerce_value()`** — `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` lines 498–551+.  
  The `TEXT` / `TEXT_AREA` branch at line 516 returns `str(value).strip()` with
  no sub-type check. This is the insertion point for the `content_type` dispatch.

- **`FileEnvelope`** — `packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py` lines 16–51.  
  Blueprint for the proposed `VoiceAnswerEnvelope`: same `BaseModel` pattern,
  `extra="forbid"`, optional blob/inline fields.

- **`AudioFormRenderer`** — `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`.  
  Imports `FormField` from `core/schema.py`; builds `AudioQuestion` objects per
  field. The renderer is the natural place to inspect `accept_content_types` and
  decide the submission shape.

- **`_FIELD_SCHEMA_SNIPPETS`** — `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` lines 15–282.  
  `TEXT_AREA` snippet currently has no `content_type`; should gain an example
  with `"content_type": "text/markdown"` as documentation.

- **`UPLOAD_FIELD_TYPES`** — `core/file_envelope.py` line 44.  
  Out of scope but confirms the precedent: typed envelopes keyed to field types
  rather than a proliferation of `FieldType` values.

## Open Questions

- [x] Should the validator actively parse `"application/json"` / `"text/yaml"` submissions in `_coerce_value()`, or only annotate the value and leave parsing to the consumer? Eager parsing makes the coerced value a `dict`/`Any`, which is a type change for `FormSubmission.data[field_id]`. — *Resolved*: leave the parsing to the consumer.

- [x] Should `VoiceAnswerEnvelope` live in `core/voice_answer.py` (formdesigner core) or in the audio renderer package (`audio/models.py` already has `AudioFormManifest`, `AudioQuestion`)? — *Resolved*: in core/voice_answer.py, the audio renderer only consumes from there.

- [x] For `accept_content_types`, should the validator enforce that the submission actually matches one of the declared MIME types (rejecting mismatches), or is it advisory-only (hints for consumers)? — *Resolved*: current is advisory-only (with hints for consumers), follow-up for build validators.

- [x] Which renderers need to emit `content_type` / `accept_content_types` in v1: JSON Schema renderer only, or also audio renderer and XForms renderer? — *Resolved*: all existing renderers, but JSON schema renderer is prioritary.
