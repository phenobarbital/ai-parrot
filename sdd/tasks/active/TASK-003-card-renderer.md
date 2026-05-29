# TASK-003: TeamsCardRenderer — InteractionType → Adaptive Card

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Each `HumanInteraction` must render as an Adaptive Card with
the **`interaction_id` embedded in every `Action.Submit.data`** so replies
correlate deterministically even with multiple pending interactions in one 1:1.
Policy-bound interactions also carry the "↑ Escalar" action. A disabled/expired
card variant is needed for cancel (TASK-005 consumes it).

---

## Scope

- Implement a pure renderer mapping each `InteractionType` → Adaptive Card dict:
  - `FREE_TEXT` → `Input.Text` (multiline) + Submit.
  - `APPROVAL` → two `Action.Submit` (Approve / Reject), `data.value` ∈ {approve, reject}.
  - `SINGLE_CHOICE` → `Input.ChoiceSet` (compact) + Submit.
  - `MULTI_CHOICE` → `Input.ChoiceSet` (`isMultiSelect=true`) + Submit.
  - `FORM` → `form_schema` → `Input.*` fields + Submit (OQ-5: decide Input.* mapping/validation here).
  - `POLL` → `Input.ChoiceSet` + Submit.
- Every submit `data` carries `{"hitl": true, "interaction_id": "...", ...fields}`.
- When the interaction is policy-bound and `render_reject_button` is on, append
  an "↑ Escalar" action with `data.value == ESCALATE_OPTION_KEY`.
- Provide a `disabled/expired` card variant builder for cancel/update.

**NOT in scope**: sending/posting cards (TASK-004/005), inbound parsing
(TASK-005), Graph (TASK-002).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py` | CREATE | `TeamsCardRenderer` |
| `packages/ai-parrot-integrations/tests/test_hitl_cards.py` | CREATE | Per-InteractionType + escalate + disabled tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.models import HumanInteraction, InteractionType, ChoiceOption
#   verified: packages/ai-parrot/src/parrot/human/models.py:359,39,80
from parrot.human.channels.base import ESCALATE_OPTION_KEY, escalate_option
#   verified: packages/ai-parrot/src/parrot/human/channels/base.py:16,19
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/models.py
class InteractionType(str, Enum):                       # line 39
    FREE_TEXT = "free_text"; SINGLE_CHOICE = "single_choice"; MULTI_CHOICE = "multi_choice"
    APPROVAL = "approval"; FORM = "form"; POLL = "poll"
class ChoiceOption(BaseModel):                          # line 80  (key, label, description, metadata)
class HumanInteraction(BaseModel):                      # line 359
    interaction_id: str
    question: str
    interaction_type: InteractionType                   # line 367
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None        # line 369
    # validators: FORM requires form_schema (line 412); SINGLE/MULTI/POLL require options (line 416)

# packages/ai-parrot/src/parrot/human/channels/base.py
ESCALATE_OPTION_KEY: str = "__escalate__"               # line 16
def escalate_option() -> "ChoiceOption": ...            # line 19 → ChoiceOption(key="__escalate__", label="↑ Escalar")
```

### Does NOT Exist
- ~~`azure_teambots.create_adaptive_card` / `CardBot`~~ — do NOT import.
- ~~reuse of `MSTeamsAgentWrapper._build_adaptive_card()`~~ — it is a *reference* only; it does not embed `interaction_id` / HITL correlation. Build a dedicated renderer.

---

## Implementation Notes

### Key Constraints
- Always include `interaction_id` in submit data — this is the correlation hook.
- Renderer must be pure (no I/O), returning Adaptive Card JSON-able dicts (easy to unit test).
- Respect model validators: a FORM without `form_schema` or a choice type
  without `options` should already be rejected upstream, but render defensively.
- OQ-5: choose `Input.*` mappings for `form_schema` field types; document the mapping.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py` `_build_adaptive_card()` — structural reference only.

---

## Acceptance Criteria

- [ ] All six InteractionTypes render; each embeds `interaction_id` in every `Action.Submit.data`.
- [ ] Policy-bound + `render_reject_button` → "↑ Escalar" action with `data.value == ESCALATE_OPTION_KEY`.
- [ ] FORM maps `form_schema` → `Input.*` (mapping documented in code).
- [ ] Disabled/expired card variant builder present.
- [ ] No linting errors: `ruff check .../msteams/hitl_cards.py`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_hitl_cards.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_hitl_cards.py
import pytest
from parrot.human.models import HumanInteraction, InteractionType

@pytest.mark.parametrize("itype", list(InteractionType))
def test_card_embeds_interaction_id(itype): ...
def test_escalate_action_when_policy_bound(): ...
def test_disabled_card_variant(): ...
```

---

## Agent Instructions
Standard SDD flow. Verify the contract, implement, move to `completed/`, update index.

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
