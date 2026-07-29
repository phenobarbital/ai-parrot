---
type: Wiki Overview
title: 'Brainstorm: TeamsHumanChannel — HITL channel over MS Teams / Azure Bot Framework'
id: doc:sdd-proposals-hitl-teams-channel-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The HITL engine can already deliver interactions to humans over Telegram
relates_to:
- concept: mod:parrot.auth.context
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: TeamsHumanChannel — HITL channel over MS Teams / Azure Bot Framework

**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

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

**Who is affected:** end users (managers receiving HITL prompts in Teams),
agent/flow developers (who target Teams for HITL), and ops (who must satisfy the
Teams app-install deployment prerequisite).

## Constraints & Requirements

- **Must satisfy the `HumanChannel` ABC** exactly as `TelegramHumanChannel`
  does — same method contract, same registry registration, same
  manager-driven dispatch loop over `interaction.target_humans`.
- **`recipient` is an email** (decision D4). The channel resolves email → AAD
  user via Microsoft Graph; it never receives a conversation id directly.
- **Proactive 1:1 is the core net-new capability.** The repo currently has
  **no** `ConversationReference` capture, `continue_conversation`, or
  `create_conversation` anywhere (verified — see Code Context).
- **Async-first**, `aiohttp` only (no `requests`/`httpx`), `self.logger`,
  Pydantic models, Google-style docstrings + type hints.
- **Lives in the `ai-parrot-integrations` satellite**, contributing
  `parrot/human/channels/teams.py` into the shared `parrot.*` namespace via the
  same PEP 420 `extend_path` + lazy-import mechanism as `telegram.py`.
- **Packaging hazard (D3):** `botbuilder` (Teams) and `aiogram` (Telegram) live
  in the *same* satellite and `botbuilder` pins a conflicting `emoji` version.
  Requires `[tool.uv] override-dependencies` **and** strict lazy imports so
  importing one channel never imports the other.
- **No secrets in code** — `${VAR_NAME}` / navconfig injection only.
- **Deployment prerequisite (accepted, D-cold):** org-wide admin app install so
  the shared HITL bot may DM arbitrary managers. On its absence, cold create
  fails, `send_interaction` returns `False`, and the engine advances the chain
  (`action_failed`). **No code fallback in v1.**

---

## Options Explored

### Option A: Dedicated shared HITL transport bot with proactive 1:1 + ConversationReference cache *(recommended)*

A single, process-level **dedicated** HITL bot identity (its own APP_ID,
`/api/messages`, Graph cred set, convref cache) wired once at boot via a
`setup_teams_hitl(app, manager, config)` helper and registered as the `"teams"`
channel on the default `HumanInteractionManager`. The channel:

1. Resolves `recipient` (email) → AAD user via a **net-new minimal `GraphClient`**
   (`/users/{upn}`, falling back to `/users?$filter=mail eq '...'`).
2. Sends proactively: cache hit on a stored `ConversationReference` →
   `adapter.continue_conversation(ref, callback, bot_app_id)`; cache miss →
   cold `create_conversation` to bootstrap the 1:1, capture the reference, post.
3. Renders the interaction as an **Adaptive Card** with `interaction_id`
   embedded in every `Action.Submit.data`.
4. Demuxes inbound card submits (`activity.value.hitl is True`) into
   `HumanResponse` and routes to the manager's `receive_response`.

Because the bot is *dedicated*, the inbound demux faces no conversational
traffic (the §6 simplification); because it is *shared*, there is no per-agent
bot proliferation. A per-agent `BotConfig` override (decision D-override) lets a
tier present a distinct HITL identity (e.g. HR-branded) when needed.

✅ **Pros:**
- Mirrors the proven `TelegramHumanChannel` shape — lowest conceptual friction
  for the engine and for maintainers.
- Clean separation of HITL transport identity from conversational identity.
- One convref cache, one cred set, one webhook → simplest demux.
- Reuses the existing `Adapter(CloudAdapter)` pattern (`msteams/adapter.py`).

❌ **Cons:**
- Cold-create reliance is heavy: a dedicated identity means most managers have
  **no** prior convref, so org-wide install is effectively mandatory.
- Proactive 1:1 (`ConversationReference` lifecycle, cold create) is net-new and
  the riskiest part — exact CloudAdapter API must be verified in spec (OQ-2).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `botbuilder-core` / `botbuilder-integration-aiohttp` | CloudAdapter, TurnContext, proactive `continue_conversation`/`create_conversation` | v4.17.1, transitive via `azure-teambots`; verify proactive API in spec |
