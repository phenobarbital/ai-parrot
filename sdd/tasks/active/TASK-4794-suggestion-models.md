# TASK-4794: `Suggestion` models + `AIMessage.suggestions` field

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other Python task needs the wire model of a chip (`Suggestion`), the LLM-lane structured
output (`SuggestionBatch`) and the additive `AIMessage.suggestions` field. The field defaults to `[]`, so an agent
that does not opt in produces byte-identical bodies (spec G1).

---

## Scope

- Create `parrot/models/suggestions.py` with `SuggestionKind`, `SuggestionSource`, `Suggestion`, `SuggestionBatch`.
- Add `AIMessage.suggestions: List[Suggestion]` right after the `a2ui_envelope` field.
- Export the four names from `parrot.models` (import + `__all__`).
- Write `tests/unit/models/test_suggestion_models.py`.

**NOT in scope**: providers, engine, bot wiring (TASK-4797+), server mirror `AgentChatSuggestion` (TASK-4801).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/suggestions.py` | CREATE | Chip models |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Import + `AIMessage.suggestions` field |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Export the four names |
| `packages/ai-parrot/tests/unit/models/test_suggestion_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # pydantic v2
from parrot.models.outputs import OutputMode            # verified: packages/ai-parrot/src/parrot/models/outputs.py:23
from parrot.models.responses import AIMessage           # verified: packages/ai-parrot/src/parrot/models/responses.py:93
from parrot.models.basic import CompletionUsage         # verified: packages/ai-parrot/src/parrot/models/basic.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/responses.py
from typing import Dict, List, Optional, Any, TypedDict, Union        # line 1 (List already imported)
from .outputs import OutputMode                                       # line 9  ← anchor for the new import
class AIMessage(BaseModel):                                           # line 93
    a2ui_envelope: Optional[Dict[str, Any]] = Field(                  # line 212-219 ← new field after this block
    model_config = ConfigDict(arbitrary_types_allowed=True)           # line 222
    def render_as(self, mode: OutputMode, formatter: Any, **kwargs) -> "AIMessage": ...  # line 369 (dump + rebuild)

# packages/ai-parrot/src/parrot/models/__init__.py
from .responses import (                                              # line 8
__all__ = (                                                           # line 119 (tuple of strings; "AIMessage" at 124)

# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum): DEFAULT="default" (26), CARD="card" (44), STRUCTURED_CHART (52), STRUCTURED_TABLE (53)
```

### Does NOT Exist
- ~~`parrot.models.suggestions`~~ — created by this task.
- ~~`AIMessage.suggestions` / `.followups` / `.chips`~~ — no such field today.
- ~~a server-side import of `parrot.models.suggestions` from `chat_models.py`~~ — the server mirror stays import-free (TASK-4801).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/suggestions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/models/responses.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/models/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/models/test_suggestion_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/outputs.py#OutputMode"
  ]
}
```

---

## Implementation Notes

- `suggestions.py` imports `OutputMode` relatively (`from .outputs import OutputMode`) — it must NOT import
  `responses.py` (that would be circular: `responses.py` imports `suggestions.py`).
- `use_enum_values=True`: `kind`, `source` and `output_mode` are stored as plain strings after validation, so
  `model_dump(mode="json")` is wire-ready.
- `extra="forbid"` is intentional: an LLM that invents keys fails `SuggestionBatch` validation (spec §7 Gotchas).

---

## Implementation Blueprint

### Steps (in order)
1. Create `suggestions.py` from the block below and fill the two validator bodies — *why*: everything else imports it.
2. Add the import to `responses.py` below line 9, then the field after the `a2ui_envelope` block — *why*: G1 additive field.
3. Export from `parrot/models/__init__.py` — *why*: spec M1 "export from `parrot.models`".
4. Write the tests and run the Validation Commands — *why*: AC "default `[]`, round-trip preserved".

### `packages/ai-parrot/src/parrot/models/suggestions.py` (CREATE)
```python
"""Follow-up suggestion chip models (FEAT-752)."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .outputs import OutputMode


class SuggestionKind(str, Enum):
    """What the chip does when clicked."""

    FOLLOWUP = "followup"
    PRESENTATION = "presentation"
    ACTION = "action"


class SuggestionSource(str, Enum):
    """Who produced the chip."""

    LLM = "llm"
    SKILL = "skill"
    PROVIDER = "provider"


ALLOWED_ACTIONS: frozenset[str] = frozenset({"explain"})


class Suggestion(BaseModel):
    """One follow-up chip. Wire shape is identical for every channel (FEAT-752)."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    label: str = Field(min_length=1, max_length=40, description="Chip text (<= 40 chars)")
    prompt: str = Field(min_length=1, max_length=500, description="Text sent through the normal chat path on click")
    output_mode: Optional[OutputMode] = Field(default=None, description="Explicit mode for the click turn, if any")
    kind: SuggestionKind = SuggestionKind.FOLLOWUP
    source: SuggestionSource = SuggestionSource.PROVIDER
    action: Optional[str] = Field(default=None, description='Client action id; v1 allows only "explain" (kind=action)')

    @field_validator("label", "prompt", mode="before")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        """Collapse internal whitespace, strip, and reject blank values."""
        # FILL IN: if not a str -> return v unchanged (let pydantic type-check); else " ".join(v.split());
        #          raise ValueError("must not be blank") when the result is "" — bounded by spec §3 M1 skeleton
        raise NotImplementedError

    @model_validator(mode="after")
    def _action_consistency(self) -> "Suggestion":
        """Reject `action` without kind=action, kind=action without action, and actions outside ALLOWED_ACTIONS."""
        # FILL IN: compare against SuggestionKind.ACTION.value (enum values are stored as str) — bounded by
        #          test_suggestion_action_requires_kind_action; return self when valid
        raise NotImplementedError


class SuggestionBatch(BaseModel):
    """Structured output requested from the lightweight model (LLM lane)."""

    suggestions: List[Suggestion] = Field(default_factory=list, max_length=4)
```
**Why this shape**: field list, limits and enums are fixed by spec §2 Data Models. `mode="before"` on the strip
validator makes whitespace collapse happen before the `max_length` check. Do not add fields.

### `packages/ai-parrot/src/parrot/models/responses.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c 'from .outputs import OutputMode' packages/ai-parrot/src/parrot/models/responses.py)
# AFTER — insert below `from .outputs import OutputMode` (verified: responses.py:9)
from .suggestions import Suggestion
```

### `packages/ai-parrot/src/parrot/models/responses.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c '    a2ui_envelope: Optional\[Dict\[str, Any\]\] = Field(' responses.py)
# AFTER — insert below the closing `    )` of the a2ui_envelope block (verified: responses.py:212-219), before the
# blank line + `# Allow arbitrary types for output field` comment (:221)
    suggestions: List[Suggestion] = Field(
        default_factory=list,
        description=(
            "Follow-up chips produced by the agent after the answer (FEAT-752). "
            "Empty unless the agent opts in."
        ),
    )
```

### `packages/ai-parrot/src/parrot/models/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .responses import (' packages/ai-parrot/src/parrot/models/__init__.py)
# AFTER — insert below the closing `)` of the `from .responses import (` block (verified: __init__.py:8-14)
from .suggestions import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource
# ...and in `__all__ = (` (verified: __init__.py:119), after the `"StreamChunk",` entry (:128):
    "Suggestion",
    "SuggestionBatch",
    "SuggestionKind",
    "SuggestionSource",
```

### FILL IN checklist
- [ ] `Suggestion._strip_nonempty` — whitespace collapse + blank rejection; bounded by spec §3 M1.
- [ ] `Suggestion._action_consistency` — three rejection rules; bounded by `test_suggestion_action_requires_kind_action`.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] 41-char label raises `ValidationError`; 40 passes.
- [ ] `action="explain"` with `kind=followup` rejected; `kind=action` without `action` rejected; `action="other"` rejected.
- [ ] `AIMessage(...).suggestions == []` by default; `model_dump()` and `render_as()` preserve chips.
- [ ] `from parrot.models import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource` works.
- [ ] Existing AIMessage tests in the Validation Commands stay green; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/models/test_suggestion_models.py -q`
- `pytest packages/ai-parrot/tests/unit/models/test_aimessage_artifact_id.py -q`
- `pytest packages/ai-parrot/tests/models/test_aimessage_url_fields.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_suggestion_models.py
import pytest
from pydantic import ValidationError
from parrot.models import AIMessage, Suggestion, SuggestionBatch
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode


def _msg(**kw) -> AIMessage:
    return AIMessage(input="q", output="a", model="fake", provider="fake", usage=CompletionUsage(), **kw)


def test_suggestion_label_max_40():
    Suggestion(label="x" * 40, prompt="p")
    with pytest.raises(ValidationError):
        Suggestion(label="x" * 41, prompt="p")


def test_suggestion_strips_and_rejects_blank():
    assert Suggestion(label="  a   b ", prompt="p").label == "a b"
    with pytest.raises(ValidationError):
        Suggestion(label="   ", prompt="p")


def test_suggestion_action_requires_kind_action():
    # FILL IN: three rejections + one valid explain chip (kind="action", action="explain")
    ...


def test_suggestion_batch_max_four():
    # FILL IN: 5 items -> ValidationError
    ...


def test_aimessage_suggestions_default_empty_and_roundtrip():
    assert _msg().suggestions == []
    m = _msg(suggestions=[Suggestion(label="View as table", prompt="p", output_mode=OutputMode.STRUCTURED_TABLE,
                                     kind="presentation")])
    # FILL IN: assert model_dump()["suggestions"][0]["output_mode"] == "structured_table" and that
    #          AIMessage(**m.model_dump()).suggestions round-trips (render_as rebuilds the same way)
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions: work in the feature worktree
(`python -m scripts.sdd.ensure_worktree --slug followup-suggestion-chips --feature-id FEAT-752`), verify the
Codebase Contract first, implement from the blueprint, run the Validation Commands with
`PYTHONPATH=packages/ai-parrot/src`, commit only the listed files, close with
`scripts/sdd/close_task.sh TASK-4794 followup-suggestion-chips verified`.

---

## Completion Note

*(Agent fills this in when done)*
