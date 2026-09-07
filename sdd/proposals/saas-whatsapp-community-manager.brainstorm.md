---
type: feature
base_branch: dev
---

# Brainstorm: WhatsApp Business management for the SaaS plane

**Date**: 2026-08-09
**Author**: Jesus Lara (investigation by Claude)
**Status**: exploration
**Recommended Option**: Option B
**Related**: `saas-hitl-escalation.brainstorm.md` (the human-handoff half)

---

## Problem Statement

A hospitality tenant wants their WhatsApp Business number answered
autonomously — bookings, hours, menu questions, offers — with a clean escape
hatch to a human when the guest asks for one or the agent is out of its depth.

WhatsApp support in this repository is **not one integration but three**, built
at different times for different purposes, with no shared abstraction. Picking
one and knowing why matters more than writing new code: two of the three are
unsuitable for a multi-tenant SaaS for reasons that are not obvious from the
outside.

## What already exists (verified)

### Path 1 — Meta Cloud API via `pywa`

`packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/`:

| File | Role |
|---|---|
| `models.py` | `WhatsAppAgentConfig` dataclass |
| `wrapper.py` | `WhatsAppAgentWrapper` — the Cloud API wrapper (~362 lines) |
| `handler.py` | `WhatsAppUserSession` — per-user session + 24h window |
| `utils.py` | markdown→WhatsApp conversion, message splitting, phone sanitising |

- Runs `pywa` in *custom server mode* (`server=None`) with routes served by
  aiohttp. Default path `/api/whatsapp/{chatbot_id}/webhook`; the wrapper
  registers its own GET (Meta `hub.challenge`) and POST routes in `__init__`
  and calls `app["auth"].add_exclude_list(route)`.
- Inbound dispatch runs in a module-level `ThreadPoolExecutor(max_workers=4)`
  because **pywa's dispatch is synchronous** — a genuine impedance mismatch
  with the rest of the async stack, and a hard capacity ceiling.
- `_process_message` → `agent.ask(text, memory=..., output_mode=OutputMode.WHATSAPP,
  session_id=sender, user_id=sender)`.
- Outbound: `send_message`, `send_image`, `send_document`, each via
  `run_in_executor`.
- Config falls back to env vars `{NAME_UPPER}_WHATSAPP_{PHONE_ID|TOKEN|...}`.

### Path 2 — whatsmeow Go bridge

`bridge_wrapper.py` + `services/whatsapp-bridge/` (`main.go`, Dockerfile).
Drives a **personal** WhatsApp account by QR pairing rather than the Business
Cloud API. Text only — no image or document sending. Fire-and-forget inbound
(`asyncio.create_task`), returns `{"status":"ok"}` immediately. Handles
`/clear` and `/help`.

### Path 3 — Redis pub/sub hook

`packages/ai-parrot/src/parrot/core/hooks/whatsapp_redis.py`,
`WhatsAppRedisHook(BaseHook)` (~339 lines). Subscribes to `whatsapp:messages`,
filters by `allowed_phones` / `allowed_groups` / `command_prefix`. **This is the
only path with content-based routing**: a `routes` list matches on keywords or
phone numbers and overrides `target_id`/`target_type`, feeding
`AutonomousOrchestrator`. Admin surface in
`packages/ai-parrot-server/src/parrot/services/whatsapp.py` (~1337 lines):
dashboard, QR, status, disconnect, hook CRUD, send, stats.

### Outbound tool

`packages/ai-parrot-tools/src/parrot_tools/messaging/whatsapp.py` —
`WhatsAppTool(AbstractTool)`, `name="send_whatsapp"`, sends through the bridge.

### The gaps that matter for a SaaS

1. **No human handoff.** There is no `WhatsAppHumanChannel`. The HITL framework
   ships CLI, Web, Telegram and Teams channels only, and neither WhatsApp
   wrapper imports anything from `parrot.human`. The only escape hatches are
   `/clear` and `/help` (bridge path only) and the keyword `routes` in the Redis
   hook — which routes bot→bot, never bot→human.
2. **Conversation memory is not persisted.** Both wrappers hardcode
   `InMemoryConversation()`; a restart loses every conversation. `RedisConversation`
   exists in `parrot/memory/redis.py` and is simply not wired in.
3. **Static 1:1 agent binding on the official path.** One wrapper per YAML
   entry, resolved once at startup from `BotManager.get_bot(chatbot_id)`. No
   dynamic routing, and no notion of a tenant.
