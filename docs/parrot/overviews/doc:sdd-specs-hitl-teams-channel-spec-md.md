---
type: Wiki Overview
title: 'Feature Specification: TeamsHumanChannel — HITL channel over MS Teams / Azure
  Bot Framework'
id: doc:sdd-specs-hitl-teams-channel-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The HITL engine can already deliver interactions to humans over Telegram
relates_to:
- concept: mod:parrot.auth.context
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: TeamsHumanChannel — HITL channel over MS Teams / Azure Bot Framework

**Feature ID**: FEAT-205
**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD (next minor)

> Input: `sdd/proposals/hitl-teams-channel.brainstorm.md` (Recommended Option A).

---

## 1. Motivation & Business Requirements

### Problem Statement

The HITL engine can already deliver interactions to humans over Telegram
(`TelegramHumanChannel`) and the Web (FEAT-146). We need an equivalent
`HumanChannel` implementation for **MS Teams** so the same engine — with its
timeout, tiered escalation, cancel and audit machinery — can reach humans on
Teams.

The driving use case (PTO escalation): an agent must **open a private 1:1 chat
with a manager the bot may never have spoken to**, ask a question (e.g. an
approval), and read the reply as the interaction result. This is fundamentally
different from the existing Teams *conversational* integration
(`MSTeamsAgentWrapper` / `MSTeamsHook`), which is **reactive** — it only
responds to messages users send first. Here the bot must **initiate** a
proactive 1:1 and **correlate** an out-of-band card submission back to a
specific pending interaction.

Affected: end users (managers receiving HITL prompts in Teams), agent/flow
developers (who target Teams for HITL), and ops (who must satisfy the Teams
app-install deployment prerequisite).

### Goals
- Implement `TeamsHumanChannel(HumanChannel)` satisfying the ABC contract
  exactly as `TelegramHumanChannel` does, registered as the `"teams"` channel.
- Build the net-new **proactive 1:1 bootstrap** (`ConversationReference`
  capture/cache + `continue_conversation`/`create_conversation`) — the core
  capability absent from the repo today.
- Build a **minimal net-new async `GraphClient`** for email→AAD resolution
  (`/users/{upn}` + mail-filter) and `get_user_manager`.
- Render **all six** `InteractionType` values as Adaptive Cards, embedding
  `interaction_id` in every `Action.Submit.data` for deterministic correlation.
- Support `send_notification` (one-way) sharing the same 1:1 bootstrap.
- Ship a `setup_teams_hitl(app, manager, config)` boot helper; default to a
  single shared HITL bot, with a per-agent `BotConfig` override path.
- Resolve the `botbuilder`↔`aiogram` `emoji` packaging clash without breaking
  either channel.

### Non-Goals (explicitly out of scope)
- **Targeting-by-role / `TargetResolver`** — escalation feature; this channel
  consumes an already-resolved email and offers `get_user_manager` as a backend.
- **Proactive escalation driver (qworker sweep)** — escalation feature.
- **BLOCK-vs-suspend wait** for the user-facing turn — PTO/escalation feature.
- **Graph-driven delivery / Outlook Actionable Messages** — rejected for v1 (see
  brainstorm Option C); retained as the v2 escape hatch if the org-install
  prerequisite proves untenable.
- **Runtime cold-create fallback** — rejected for v1; org-wide install is a
  documented deployment prerequisite and the channel fails fast
  (`brainstorm.md` OQ-COLD).
- **Per-agent conversational bot identity** (`MSTeamsAgentWrapper`) — unchanged
  and out of scope; HITL transport identity is separate (brainstorm §8/D5).

---

## 2. Architectural Design

### Overview

