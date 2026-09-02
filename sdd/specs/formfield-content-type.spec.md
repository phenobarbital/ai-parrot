---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: FormField Content-Type

**Feature ID**: FEAT-488
**Date**: 2026-09-01
**Author**: jesuslarag@gmail.com
**Status**: draft
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

Field values in `FormSubmission.data` carry no declared content type. Renderers
and consumers must guess encoding from `FieldType` alone — which is ambiguous.
A `TEXT_AREA` today collapses every text-like answer to a plain Python `str`
(see `_coerce_value()` lines 516-527 in `services/validators.py`). A consumer
that needs to render Markdown must guess; one that needs to parse YAML must guess.

A secondary gap: there is no way for a `TEXT_AREA` to carry a voice note alongside
the transcribed text answer. `FileEnvelope` (FEAT-460) solved the same problem for
upload fields via a typed envelope — but no equivalent exists for text-like fields.

### Goals

- Add `content_type: str | None` to `FormField` — declares the primary MIME type of
  the expected answer (`"text/markdown"`, `"text/yaml"`, `"application/json"`). `None`
  means "inferred from `FieldType`" (backward-compatible default).
- Add `accept_content_types: list[str] | None` to `FormField` — declares additional
  accepted MIME types (order-significant; first entry is preferred). `None` means
  single-type acceptance inferred from `content_type`/`FieldType`.
- Add `VoiceAnswerEnvelope` (new Pydantic model in `core/voice_answer.py`) — the
  typed dual-payload shape for fields that accept both a text answer and a voice note.
- Extend `_coerce_value()` to pass `dict` submissions through unchanged when
  `field.accept_content_types` includes `"application/json"`.
- Emit `content_type` / `accept_content_types` metadata in all three existing
  renderers: JSON Schema (priority), audio, and XForms.
- Update `_FIELD_SCHEMA_SNIPPETS` examples for `TEXT_AREA` with a `content_type`
  example.

### Amendment (post-review, 2026-09-02): `FormField.answer_envelope`

Code review found that `VoiceAnswerEnvelope` as originally specified was
unreachable: nothing in production ever validated against it, so the
"canonical value shape" was never enforced. The cause is that this spec gives
`"application/json"` in `accept_content_types` two different meanings —

- §Goals line 151 uses `["text/plain", "application/json"]` to declare a
  **voice-note field**, whose dict answer should be a `VoiceAnswerEnvelope`;
- §Goals line 36 uses `content_type="application/json"` to declare a field
  that simply **holds arbitrary JSON**.

`FormField` carried no signal to tell them apart, so enforcing the envelope
would have broken the arbitrary-JSON case and not enforcing it left the model
dead. Resolved by adding a third, explicit annotation:

- `answer_envelope: Literal["voice"] | None` on `FormField`. `"voice"` means
  a submitted `dict` MUST validate as a `VoiceAnswerEnvelope` — the validator
  enforces the shape and returns the canonical `model_dump()`. `None` (the
  default) keeps the v1 pass-through: a submitted `dict` is arbitrary JSON and
  is not inspected.

This preserves both use cases and leaves the Non-Goals below intact — MIME
mismatch is still advisory-only, and the audio storage pipeline is still out
of scope (`blob_ref` remains client-populated). The annotation is emitted by
all three renderers as `x-answer-envelope` and read back by
`JsonSchemaExtractor`.

