---
type: Wiki Overview
title: 'TASK-1279: Reject-button hook on HumanChannel + Telegram/Web rendering'
id: doc:sdd-tasks-completed-task-1279-reject-button-channels-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C6**. Adds the standardised "↑ Escalar" button
relates_to:
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1279: Reject-button hook on HumanChannel + Telegram/Web rendering

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1277
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C6**. Adds the standardised "↑ Escalar" button
to channels that opt in, and the manager-side interception that turns
a `value="__escalate__"` response into an `advance_chain(cause="reject")`
call instead of accumulating it as a regular answer.

---

## Scope

- In `parrot/human/channels/base.py`:
  - Add class attribute `render_reject_button: bool = False`.
  - Export module-level constant `ESCALATE_OPTION_KEY = "__escalate__"`.
  - Provide a helper `escalate_option() -> ChoiceOption` that returns
    the standard reject `ChoiceOption(key=ESCALATE_OPTION_KEY, label="↑ Escalar")`.
- In `parrot/human/channels/telegram.py`:
  - Set `render_reject_button = True`.
  - When `interaction.policy is not None`, append `escalate_option()`
    to the inline keyboard rendered by `send_interaction`.
- In `parrot/human/channels/web.py`:
  - Set `render_reject_button = True`.
  - When rendering options (or for free_text interactions on policy-
    bound interactions, add the reject affordance as an extra option in
    the payload).
- `parrot/human/channels/cli.py` and `cli_companion.py`: leave
  defaults (`False`); no UI change.
- In `parrot/human/manager.py.receive_response`: before accumulation,
  if `response.response_type == InteractionType.SINGLE_CHOICE` (or the
  channel-translated equivalent) and `response.value == ESCALATE_OPTION_KEY`
  AND `interaction.policy is not None`, call
  `await self.advance_chain(response.interaction_id, cause="reject")`
  and `return` without accumulating.

**NOT in scope**: Web HITL handler-level routing for the reject button
on the HTTP side (TASK-1285). RejectIntentDetector (TASK-1278).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/channels/base.py` | MODIFY | Add `render_reject_button`, `ESCALATE_OPTION_KEY`, `escalate_option()` |
| `packages/ai-parrot/src/parrot/human/channels/telegram.py` | MODIFY | Opt-in to reject button + render in keyboard |
| `packages/ai-parrot/src/parrot/human/channels/web.py` | MODIFY | Opt-in to reject button + render affordance |
| `packages/ai-parrot/src/parrot/human/manager.py` | MODIFY | Intercept `value=ESCALATE_OPTION_KEY` in `receive_response` |
| `packages/ai-parrot/tests/human/channels/test_telegram_reject_button.py` | CREATE | Inline keyboard contains escalate option |
| `packages/ai-parrot/tests/human/channels/test_web_reject_button.py` | CREATE | Web payload contains escalate option |
| `packages/ai-parrot/tests/test_human_manager.py` | MODIFY | Add test: escalate-value response routes to `advance_chain` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing:
from parrot.human.channels.base import HumanChannel          # channels/base.py:11
from parrot.human.models import ChoiceOption, HumanInteraction, HumanResponse, InteractionType
```

### Existing Signatures to Use

```python
# parrot/human/channels/base.py:11-70
class HumanChannel(ABC):
    channel_type: str = "base"                                  # line 19
    @abstractmethod
    async def send_interaction(self, interaction, recipient) -> bool: ...
    @abstractmethod
    async def register_response_handler(self, callback) -> None: ...
    async def register_cancel_handler(self, callback) -> None: return None

# parrot/human/channels/telegram.py — TelegramHumanChannel(HumanChannel)
#   channel_type = "telegram"                                   # line 75
#   send_interaction renders inline keyboard from interaction.options

# parrot/human/channels/web.py — WebHumanChannel(HumanChannel)
#   channel_type = "web"                                        # line 42

# parrot/human/channels/cli.py — CLIHumanChannel(HumanChannel)
#   channel_type = "cli"                                        # line 64
```

### Does NOT Exist

- ~~`HumanChannel.render_reject_button`~~ — to be added.
- ~~`parrot.human.channels.ESCALATE_OPTION_KEY`~~ — to be added to base.py.
- ~~`InteractionStatus.REJECTED`~~ — reject is a cause, not a status.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/human/channels/base.py
ESCALATE_OPTION_KEY = "__escalate__"

def escalate_option() -> "ChoiceOption":
    from ..models import ChoiceOption
    return ChoiceOption(key=ESCALATE_OPTION_KEY, label="↑ Escalar")


