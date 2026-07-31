---
type: Wiki Overview
title: FEAT-XXX — TeamsHumanChannel (HITL channel over MS Teams / Azure Bot Framework)
id: doc:sdd-proposals-hitl-teams-channel-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Graph / card / service helpers into `ai-parrot-integrations` as a Teams
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# FEAT-XXX — TeamsHumanChannel (HITL channel over MS Teams / Azure Bot Framework)

> **Status:** Brainstorm (pre-spec). Design-level only.
> Codebase contract (verified imports, exact Bot Framework signatures, line
> numbers) is deferred to `/sdd-spec`. Where a Bot Framework API is named
> below, treat it as "verify exact signature in spec".
>
> **Lives in:** `ai-parrot-integrations` satellite, contributing
> `parrot/human/channels/teams.py` into the shared namespace (same `extend_path`
> mechanism as `telegram.py`), registered via
> `ChannelRegistry.register("teams", TeamsHumanChannel)` at import time.
> The Bot Framework plumbing (adapter, Graph, cards, proactive 1:1) is
> **vendored** from `azure_teambots` into the satellite — not a dependency.

---

## 0. Resolved decisions (this session)

- **D1 — Vendor, don't depend (OQ-8).** Fork the `azure_teambots` adapter /
  Graph / card / service helpers into `ai-parrot-integrations` as a Teams
  bot-interaction module. Net-new: the proactive private 1:1 (bot ↔ manager)
  and its message send, which the upstream repo does not have.
- **D2 — NotifyAction over Teams in v1 (OQ-6).** `send_interaction` (card,
  awaits reply) and `send_notification` (text, fire-and-forget) **share one
  proactive 1:1 bootstrap**. NOTIFY is the same `create/continue_conversation`
  path without waiting for a reply.
- **D3 — botbuilder is a packaging hazard (OQ-7).** It hardcodes an `emoji`
  version that conflicts with aiogram (Telegram channel, same satellite).
  Mandatory: `[tool.uv] override-dependencies` to pin a compatible `emoji`,
  **and** strict lazy imports so using one channel never imports the other.
- **D4 — `target_humans` carries email (OQ-3/Q3).** Email is what the
  escalation chain designer actually knows. The channel resolves email → AAD
  user via Graph: `/users/{upn}` when email == UPN, else
  `/users?$filter=mail eq '...'`.
- **D5 — One shared HITL transport bot by default (OQ-1/Q1).** See §8.

---

## 1. Problem

We need a `HumanChannel` implementation for **MS Teams** so the HITL engine can
deliver interactions to humans over Teams, exactly as `TelegramHumanChannel`
does for Telegram. The driving use case (PTO escalation): an agent must **open a
private 1:1 chat with a manager the bot may have never spoken to**, ask a
question, and read the reply as the interaction result — with the existing
engine handling timeout, escalation, cancel, and audit.

This differs from the existing Teams *conversational* integration
(`MSTeamsAgentWrapper`, `MSTeamsHook`), which is **reactive**. Here the bot must
**initiate** (proactive 1:1) and **correlate** an out-of-band reply back to a
specific pending interaction.

---

## 2. The contract to satisfy (`HumanChannel` ABC)

`TeamsHumanChannel(HumanChannel)` must implement:

| Member | Role for Teams |
|---|---|
| `channel_type = "teams"` | identifier used by `ChannelRegistry` / tier `channel_type`. |
| `render_reject_button = True` | append `escalate_option()` ("↑ Escalar") to policy-bound interactions, as an Adaptive Card action. |
| `start()` / `stop()` | acquire/release the shared CloudAdapter, Graph client, Redis maps; no long-poll (Teams is webhook-driven). |
| `send_interaction(interaction, recipient) -> bool` | resolve `recipient` (email) → conversation, render an Adaptive Card, proactively post it. `True` on delivery. |
| `send_notification(recipient, message) -> None` | one-way proactive text — **same 1:1 bootstrap as send_interaction**, no reply expected (D2). |
| `cancel_interaction(interaction_id, recipient) -> bool` | `update_activity` the previously-sent card to a disabled "expired/withdrawn" state. Idempotent. |
| `register_response_handler(cb)` | store `manager.receive_response`; invoked when a manager submits a card. |
| `register_cancel_handler(cb)` | store `manager.cancel_pending`; invoked on a user-driven cancel. |

**Key contract fact:** the manager loops over `interaction.target_humans` and
calls `send_interaction(interaction, human_id)` once per human. `recipient` is a
**human identifier — an email (D4)** — NOT a conversation id. Resolving
email → Teams conversation is the channel's job (§5).

---

## 3. Reusable assets

### 3.1 From `ai-parrot`
- `HumanChannel` ABC, `escalate_option()` / `ESCALATE_OPTION_KEY`, `ChannelRegistry`.
- `UserContext(channel="msteams", user_id, email, metadata)`.
- `MSTeamsAgentWrapper` (conversational bot) + `MSTeamsHook` (Activity parsing:
  `from.id/name`, `conversation.id/conversationType`, `channelId`, `serviceUrl`,
  activity `id`, mention `entities`).
