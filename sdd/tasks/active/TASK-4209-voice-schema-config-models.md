# TASK-4209: Voice & LLM-validation config models + FormField/FormSchema typed attributes

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Root task of FEAT-649 (spec §3 Module 1, §2 Data Models). Every other module consumes
the typed configuration blocks the owner decided: per-field `hint` and `llm_validation`,
per-form `voice` and `llm_validation` blocks, the `FieldVoiceMeta` parser for
`FormField.meta["voice"]`, and the single sensitivity policy `is_sensitive()` (S8).
The `VoiceEvidenceEnvelope` part of Module 1 is a separate task (TASK-4210).

---

## Scope

- Create `core/voice.py` with `HandsFreeConfig`, `UiCue`, `FieldVoiceMeta`, `VoiceFormConfig`,
  `is_sensitive()`, `field_voice_meta()`, `resolve_voice_config()`.
- Create `core/llm_validation.py` with `LLMValidationConfig`, `PlausibilityVerdict`,
  `PlausibilityReport`, `llm_validation_enabled()`.
- Add `hint: LocalizedString | None` and `llm_validation: bool | None` to `FormField`.
- Add `voice: VoiceFormConfig | None` and `llm_validation: LLMValidationConfig | None` to `FormSchema`.
- Export the new public symbols from `core/__init__.py`.
- Write unit tests `test_schema_hint_and_llm_validation_fields` and the M1 part of
  `test_sensitive_policy_everywhere`.

**NOT in scope**: `VoiceEvidenceEnvelope` and `is_voice_envelope/unwrap_voice/wrap_voice`
(TASK-4210); audio model deltas and `Phase` (TASK-4211); renderers reading `hint`
(TASK-4231/TASK-4232); YAML extractor / toolkit round-trip (TASK-4233); the plausibility
checker itself (TASK-4220).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` | CREATE | Voice config models + `is_sensitive`, `field_voice_meta`, `resolve_voice_config` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | CREATE | `LLMValidationConfig`, `PlausibilityVerdict`, `PlausibilityReport`, `llm_validation_enabled` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `FormField.hint`, `FormField.llm_validation`, `FormSchema.voice`, `FormSchema.llm_validation` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export new symbols |
| `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# inside core/voice.py and core/llm_validation.py (relative, same package)
from .types import FieldType, LocalizedString          # verified: core/types.py:13 (LocalizedString), :16 (FieldType)
from pydantic import BaseModel, ConfigDict, Field      # used by every core module (e.g. core/schema.py:17)

# TYPE_CHECKING only (core must never import audio/ or schema at runtime from these modules)
from .schema import FormField, FormSchema              # verified: core/schema.py:65 (FormField), :401 (FormSchema)
from ..audio.models import AudioSessionConfig          # verified: audio/models.py:38

# inside core/schema.py (new runtime imports, added next to the existing `from .types import ...` at :25)
from .llm_validation import LLMValidationConfig
from .voice import VoiceFormConfig

# tests
from parrot_formdesigner.core import FormField, FormSchema, FieldType   # verified: core/__init__.py:30-52
```

### Existing Signatures to Use
```python
# core/types.py
LocalizedString = str | dict[str, str]                                  # line 13
class FieldType(str, Enum):                                             # line 16
    PASSWORD = "password"; HIDDEN = "hidden"; FILE = "file"; IMAGE = "image"; SIGNATURE = "signature"   # :35, :36, :29, :30, :40
    CREDIT_CARD = "credit_card"; IMAGE_DROPZONE = "image_dropzone"     # :64, :65

# core/schema.py
class FormField(BaseModel):                                             # line 65
    model_config = ConfigDict(extra="forbid")                           # line 121
    field_id: str; field_type: FieldType                                # :124-125
    label: LocalizedString; description: LocalizedString | None         # :126-127
    read_only: bool = False                                             # :131
    meta: dict[str, Any] | None = None                                  # :140
    answer_envelope: Literal["voice"] | None = None                     # :143  <- anchor
class FormSchema(BaseModel):                                            # line 401 — NO model_config (extra ignored)
    persistence: FormPersistenceConfig | None = None                    # :473
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP      # :475  <- anchor