4. **No common base class across integration wrappers.** `WhatsAppAgentWrapper`,
   `TelegramAgentWrapper`, `MSTeamsAgentWrapper`, `SlackAgentWrapper` and
   `MSAgentSDKWrapper` share only *convention*: constructor shape
   `(agent, config, app)`, self-registered routes, `parse_response()`
   normalisation, and the `agent.ask(...)` call. Anything built for one does not
   transfer.
5. **Startup is all-or-nothing.** `IntegrationBotConfig.validate()` aborts
   startup of *every* bot if any YAML entry is invalid — unacceptable when
   tenants self-serve their own credentials.

---

## Constraints & Requirements

- Per-tenant WhatsApp credentials (`phone_id`, `token`, `verify_token`,
  `app_secret`) must come from the `SecretStore`, not YAML and not env vars.
- One tenant's bad or expired credentials must not prevent other tenants from
  starting — the current fail-everything validation is disqualifying as-is.
- Conversation state must survive restarts.
- Human handoff is a requirement, not a nice-to-have, for hospitality.
- Meta's 24-hour customer-service window governs when a free-form message may
  be sent; `WhatsAppUserSession.is_within_24h_window` already models it and
  must gate outbound coupon delivery.

---

## Options Explored

### Option A: Multi-tenant the existing `WhatsAppAgentWrapper`

Extend the Cloud API wrapper with a tenant dimension: route per tenant, resolve
credentials from the `SecretStore`, swap in `RedisConversation`.

✅ **Pros:** smallest diff; keeps the Meta-official path.

❌ **Cons:** inherits the synchronous `pywa` dispatch and its thread pool; the
wrapper self-registers routes in `__init__`, which fits a fixed startup list and
not dynamic tenant onboarding; still no human channel.

📊 **Effort:** Medium.

### Option B: A tenant-aware WhatsApp *port* with the Cloud API as first adapter — RECOMMENDED

Define a `MessagingChannel` port in `parrot_saas` (inbound webhook →
normalised event; outbound send; session/window awareness), implement it over
the Meta Cloud API, and drive it from a `whatsapp_conversation` AgentsFlow that
reuses the Community Manager's node conventions. Register **one** webhook route
with a `{tenant_id}` path segment rather than one route per tenant.

✅ **Pros:** onboarding a tenant becomes a database row, not a route
registration; credentials resolve per request from the `SecretStore`; a bad
tenant fails alone; the same port later accepts the bridge or another provider;
handoff is a node, not a bolt-on.

❌ **Cons:** genuinely new code, and it deliberately does not reuse
`WhatsAppAgentWrapper` — the duplication has to be justified and the old path
eventually retired.

📊 **Effort:** Medium-High.

🔗 **Existing Code to Reuse:**
- `integrations/whatsapp/utils.py` — markdown conversion, splitting, phone
  sanitising: provider-agnostic and directly reusable
- `integrations/whatsapp/handler.py` — `WhatsAppUserSession.is_within_24h_window`
- `integrations/parser.py` — `parse_response` / `ParsedResponse`
- `parrot/memory/redis.py` — `RedisConversation`, the persistence that is
  missing today
- `parrot/human/escalation_intent.py` — `RejectIntentDetector`, which is exactly
  the "I want to talk to a human" detector this needs

### Option C: Adopt the Redis-hook orchestrator path

Route everything through `WhatsAppRedisHook` + `AutonomousOrchestrator`.

✅ **Pros:** already has content-based routing and a live admin UI.

❌ **Cons:** built around the personal-account bridge, not the Business API;
its routing targets agents/crews, not tenants; the admin surface assumes a
single operator.

📊 **Effort:** Medium — but it optimises for the wrong axis.

---

## Open Questions

- [ ] Cloud API only, or must the whatsmeow bridge stay supported? The bridge
      uses a personal account, which is against WhatsApp's terms for business
      messaging at scale — worth an explicit decision rather than drift.
- [ ] Does each tenant bring their own Meta app (own `app_id`/`app_secret`), or
      does the platform own one app with tenants adding phone numbers? This
      changes the onboarding flow and the webhook signature verification.
- [ ] Template-message management for out-of-window sends: platform-level or
      per tenant?
- [ ] Retire `WhatsAppAgentWrapper`, or keep it for single-tenant deployments?

## Recommendation

Option B, sequenced after the HITL channel work — a WhatsApp agent without a
human handoff is not shippable for hospitality, and the handoff is the part
with no existing implementation to lean on.