- `OutputMode.MSTEAMS` (Adaptive-Card rendering, suppresses code blocks).

### 3.2 Vendored from `azure_teambots` (D1)
- **`AdapterHandler(CloudAdapter)`** — `ConfigurationBotFrameworkAuthentication`
  + `BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)` + `on_error`.
- **`AzureBots` service** — aiohttp `/api/messages`, `MemoryStorage` /
  `UserState` / `ConversationState`, multi-bot config (`BotConfig`).
- **`GraphClient`** — `get_access_token`, `get_user_by_upn`,
  `get_user_manager(upn)`, `get_user_photo`. `get_user_manager`
  (`/users/{upn}/manager`) is the natural backend for the escalation
  `TargetResolver`; `get_user_by_upn` / mail-filter is the email→user resolver (D4).
- **`CardBot`** — `create_adaptive_card()` (`Input.ChoiceSet`, `Input.Text`,
  `Action.Submit` with `data:{...}`); card submit returns its payload in
  **`turn_context.activity.value`**. This is the correlation hook.

### 3.3 Net-new (not in the upstream repo)
- **Proactive 1:1 messaging.** `grep` finds no `ConversationReference`,
  `create_conversation`, `continue_conversation`, or `proactive` in
  `azure_teambots` — it is purely reactive. The bot-initiated 1:1 (and the
  `ConversationReference` lifecycle) is the core build (§4).

---

## 4. The new core: proactive 1:1 bootstrap + ConversationReference cache

Shared by `send_interaction` and `send_notification` (D2).

1. **Manager has DM'd the HITL bot before** → we captured a
   `ConversationReference` (`TurnContext.get_conversation_reference(activity)`)
   and cached it. Send = `adapter.continue_conversation(ref, callback,
   bot_app_id)`; post inside the callback.
2. **Manager never met the HITL bot** → construct it: create/get the 1:1 via the
   Teams path (`adapter.create_conversation(...)` / `POST /v3/conversations`
   with `members=[{id: manager_aad_id}]`, `tenantId`, `isGroup=false`,
   `bot=...`, `serviceUrl=...`), capture the reference, then post. *(Verify exact
   CloudAdapter API in spec — OQ-2.)*

**`ConversationReferenceStore` (Redis), new:**
```
hitl:teams:convref:{manager_email}  ->  serialized ConversationReference  (persistent)
```
Populated cache-on-contact (any inbound activity) and lazily via path (2).

**Activity→interaction map (Redis), new** — for cancel/update + cross-worker:
```
hitl:teams:sent:{interaction_id}  ->  {conversation_reference, activity_id, recipient}
```
`activity_id` (returned by the proactive `send_activity`) is needed for
`update_activity` on cancel/expire.

---

## 5. Recipient resolution (D4)

`recipient` is an **email**:
1. Cache hit on `convref:{email}` → use it.
2. Else Graph: `get_user_by_upn(email)`; if that 404s (email ≠ UPN), fall back
   to `/users?$filter=mail eq '{email}'`. Obtain AAD object id + serviceUrl.
3. Cache miss + no prior reference → cold create (path 2 of §4), subject to
   tenant policy (§7).

Role-based targeting ("manager") is resolved upstream by the escalation
`TargetResolver`, with `GraphClient.get_user_manager(employee_upn)` as its
backend — kept **out of the LLM**.

---

## 6. InteractionType → Adaptive Card, and reply correlation

Render per `interaction.interaction_type`, **embedding `interaction_id` in every
`Action.Submit.data`**:

| `InteractionType` | Card |
|---|---|
| `FREE_TEXT` | `Input.Text` (multiline) + Submit. |
| `APPROVAL` | two `Action.Submit` (Approve / Reject), `data.value` ∈ {approve, reject}. |
| `SINGLE_CHOICE` | `Input.ChoiceSet` (compact) + Submit. |
| `MULTI_CHOICE` | `Input.ChoiceSet` (`isMultiSelect=true`) + Submit. |
| `FORM` | `form_schema` → `Input.*` fields + Submit. |
| `POLL` | `Input.ChoiceSet` + Submit. |

Submit `data` carries `{"hitl": true, "interaction_id": "...", ...fields}`. When
`render_reject_button` is on and the interaction is policy-bound, append an
"↑ Escalar" action with `data.value = ESCALATE_OPTION_KEY` — `receive_response`
intercepts the sentinel and routes to `advance_chain`.

**Inbound demux** (simplified by D5 — the HITL bot is dedicated, so little/no
conversational traffic competes):
- `activity.value` present and `value.hitl is True` → **HITL reply**: build
  `HumanResponse(interaction_id=value["interaction_id"],
  respondent=<sender AAD id from activity>, value=<parsed fields>)` →
  stored `response_callback` (`manager.receive_response`).
- otherwise → ignore / generic ack (dedicated HITL bot has no agent flow).

Always send a card (even FREE_TEXT routes through `activity.value`), so
correlation stays deterministic with multiple pending interactions in one 1:1.