class HumanChannel(ABC):
    channel_type: str = "base"
    render_reject_button: bool = False
    # ...
```

```python
# In TelegramHumanChannel.send_interaction, when building the keyboard:
if interaction.policy is not None and self.render_reject_button:
    keyboard_rows.append([
        InlineKeyboardButton(text="↑ Escalar", callback_data=f"hitl:{interaction.interaction_id}:{ESCALATE_OPTION_KEY}")
    ])
```

```python
# In HumanInteractionManager.receive_response, after type validation:
if (
    interaction.policy is not None
    and isinstance(response.value, str)
    and response.value == ESCALATE_OPTION_KEY
):
    await self.advance_chain(response.interaction_id, cause="reject")
    return
```

### Key Constraints

- Only append the reject button when `interaction.policy is not None` —
  legacy non-policy interactions look identical to today.
- Telegram callback_data must remain under the 64-byte limit; if the
  interaction_id (UUID) + `__escalate__` exceed it, encode by truncating
  the UUID and looking up via a hash map maintained by the channel.
- Web channel: the reject affordance must be rendered for ALL
  interaction types (free_text, approval, single_choice, …) when policy
  is set. For free_text, it appears as a separate button next to the
  text input.
- The escalate response delivered back through `receive_response` MUST
  carry `response_type` consistent with the channel's normal pathway
  (e.g., Telegram inline button → `SINGLE_CHOICE`). The manager
  intercepts purely on `value == ESCALATE_OPTION_KEY`, not on type.

### References in Codebase

- Telegram channel current keyboard-building code (search for
  `InlineKeyboardButton` in `parrot/human/channels/telegram.py`).
- Web channel render path in `parrot/human/channels/web.py`.

---

## Acceptance Criteria

- [ ] `HumanChannel.render_reject_button == False` by default.
- [ ] `TelegramHumanChannel.render_reject_button == True`.
- [ ] `WebHumanChannel.render_reject_button == True`.
- [ ] `CLIHumanChannel.render_reject_button == False`.
- [ ] When `interaction.policy is None`, NO reject button is rendered
  on Telegram or Web (legacy behaviour preserved).
- [ ] When `interaction.policy is not None`, Telegram inline keyboard
  contains a button with the escalate callback_data.
- [ ] When `interaction.policy is not None`, Web payload contains an
  affordance with `key == "__escalate__"`.
- [ ] Manager `receive_response` with `value="__escalate__"` calls
  `advance_chain(cause="reject")` exactly once and does NOT accumulate.
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/human/channels/ packages/ai-parrot/tests/test_human_manager.py -v`.

---

## Test Specification

```python
# tests/human/channels/test_telegram_reject_button.py
async def test_keyboard_includes_escalate_when_policy_present(): ...
async def test_keyboard_excludes_escalate_when_no_policy(): ...
async def test_escalate_callback_data_format(): ...

# tests/human/channels/test_web_reject_button.py
async def test_payload_includes_escalate_option_when_policy_present(): ...

# tests/test_human_manager.py — new
async def test_receive_response_escalate_value_routes_to_advance_chain(): ...
async def test_receive_response_escalate_value_does_not_accumulate(): ...
```

---

## Agent Instructions

1. Read spec §3 C6 + §6 contract.
2. Verify TASK-1277 completed (`advance_chain` available).
3. Implement; CLI must remain untouched in behaviour.
4. Test, lint.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-21 by sdd-worker (FEAT-194).

- `channels/base.py`: Added `ESCALATE_OPTION_KEY = "__escalate__"`, `escalate_option()` helper, and `render_reject_button: ClassVar[bool] = False` on `HumanChannel`.
- `channels/telegram.py`: Set `render_reject_button = True`. Added `_build_escalate_row()`. Wired into `_send_approval`, `_send_single_choice`, and `_send_free_text` (appends row when `interaction.policy is not None`). Imported `ESCALATE_OPTION_KEY`.
- `channels/web.py`: Set `render_reject_button = True`. `_build_question_payload` appends `{"key": "__escalate__", "label": "↑ Escalar"}` to options when policy is set.
- `channels/cli.py` and `cli_companion.py`: Unchanged (inherits `render_reject_button = False` from base).
- `manager.py`: Imported `ESCALATE_OPTION_KEY`. Added intercept block before intent-detector check: if `response.value == ESCALATE_OPTION_KEY` and policy bound → `advance_chain(cause="reject")`.
- 11 channel tests (6 Telegram, 5 Web) + 3 manager integration tests; all pass.