# audio/models.py
class AudioSessionConfig(BaseModel):                                    # line 38 ; extra="forbid"
    tts_backend: Literal["supertonic", "google"]; tts_voice: Optional[str]
    enumerate_options: bool = True                                      # :67
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)   # :69

# renderers/audio.py — sensitivity today is PASSWORD only
sensitive = field.field_type == FieldType.PASSWORD                      # :361 (reference; not modified here)
```

### Does NOT Exist
- ~~`FormField.hint`~~, ~~`FormField.llm_validation`~~, ~~`FormField.sensitive`~~, ~~`FormField.audio_hint`~~ — `hint`/`llm_validation` are created by this task; `sensitive` is never a field attribute (policy is `is_sensitive()`).
- ~~`FormSchema.voice`~~, ~~`FormSchema.llm_validation`~~, ~~`FormSchema.model_config`~~ — none declared before this task; do NOT add a `model_config` to `FormSchema`.
- ~~`core/voice.py`~~, ~~`core/llm_validation.py`~~ — created by this task.
- ~~`ValidationResult.plausibility`~~ — never add plausibility to the validator result.
- ~~`FieldType.CHECKBOX`~~, ~~`FieldType.RADIO`~~ — not members; use the real names above.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py#FieldType",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No import cycle**: `core/schema.py` imports `core/voice.py` and `core/llm_validation.py` at runtime; those two modules must import only `.types` and pydantic at runtime — `FormField`, `FormSchema`, `AudioSessionConfig` go under `TYPE_CHECKING` with `from __future__ import annotations`.
- `FormField` is `extra="forbid"`: adding fields with defaults keeps every existing construction valid; JSON with `hint` must now parse.
- `FormSchema` tolerates unknown keys; the new blocks are optional (`None` default) so old readers are unaffected.
- `FieldVoiceMeta` uses `extra="ignore"`; the "one warning" for unknown keys is emitted by `field_voice_meta()`, not by the model.
- `is_sensitive()` is the single policy (S8) used later by narration, review, plausibility, logs and `form_complete`.
- Logging: `logging.getLogger(__name__)`; Google-style docstrings; strict type hints.

### References in Codebase
- `core/voice_answer.py` — style of a small core model module.
- `core/persistence.py` — another typed optional block on `FormSchema`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `core/llm_validation.py` — *why*: it has no dependency on `core/voice.py` and is imported by `core/schema.py`.
2. Create `core/voice.py` — *why*: `FormSchema.voice` needs `VoiceFormConfig` at class-definition time.
3. Add the two runtime imports and the four attributes to `core/schema.py` — *why*: owner decision "typed blocks", spec §2.
4. Export the new names from `core/__init__.py` — *why*: downstream tasks import from `parrot_formdesigner.core`.
5. Write the tests, then run the Validation Commands plus the existing core model tests — *why*: `FormField` is used everywhere; regressions surface in `test_core_models.py`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (CREATE)
```python
"""LLM-assisted answer plausibility configuration and report models (FEAT-649).

Declares the typed ``FormSchema.llm_validation`` block, the per-answer verdict
and the report returned by ``AnswerPlausibilityChecker`` (services/plausibility.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from .types import FieldType

if TYPE_CHECKING:
    from .schema import FormField, FormSchema

_DEFAULT_EXCLUDED: tuple[FieldType, ...] = (
    FieldType.PASSWORD,
    FieldType.HIDDEN,
    FieldType.FILE,
    FieldType.IMAGE_DROPZONE,
    FieldType.CREDIT_CARD,
    FieldType.SIGNATURE,
)


class LLMValidationConfig(BaseModel):
    """Per-form LLM plausibility settings (``FormSchema.llm_validation``)."""

    enabled: bool = False
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    on_error: Literal["skip", "block"] = "skip"
    model: str | None = None
    timeout_s: float = Field(default=8.0, gt=0.0)
    max_fields: int = Field(default=50, ge=1)
    exclude_field_types: list[FieldType] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDED))


class PlausibilityVerdict(BaseModel):
    """LLM judgement for one (question, answer) pair."""

    plausible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> float:
        """Clamp out-of-range confidences into [0, 1] instead of rejecting them."""
        # FILL IN: coerce to float and clamp to [0.0, 1.0]; non-numeric → raise ValueError — bounded by spec §2 "clamped on parse"
        raise NotImplementedError


class PlausibilityReport(BaseModel):
    """Outcome of one plausibility batch."""

    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)


def llm_validation_enabled(form: FormSchema, field: FormField) -> bool:
    """Return whether ``field`` takes part in plausibility checking.

    ``field.llm_validation`` wins when not ``None``; otherwise inherit
    ``form.llm_validation.enabled`` (``False`` when the block is absent).
    """
    if field.llm_validation is not None:
        return field.llm_validation
    return bool(form.llm_validation and form.llm_validation.enabled)
```
**Why this shape**: field names, types and defaults are fixed by spec §2 Data Models. The default exclusion list is a factory so instances never share a mutable list.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` (CREATE)
```python
"""Voice-mode configuration models and helpers (FEAT-649)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .types import FieldType