| `azure-teambots` (private fork) | Vendored adapter/cards/service helpers | `>=0.1.1` declared; **public PyPI build only exports `AzureBots`** — fork contents to confirm in spec |
| `aiohttp` | Graph HTTP + `/api/messages` webhook | async-only, per project rules |
| `redis` (async) | convref + sent-activity maps | shared with the manager |
| `[tool.uv] override-dependencies` | pin `emoji` to resolve botbuilder↔aiogram clash | D3 — mandatory |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/human/channels/base.py:47` — `HumanChannel` ABC (the contract).
- `packages/ai-parrot/src/parrot/human/channels/base.py:16,19` — `ESCALATE_OPTION_KEY` / `escalate_option()`.
- `packages/ai-parrot/src/parrot/human/channels/__init__.py:34` — `ChannelRegistry.register()`.
- `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py:54` — full reference implementation (correlation, registry hook, lazy import).
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18` — `Adapter(CloudAdapter)` settings pattern.
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:920` — `_build_adaptive_card()` card-building reference.
- `packages/ai-parrot/src/parrot/human/__init__.py:42` — `_LAZY_EXPORTS` lazy-import pattern (add `TeamsHumanChannel`).

---

### Option B: Piggyback on the existing conversational bot identity

Instead of a separate identity, reuse `MSTeamsAgentWrapper`'s adapter, webhook
(`/api/teambots/{id}/messages`) and credentials. The HITL channel captures a
`ConversationReference` from the conversational bot's turns and sends HITL
cards through that same bot.

✅ **Pros:**
- Managers who already chat with the agent's bot have a **warm convref** → fewer
  cold creates, lighter install requirement.
- Single bot identity to provision/operate.

❌ **Cons:**
- Conflates conversational and HITL identities (the §8 anti-pattern); inbound
  demux must now distinguish HITL submits from ordinary agent traffic.
- Per-agent: every conversational bot would need HITL wiring, re-introducing
  bot proliferation.
- A manager who never chatted with *that* agent's bot still needs cold create —
  so it doesn't actually remove the prerequisite, only narrows it.
- Couples the HITL channel's lifecycle to each agent wrapper's lifecycle.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same `botbuilder` stack as Option A; no separate cred set.

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py:56,332,367` — wrapper, webhook, `on_message_activity` (convref capture point).

---

### Option C: Graph-driven delivery (no Bot Framework proactive) — *unconventional*

Bypass Bot Framework proactive entirely. Deliver the Adaptive Card via
**Microsoft Graph**: `POST /chats` (create a 1:1 `oneOnOne` chat with the
manager) then `POST /chats/{id}/messages` with an attached card; OR fall back to
**Outlook Actionable Messages** (an actionable Adaptive Card delivered by
email), which needs no Teams bot install at all. Replies arrive via a Graph
change-notification subscription (webhook) or the Actionable Message action
endpoint.

✅ **Pros:**
- Sidesteps the bot-install / cold-`create_conversation` prerequisite — the
  biggest operational risk in Options A/B.
- Actionable Messages reach managers even when Teams adoption is partial (email
  is universal).
- Pure HTTP/Graph — fits the async aiohttp stack with no botbuilder proactive API.

❌ **Cons:**
- Diverges sharply from the `TelegramHumanChannel` shape; least code reuse.
- Graph chat-message send + change-notification subscriptions are their own
  large surface (subscription lifecycle, validation tokens, renewal).
- Actionable Messages have strict provider registration and card-schema limits;
  correlation/security model differs from Bot Framework's validated activities.
- Respondent authz no longer rides on BF-validated `activity.from.id`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | Graph chat/message + subscriptions | async-only |
| Microsoft Graph `chats`/`subscriptions` | delivery + reply notifications | needs `Chat.Create`, `ChatMessage.Send`, change-notification infra |
| Actionable Message provider | email-delivered cards | separate registration; out-of-Teams reach |

🔗 **Existing Code to Reuse:**
- Minimal — only the `HumanChannel` ABC and models. Card-building logic could be
  shared with Option A.

---

## Recommendation

**Option A** is recommended.

It is the only option that preserves the proven `HumanChannel` shape end-to-end
(dispatch loop, registry, response/cancel callbacks, escalate-button
interception), which keeps the engine untouched and makes the channel a true
peer of `TelegramHumanChannel`. The dedicated-but-shared identity (D5) gives the
best of both framings: a clean inbound demux (no conversational traffic to
disambiguate) **and** no per-agent bot sprawl.