Related review findings fixed alongside it: dict answers no longer bypass the
required check or the `min_length`/`max_length`/`pattern` constraints (those
now apply to the envelope's transcript); the renderers no longer emit an
empty `x-accept-content-types`; and `JsonSchemaExtractor` now round-trips all
three annotations, which it previously dropped.

### Non-Goals (explicitly out of scope)

- `FileEnvelope` and the `UPLOAD_FIELD_TYPES` blob pipeline — they already have
  their own content-type negotiation. This feature does not alter upload-field coercion.
- `FieldType` enum — no new values added; `content_type` is orthogonal to `field_type`.
- Hard MIME-type enforcement at submission time — mismatch enforcement is advisory-only
  in v1 (follow-up for build validators, per resolved Q3).
- Server-side audio recording/storage pipeline — `VoiceAnswerEnvelope.blob_ref` is
  expected to be pre-populated by the audio-renderer session before submission; this
  spec only defines the schema and the validator pass-through.
- XForms hard MIME-type validation at submission time — `renderers/xforms.py` emits
  the metadata in v1; enforcement is a non-goal.

---

## 2. Architectural Design

### Overview

`content_type` and `accept_content_types` are **schema-side** annotations on
`FormField`. They are declared at form-design time and surfaced by renderers; they do
not cause eager parsing inside the validator. Parsing responsibility stays with the
consumer (resolved Q1).

The `VoiceAnswerEnvelope` model in `core/voice_answer.py` follows the same `BaseModel`
pattern as `FileEnvelope` (FEAT-460): `extra="forbid"`, optional blob/inline fields.
It is the concrete JSON shape submitted when `accept_content_types` contains
`"application/json"` alongside `"text/plain"` in a voice-capable field.

### Component Diagram

```
FormField (core/schema.py)
  ├── content_type: str | None              [NEW — after meta field]
  └── accept_content_types: list[str] | None [NEW — after content_type]

VoiceAnswerEnvelope (core/voice_answer.py)  [NEW FILE]
  ├── answer: str
  ├── blob_ref: str | None
  └── data_url: str | None

FormValidator._coerce_value() (services/validators.py)
  └── dict pass-through when accept_content_types includes "application/json"

Renderers (all three):
  ├── renderers/jsonschema.py  ← emit x-content-type, x-accept-content-types (priority)
  ├── renderers/audio.py       ← surface accept_content_types on AudioQuestion
  └── renderers/xforms.py      ← emit mediatype attr on <xf:bind>

tools/field_helpers.py
  └── _FIELD_SCHEMA_SNIPPETS["text_area"]  ← add content_type example
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormField` (`core/schema.py`) | extend | Add two new optional fields with `None` defaults |
| `FileEnvelope` (`core/file_envelope.py`) | blueprint | `VoiceAnswerEnvelope` mirrors its pattern |
| `FormValidator._coerce_value()` (`services/validators.py`) | patch | dict pass-through guard on TEXT/TEXT_AREA |
| `JSONSchemaRenderer._field_to_property()` (`renderers/jsonschema.py`) | patch | Emit `x-content-type` / `x-accept-content-types` |
| `AudioFormRenderer` / `classify_voice_mode()` (`renderers/audio.py`) | patch | Surface `accept_content_types` on AudioQuestion |
| `XFormsRenderer._collect_binds()` (`renderers/xforms.py`) | patch | Add `mediatype` attribute to `<xf:bind>` |
| `_FIELD_SCHEMA_SNIPPETS` (`tools/field_helpers.py`) | patch | Update `TEXT_AREA` snippet |

### Data Models

```python
# NEW — packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py
class VoiceAnswerEnvelope(BaseModel):
    """Dual payload for voice-note-capable TEXT_AREA fields.

    Submitted when accept_content_types contains "application/json"
    and the user answered via voice. The consumer is responsible for
    parsing; the validator passes the dict through unchanged.
    """
    model_config = ConfigDict(extra="forbid")

    answer: str                      # Transcription / text answer
    blob_ref: str | None = None      # Server-side voice note reference
    data_url: str | None = None      # Inline base64 audio (small notes only)

# PATCH — FormField additions (core/schema.py, inserted after line 123)
content_type: str | None = None
# "text/markdown", "text/yaml", "application/json" — or None (inferred)
accept_content_types: list[str] | None = None
# ["text/plain", "application/json"] — first is preferred; None = infer
```

### New Public Interfaces

```python
# New model importable from:
from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope

# Usage example — define a voice-note field:
voice_field = FormField(
    field_id="voice_answer",
    field_type=FieldType.TEXT_AREA,
    label="Voice note",
    content_type="text/plain",
    accept_content_types=["text/plain", "application/json"],
)
```

---

## 3. Module Breakdown

### Module 1: `VoiceAnswerEnvelope` model

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py`
- **Responsibility**: Define `VoiceAnswerEnvelope` Pydantic model. Export it from
  `parrot_formdesigner.core` package (update `core/__init__.py` if needed).
- **Depends on**: `pydantic` (already a core dependency)

### Module 2: `FormField` schema extension

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: Add `content_type: str | None = None` and
  `accept_content_types: list[str] | None = None` to `FormField` after `meta` (line 123).
  Update the class docstring to document both new attributes.
- **Depends on**: Module 1 (for docstring cross-reference only — no runtime import needed)

### Module 3: Validator dict pass-through

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: In `_coerce_value()` (line 498), add a guard before the
  `TEXT`/`TEXT_AREA` branch (line 516): if `field.accept_content_types` is not `None`
  and `"application/json"` is in `field.accept_content_types` and
  `isinstance(value, dict)`, return `value` unchanged. Advisory-only: no rejection of
  type mismatches in v1.
- **Depends on**: Module 2 (`FormField.accept_content_types` attribute)

### Module 4: JSON Schema renderer extension (priority)

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`
- **Responsibility**: In `_field_to_property()` (line 472), after existing `x-*`
  extensions are emitted (around line 614), add:
  - `prop["x-content-type"] = field.content_type` when `field.content_type is not None`
  - `prop["x-accept-content-types"] = field.accept_content_types` when
    `field.accept_content_types is not None`
- **Depends on**: Module 2

### Module 5: Audio renderer extension

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`
- **Responsibility**: Surface `accept_content_types` on the `AudioQuestion` output when
  `field.accept_content_types` is set. Either add an `accept_content_types` field to
  `AudioQuestion` (in `audio/models.py`) or store it in `AudioQuestion.meta`. Document
  that the audio renderer does not enforce the shape — the consumer reads
  `accept_content_types` to decide whether to submit a `VoiceAnswerEnvelope` dict or a
  plain string.
- **Depends on**: Module 2

### Module 6: XForms renderer extension

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`
- **Responsibility**: In `_collect_binds()` (line 306), when `field.content_type is not
  None`, set `attrs["mediatype"] = field.content_type` on the `<xf:bind>` element.
  When `field.accept_content_types is not None`, set
  `attrs["x-accept-content-types"] = " ".join(field.accept_content_types)` (space-
  separated list, parrot-specific extension).
- **Depends on**: Module 2

### Module 7: Field helpers update

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`
- **Responsibility**: Update `_FIELD_SCHEMA_SNIPPETS["text_area"]` (lines 22-26) to
  include `"content_type": "text/markdown"` as a documentation example.
- **Depends on**: Module 2

### Module 8: Unit and integration tests

- **Path**: `packages/parrot-formdesigner/tests/unit/` and
  `packages/parrot-formdesigner/tests/integration/`
- **Responsibility**: New test files covering Modules 1-7. See §4 for details.
- **Depends on**: Modules 1-7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_voice_answer_envelope_roundtrip` | Module 1 | Model validates with answer only, blob_ref, data_url |
| `test_voice_answer_extra_forbidden` | Module 1 | `extra="forbid"` rejects unknown fields |
| `test_formfield_content_type_default_none` | Module 2 | Existing FormField deserialization is backward-compatible |
| `test_formfield_content_type_set` | Module 2 | `content_type` + `accept_content_types` round-trip cleanly |
| `test_coerce_dict_passthrough_with_json_accept` | Module 3 | dict value passes through when `"application/json"` in `accept_content_types` |
| `test_coerce_str_unchanged_no_accept` | Module 3 | No regression: str coercion unchanged when `accept_content_types=None` |
| `test_jsonschema_emits_x_content_type` | Module 4 | `x-content-type` present when field declares it |
| `test_jsonschema_no_x_content_type_when_none` | Module 4 | Key absent when `content_type=None` |
| `test_jsonschema_emits_x_accept_content_types` | Module 4 | `x-accept-content-types` list emitted correctly |
| `test_audio_accept_content_types_surfaced` | Module 5 | `accept_content_types` on AudioQuestion when field declares it |
| `test_xforms_mediatype_emitted` | Module 6 | `mediatype` attr on `<xf:bind>` when `content_type` set |
| `test_xforms_no_mediatype_when_none` | Module 6 | Attr absent when `content_type=None` |
| `test_field_helpers_text_area_example` | Module 7 | `_FIELD_SCHEMA_SNIPPETS["text_area"]` includes `content_type` key |

### Integration Tests

| Test | Description |
|---|---|
| `test_submit_voice_answer_envelope` | Full round-trip: form with TEXT_AREA + `accept_content_types=["text/plain","application/json"]`, submit a VoiceAnswerEnvelope dict — validator accepts it unchanged |
| `test_jsonschema_render_voice_field` | Render a form with a voice-note field via JSONSchemaRenderer; assert `x-accept-content-types` in output |

### Test Data / Fixtures

```python
@pytest.fixture
def voice_field() -> FormField:
    return FormField(
        field_id="voice_answer",
        field_type=FieldType.TEXT_AREA,
        label="Voice note",
        content_type="text/plain",
        accept_content_types=["text/plain", "application/json"],
    )

@pytest.fixture
def voice_envelope_payload() -> dict:
    return {
        "answer": "I agree with the terms.",
        "blob_ref": "s3://bucket/voice-notes/abc123.wav",
        "data_url": None,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `FormField` deserializes with `content_type=None` and `accept_content_types=None`
  (backward-compatible default) — existing `FormSchema` documents load without error.
- [ ] `FormField` serializes and deserializes `content_type` and `accept_content_types`
  with non-`None` values correctly (round-trip stable).
- [ ] `VoiceAnswerEnvelope` validates `answer`, `blob_ref`, `data_url`; `extra="forbid"`
  rejects unknown fields.
- [ ] `_coerce_value()` passes a `dict` value through unchanged when
  `field.accept_content_types` contains `"application/json"` (dict pass-through guard).
- [ ] `_coerce_value()` str-coerces `TEXT_AREA` values unchanged when
  `accept_content_types=None` (no regression).
- [ ] `JSONSchemaRenderer._field_to_property()` emits `x-content-type` when
  `field.content_type` is set; key absent when `None`.
- [ ] `JSONSchemaRenderer._field_to_property()` emits `x-accept-content-types` when
  `field.accept_content_types` is set; key absent when `None`.
- [ ] `AudioFormRenderer` surfaces `accept_content_types` for fields that declare it.
- [ ] `XFormsRenderer._collect_binds()` emits `mediatype` attribute on `<xf:bind>`
  when `field.content_type` is set; attribute absent when `None`.
- [ ] `_FIELD_SCHEMA_SNIPPETS["text_area"]` includes an example with
  `"content_type": "text/markdown"`.
- [ ] All new unit tests pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`).
- [ ] All integration tests pass
  (`pytest packages/parrot-formdesigner/tests/integration/ -v`).