if TYPE_CHECKING:
    from ..audio.models import AudioSessionConfig
    from .schema import FormField, FormSchema

_logger = logging.getLogger(__name__)


class HandsFreeConfig(BaseModel):
    """Client hands-free behaviour: auto-open mic after TTS, end-of-speech silence."""

    auto_record: bool = True
    silence_ms: int = Field(default=1200, ge=0)


class UiCue(BaseModel):
    """Visual cue telling the client which control to focus/highlight."""

    control: str
    focus: bool = True
    highlight: bool = True
    submit_via: Literal["voice", "control", "both"] = "both"


class FieldVoiceMeta(BaseModel):
    """Per-field voice settings parsed from ``FormField.meta["voice"]``."""

    model_config = ConfigDict(extra="ignore")

    prompt: str | None = None
    enumerate: Literal["auto", "always", "never", "count_only"] = "auto"
    confirm: Literal["auto", "always", "never"] = "auto"
    pause_ms: int | None = None
    ui_cue: UiCue | None = None
    match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    skip_in_review: bool = False
    commands: Literal["on", "off"] = "on"
    sensitive: bool = False


class VoiceFormConfig(BaseModel):
    """Per-form voice settings (``FormSchema.voice``)."""

    enabled: bool = True
    max_questions: int | None = Field(default=10, ge=1)
    hint_pause_ms: int = Field(default=600, ge=0)
    enumerate_options: bool = True
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    option_match_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    review: Literal["always", "never", "ask"] = "always"
    review_playback: Literal["tts", "recording", "both"] = "tts"
    store_recordings: bool = True
    resume_ttl_seconds: int = Field(default=3600, ge=1)
    llm_refine_options: bool = False
    commands: Literal["on", "off"] = "on"
    hands_free: HandsFreeConfig = Field(default_factory=HandsFreeConfig)
    tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: str | None = None
    max_recording_seconds: int = Field(default=60, ge=1)