The tradeoff we accept is the **cold-create / org-wide-install dependency** —
Option B would soften it only partially while reintroducing identity conflation,
and Option C would remove it only by taking on the much larger Graph
subscription / Actionable Message surface and abandoning code reuse. Per your
decision, org-wide install is a **documented deployment prerequisite** and the
channel **fails fast** (returns `False`, engine advances the tier) rather than
shipping a v1 fallback path. Graph-driven delivery (Option C) remains a credible
**v2 escape hatch** if the install prerequisite proves untenable in the field.

---

## Feature Description

### User-Facing Behavior
A manager receives a private 1:1 message from the HITL bot in Teams containing
an **Adaptive Card** appropriate to the interaction type (approve/reject
buttons, a text box, a choice set, a form, etc.). When policy-bound, the card
also carries an **"↑ Escalar"** action. The manager taps/submits; the card's
submission is read as the interaction result. If the interaction is cancelled or
expires, the original card is updated in place to a disabled
"expired/withdrawn" state so a stale card can't be submitted. A reply that
arrives after expiry gets an in-thread "already expired" acknowledgement.

### Internal Behavior
- **`start()/stop()`**: acquire/release the shared `CloudAdapter`, `GraphClient`
  and Redis maps. No long-poll — Teams is webhook-driven via `/api/messages`.
- **`send_interaction(interaction, recipient)`**: resolve email → AAD via Graph
  → obtain/construct a `ConversationReference` (cache hit → `continue_conversation`;
  miss → cold `create_conversation`, capture ref) → render the card with
  `interaction_id` in every `Action.Submit.data` → post → store
  `{convref, activity_id, recipient}` under `hitl:teams:sent:{interaction_id}`.
  Returns `True` on delivery.
- **`send_notification(recipient, message)`**: the **same 1:1 bootstrap** (D2),
  one-way text, no reply expected.
- **`cancel_interaction(interaction_id, recipient)`**: `update_activity` the
  previously-sent card (via cached `activity_id`) to a disabled state.
  Idempotent.
- **Inbound demux** (webhook): `activity.value.hitl is True` → build
  `HumanResponse(interaction_id=value["interaction_id"], respondent=<sender AAD
  id from the BF-validated activity>, value=<parsed fields>)` → invoke the
  stored `response_callback` (`manager.receive_response`). The
  `ESCALATE_OPTION_KEY` sentinel is intercepted by the manager and routed to
  `advance_chain`. Any inbound activity also refreshes the convref cache
  (cache-on-contact) and the `serviceUrl`.
- **Identity**: one shared HITL bot by default; a per-agent `BotConfig`
  (decision D-override) presents a distinct HITL identity when a tier requests
  it.

### Edge Cases & Error Handling
- **Tenant blocks bot-initiated 1:1 / bot not installed** → cold create fails →
  `send_interaction` returns `False` → engine advances (`action_failed`). Doc'd
  deployment prerequisite, no code fallback (v1).
- **Manager not provisioned / Graph lookup fails** → return `False`, never hang.
- **Multiple pending interactions in one 1:1** → disambiguated by
  `interaction_id` in submit data; always send a card (even FREE_TEXT) so
  correlation is deterministic.
- **Late reply after timeout/expiry** → `hitl:result:{id}` tombstone exists;
  late-ack in-thread.
- **Respondent authz** → `respondent` taken from BF-validated `activity.from.id`,
  not card payload; `manager.is_valid_respondent` enforces `target_humans`
  membership (resolved to AAD).
- **Cross-worker replies** → channel is stateless via Redis maps; the waiting
  side (HumanTool Future) is owned by the escalation/PTO feature.
- **`serviceUrl` trust/rotation** → `AppCredentials.trust_service_url` before
  proactive send; refresh from latest inbound activity, don't pin.

---

## Capabilities

### New Capabilities
- `hitl-teams-channel`: `TeamsHumanChannel(HumanChannel)` delivering HITL
  interactions over MS Teams via proactive 1:1 + Adaptive Cards, registered as
  the `"teams"` channel.
- `teams-proactive-messaging`: net-new `ConversationReference` capture/cache and
  proactive `continue_conversation`/`create_conversation` 1:1 bootstrap (the
  core build; nothing equivalent exists in the repo).
- `teams-graph-client`: minimal net-new async `GraphClient` for email→AAD
  resolution (`/users/{upn}` + mail-filter) and `get_user_manager` (offered as
  the escalation `TargetResolver` backend).

