---
type: feature
base_branch: dev
---

# Feature Specification: FormField Content-Type

**Feature ID**: FEAT-488
**Date**: 2026-09-01
**Author**: jesuslarag@gmail.com
**Status**: draft
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

Field values in `FormSubmission.data` carry no declared content type, so
renderers and consumers must guess encoding from `FieldType` alone — which is
ambiguous. A `TEXT_AREA` could hold Markdown, YAML, or plain prose; the
consumer has no way to know without external convention. Additionally, there is
no way for a `TEXT_AREA` to carry both a transcribed text answer AND a voice
note reference in a single structured payload without introducing a new
`FieldType`.

The gap is two-part:
1. **Schema-side**: `FormField` has no `content_type` declaration, so
   consumers must guess encoding from `FieldType`.
2. **Voice note case**: `TEXT_AREA` cannot carry a dual payload (transcription
   + audio blob reference) without proliferating `FieldType` values.

### Goals

- Declare the primary MIME type of a field's expected answer on the schema
  (`content_type: str | None = None`), making the contract explicit and
  backward-compatible (default `None`).
- Support multi-type acceptance per field (`accept_content_types: list[str] |
  None = None`) to enable the audio-renderer voice-note scenario without new
  `FieldType` values.
- Define `VoiceAnswerEnvelope` as the concrete JSON shape for voice note
  submissions, following the `FileEnvelope` pattern (FEAT-460).
- Propagate `content_type` / `accept_content_types` through all three existing
  renderers: JSON Schema (priority), audio, and XForms.
- Leave parsing and MIME-type enforcement to the consumer (advisory-only in v1).

### Non-Goals (explicitly out of scope)

- `FileEnvelope` and the `UPLOAD_FIELD_TYPES` blob pipeline (FILE, IMAGE,
  IMAGE_DROPZONE, MULTI_UPLOAD) — they already have their own content-type
  negotiation inside `FileEnvelope.content_type`.
- `FieldType` enum changes — `content_type` is orthogonal to `field_type`.
- `FormSubmission.data` outer shape — the key remains `field_id`.
- Server-side audio recording/storage pipeline — `VoiceAnswerEnvelope.blob_ref`
  is pre-populated by the audio renderer; storage remains its responsibility.
- Hard MIME-type validation at submission time — advisory-only in v1; hard
  enforcement is a follow-up for build validators. *(Runtime fallback-on-failure
  was explicitly deferred — see proposals/formfield-content-type.proposal.md.)*
- Eager JSON/YAML parsing inside `_coerce_value()` — parsing responsibility
  belongs to the consumer. *(Resolved in brainstorm.)*

---

## 2. Architectural Design

### Overview

Two new optional fields are added to `FormField`:
- `content_type: str | None = None` — declares the primary MIME type of the
  expected answer (e.g. `"text/markdown"`, `"text/yaml"`, `"application/json"`).
  `None` means "inferred from `FieldType`" — backward-compatible default.
- `accept_content_types: list[str] | None = None` — declares additional MIME
  types the field can accept (order-significant; first entry is preferred).
  `None` means single-type acceptance inferred from `content_type`/`FieldType`.

A new `VoiceAnswerEnvelope` model is introduced in `core/voice_answer.py` —
the canonical JSON shape for fields answered with a voice note (transcription +
optional audio blob reference). This follows the `FileEnvelope` pattern
(FEAT-460): a typed envelope that coexists with the field's base `FieldType`.

`_coerce_value()` in `FormValidator` receives a single behavioural change: when
`field.accept_content_types` is set and the submitted value is a `dict`, pass
it through unchanged instead of coercing to `str`. No eager Pydantic
deserialization into `VoiceAnswerEnvelope` — the consumer is responsible.

All three renderers surface the new fields as x-extension keys / bind
attributes so downstream consumers can read the declared MIME type without
inspecting `FormField` directly.

### Component Diagram