```
**Why this shape**: verbatim from spec §2 Data Models; `max_questions=None` means unlimited (required fields are always kept — enforced by the planner, TASK-4217).

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice.py` (CREATE — continued, helper functions)
```python
def is_sensitive(field: FormField) -> bool:
    """Single sensitivity policy (S8).

    True when the field is a PASSWORD or ``meta["voice"]["sensitive"]`` is True.
    Used by narration, review, plausibility eligibility, logging and form_complete.
    """
    if field.field_type == FieldType.PASSWORD:
        return True
    voice = (field.meta or {}).get("voice")
    return isinstance(voice, dict) and voice.get("sensitive") is True


def field_voice_meta(field: FormField, *, logger: logging.Logger | None = None) -> FieldVoiceMeta:
    """Parse ``field.meta["voice"]`` into a ``FieldVoiceMeta``.

    Unknown keys are ignored with ONE warning per call; an absent or invalid
    block yields defaults (invalid also logs a warning). Never raises.
    """
    log = logger or _logger
    raw: Any = (field.meta or {}).get("voice")
    if not isinstance(raw, dict):
        return FieldVoiceMeta()
    unknown = sorted(set(raw) - set(FieldVoiceMeta.model_fields))
    if unknown:
        log.warning("field %s: ignoring unknown meta.voice keys %s", field.field_id, unknown)
    try:
        return FieldVoiceMeta.model_validate(raw)
    except ValidationError as exc:
        log.warning("field %s: invalid meta.voice (%s); using defaults", field.field_id, exc)
        return FieldVoiceMeta()


def resolve_voice_config(form: FormSchema, session: AudioSessionConfig | None) -> VoiceFormConfig:
    """Return the effective voice config for a session.

    Starts from ``form.voice`` (or defaults). A session config may only TIGHTEN
    it: thresholds may go up, caps may go down, features may be switched off —
    never the reverse.
    """
    base = form.voice or VoiceFormConfig()
    if session is None:
        return base
    # FILL IN: build the overrides dict — stt_confirm_threshold = max(base, session); enumerate_options = base AND session;
    #          tts_backend / tts_voice taken from the session only when it sets them — bounded by spec §3 M1 "session may only tighten"
    overrides: dict[str, Any] = {}
    return base.model_copy(update=overrides)
```
**Why**: `is_sensitive` and `field_voice_meta` are complete because the spec fixes their rules; only the tightening merge is a judgement call. `meta["voice_mode"]` (FEAT-236) is a different key and stays untouched.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from .types import FieldType, LocalizedString' core/schema.py)
# AFTER — insert below `from .types import FieldType, LocalizedString` (verified: core/schema.py:25)
from .llm_validation import LLMValidationConfig
from .voice import VoiceFormConfig
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY — FormField)
```python
# occurrences: 1 (verified: grep -c '    answer_envelope: Literal["voice"] | None = None' core/schema.py)
# AFTER — insert below `    answer_envelope: Literal["voice"] | None = None` (verified: core/schema.py:143)
    # FEAT-649 — voice hint narrated after the pause; shown as help text by renderers.
    hint: LocalizedString | None = None
    # FEAT-649 — LLM plausibility opt-in; None inherits FormSchema.llm_validation.enabled.
    llm_validation: bool | None = None
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` (MODIFY — FormSchema)
```python
# occurrences: 1 (verified: grep -c '    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP' core/schema.py)
# AFTER — insert below `    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP` (verified: core/schema.py:475)
    # FEAT-649 — typed voice-mode block (owner decision: typed, not meta).
    voice: VoiceFormConfig | None = None
    # FEAT-649 — LLM-assisted answer plausibility (all channels).
    llm_validation: LLMValidationConfig | None = None
```
**Why**: also add `hint` and `llm_validation` entries to the `FormField` docstring "Attributes" list and `voice` / `llm_validation` to the `FormSchema` docstring — the file documents every attribute.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .voice_answer import VoiceAnswerEnvelope' core/__init__.py)
# AFTER — insert below `from .voice_answer import VoiceAnswerEnvelope` (verified: core/__init__.py:53)
from .llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,
)
from .voice import (
    FieldVoiceMeta,
    HandsFreeConfig,
    UiCue,
    VoiceFormConfig,
    field_voice_meta,
    is_sensitive,
    resolve_voice_config,
)
# and append to __all__ (after the "VoiceAnswerEnvelope" entry, :60):
#   # Voice mode + LLM plausibility (FEAT-649)
#   "HandsFreeConfig", "UiCue", "FieldVoiceMeta", "VoiceFormConfig", "is_sensitive", "field_voice_meta",
#   "resolve_voice_config", "LLMValidationConfig", "PlausibilityVerdict", "PlausibilityReport", "llm_validation_enabled",
```

### `packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py` (CREATE)
See Test Specification below — write it verbatim, then complete the `FILL IN` bodies.

### FILL IN checklist
- [ ] `core/llm_validation.py::PlausibilityVerdict._clamp` — float coercion + clamp; bounded by spec §2 "clamped on parse"
- [ ] `core/voice.py::resolve_voice_config` — tightening merge; bounded by spec §3 M1 "session may only tighten"
- [ ] `core/__init__.py` — `__all__` entries for the 11 new names
- [ ] test bodies marked `FILL IN`

---

## Acceptance Criteria

- [ ] `FormField(..., hint={"en": "..", "es": ".."}, llm_validation=True)` validates and round-trips through `model_dump()`/`model_validate()`.
- [ ] `FormSchema` accepts `voice` and `llm_validation` typed blocks; omitted blocks are `None`.
- [ ] `field_voice_meta()` ignores unknown keys with exactly one warning and returns defaults for absent/invalid blocks.
- [ ] `is_sensitive()` is True for PASSWORD and for `meta.voice.sensitive: true`, False otherwise.
- [ ] `llm_validation_enabled()` follows field → form inheritance (spec AC10).
- [ ] `PlausibilityVerdict(confidence=1.7)` yields `1.0`; `-0.2` yields `0.0`.
- [ ] Importing `parrot_formdesigner.core` does not import `parrot_formdesigner.audio` (no cycle).
- [ ] Existing tests `packages/parrot-formdesigner/tests/unit/test_core_models.py` still pass.
- [ ] `ruff check` passes on every touched file.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_core_models.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_voice_schema_models.py
import logging
import sys

import pytest

from parrot_formdesigner.core import (
    FieldType,
    FieldVoiceMeta,
    FormField,
    FormSchema,
    LLMValidationConfig,
    PlausibilityVerdict,
    VoiceFormConfig,
    field_voice_meta,
    is_sensitive,
    llm_validation_enabled,
)


def _form(**kwargs) -> FormSchema:
    return FormSchema(form_id="f", title="F", sections=[], **kwargs)


class TestSchemaHintAndLLMValidationFields:
    def test_field_hint_roundtrip(self):
        f = FormField(field_id="a", field_type=FieldType.TEXT, label="A", hint={"en": "Say it", "es": "Dilo"}, llm_validation=True)
        again = FormField.model_validate(f.model_dump())
        assert again.hint == {"en": "Say it", "es": "Dilo"}
        assert again.llm_validation is True

    def test_form_typed_blocks(self):
        form = _form(voice={"max_questions": 3}, llm_validation={"enabled": True})
        assert isinstance(form.voice, VoiceFormConfig) and form.voice.max_questions == 3
        assert isinstance(form.llm_validation, LLMValidationConfig) and form.llm_validation.on_error == "skip"
        assert _form().voice is None and _form().llm_validation is None

    def test_meta_voice_unknown_keys_one_warning(self, caplog):
        f = FormField(field_id="a", field_type=FieldType.TEXT, label="A", meta={"voice": {"pause_ms": 300, "bogus": 1, "x": 2}})
        with caplog.at_level(logging.WARNING):
            meta = field_voice_meta(f)
        assert isinstance(meta, FieldVoiceMeta) and meta.pause_ms == 300
        assert len([r for r in caplog.records if "unknown meta.voice" in r.getMessage()]) == 1

    def test_meta_voice_absent_or_invalid_defaults(self):
        # FILL IN: no meta → defaults; meta.voice = {"enumerate": "loud"} → defaults (+ warning)
        ...

    def test_llm_validation_inheritance(self):
        # FILL IN: field None + form enabled → True; field False + form enabled → False; no form block → False
        ...

    def test_verdict_confidence_clamped(self):
        assert PlausibilityVerdict(plausible=True, confidence=1.7, reason="r").confidence == 1.0
        assert PlausibilityVerdict(plausible=False, confidence=-0.2, reason="r").confidence == 0.0


class TestSensitivePolicy:
    def test_password_and_meta_flag(self):
        assert is_sensitive(FormField(field_id="p", field_type=FieldType.PASSWORD, label="P"))
        assert is_sensitive(FormField(field_id="s", field_type=FieldType.TEXT, label="S", meta={"voice": {"sensitive": True}}))
        assert not is_sensitive(FormField(field_id="t", field_type=FieldType.TEXT, label="T"))


def test_core_does_not_import_audio():
    # FILL IN: in a subprocess (python -c), import parrot_formdesigner.core and assert
    #          "parrot_formdesigner.audio" not in sys.modules
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/audio-form-interaction-workflow.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/audio-form-interaction-workflow.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
   (with `PYTHONPATH=packages/parrot-formdesigner/src` inside the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4209 audio-form-interaction-workflow verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