### Modified Capabilities
- `ai-parrot-integrations` packaging: add the `botbuilder`↔`aiogram` `emoji`
  override and strict lazy imports (D3).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/human/channels/` (core) | extends | add `TeamsHumanChannel` to `ChannelRegistry`; add `_LAZY_EXPORTS` entry in `human/__init__.py:42`. |
| `ai-parrot-integrations` satellite | adds | new `src/parrot/human/channels/teams.py` + vendored BF plumbing + `GraphClient`. |
| `ai-parrot-integrations/pyproject.toml` | modifies | `[tool.uv] override-dependencies` for `emoji`; confirm `azure-teambots` fork. |
| `HumanInteractionManager` | depends on | no change to manager code; channel plugs into existing `_dispatch_to_channel`/`startup` flow. |
| `msteams/adapter.py` | reuses | `Adapter(CloudAdapter)` settings pattern. |
| navconfig / `parrot.conf` | adds | `MSTEAMS_HITL_APP_ID/PASSWORD`, `MSTEAMS_TENANT_ID`, Graph app creds (`User.Read.All`), Redis URL. |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/human/channels/base.py:47
class HumanChannel(ABC):
    channel_type: ClassVar[str] = "base"            # line 74
    render_reject_button: ClassVar[bool] = False    # line 79
    async def start(self) -> None: ...              # line 83
    async def stop(self) -> None: ...               # line 90
    @abstractmethod
    async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool: ...   # line 100
    @abstractmethod
    async def send_notification(self, recipient: str, message: str) -> None: ...                    # line 119
    @abstractmethod
    async def cancel_interaction(self, interaction_id: str, recipient: str) -> bool: ...            # line 132
    @abstractmethod
    async def register_response_handler(self, callback: ResponseCallback) -> None: ...              # line 151
    async def register_cancel_handler(self, callback: CancelCallback) -> None: ...                   # line 162

# From packages/ai-parrot/src/parrot/human/channels/base.py:16,19
ESCALATE_OPTION_KEY: str = "__escalate__"
def escalate_option() -> "ChoiceOption":  # ChoiceOption(key="__escalate__", label="↑ Escalar")
    ...

# From packages/ai-parrot/src/parrot/human/channels/__init__.py:16,34
class ChannelRegistry:
    _channels: dict[str, type] = {}
    @classmethod
    def register(cls, name: str, channel_cls: type) -> None: ...

# From packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py:54  (reference impl)
class TelegramHumanChannel(HumanChannel):
    channel_type = "telegram"
    render_reject_button = True
    def __init__(self, bot: Any, redis: Any, token_ttl: int = 86400, parse_mode: str = "Markdown") -> None: ...
    async def send_interaction(self, interaction: HumanInteraction, recipient: str) -> bool: ...   # line 189
# auto-registers at module bottom: ChannelRegistry.register("telegram", TelegramHumanChannel)  (~line 1140)

# From src/parrot/human/manager.py (HumanInteractionManager)
class HumanInteractionManager:
    async def receive_response(self, response: HumanResponse) -> None: ...        # line 580; intercepts ESCALATE_OPTION_KEY (607-621)
    async def cancel_pending(self, interaction_id: str, reason: str = "user_cancelled") -> bool: ...  # line 693
    async def advance_chain(self, interaction_id: str, cause: Literal["timeout","reject","business_hours_off","action_failed"] = "timeout") -> None: ...  # line 521
    async def _dispatch_to_channel(self, interaction: HumanInteraction, channel: str) -> None: ...    # line 391; loops: for human_id in interaction.target_humans: await channel_impl.send_interaction(interaction, human_id)
    async def is_valid_respondent(self, interaction_id: str, respondent: str) -> bool: ...            # line 222 (fails closed)
    def register_channel(self, name: str, channel: HumanChannel) -> None: ...                          # line 252
    async def startup(self) -> None: ...   # line 256; calls register_response_handler(self.receive_response) + register_cancel_handler(self.cancel_pending)

# From packages/ai-parrot/src/parrot/human/models.py:39
class InteractionType(str, Enum):
    FREE_TEXT = "free_text"; SINGLE_CHOICE = "single_choice"; MULTI_CHOICE = "multi_choice"
    APPROVAL = "approval"; FORM = "form"; POLL = "poll"

# From packages/ai-parrot/src/parrot/human/models.py:359
class HumanInteraction(BaseModel):
    interaction_id: str                       # default_factory uuid4
    question: str
    interaction_type: InteractionType = InteractionType.FREE_TEXT
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None
    target_humans: List[str] = []             # the recipients the manager loops over (emails, per D4)
    timeout: float = 7200.0
    policy_id / policy / current_tier_level / severity / channel ...

# From packages/ai-parrot/src/parrot/human/models.py:427
class HumanResponse(BaseModel):
    interaction_id: str; respondent: str; response_type: InteractionType; value: Any
    timestamp: datetime; metadata: Dict[str, Any]

# From packages/ai-parrot/src/parrot/auth/context.py:18
@dataclass(frozen=True)
class UserContext:
    channel: str; user_id: str; display_name: Optional[str] = None
    email: Optional[str] = None; session_id: Optional[str] = None; metadata: Dict[str, Any] = {}

# From packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18  (reuse pattern)
class Adapter(CloudAdapter):
    # ConfigurationBotFrameworkAuthentication + BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
    ...
```