```
FormField (core/schema.py)
  ├── content_type: str | None
  └── accept_content_types: list[str] | None

VoiceAnswerEnvelope (core/voice_answer.py)    ← new, modeled on FileEnvelope
  ├── answer: str
  ├── blob_ref: str | None
  └── data_url: str | None

FormValidator._coerce_value() (services/validators.py)
  └── dict pass-through when accept_content_types set + value is dict

Renderers
  ├── jsonschema.py  → x-content-type / x-accept-content-types in property dict (priority)
  ├── audio.py       → reads accept_content_types to choose submission shape
  └── xforms.py     → emits content_type / accept_content_types in <xf:bind>

tools/field_helpers.py
  └── _FIELD_SCHEMA_SNIPPETS[text_area] gains content_type example
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormField` (`core/schema.py`) | extends | Two new optional fields, both `None`-defaulted |
| `FileEnvelope` (`core/file_envelope.py`) | blueprint | `VoiceAnswerEnvelope` follows the same pattern |
| `FormValidator._coerce_value()` (`services/validators.py`) | modifies | Dict pass-through for `accept_content_types` |
| `JsonSchemaRenderer._field_to_property()` (`renderers/jsonschema.py`) | modifies | Emit `x-content-type`, `x-accept-content-types` |
| `AudioFormRenderer` (`renderers/audio.py`) | modifies | Read `accept_content_types` to determine submission shape |
| `XFormsRenderer` (`renderers/xforms.py`) | modifies | Emit metadata in `<xf:bind>` when field declares content type |
| `_FIELD_SCHEMA_SNIPPETS` (`tools/field_helpers.py`) | modifies | Add `content_type` example to `TEXT_AREA` snippet |

### Data Models

```python
# core/voice_answer.py (new)
class VoiceAnswerEnvelope(BaseModel):
    """Dual payload submitted when a voice note drives a TEXT_AREA field.

    Attributes:
        answer: Transcription / text answer.
        blob_ref: Server-side voice note reference (pre-populated by audio renderer).
        data_url: Inline base64 audio for small notes only.
    """
    model_config = ConfigDict(extra="forbid")

    answer: str
    blob_ref: str | None = None
    data_url: str | None = None


# core/schema.py — extended FormField (new fields only)
class FormField(BaseModel):
    ...
    content_type: str | None = None          # "text/markdown", "text/yaml", etc.
    accept_content_types: list[str] | None = None   # e.g. ["text/plain", "application/json"]
```

### New Public Interfaces

```python
# core/voice_answer.py
class VoiceAnswerEnvelope(BaseModel):
    answer: str
    blob_ref: str | None = None
    data_url: str | None = None
```

---

## 3. Module Breakdown

### Module 1: FormField Schema Extension
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: Add `content_type: str | None = None` and
  `accept_content_types: list[str] | None = None` to `FormField` after the
  existing `meta` field (line 123). Both fields must be explicitly declared
  (because `model_config = ConfigDict(extra="forbid")` at line 104).
  Update the class docstring to document the two new attributes.
- **Depends on**: nothing (first task)

### Module 2: VoiceAnswerEnvelope Model
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` (new file)
- **Responsibility**: Define `VoiceAnswerEnvelope` as a Pydantic `BaseModel`
  with `model_config = ConfigDict(extra="forbid")`, following the exact pattern
  of `FileEnvelope` (`core/file_envelope.py`). Export it from
  `parrot_formdesigner.core` (`core/__init__.py`).
- **Depends on**: Module 1 (uses `FormField` imports from core)

### Module 3: Validator Dict Pass-Through
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`
- **Responsibility**: In `_coerce_value()` (line 498), add a guard before the
  existing `ft in (FieldType.TEXT, FieldType.TEXT_AREA, ...)` branch: when
  `field.accept_content_types` is set (not `None`) and `isinstance(value, dict)`,
  return `value` unchanged. This is the only validator change; no eager
  deserialization into `VoiceAnswerEnvelope`.