A single, process-level **dedicated** HITL bot identity (its own APP_ID,
`/api/messages` route, Graph cred set, convref cache) is wired once at boot via
`setup_teams_hitl(app, manager, config)` and registered as the `"teams"`
channel on the default `HumanInteractionManager`. Because the bot is
*dedicated*, its inbound webhook faces no conversational traffic, so the demux
is a simple `activity.value.hitl is True` check; because it is *shared*, there
is no per-agent bot proliferation. A per-agent `BotConfig` override
(`brainstorm` OQ-9) lets a tier present a distinct HITL identity when needed,
exposed as keyed channels (`"teams"` default; additional keyed entries for
overrides) — exact selection wiring is an open question for implementation
(OQ-9-impl).

`send_interaction(interaction, recipient)`:
1. Resolve `recipient` (an **email**, per D4) → AAD user via the net-new
   `GraphClient` (`/users/{upn}`, fall back to `/users?$filter=mail eq '...'`).
2. Obtain a `ConversationReference`: cache hit (`hitl:teams:convref:{email}`) →
   `adapter.continue_conversation(ref, callback, bot_app_id)`; miss → cold
   `create_conversation` to bootstrap the 1:1, capture the reference, post.
3. Render the Adaptive Card for `interaction.interaction_type`, embedding
   `interaction_id` in every `Action.Submit.data`; append an "↑ Escalar" action
   when `render_reject_button` is on and the interaction is policy-bound.
4. Store `{conversation_reference, activity_id, recipient}` under
   `hitl:teams:sent:{interaction_id}` for cancel/update + cross-worker access.
5. Return `True` on delivery, `False` on any resolution/delivery failure (never
   hang).

`send_notification(recipient, message)` uses the **same 1:1 bootstrap** (D2),
one-way text, no reply wait.

`cancel_interaction(interaction_id, recipient)` calls `update_activity` on the
previously-sent card (via cached `activity_id`) to a disabled "expired/withdrawn"
state. Idempotent.

**Inbound demux** (webhook → `TurnContext`): `activity.value.hitl is True` →
build `HumanResponse(interaction_id=value["interaction_id"], respondent=<sender
AAD id from the BF-validated activity>, value=<parsed fields>)` → invoke the
stored `response_callback` (`manager.receive_response`). The manager intercepts
the `ESCALATE_OPTION_KEY` sentinel and routes to `advance_chain`. Every inbound
activity refreshes the convref cache (cache-on-contact) and `serviceUrl`.

### Component Diagram
```
HumanInteractionManager._dispatch_to_channel
        │  for human_id in interaction.target_humans:
        │      await channel_impl.send_interaction(interaction, human_id)
        ▼
TeamsHumanChannel ─┬─→ GraphClient (email → AAD object id, serviceUrl)
                   ├─→ ConversationReferenceStore (Redis: convref cache)
                   ├─→ ProactiveMessenger (CloudAdapter continue/create_conversation)
                   ├─→ TeamsCardRenderer (InteractionType → Adaptive Card)
                   └─→ SentActivityStore (Redis: sent map for cancel/update)

/api/messages (aiohttp webhook) ─→ CloudAdapter.process_activity ─→ on_turn
        │   activity.value.hitl is True
        ▼
HumanResponse ─→ response_callback (== manager.receive_response)
                     │ ESCALATE_OPTION_KEY → manager.advance_chain
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HumanChannel` (ABC) | extends | `TeamsHumanChannel(HumanChannel)` implements the full contract. |
| `ChannelRegistry` | registers | `ChannelRegistry.register("teams", TeamsHumanChannel)` at import time (mirrors telegram.py:1141). |
| `HumanInteractionManager` | plugs into | no manager code change; channel consumed via existing `_dispatch_to_channel` (manager.py:391) + `startup` (manager.py:256) callback wiring. |
| `parrot.human.__init__._LAZY_EXPORTS` | extends | add `"TeamsHumanChannel": ".channels.teams"` (mirrors telegram entry, __init__.py:38) so botbuilder isn't imported eagerly. |
| `escalate_option()` / `ESCALATE_OPTION_KEY` | uses | append "↑ Escalar" Adaptive Card action; sentinel intercepted by manager.receive_response (manager.py:580). |
| `Adapter(CloudAdapter)` pattern | reuses | follow `msteams/adapter.py:18` settings construction for the HITL adapter. |
| `MSTeamsAgentWrapper._build_adaptive_card()` | reference | card-building reference (wrapper.py); HITL needs its own renderer with `interaction_id` correlation. |
| `set_default_human_manager` / `register_channel` | uses | `setup_teams_hitl` registers the channel on the default manager (human/__init__.py:63, manager.py:252). |
| `ai-parrot-integrations/pyproject.toml` | modifies | `[tool.uv] override-dependencies` for `emoji`; confirm `azure-teambots` source. |

