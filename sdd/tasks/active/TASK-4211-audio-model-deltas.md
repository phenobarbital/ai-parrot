# TASK-4211: Audio model deltas: Phase, UiCue re-export, OptionMatch, NarrationPlan, ReviewItemData, AudioQuestion/AudioAnswer/AudioSessionState fields

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4209
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (model part) and §2 Data Models "audio/models.py (modify) — deltas".
The engine (TASK-4225/4226), narrator (TASK-4214), matcher (TASK-4215), commands (TASK-4216),
planner (TASK-4217), session store (TASK-4219) and audio renderer (TASK-4232) all consume
these types. Binding plan decision: **`Phase` and `ReviewItemData` live in `audio/models.py`**
(not `audio/events.py`) so `models.py` never imports `events.py` — `audio/events.py`
(TASK-4212) re-exports `Phase`.

---

## Scope

- Add `Phase(str, Enum)` with members `IDLE, PLANNING, ASKING, ACCEPTING, CONFIRMING, PLAUSIBILITY, REVIEW, REVIEW_EDITING, SUBMITTING, COMPLETE, ABORTED`.
- Re-export `UiCue` from `core/voice.py`; add `OptionMatch`, `NarrationPlan`, `ReviewItemData`.
- Add the `AudioQuestion` fields: `section_uid, section_title, subsection_title, hint, prompt, narration, ui_cue, answer_modes, voice_meta, llm_validation`.
- Change `AudioAnswer.value` to `Any` and add `blob_ref, audio_mime, audio_bytes_len, duration_ms, matched, stt_language, answered_at, version`.
- Add the `AudioSessionState` fields: `phase, cursor, history, plan, return_to_review, review_cursor, resolution, tenant, locale, submission_id, protocol_version, plausibility, flagged`.
- Export the new names from `audio/__init__.py`.
- Tests: new-field defaults, backwards compatibility of existing constructions.

**NOT in scope**: protocol event models (TASK-4212); populating the new `AudioQuestion` fields (TASK-4232);
any change to `api/audio_ws.py` (TASK-4227); `AudioSnapshot` (TASK-4219).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | New enum/models + field deltas |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/__init__.py` | MODIFY | Export new names |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# inside audio/models.py (new runtime imports)
from datetime import datetime
from typing import Any, Literal, Optional                                       # Literal, Optional verified at audio/models.py:13
from pydantic import BaseModel, ConfigDict, Field                               # verified: audio/models.py:15
from ..core.voice import FieldVoiceMeta, UiCue                                  # created by TASK-4209 (core/voice.py)
from ..core.llm_validation import PlausibilityReport                            # created by TASK-4209 (core/llm_validation.py)
from ..services.rule_evaluator import RuleResolution                            # verified: services/rule_evaluator.py:53

# tests
from parrot_formdesigner.audio import AudioAnswer, AudioQuestion, AudioSessionState   # verified: audio/__init__.py:15-21
```
`services/` has no import of `audio/` (verified: `grep -rn "from.*audio" services/*.py` → none), so importing
`RuleResolution` from `audio/models.py` creates no cycle.

### Existing Signatures to Use
```python
# audio/models.py
class VoiceMode(str, Enum)                                                      # line 18
class AudioQuestion(BaseModel):                                                 # line 72 ; extra="forbid"
    answer_envelope: Optional[Literal["voice"]] = None                          # line 125 (last field) <- anchor
class AudioFormManifest(BaseModel)                                              # line 128
class AudioAnswer(BaseModel):                                                   # line 153 ; extra="forbid"
    field_id: str; field_uid: Optional[uuid.UUID] = None
    value: str                                                                  # line 173 <- becomes Any
    source: Literal["text", "speech", "selection"] = "text"; confidence: Optional[float] = None
    raw_transcript: Optional[str] = None                                        # line 176 (last field) <- anchor
class AudioSessionState(BaseModel):                                             # line 179 ; extra="forbid"
    current_index: int = 0                                                      # line 206 (kept for v1)
    pending: Optional[AudioAnswer] = None                                       # line 211 (last field) <- anchor

# services/rule_evaluator.py
class RuleResolution(BaseModel):                                                # line 53 — visible, required, computed, cleared
```