- **Depends on**: Module 1

### Module 4: JSON Schema Renderer — Content-Type Extension
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`
- **Responsibility**: In `_field_to_property()` (line 472), after the existing
  `x-field-type` entry (line 493), emit `x-content-type` when `field.content_type`
  is set, and `x-accept-content-types` when `field.accept_content_types` is set.
  These follow the existing `x-` extension convention for the renderer.
- **Depends on**: Module 1

### Module 5: Audio Renderer — Submission Shape Detection
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`
- **Responsibility**: In the `AudioFormRenderer`, when building an `AudioQuestion`
  for a field, read `field.accept_content_types`. If `"application/json"` is in
  the list, annotate the question to signal that the submission may be a
  `VoiceAnswerEnvelope` dict. Import `VoiceAnswerEnvelope` from
  `parrot_formdesigner.core.voice_answer`.
- **Depends on**: Module 1, Module 2

### Module 6: XForms Renderer — Bind Metadata
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py`
- **Responsibility**: For fields that declare `content_type` or
  `accept_content_types`, emit these as attributes on the `<xf:bind>` element
  (using a custom `x-content-type` / `x-accept-content-types` namespace or as
  plain string attributes). Follow the existing `_FIELD_TO_XFORMS` mapping
  pattern for all in-scope field types.
- **Depends on**: Module 1

### Module 7: Field Helpers — TEXT_AREA Snippet Update
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`
- **Responsibility**: Update the `_FIELD_SCHEMA_SNIPPETS[FieldType.TEXT_AREA.value]`
  dict (currently lines 22-26, just `field_id`, `field_type`, `label`) to add a
  `content_type: "text/markdown"` example key documenting the new field.
- **Depends on**: Module 1

### Module 8: Tests
- **Path**: `packages/parrot-formdesigner/tests/unit/`
- **Responsibility**: Add unit tests covering:
  - `FormField` round-trips with `content_type` and `accept_content_types`
    (including `None` defaults for backward-compatibility).
  - `_coerce_value()`: dict is passed through unchanged when
    `accept_content_types` includes `"application/json"` and value is `dict`.
  - `_coerce_value()`: existing TEXT_AREA string path is not broken.
  - `VoiceAnswerEnvelope` round-trip (serialization/deserialization).
  - JSON Schema renderer emits `x-content-type` / `x-accept-content-types`
    when set; omits them when `None`.
  - Audio renderer propagates `accept_content_types` context.
  - XForms renderer emits bind attributes when content type is set.
- **Depends on**: Modules 1–7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_formfield_content_type_defaults` | Module 1 | `FormField` with no `content_type`/`accept_content_types` round-trips cleanly (backward compat) |
| `test_formfield_content_type_set` | Module 1 | `FormField` with `content_type="text/markdown"` serializes and deserializes correctly |
| `test_formfield_accept_content_types` | Module 1 | `FormField` with `accept_content_types=["text/plain","application/json"]` serializes correctly |
| `test_voice_answer_envelope_roundtrip` | Module 2 | `VoiceAnswerEnvelope` round-trips with all fields; `extra="forbid"` rejects unknown keys |
| `test_coerce_value_dict_passthrough` | Module 3 | When `accept_content_types=["application/json"]` and value is `dict`, `_coerce_value()` returns dict unchanged |
| `test_coerce_value_text_area_unchanged` | Module 3 | Existing `TEXT_AREA` string coercion is unaffected when `accept_content_types=None` |
| `test_jsonschema_emits_content_type` | Module 4 | `JsonSchemaRenderer` property dict contains `x-content-type` when field declares it |
| `test_jsonschema_omits_content_type_when_none` | Module 4 | Property dict has no `x-content-type` when field `content_type=None` |
| `test_jsonschema_emits_accept_content_types` | Module 4 | Property dict contains `x-accept-content-types` list when field declares it |
| `test_audio_renderer_accept_content_types` | Module 5 | `AudioFormRenderer` propagates `accept_content_types` for fields that declare it |
| `test_xforms_bind_content_type` | Module 6 | `XFormsRenderer` emits content-type attributes on `<xf:bind>` when field declares it |
| `test_field_helpers_text_area_snippet` | Module 7 | `_FIELD_SCHEMA_SNIPPETS["text_area"]` contains `content_type` key |

### Integration Tests

| Test | Description |
|---|---|
| `test_voice_answer_submission_passthrough` | End-to-end: `FormSchema` with `TEXT_AREA + accept_content_types`, validator accepts `VoiceAnswerEnvelope` dict payload without coercing |
| `test_backward_compatible_schema_deserialization` | Existing stored `FormSchema` JSON with no `content_type` deserializes without error |

### Test Data / Fixtures

```python
@pytest.fixture
def text_area_with_markdown():
    return FormField(
        field_id="notes",
        field_type=FieldType.TEXT_AREA,
        label="Notes",
        content_type="text/markdown",
    )