- [ ] No breaking changes to existing `FormSchema` serialization.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All file paths and line numbers verified 2026-09-01.

### Verified Imports

```python
# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
from parrot_formdesigner.core.schema import FormField, FormSchema, RenderedForm

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py
from parrot_formdesigner.core.file_envelope import FileEnvelope, UPLOAD_FIELD_TYPES

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
from parrot_formdesigner.renderers.jsonschema import JSONSchemaRenderer

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py
from parrot_formdesigner.renderers.audio import AudioFormRenderer, classify_voice_mode

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py
from parrot_formdesigner.renderers.xforms import XFormsRenderer

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
from parrot_formdesigner.services.validators import FormValidator

# Verified: packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
from parrot_formdesigner.tools.field_helpers import _FIELD_SCHEMA_SNIPPETS
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormField(BaseModel):                          # line 65
    model_config = ConfigDict(extra="forbid")        # line 104
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # line 106
    field_id: str                                    # line 107
    field_type: FieldType                            # line 108
    label: LocalizedString                           # line 109
    description: LocalizedString | None = None       # line 110
    placeholder: LocalizedString | None = None       # line 111
    required: bool = False                           # line 112
    default: Any = None                              # line 113
    read_only: bool = False                          # line 114
    constraints: FieldConstraints | None = None      # line 115
    options: list[FieldOption] | None = None         # line 116
    options_source: OptionsSource | None = None      # line 117
    depends_on: DependencyRule | None = None         # line 118
    post_depends: list[PostDependency] | None = None # line 119
    children: list[FormField] | None = None          # line 120
    item_template: FormField | None = None           # line 121
    relation: RelationSpec | None = None             # line 122
    meta: dict[str, Any] | None = None               # line 123
    # NEW fields inserted after line 123 — content_type, accept_content_types

# packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py
class FileEnvelope(BaseModel):                       # line 16
    model_config = ConfigDict(extra="forbid")        # line 33
    filename: str = Field(...)                       # line 35
    content_type: str = Field(...)                   # line 36
    size: int = Field(...)                           # line 37
    blob_ref: str | None = Field(default=None)       # line 38
    data_url: str | None = Field(default=None)       # line 39
    thumbnail_url: str | None = Field(default=None)  # line 40
    checksum: str | None = Field(default=None)       # line 41
UPLOAD_FIELD_TYPES: frozenset[FieldType]             # line 44

# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class FormValidator:
    def _coerce_value(self, value: Any, field: FormField) -> Any:  # line 498
        # TEXT/TEXT_AREA branch: lines 516-527 → return str(value).strip()
        # NEW dict pass-through guard inserted BEFORE line 516

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py
class JSONSchemaRenderer:
    def _field_to_property(
        self,
        field: FormField,
        locale: str,
        prefilled: dict[str, Any],
    ) -> dict[str, Any]:                             # line 472
        # Returns prop dict with x-* extensions
        # Existing x-* pattern at lines 554-668
        # NEW x-content-type / x-accept-content-types inserted after line 668

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py
def classify_voice_mode(field: FormField) -> VoiceMode:  # line 95
    # Returns VoiceMode.VOICE / PROMPT_SELECT / VISUAL_FALLBACK

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py
class XFormsRenderer:
    def _collect_binds(
        self,
        binds: list[etree._Element],
        path: str,
        field: FormField,
    ) -> None:                                       # line 306
        # builds attrs dict; creates etree.Element(_qn("bind"), attrib=attrs) at line 333
        # NEW: mediatype attr inserted when field.content_type is not None

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]]   # line 15
# TEXT_AREA entry at lines 22-26 — currently has no content_type key
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VoiceAnswerEnvelope` | `FileEnvelope` | blueprint pattern | `core/file_envelope.py:16` |
| `FormField.content_type` | `_field_to_property()` | attribute access | `renderers/jsonschema.py:472` |
| `FormField.accept_content_types` | `_coerce_value()` | guard before line 516 | `services/validators.py:498` |
| `FormField.content_type` | `_collect_binds()` | `attrs["mediatype"]` | `renderers/xforms.py:306` |
| `FormField.accept_content_types` | `classify_voice_mode()` / AudioQuestion | attribute access | `renderers/audio.py:95` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.core.voice_answer`~~ — does not exist yet (Module 1 creates it)
- ~~`FormField.content_type`~~ — not yet on the model (Module 2 adds it)
- ~~`FormField.accept_content_types`~~ — not yet on the model (Module 2 adds it)
- ~~`VoiceAnswerEnvelope`~~ — not yet defined anywhere in the package
- ~~`AudioQuestion.accept_content_types`~~ — not currently a field on `AudioQuestion`
  (Module 5 adds it or stores via meta)
- ~~`x-content-type` in `JSONSchemaRenderer` output~~ — not currently emitted
- ~~`mediatype` attribute on XForms `<xf:bind>`~~ — not currently emitted

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use the `FileEnvelope` blueprint (`core/file_envelope.py`) for `VoiceAnswerEnvelope`:
  `BaseModel`, `ConfigDict(extra="forbid")`, `Field(default=None)` for optional fields.
- All new fields on `FormField` MUST have defaults (`None`) — existing form documents
  that omit these fields must deserialize without error (backward-compatible).
- `model_config = ConfigDict(extra="forbid")` on `FormField` (line 104) means any new
  field MUST be declared explicitly in the class body — Pydantic will not ignore it.
- Do NOT eagerly parse `"application/json"` / `"text/yaml"` submissions in
  `_coerce_value()` — leave parsing to the consumer (resolved Q1).
- MIME-type mismatch enforcement is **advisory-only in v1** — no validation errors for
  type mismatches (resolved Q3).
- Emit `x-content-type` / `x-accept-content-types` in the JSON Schema renderer using
  the same conditional guard pattern as existing `x-relation`, `x-depends-on`,
  `x-post-depends` (see `renderers/jsonschema.py:554-668`).
- `FormField.model_rebuild()` call at line 172 — new fields are `str | None` and
  `list[str] | None`, both fully concrete — no forward-ref issue.

### Known Risks / Gotchas

- **Downstream sinks**: `FormSubmission.data` values for fields that declare
  `"application/json"` acceptance will be `dict` (not `str`). Downstream sinks
  (CSV, Google Sheets, Postgres) may not handle raw dicts gracefully — this is a
  known follow-up, not a blocker for v1.
- **XForms `mediatype` attr**: XForms 1.1 spec defines `mediatype` on `<xf:upload>`
  elements, not on `<xf:bind>`. Using it on a bind element is a parrot-specific
  extension — document clearly in the renderer docstring.
- **Backward compatibility**: `content_type=None` and `accept_content_types=None`
  replicate today's behavior exactly. Consumer code should guard with
  `isinstance(value, dict)` for fields that declare `"application/json"` acceptance —
  the same pattern already used for `FileEnvelope` fields.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Already a core dependency — `BaseModel`, `ConfigDict` |
| `lxml` | any | Already a dep of XFormsRenderer — `etree.Element` |

---

## 8. Open Questions

- [x] Should the validator actively parse `"application/json"` / `"text/yaml"` submissions
  in `_coerce_value()`, or only annotate and leave parsing to the consumer? —
  *Resolved in proposal*: leave the parsing to the consumer. Eager parsing is a type
  change for `FormSubmission.data[field_id]` and belongs to consumers.

- [x] Should `VoiceAnswerEnvelope` live in `core/voice_answer.py` or in the audio
  renderer package? — *Resolved in proposal*: in `core/voice_answer.py`; the audio
  renderer only consumes from there.

- [x] For `accept_content_types`, should the validator enforce MIME-type match
  (rejecting mismatches), or advisory-only? — *Resolved in proposal*: advisory-only
  in v1; hard enforcement is a follow-up for build validators.

- [x] Which renderers emit `content_type`/`accept_content_types` in v1 — JSON Schema
  only, or all three? — *Resolved in proposal*: all three existing renderers; JSON
  Schema renderer is prioritary (first to ship).

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all 8 modules run sequentially in one worktree.
- **Rationale**: Modules 3-7 all depend on Module 2 (`FormField` changes), and
  Module 8 depends on all others. The dependency chain is linear; no task is
  independent enough to benefit from a parallel worktree.
- **Cross-feature dependencies**: none. `FileEnvelope` (FEAT-460) is already merged
  and used only as a blueprint reference.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | jesuslarag@gmail.com | Initial spec from proposal |