### Data Models
```python
# New Pydantic / config models (illustrative — finalize during implementation)

class TeamsHitlConfig(BaseModel):
    """Boot config for the shared HITL bot (sourced from navconfig)."""
    app_id: str                      # MSTEAMS_HITL_APP_ID
    app_password: str                # MSTEAMS_HITL_APP_PASSWORD
    tenant_id: str                   # MSTEAMS_TENANT_ID
    graph_client_id: str             # Graph app creds (may differ from bot creds)
    graph_client_secret: str
    graph_tenant_id: str
    redis_url: str
    route: str = "/api/teams-hitl/messages"
    convref_ttl: int = 2_592_000     # 30 days (OQ-4: long TTL + refresh)

class ResolvedTeamsUser(BaseModel):
    """Result of GraphClient email→AAD resolution."""
    aad_object_id: str
    upn: str
    email: str
    service_url: Optional[str] = None
```
Redis key shapes (new):
- `hitl:teams:convref:{email}` → serialized `ConversationReference` (TTL = `convref_ttl`, refreshed on inbound contact).
- `hitl:teams:sent:{interaction_id}` → `{conversation_reference, activity_id, recipient}`.

### New Public Interfaces
```python
class TeamsHumanChannel(HumanChannel):
    channel_type = "teams"
    render_reject_button = True
    def __init__(self, adapter, graph_client, redis, config: TeamsHitlConfig) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool: ...
    async def send_notification(self, recipient: str, message: str) -> None: ...
    async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool: ...
    async def register_response_handler(self, callback) -> None: ...
    async def register_cancel_handler(self, callback) -> None: ...
    # Inbound entry called by the webhook turn handler:
    async def on_turn(self, turn_context) -> None: ...

async def setup_teams_hitl(app, manager: "HumanInteractionManager", config: TeamsHitlConfig) -> TeamsHumanChannel: ...
```

---

## 3. Module Breakdown

### Module 1: GraphClient (net-new)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py` (path to confirm in impl — may live alongside vendored BF plumbing)
- **Responsibility**: Async aiohttp Microsoft Graph client: client-credentials token acquisition; `get_user_by_email(email)` (`/users/{upn}`, fall back to mail-filter); `get_user_manager(upn)`. Returns `ResolvedTeamsUser`.
- **Depends on**: navconfig Graph creds; `aiohttp`.

### Module 2: Vendored Bot Framework plumbing (vendor from private fork — OQ-VENDOR)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/` (adapter / cards / service helpers)
- **Responsibility**: Adapter (`CloudAdapter` settings), Adaptive Card builder helpers, `/api/messages` service wiring — sourced from the private `azure_teambots` fork. **Exact fork contents must be confirmed before tasks assume any vendored class** (OQ-VENDOR). Reuse `msteams/adapter.py:18` pattern where the fork doesn't supply it.
- **Depends on**: `botbuilder` (transitive, v4.17.1).

### Module 3: Proactive 1:1 bootstrap + ConversationReference cache (net-new core)
- **Path**: `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py` (or a `_proactive.py` helper)
- **Responsibility**: capture `ConversationReference` from inbound activities; `ConversationReferenceStore` (Redis, TTL + refresh); cache-hit `continue_conversation`; cache-miss cold `create_conversation`; `serviceUrl` trust/refresh. Returns `activity_id` for the sent map.
- **Depends on**: Module 1 (resolve AAD/serviceUrl), Module 2 (adapter), Redis.