@pytest.fixture
def text_area_with_voice():
    return FormField(
        field_id="answer",
        field_type=FieldType.TEXT_AREA,
        label="Your answer",
        accept_content_types=["text/plain", "application/json"],
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `FormField` accepts `content_type: str | None = None` and
  `accept_content_types: list[str] | None = None`; both default to `None`
  (backward-compatible).
- [ ] `VoiceAnswerEnvelope` model exists in
  `parrot_formdesigner/core/voice_answer.py` with `answer`, `blob_ref`,
  `data_url` fields and `extra="forbid"`.
- [ ] `_coerce_value()` passes `dict` values through unchanged when
  `field.accept_content_types` is not `None` (no eager coercion to str).
- [ ] `JsonSchemaRenderer` emits `x-content-type` and `x-accept-content-types`
  in the property dict when the corresponding `FormField` attributes are set.
- [ ] `AudioFormRenderer` reads `accept_content_types` from `FormField` and
  propagates the information into the `AudioQuestion` output.
- [ ] `XFormsRenderer` emits `content_type` / `accept_content_types` as
  attributes on `<xf:bind>` when the field declares them.
- [ ] `_FIELD_SCHEMA_SNIPPETS["text_area"]` contains a `content_type` example.
- [ ] All unit tests listed in §4 pass (`pytest packages/parrot-formdesigner/tests/unit/ -v`).
- [ ] All integration tests listed in §4 pass.
- [ ] Existing test suite passes without regressions (`pytest packages/parrot-formdesigner/ -v`).
- [ ] No breaking changes to existing `FormField` serialization / deserialization
  (verified by `test_backward_compatible_schema_deserialization`).
- [ ] MIME-type enforcement is advisory-only in v1 (no hard rejection on mismatch).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# core/schema.py — existing imports to keep
from pydantic import BaseModel, ConfigDict, Field, model_validator

# For new VoiceAnswerEnvelope (core/voice_answer.py)
from pydantic import BaseModel, ConfigDict

# audio renderer import of the new model
from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope

# validator imports (no change needed — FormField already imported)
from parrot_formdesigner.core.types import FieldType
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py

class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")           # line 104
    field_uid: uuid.UUID = Field(default_factory=uuid.uuid4)  # line 106
    field_id: str                                        # line 107
    field_type: FieldType                                # line 108
    label: LocalizedString                               # line 109
    description: LocalizedString | None = None           # line 110
    placeholder: LocalizedString | None = None           # line 111
    required: bool = False                               # line 112
    default: Any = None                                  # line 113
    read_only: bool = False                              # line 114
    constraints: FieldConstraints | None = None          # line 115
    options: list[FieldOption] | None = None             # line 116
    options_source: OptionsSource | None = None          # line 117
    depends_on: DependencyRule | None = None             # line 118
    post_depends: list[PostDependency] | None = None     # line 119
    children: list[FormField] | None = None              # line 120
    item_template: FormField | None = None               # line 121
    relation: RelationSpec | None = None                 # line 122
    meta: dict[str, Any] | None = None                  # line 123
    # ← new fields go here (after meta)
    # content_type: str | None = None
    # accept_content_types: list[str] | None = None


# packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py

class FileEnvelope(BaseModel):                           # line 16 — blueprint for VoiceAnswerEnvelope
    model_config = ConfigDict(extra="forbid")            # line 33
    filename: str = Field(..., ...)                      # line 35
    content_type: str = Field(..., ...)                  # line 36
    size: int = Field(..., ge=0, ...)                    # line 37
    blob_ref: str | None = Field(default=None, ...)      # line 38
    data_url: str | None = Field(default=None, ...)      # line 39
    thumbnail_url: str | None = Field(default=None, ...) # line 40
    checksum: str | None = Field(default=None, ...)      # line 41

UPLOAD_FIELD_TYPES: frozenset[FieldType] = frozenset({...})  # line 44


# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py

class FormValidator:
    def _coerce_value(self, value: Any, field: FormField) -> Any:  # line 498
        # TEXT/TEXT_AREA/... branch at line 516:
        # if ft in (FieldType.TEXT, FieldType.TEXT_AREA, ...):
        #     return str(value).strip()
        # New guard BEFORE this branch:
        # if field.accept_content_types is not None and isinstance(value, dict):
        #     return value


# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py

class JsonSchemaRenderer:
    def _field_to_property(self, field: FormField, ...) -> dict[str, Any]:  # line 472
        # Existing x- keys emitted: x-field-type (line 493),
        # x-depends-on, x-post-depends, x-options-source, x-placeholder,
        # x-read-only, x-section, x-subsection.
        # New: x-content-type, x-accept-content-types when field attributes set.


# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py

class AudioFormRenderer(AbstractFormRenderer):
    # Imports from ..audio.models: AudioFormManifest, AudioQuestion,
    #   AudioSessionConfig, VoiceMode
    # Imports from ..core.schema: FormField, FormSchema, RenderedForm
    # Add import: from ..core.voice_answer import VoiceAnswerEnvelope

class AudioQuestion:
    # Defined in packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
    # (not renderers/audio.py) — verify before adding fields


# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py

class XFormsRenderer(AbstractFormRenderer):
    # Uses _FIELD_TO_XFORMS dict for FieldType → XForms element mapping
    # XF_NS = "http://www.w3.org/2002/xforms" (line ~52)
    # New: emit x-content-type/x-accept-content-types on <xf:bind> element


# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py

_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {  # line 15
    FieldType.TEXT_AREA.value: {                         # line 22
        "field_id": "comments",
        "field_type": "text_area",
        "label": "Comments",
        # ← add: "content_type": "text/markdown"
    },
    ...
}
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormField.content_type` | `JsonSchemaRenderer._field_to_property()` | attribute read | `renderers/jsonschema.py:472` |
| `FormField.accept_content_types` | `FormValidator._coerce_value()` | attribute read | `services/validators.py:498` |
| `VoiceAnswerEnvelope` | `AudioFormRenderer` | import | `renderers/audio.py:~17` |
| `VoiceAnswerEnvelope` | `core/__init__.py` | re-export | `core/__init__.py` (verify exports) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.core.voice_answer`~~ — does **not** exist yet; this
  spec creates it.
- ~~`FormField.content_type`~~ — does **not** exist yet; this spec adds it.
- ~~`FormField.accept_content_types`~~ — does **not** exist yet.
- ~~`VoiceAnswerEnvelope`~~ — does **not** exist anywhere in the codebase yet.
- ~~`AudioQuestion.accept_content_types`~~ — verify `AudioQuestion` structure
  in `audio/models.py` before adding any field; do not assume it has one.
- ~~`FormValidator._coerce_content_type()`~~ — no such method; the only change
  is a guard inside `_coerce_value()`.
- ~~`FileEnvelope.accept_content_types`~~ — `FileEnvelope` does NOT have this
  field; it has a `content_type: str` (required, not optional).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `VoiceAnswerEnvelope` must mirror `FileEnvelope` exactly:
  `model_config = ConfigDict(extra="forbid")`, optional blob fields with
  `Field(default=None, description="...")`, Google-style docstring.
- `content_type` and `accept_content_types` on `FormField` must be placed
  **after** `meta` (line 123) to preserve the existing field ordering — this
  avoids any serialization-order surprises.
- JSON Schema x-extension key names follow the pattern already in use:
  `x-field-type`, `x-depends-on`, etc. Use `x-content-type` and
  `x-accept-content-types` (hyphenated, lowercase).
- XForms attribute names: use the `x-` prefix consistently with the JSON
  Schema renderer for predictable consumer convention.

### Known Risks / Gotchas

- `model_config = ConfigDict(extra="forbid")` on `FormField` means any typo
  in the new field names will produce a Pydantic validation error at import
  time — run `pytest` immediately after adding the fields to catch this early.
- `FormField.model_rebuild()` is called at module level (line 172). The new
  fields must be proper Pydantic field declarations (not just class attributes)
  or `model_rebuild()` will not include them.
- `_coerce_value()` guard must be inserted **before** the existing
  `TEXT`/`TEXT_AREA` branch (line 516), not after. Inserting after would
  mean `TEXT_AREA` already coerces `dict` to `str` before the guard fires.
- The XForms renderer uses `lxml`; attribute names with colons (namespaced)
  must use Clark notation (`{ns}local`) — plain string attributes are simpler
  and consistent with what the consumer needs; prefer plain string attributes
  unless a namespace is required.
- `accept_content_types` advisory-only: do NOT add any `ValidationError`-
  raising logic in v1 — the field is a hint only.
- `AudioQuestion` is defined in `audio/models.py`, not in `renderers/audio.py`.
  Read `audio/models.py` before adding any attribute to `AudioQuestion` to
  avoid collisions.

### External Dependencies

No new external packages required. All changes use existing Pydantic,
`lxml` (already a dependency of the XForms renderer), and stdlib only.

---

## 8. Open Questions

- [x] Should the validator actively parse `"application/json"` / `"text/yaml"`
  submissions in `_coerce_value()`, or only annotate and leave parsing to the
  consumer? — *Resolved in brainstorm*: leave the parsing to the consumer.
- [x] Should `VoiceAnswerEnvelope` live in `core/voice_answer.py` (formdesigner
  core) or in the audio renderer package (`audio/models.py`)? — *Resolved in
  brainstorm*: `core/voice_answer.py`; the audio renderer only consumes from there.
- [x] For `accept_content_types`, should the validator enforce MIME-type matching
  (hard reject on mismatch) or advisory-only? — *Resolved in brainstorm*:
  advisory-only in v1; hard enforcement is a follow-up for build validators.
- [x] Which renderers emit `content_type`/`accept_content_types` in v1? —
  *Resolved in brainstorm*: all existing renderers (JSON Schema prioritary, then
  audio, then XForms).

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks run sequentially in one worktree).
- **Rationale**: modules are tightly coupled — renderers and validator changes
  both depend on the `FormField` schema extension landing first; testing covers
  all modules together. Parallel worktrees would require cross-worktree merges
  before tests can run end-to-end.
- **Parallelizable tasks**: Modules 4, 5, and 6 (renderers) are independent of
  each other once Module 1 is committed; they can be worked in parallel if the
  sdd-worker is configured for multi-agent within-worktree execution. The default
  path is sequential.
- **Cross-feature dependencies**: none. FEAT-460 (`FileEnvelope`) is already
  merged to `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-01 | jesuslarag@gmail.com | Initial spec scaffolded from proposal (sdd-planner / FEAT-488) |
