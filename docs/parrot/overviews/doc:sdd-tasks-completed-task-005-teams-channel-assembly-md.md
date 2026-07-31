---
type: Wiki Overview
title: 'TASK-005: TeamsHumanChannel assembly + inbound demux + registry'
id: doc:sdd-tasks-completed-task-005-teams-channel-assembly-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 (core assembly). Implements the `HumanChannel` contract
  using
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.integrations.msteams.graph
  rel: mentions
- concept: mod:parrot.integrations.msteams.hitl_cards
  rel: mentions
- concept: mod:parrot.integrations.msteams.proactive
  rel: mentions
---

# TASK-005: TeamsHumanChannel assembly + inbound demux + registry

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-002, TASK-003, TASK-004
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (core assembly). Implements the `HumanChannel` contract using
the GraphClient (TASK-002), TeamsCardRenderer (TASK-003), and proactive
messenger + Redis stores (TASK-004). Wires the inbound webhook demux that turns
a card submit into a `HumanResponse`, and registers the channel.

---

## Scope

- Implement `TeamsHumanChannel(HumanChannel)` with `channel_type = "teams"`,
  `render_reject_button = True`:
  - `start()/stop()`: acquire/release adapter, GraphClient, Redis stores. No long-poll.
  - `send_interaction(interaction, recipient)`: resolve email → AAD (TASK-002) →
    obtain convref + post card (TASK-004 + TASK-003) → store sent map → `True`;
    `False` on any failure (never hang).
  - `send_notification(recipient, message)`: same 1:1 bootstrap, one-way text (D2).
  - `cancel_interaction(interaction_id, recipient)`: `update_activity` cached card
    → disabled/expired variant (TASK-003). Idempotent.
  - `register_response_handler` / `register_cancel_handler`: store callbacks.
- **Inbound demux** (`on_turn`/webhook): `activity.value.hitl is True` → build
  `HumanResponse(interaction_id=value["interaction_id"], respondent=<sender AAD
  id from the BF-validated activity>, value=<parsed fields>)` → invoke stored
  `response_callback`. Refresh convref/serviceUrl on every inbound activity.
- **Register**: `ChannelRegistry.register("teams", TeamsHumanChannel)` at import
  bottom (mirror telegram.py:1141); add `"TeamsHumanChannel": ".channels.teams"`
  to `_LAZY_EXPORTS` in `packages/ai-parrot/src/parrot/human/__init__.py`.

**NOT in scope**: `setup_teams_hitl` boot helper + per-agent `BotConfig`
override + docs (TASK-006); packaging (TASK-001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py` | CREATE | `TeamsHumanChannel` + registry hook |
| `packages/ai-parrot/src/parrot/human/__init__.py` | MODIFY | add `_LAZY_EXPORTS` teams entry + `__all__` |
| `packages/ai-parrot-integrations/tests/test_teams_channel.py` | CREATE | contract + demux + cancel + registry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.channels.base import HumanChannel, ESCALATE_OPTION_KEY, escalate_option
#   verified: packages/ai-parrot/src/parrot/human/channels/base.py:47,16,19
from parrot.human.channels import ChannelRegistry            # channels/__init__.py:16,34
from parrot.human.models import HumanInteraction, HumanResponse, InteractionType  # models.py:359,427,39
# Consume TASK-002/003/004 modules:
from parrot.integrations.msteams.graph import GraphClient, ResolvedTeamsUser
from parrot.integrations.msteams.hitl_cards import TeamsCardRenderer
from parrot.integrations.msteams.proactive import ProactiveMessenger, ConversationReferenceStore, SentActivityStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/channels/base.py:47  (the contract to implement)
class HumanChannel(ABC):
    channel_type: ClassVar[str] = "base"            # line 74  -> override "teams"
    render_reject_button: ClassVar[bool] = False    # line 79  -> override True
    @abstractmethod async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool   # line 100
    @abstractmethod async def send_notification(self, recipient: str, message: str) -> None                    # line 119
    @abstractmethod async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool            # line 132
    @abstractmethod async def register_response_handler(self, callback) -> None                                # line 151
    async def register_cancel_handler(self, callback) -> None                                                  # line 162

# packages/ai-parrot/src/parrot/human/channels/__init__.py:34
ChannelRegistry.register(name: str, channel_cls: type) -> None

# packages/ai-parrot/src/parrot/human/__init__.py:37-38  (extend this dict)
_LAZY_EXPORTS = {"TelegramHumanChannel": ".channels.telegram"}

# Reference impl to mirror (registry hook at bottom):
# packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py:54 (class), :1141 (register)

# Manager callback target (do NOT call manager internals directly — just store the callback):
# packages/ai-parrot/src/parrot/human/manager.py:580 receive_response  (intercepts ESCALATE_OPTION_KEY)
```

### Does NOT Exist
- ~~`HumanResponse.respondent` from card payload~~ — `respondent` MUST come from the BF-validated `activity.from.id`, not `activity.value` (authz). `is_valid_respondent` (manager.py:222) enforces membership.
- ~~a `teams` entry already in `_LAZY_EXPORTS`~~ — only `TelegramHumanChannel` (__init__.py:38); you add `teams`.
- ~~botbuilder imports at module top of any Telegram-shared module~~ — keep them lazy (TASK-001 isolation).

---

## Implementation Notes

### Key Constraints
- Always send a card (even FREE_TEXT) so correlation via `interaction_id` is deterministic.
- `False` on any resolution/delivery failure; never hang.
- Late reply after expiry: if a `hitl:result:{id}` tombstone exists, late-ack in-thread ("already expired"); do not crash.
- async/await; `self.logger`; Pydantic; Google-style docstrings.

### References in Codebase
- `telegram.py:54,189,1141` — channel shape, send_interaction dispatch, registry hook.

---

## Acceptance Criteria

- [ ] `TeamsHumanChannel` implements every ABC member; `channel_type="teams"`, `render_reject_button=True`.
- [ ] `send_interaction` returns `True`/`False` correctly; `send_notification` one-way; `cancel_interaction` idempotent via `update_activity`.
- [ ] Inbound demux builds correct `HumanResponse` (respondent from activity, not payload) and calls the stored callback.
- [ ] `ChannelRegistry.register("teams", ...)` at import; `_LAZY_EXPORTS` entry added; `from parrot.human import TeamsHumanChannel` resolves lazily.
- [ ] No linting errors: `ruff check .../human/channels/teams.py`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_teams_channel.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_teams_channel.py
import pytest

async def test_send_interaction_false_on_resolve_fail(channel): ...
async def test_inbound_demux_builds_human_response(channel): ...
async def test_respondent_from_activity_not_payload(channel): ...
async def test_cancel_updates_activity_idempotent(channel): ...
def test_registry_registers_teams(): ...
def test_lazy_export_resolves(): ...
```

---

## Agent Instructions
Standard SDD flow. Confirm dependencies (TASK-002/003/004) are in `completed/`,
verify the contract, implement, move to `completed/`, update index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-29
**Notes**: TeamsHumanChannel fully implements HumanChannel ABC with channel_type="teams", render_reject_button=True.
Inbound demux: activity.value.hitl=True → HumanResponse (respondent from activity.from_property.aad_object_id, never payload).
Late-reply tombstone check implemented. ChannelRegistry.register("teams", TeamsHumanChannel) at import bottom.
_LAZY_EXPORTS entry added to parrot/human/__init__.py. conftest.py updated to prepend ai-parrot core src path.
11 tests pass. _LAZY_EXPORTS uses ._channels (not ._registry) in ChannelRegistry.
**Deviations from spec**: none