### Does NOT Exist
- ~~`AudioQuestion.hint / narration / ui_cue / section_uid / answer_modes / voice_meta`~~ — created here.
- ~~`AudioAnswer.blob_ref / matched / version / plausibility`~~ — `blob_ref/matched/version` created here; there is NO `AudioAnswer.plausibility` (plausibility lives in the report and the envelope).
- ~~`AudioSessionState.phase / cursor / plan / flagged`~~ — created here.
- ~~`audio/events.py`~~ — created by TASK-4212; do NOT import it from `models.py`.
- ~~`Phase.CONNECTED`~~ — the spec's diagram says CONNECTED; the enum member is `IDLE`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/audio/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioQuestion",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioAnswer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py#AudioSessionState",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py#RuleResolution"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Every new field has a default → all existing constructions (renderer, WS handler, `tests/formdesigner/test_audio_models.py`) keep working.
- All three models stay `extra="forbid"`.
- `AudioAnswer.value: Any` — MULTI_SELECT is stored as a **list** (owner decision, AC6).
- `AudioQuestion.required` keeps its name; from now on it carries the **dynamic** required flag (S1a) — set by the renderer/planner, not here.
- `current_index` is kept for v1 compatibility; the engine derives it from `cursor` (TASK-4225).
- `flagged: dict[str, int]` = field_id → answer version flagged (one flag per answer version, AC12).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the imports — *why*: new field types reference `datetime`, `Any`, core voice models and `RuleResolution`.
2. Add `Phase`, `OptionMatch`, `NarrationPlan`, `ReviewItemData` right after `VoiceMode` — *why*: they must be defined before `AudioQuestion`/`AudioAnswer` reference them.
3. Append the field deltas to the three models and update their docstrings — *why*: spec §2 Data Models.
4. Export from `audio/__init__.py` — *why*: consumers import from `parrot_formdesigner.audio`.
5. Run the new tests and the existing `test_audio_models.py`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from pydantic import BaseModel, ConfigDict, Field' audio/models.py)
# REPLACE lines 11-15 (`import uuid` … `from pydantic import BaseModel, ConfigDict, Field`) with:
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.llm_validation import PlausibilityReport
from ..core.voice import FieldVoiceMeta, UiCue
from ..services.rule_evaluator import RuleResolution
# UiCue is re-exported simply by being imported here (spec §3 M1); do not add __all__ to models.py.
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY — new models)
```python
# occurrences: 1 (verified: grep -c 'class VoiceMode(str, Enum):' audio/models.py)
# AFTER — insert below the VoiceMode class body, before `class AudioSessionConfig(BaseModel):` (verified: audio/models.py:38)


class Phase(str, Enum):
    """Audio session engine phase (FEAT-649). Re-exported by ``audio/events.py``."""

    IDLE = "idle"
    PLANNING = "planning"
    ASKING = "asking"
    ACCEPTING = "accepting"
    CONFIRMING = "confirming"
    PLAUSIBILITY = "plausibility"
    REVIEW = "review"
    REVIEW_EDITING = "review_editing"
    SUBMITTING = "submitting"
    COMPLETE = "complete"
    ABORTED = "aborted"


class OptionMatch(BaseModel):
    """A transcript resolved to one option (or boolean / scale value)."""

    value: Any
    label: str
    method: Literal["exact", "ordinal", "yes_no", "numeric", "contains", "fuzzy", "llm"]
    score: float = Field(ge=0.0, le=1.0)


class NarrationPlan(BaseModel):
    """Deterministic narration for one turn: full text + ordered audio segment keys."""

    text: str
    audio_keys: list[str] = Field(default_factory=list)
    segments: dict[str, str] = Field(default_factory=dict)  # key -> text to synthesise


class ReviewItemData(BaseModel):
    """One line of the final review (position is 1-based, as narrated)."""

    position: int = Field(ge=1)
    field_id: str
    label: str
    answer_text: str
    skipped: bool = False
    flagged: bool = False
    sensitive: bool = False
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY — AudioQuestion)
```python
# occurrences: 1 (verified: grep -c '    answer_envelope: Optional[Literal["voice"]] = None' audio/models.py)
# AFTER — insert below `    answer_envelope: Optional[Literal["voice"]] = None` (verified: audio/models.py:125)
    # FEAT-649 — sections, hint, narration and hands-free cues
    section_uid: Optional[str] = None
    section_title: Optional[str] = None
    subsection_title: Optional[str] = None
    hint: Optional[str] = None
    prompt: Optional[str] = None
    narration: Optional[NarrationPlan] = None
    ui_cue: Optional[UiCue] = None
    answer_modes: list[str] = Field(default_factory=list)
    voice_meta: Optional[FieldVoiceMeta] = None
    llm_validation: bool = False
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY — AudioAnswer)
```python
# occurrences: 1 (verified: grep -c '    value: str' audio/models.py)
# REPLACE `    value: str` (verified: audio/models.py:173) with:
    value: Any
# occurrences: 1 (verified: grep -c '    raw_transcript: Optional[str] = None' audio/models.py)
# AFTER — insert below `    raw_transcript: Optional[str] = None` (verified: audio/models.py:176)
    # FEAT-649 — recording evidence and matching
    blob_ref: Optional[str] = None
    audio_mime: Optional[str] = None
    audio_bytes_len: Optional[int] = None
    duration_ms: Optional[int] = None
    matched: Optional[OptionMatch] = None
    stt_language: Optional[str] = None
    answered_at: Optional[datetime] = None
    version: int = Field(default=1, ge=1)
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (MODIFY — AudioSessionState)
```python
# occurrences: 1 (verified: grep -c '    pending: Optional[AudioAnswer] = None' audio/models.py)
# AFTER — insert below `    pending: Optional[AudioAnswer] = None` (verified: audio/models.py:211)
    # FEAT-649 — engine state
    phase: Phase = Phase.IDLE
    cursor: Optional[str] = None
    history: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    return_to_review: bool = False
    review_cursor: int = 0
    resolution: Optional[RuleResolution] = None
    tenant: Optional[str] = None
    locale: str = "en"
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    protocol_version: int = 1
    plausibility: Optional[PlausibilityReport] = None
    flagged: dict[str, int] = Field(default_factory=dict)