#### Verified Imports
```python
# Confirmed to work:
from parrot.human.channels.base import HumanChannel, ESCALATE_OPTION_KEY, escalate_option
from parrot.human.channels import ChannelRegistry
from parrot.human.models import HumanInteraction, HumanResponse, InteractionType, ChoiceOption
from parrot.auth.context import UserContext
# Bot Framework (transitive via azure-teambots, v4.17.1 installed):
from botbuilder.core import TurnContext, ConversationState, MemoryStorage, UserState, BotFrameworkAdapterSettings
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botbuilder.schema import Activity, ActivityTypes
# Namespace mechanism (add TeamsHumanChannel here):
# packages/ai-parrot/src/parrot/human/__init__.py:42  _LAZY_EXPORTS = {"TelegramHumanChannel": ".channels.telegram"}
```

#### Key Attributes & Constants
- `OutputMode.MSTEAMS` → `"msteams"` (packages/ai-parrot/src/parrot/models/outputs.py:67) — Adaptive-Card render mode.
- Existing Teams webhook route pattern: `/api/teambots/{id}/messages` (msteams/wrapper.py:134).
- `azure-teambots>=0.1.1` declared at `packages/ai-parrot-integrations/pyproject.toml:42` (msteams extra).
- `aiogram>=3.12` at `packages/ai-parrot-integrations/pyproject.toml:39` (the `emoji`-clash counterpart).

### Does NOT Exist (Anti-Hallucination)
> ⚠️ The proposal's §3.2 lists these as "vendored from `azure_teambots`", but
> **none of them exist** in this repo or in the installed `azure-teambots`
> (PyPI build of `azure-teambots>=0.1.1` exports only `AzureBots`). They must
> be **built net-new or sourced from the private fork** (vendor scope: confirm
> in spec).
- ~~`azure_teambots.AdapterHandler`~~ — not in installed package (only `AzureBots`).
- ~~`azure_teambots.GraphClient` / `get_user_by_upn` / `get_user_manager` / `get_user_photo`~~ — do not exist; `GraphClient` is **net-new** (your decision).
- ~~`azure_teambots.CardBot` / `create_adaptive_card`~~ — do not exist; the existing card-builder is `MSTeamsAgentWrapper._build_adaptive_card()` (wrapper.py:920).
- ~~`ConversationReference` / `continue_conversation` / `create_conversation` / `get_conversation_reference` usage~~ — **not present anywhere in the repo**; proactive 1:1 is entirely net-new (the core build).
- ~~`MSTeamsHook` proactive send~~ — `MSTeamsHook` (core/hooks/messaging.py:186) is reactive only.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Three buildable units — (1) `GraphClient`
  (email→AAD, get_user_manager), (2) proactive 1:1 + `ConversationReference`
  cache, (3) Adaptive-Card rendering per `InteractionType`. (1) and (3) are
  largely independent; (2) is the spine that the channel's `send_interaction`
  depends on, so the final `TeamsHumanChannel` assembly + packaging (`emoji`
  override, lazy imports, registry/lazy-export wiring) must land last.
- **Cross-feature independence**: New file `teams.py` in the satellite — no
  conflict with `telegram.py`. Touches `human/__init__.py:42` (`_LAZY_EXPORTS`)
  and `ai-parrot-integrations/pyproject.toml`, both shared with the Telegram
  channel — coordinate to avoid merge churn. No conflict with core
  `manager.py`/`base.py` (consumed, not modified).
- **Recommended isolation**: `per-spec` — tasks are tightly coupled through the
  proactive-messaging spine and share the packaging/wiring touch-points;
  sequential execution in one worktree avoids `pyproject.toml`/`__init__.py`
  contention.
- **Rationale**: The risk concentrates in one place (proactive 1:1 against an

…(truncated)…