---

## 7. Edge cases

- **Tenant blocks bot-initiated 1:1 / bot not installed for the user.** A
  dedicated shared HITL bot (D5) needs **org-wide installation (admin app
  policy)** to DM arbitrary managers; otherwise cold `create_conversation`
  fails → `send_interaction` returns `False` → engine advances the chain
  (`action_failed`). This is a deployment prerequisite, not code.
- **Cache-on-contact is weaker under D5.** Because the HITL bot is a separate
  identity from any conversational bot, a manager who only ever chatted with a
  conversational agent has no convref for the HITL bot → cold create is the
  common path. Reinforces the org-install requirement.
- **Manager not provisioned / Graph lookup fails** → `send_interaction` returns
  `False` (never hang); fast-fail to next tier.
- **Multiple pending interactions in one 1:1** → disambiguated by
  `interaction_id` in submit data.
- **Late reply after timeout/expiry** → `hitl:result:{id}` tombstone exists;
  `receive_response` late-acks; channel replies in-thread "already expired".
- **Cancel / expire UX** → `update_activity` the original card (cached
  `activity_id`) to a disabled state so a stale card can't be submitted.
- **Respondent authz** → `respondent` = sender AAD id from the BF-validated
  activity (not from card payload); `is_valid_respondent` enforces membership in
  `target_humans` (resolved to AAD).
- **Cross-worker replies** → channel is stateless via the Redis maps (§4); the
  waiting side (HumanTool Future) uses poll/pubsub, owned by the escalation/PTO
  feature.
- **`serviceUrl` trust/rotation** → `AppCredentials.trust_service_url` before
  proactive send; refresh from latest inbound activity, don't pin.

---

## 8. HITL transport identity — one shared bot by default (D5, resolves OQ-1)

Two distinct identities were being conflated:

- **Conversational identity** — the bot the *end user* chats with
  (`MSTeamsAgentWrapper`). May be per-agent (branding/purpose). **Out of scope
  here.**
- **HITL transport identity** — the bot that DMs the *manager* to relay a
  question. A pure relay; it need not be any agent's identity.

**Decision:** a **single shared HITL bot**, process/app-level singleton, **by
default**. One APP_ID, one `/api/messages`, one Graph cred set, one convref
cache. Configured once at boot via a `setup_teams_hitl(app, manager, config)`
helper (analogous to `set_default_human_manager` / `setup_telemetry()`), and
registered as the `"teams"` channel on the default `HumanInteractionManager`.

A per-agent override is allowed but rare: an agent may pass its own `BotConfig`
to present a distinct HITL identity (e.g. an HR-branded bot). Wiring: default
`"teams"` channel + optional keyed channels for overrides.

**Why this beats the earlier A/B framing:** the HITL bot is *dedicated* (so the
inbound demux faces no conversational traffic — the §6 simplification) **and**
*shared* (so no per-agent bot proliferation). Best of both. Cost: the
deployment prerequisites in §7 (org-wide install, cold-create reliance).

---

## 9. Configuration (`navconfig` / `parrot.conf`)

- `MSTEAMS_HITL_APP_ID`, `MSTEAMS_HITL_APP_PASSWORD` (the shared HITL bot).
- `MSTEAMS_TENANT_ID` (single-tenant) or multi-tenant handling.
- Graph app creds (`client_id/secret/tenant`) with `User.Read.All` for
  `get_user_manager` / mail-filter lookups — may differ from bot creds.
- Redis URL (shared with the manager) for convref / sent maps.
- `[tool.uv] override-dependencies` for the botbuilder↔aiogram `emoji` clash (D3).
- `${VAR_NAME}` injection; no hardcoded secrets.

---

## 10. Dependencies & out of scope

- **Targeting-by-role / `TargetResolver`** → escalation brainstorm (this channel
  consumes a resolved email; offers `get_user_manager` as the resolver backend).
- **Proactive escalation driver (qworker sweep)** → escalation brainstorm.
- **BLOCK-vs-suspend wait** for the user-facing turn → PTO/escalation feature.

The channel is **reusable standalone**: any agent or flow can target Teams for
HITL, independent of escalation.

---

## 11. Open questions remaining for `/sdd-spec`

- **OQ-2:** Exact CloudAdapter proactive API for a cold 1:1
  (`create_conversation` parameters vs a `TeamsInfo`-assisted flow); confirm
  against the botbuilder version vendored from `azure_teambots`.
- **OQ-4:** `ConversationReference` serialization format & TTL in Redis.
- **OQ-5:** `form_schema` → Adaptive Card field mapping (which `Input.*` types,
  validation, required fields).
- **OQ-9 (new):** Override wiring — keyed channels (`"teams"` default +
  `"teams:{agent}"`) vs a per-agent `BotConfig` passed at tool/agent
  construction. How a tier's `channel_type` selects the override.

*Resolved this session: OQ-1 (→§8/D5), OQ-3 (→D4), OQ-6 (→D2), OQ-7 (→D3),
OQ-8 (→D1).*