```
**Why**: `submission_id` is pre-generated so the commit is idempotent (S2); `protocol_version` defaults to v1 so legacy sessions behave as today. Update the class docstrings' Attributes lists for every added field.

### `packages/parrot-formdesigner/src/parrot_formdesigner/audio/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .models import (' audio/__init__.py)
# REPLACE the import block at audio/__init__.py:15-21 and __all__ :23-29 with:
from .models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
    NarrationPlan,
    OptionMatch,
    Phase,
    ReviewItemData,
    UiCue,
)

__all__ = [
    "AudioAnswer",
    "AudioFormManifest",
    "AudioQuestion",
    "AudioSessionConfig",
    "AudioSessionState",
    "NarrationPlan",
    "OptionMatch",
    "Phase",
    "ReviewItemData",
    "UiCue",
]
```
Also add the new names to the module docstring's "Public exports" list.

### FILL IN checklist
- [ ] docstring Attributes entries for every new field
- [ ] test bodies marked `FILL IN`

---

## Acceptance Criteria

- [ ] `AudioQuestion`, `AudioAnswer`, `AudioSessionState` built with only their pre-FEAT-649 arguments still validate; new fields take the defaults above.
- [ ] `AudioAnswer(field_id="c", value=["a", "b"], source="speech")` validates (list value).
- [ ] `Phase` has exactly the 11 members listed; `from parrot_formdesigner.audio import Phase, UiCue` works.
- [ ] `from parrot_formdesigner.audio.models import UiCue` is the same object as `parrot_formdesigner.core.voice.UiCue`.
- [ ] Two `AudioSessionState` instances get different `submission_id`s.
- [ ] Existing `tests/formdesigner/test_audio_models.py` passes unchanged; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_models_v2.py
import uuid

import pytest
from pydantic import ValidationError

from parrot_formdesigner.audio import (
    AudioAnswer,
    AudioQuestion,
    AudioSessionState,
    NarrationPlan,
    OptionMatch,
    Phase,
    ReviewItemData,
    UiCue,
)
from parrot_formdesigner.core.voice import UiCue as CoreUiCue


def _question(**kw) -> AudioQuestion:
    return AudioQuestion(index=0, field_id="q", field_uid=uuid.uuid4(), field_type="text", label="Q", **kw)


class TestAudioModelDeltas:
    def test_question_defaults(self):
        q = _question()
        assert q.hint is None and q.answer_modes == [] and q.llm_validation is False

    def test_question_with_narration_and_cue(self):
        q = _question(narration=NarrationPlan(text="Q", audio_keys=["q:x:label"]), ui_cue=UiCue(control="select"))
        assert q.narration.audio_keys == ["q:x:label"]

    def test_answer_any_value_and_evidence(self):
        a = AudioAnswer(field_id="c", value=["a", "b"], source="speech", blob_ref="voice-s-u",
                        matched=OptionMatch(value="a", label="A", method="ordinal", score=1.0))
        assert a.version == 1 and a.value == ["a", "b"]

    def test_state_defaults(self):
        s1 = AudioSessionState(session_id="s", form_uid="f", user_id="u")
        s2 = AudioSessionState(session_id="s", form_uid="f", user_id="u")
        assert s1.phase is Phase.IDLE and s1.protocol_version == 1 and s1.flagged == {}
        assert s1.submission_id != s2.submission_id

    def test_extra_still_forbidden(self):
        with pytest.raises(ValidationError):
            AudioAnswer(field_id="x", value="v", bogus=1)

    def test_phase_members_and_uicue_reexport(self):
        assert {p.name for p in Phase} == {"IDLE", "PLANNING", "ASKING", "ACCEPTING", "CONFIRMING", "PLAUSIBILITY",
                                          "REVIEW", "REVIEW_EDITING", "SUBMITTING", "COMPLETE", "ABORTED"}
        assert UiCue is CoreUiCue

    def test_review_item_position_is_one_based(self):
        # FILL IN: position=0 raises ValidationError; position=1 ok
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4211 audio-form-interaction-workflow verified`
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