### Module 4: TeamsCardRenderer (net-new)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py`
- **Responsibility**: map each `InteractionType` → Adaptive Card with `interaction_id` in every `Action.Submit.data`; append "↑ Escalar" when policy-bound; build disabled/expired card variant for cancel. FORM uses `form_schema`→`Input.*` mapping (OQ-5).
- **Depends on**: `parrot.human.models` (InteractionType, ChoiceOption); `escalate_option`.

### Module 5: TeamsHumanChannel + setup helper (assembly — lands last)
- **Path**: `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py`
- **Responsibility**: implement the `HumanChannel` contract using Modules 1–4; inbound demux (`on_turn`) → `HumanResponse`; `setup_teams_hitl`; `ChannelRegistry.register("teams", ...)`; add `_LAZY_EXPORTS` entry; `pyproject.toml` `emoji` override + strict lazy imports; per-agent `BotConfig` override scaffolding.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_graph_resolve_by_upn` | M1 | email == UPN → `/users/{upn}` path returns `ResolvedTeamsUser`. |
| `test_graph_resolve_mail_filter_fallback` | M1 | `/users/{upn}` 404 → mail-filter fallback resolves. |
| `test_graph_resolve_failure_returns_none` | M1 | Graph error → resolution returns None (channel must fail-fast, not raise). |
| `test_convref_cache_hit_uses_continue` | M3 | cached ref → `continue_conversation` path (no cold create). |
| `test_convref_cache_miss_cold_create` | M3 | no ref → `create_conversation` then capture + store. |
| `test_convref_ttl_refreshed_on_contact` | M3 | inbound activity refreshes TTL + serviceUrl (OQ-4). |
| `test_card_per_interaction_type` | M4 | each of FREE_TEXT/APPROVAL/SINGLE/MULTI/FORM/POLL renders + embeds `interaction_id` in submit data. |
| `test_card_escalate_action_when_policy_bound` | M4 | "↑ Escalar" action present with `data.value == ESCALATE_OPTION_KEY`. |
| `test_send_interaction_returns_false_on_resolve_fail` | M5 | unresolved recipient → `False`, no exception. |
| `test_inbound_demux_builds_human_response` | M5 | `activity.value.hitl is True` → correct `HumanResponse` (respondent from activity, not payload). |
| `test_cancel_updates_activity` | M5 | `cancel_interaction` calls `update_activity` on cached `activity_id`; idempotent. |
| `test_registry_registers_teams` | M5 | `ChannelRegistry.register("teams", ...)` at import; lazy export resolves. |

### Integration Tests
| Test | Description |
|---|---|
| `test_dispatch_loop_over_target_humans` | manager `_dispatch_to_channel` calls `send_interaction` once per email in `target_humans`. |
| `test_escalate_button_routes_to_advance_chain` | submitting "↑ Escalar" → `receive_response` → `advance_chain(cause="reject")`. |
| `test_late_reply_after_expiry_acks` | reply after tombstone → in-thread "already expired" ack, no crash. |
| `test_lazy_import_isolation` | importing the teams channel does not import aiogram, and vice-versa. |

### Test Data / Fixtures
```python
@pytest.fixture
def teams_hitl_config():
    return TeamsHitlConfig(app_id="...", app_password="...", tenant_id="...",
                           graph_client_id="...", graph_client_secret="...",
                           graph_tenant_id="...", redis_url="redis://localhost/0")

@pytest.fixture
def fake_adapter():
    """Stub CloudAdapter recording continue_conversation/create_conversation calls."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `TeamsHumanChannel(HumanChannel)` implements every ABC member with `channel_type = "teams"` and `render_reject_button = True`.
- [ ] `recipient` is treated as an **email**; resolution via Graph `/users/{upn}` with mail-filter fallback (D4).
- [ ] Proactive 1:1 works for both warm (cached convref → `continue_conversation`) and cold (`create_conversation`) paths; sent activity stored under `hitl:teams:sent:{interaction_id}`.
- [ ] `send_notification` reuses the same 1:1 bootstrap, one-way, no reply wait (D2).
- [ ] All six `InteractionType` values render as Adaptive Cards with `interaction_id` in every `Action.Submit.data` (OQ-CARDS).
- [ ] Policy-bound interactions append the "↑ Escalar" action (`data.value == ESCALATE_OPTION_KEY`); manager routes it to `advance_chain`.
- [ ] `cancel_interaction` updates the prior card to a disabled state via cached `activity_id`; idempotent.
- [ ] On any resolution/delivery failure, `send_interaction` returns `False` (never hangs); cold-create failure surfaces as `False` so the engine advances (`action_failed`) — no runtime fallback (OQ-COLD).
- [ ] `ConversationReference` cache uses a long TTL refreshed on inbound contact; `serviceUrl` refreshed from latest activity, not pinned (OQ-4).
- [ ] `setup_teams_hitl(app, manager, config)` registers the channel as `"teams"` on the default manager; a per-agent `BotConfig` override path exists (OQ-9).
- [ ] `ChannelRegistry.register("teams", TeamsHumanChannel)` at import; `_LAZY_EXPORTS` entry added; importing the Teams channel does not import aiogram (and vice-versa).
- [ ] `[tool.uv] override-dependencies` resolves the `botbuilder`↔`aiogram` `emoji` clash; both channels import cleanly (D3).
- [ ] No secrets in code — all creds via navconfig/`${VAR}`.
- [ ] All unit + integration tests pass (`pytest packages/ai-parrot-integrations/tests/ -v`).
- [ ] Migration/usage doc added under `docs/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against the repo on 2026-05-29.

### Verified Imports
```python
from parrot.human.channels.base import HumanChannel, ESCALATE_OPTION_KEY, escalate_option  # base.py:16,19,47
from parrot.human.channels import ChannelRegistry                                          # channels/__init__.py:16
from parrot.human.models import HumanInteraction, HumanResponse, InteractionType, ChoiceOption  # models.py:359,427,39,80
from parrot.human import set_default_human_manager, get_default_human_manager              # human/__init__.py:63,69
from parrot.auth.context import UserContext                                                # auth/context.py:18
# Bot Framework (transitive via azure-teambots, v4.17.1 installed):
from botbuilder.core import TurnContext, ConversationState, MemoryStorage, UserState, BotFrameworkAdapterSettings
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.schema import Activity, ActivityTypes
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/human/channels/base.py
class HumanChannel(ABC):
    channel_type: ClassVar[str] = "base"            # line 74
    render_reject_button: ClassVar[bool] = False    # line 79
    async def start(self) -> None: ...              # line 83 (no-op default)
    async def stop(self) -> None: ...               # line 90 (no-op default)
    @abstractmethod
    async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool: ...  # line 100
    @abstractmethod
    async def send_notification(self, recipient: str, message: str) -> None: ...                   # line 119
    @abstractmethod
    async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool: ...           # line 132
    @abstractmethod
    async def register_response_handler(self, callback: ResponseCallback) -> None: ...             # line 151
    async def register_cancel_handler(self, callback: CancelCallback) -> None: ...                  # line 162 (no-op default)

ESCALATE_OPTION_KEY: str = "__escalate__"                          # base.py:16
def escalate_option() -> "ChoiceOption": ...                       # base.py:19 → ChoiceOption(key="__escalate__", label="↑ Escalar")  base.py:32

# packages/ai-parrot/src/parrot/human/channels/__init__.py
class ChannelRegistry:                                             # line 16
    @classmethod
    def register(cls, name: str, channel_cls: type) -> None: ...   # line 34

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:                                     # line 51
    async def is_valid_respondent(self, interaction_id: str, respondent: str) -> bool: ...  # line 222 (fails closed)
    def register_channel(self, name: str, channel: HumanChannel) -> None: ...               # line 252
    async def startup(self) -> None: ...                                                     # line 256 (registers response+cancel handlers on all channels)
    async def _dispatch_to_channel(self, interaction: HumanInteraction, channel: str) -> None: ...  # line 391
    #   line 411: for human_id in interaction.target_humans: await channel_impl.send_interaction(interaction, human_id)
    async def advance_chain(self, interaction_id: str, cause: Literal["timeout","reject","business_hours_off","action_failed"] = "timeout") -> None: ...  # line 521
    async def receive_response(self, response: HumanResponse) -> None: ...                   # line 580 (intercepts ESCALATE_OPTION_KEY)
    async def cancel_pending(self, interaction_id: str, reason: str = "user_cancelled") -> bool: ...  # line 693

# packages/ai-parrot/src/parrot/human/__init__.py
def set_default_human_manager(manager: Optional[HumanInteractionManager]) -> None: ...       # line 63
def get_default_human_manager() -> Optional[HumanInteractionManager]: ...                     # line 69
__path__ = extend_path(__path__, __name__)                                                   # line 12 (PEP 420)
_LAZY_EXPORTS = {"TelegramHumanChannel": ".channels.telegram"}                               # line 37-38 (add teams entry here)

# packages/ai-parrot/src/parrot/human/models.py
class InteractionType(str, Enum):  # line 39: FREE_TEXT, SINGLE_CHOICE, MULTI_CHOICE, APPROVAL, FORM, POLL
class ChoiceOption(BaseModel): ...  # line 80 (key, label, description, metadata)
class HumanInteraction(BaseModel):  # line 359
    interaction_type: InteractionType = InteractionType.FREE_TEXT   # line 367
    form_schema: Optional[Dict[str, Any]] = None                    # line 369
    target_humans: List[str] = Field(default_factory=list)          # line 373
    # FORM requires non-empty form_schema (validator, line 412); SINGLE/MULTI/POLL require options (line 416)
class HumanResponse(BaseModel): ...  # line 427 (interaction_id, respondent, response_type, value, timestamp, metadata)

# packages/ai-parrot/src/parrot/models/outputs.py
MSTEAMS = "msteams"  # OutputMode.MSTEAMS, line 67

# Reuse references (ai-parrot-integrations):
# packages/.../human/channels/telegram.py:54  class TelegramHumanChannel(HumanChannel)  (full reference impl)
# packages/.../human/channels/telegram.py:1141  ChannelRegistry.register("telegram", TelegramHumanChannel)
# packages/.../integrations/msteams/adapter.py:18  class Adapter(CloudAdapter)  (settings pattern to reuse)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TeamsHumanChannel` | `HumanChannel` | subclass | base.py:47 |
| `TeamsHumanChannel` | `ChannelRegistry.register` | import-time call | channels/__init__.py:34 |
| `TeamsHumanChannel.on_turn` | `manager.receive_response` | stored response_callback | manager.py:580 |
| escalate action | `manager.advance_chain` | ESCALATE_OPTION_KEY interception | manager.py:521,580 |
| `setup_teams_hitl` | `manager.register_channel` / `set_default_human_manager` | registration | manager.py:252 / human/__init__.py:63 |
| HITL adapter | `Adapter(CloudAdapter)` | settings construction pattern | msteams/adapter.py:18 |
| lazy export | `_LAZY_EXPORTS` | add `"TeamsHumanChannel"` | human/__init__.py:37 |

### Does NOT Exist (Anti-Hallucination)
> The brainstorm's §3.2 listed these as "vendored from azure_teambots", but the
> installed `azure-teambots>=0.1.1` exports **only** `AzureBots`. They must be
> built net-new or sourced from the private fork (OQ-VENDOR).
- ~~`azure_teambots.AdapterHandler`~~ — not in installed package (only `AzureBots`).
- ~~`azure_teambots.GraphClient` / `get_user_by_upn` / `get_user_manager` / `get_user_photo`~~ — do not exist; `GraphClient` is **net-new** (Module 1).

…(truncated)…
