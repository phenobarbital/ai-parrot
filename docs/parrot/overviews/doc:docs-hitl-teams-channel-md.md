---
type: Wiki Overview
title: Teams HITL Channel Setup Guide (FEAT-205)
id: doc:docs-hitl-teams-channel-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: Human-in-the-Loop over Microsoft Teams — setup, deployment prerequisites,
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.teams
  rel: mentions
---

# Teams HITL Channel Setup Guide (FEAT-205)

Human-in-the-Loop over Microsoft Teams — setup, deployment prerequisites,
and usage reference.

---

## Overview

`TeamsHumanChannel` extends the AI-Parrot HITL engine to deliver
interactions (approvals, free-text questions, choice polls, forms) to
humans via Microsoft Teams **private 1:1 chats**, rendered as Adaptive
Cards.  It mirrors the `TelegramHumanChannel` in functionality but uses
the Azure Bot Framework for transport.

Key design decisions:
- A **single, shared HITL bot identity** per process (dedicated, not the
  conversational `MSTeamsAgentWrapper` bot).
- Recipient is always an **email address**; the channel resolves it to an
  AAD object ID via Microsoft Graph.
- Proactive 1:1 bootstrap: warm path (cached `ConversationReference`) or
  cold path (`create_conversation`).
- All card submits embed `interaction_id` for deterministic correlation.
- `respondent` always taken from the BF-validated `activity.from_property`
  (never from the card payload).

---

## Prerequisites

### Azure App Registration (HITL Bot)

1. Register a new **Bot Channel Registration** (or App Registration + Bot
   resource) in the Azure portal.
2. Note the **App ID** and **App Password** (client secret).
3. Set the messaging endpoint:
   `https://<your-host>/api/teams-hitl/messages` (or custom via `route`).

### Microsoft Graph App Registration

4. Register a separate (or the same) App Registration for Graph API access.
5. Grant the **application permission** `User.Read.All` (NOT delegated).
6. Grant admin consent.

### CRITICAL: Org-Wide Bot Installation (OQ-COLD)

> **This is a hard deployment prerequisite.**

The HITL channel bootstraps **proactive 1:1 conversations** — meaning it
initiates chats with users who have never messaged the bot.  This requires
the bot to be installed **org-wide** by a Teams tenant administrator:

1. In the Teams Admin Center, go to **Manage apps** → **Upload a custom app** (or
   publish via the app catalog).
2. Once published, go to **Setup policies** → add the app as a **pre-installed
   app** for all users (or the target group).

If the bot is NOT installed org-wide, `create_conversation` will fail and
`send_interaction` will return `False` (the engine will advance the
interaction chain with `action_failed`).  **There is no runtime fallback
in v1** — the org-wide install is required for the cold bootstrap path.

### Redis

A Redis instance is required for:
- `hitl:teams:convref:{email}` — ConversationReference cache (30-day TTL,
  refreshed on every inbound contact).
- `hitl:teams:sent:{interaction_id}` — sent-activity map (for cancel/update).

---

## Environment Variables

Set these in your navconfig / `.env` file:

```bash
# HITL Bot credentials
MSTEAMS_HITL_APP_ID=<bot-app-id>
MSTEAMS_HITL_APP_PASSWORD=<bot-app-password>
MSTEAMS_TENANT_ID=<aad-tenant-id>

# Graph app credentials (User.Read.All)
MSTEAMS_GRAPH_CLIENT_ID=<graph-app-client-id>
MSTEAMS_GRAPH_CLIENT_SECRET=<graph-app-client-secret>
MSTEAMS_GRAPH_TENANT_ID=<aad-tenant-id>

# Redis
REDIS_URL=redis://localhost:6379/0
```

Do **not** hardcode credentials in code.  All fields use
`default_factory=lambda: os.environ.get(...)`.

---

## Setup

### 1. Install the `msteams` extra

```bash
pip install ai-parrot-integrations[msteams]
```

### 2. Wire the channel at application startup

```python
from aiohttp import web
from parrot.human import get_default_human_manager
from parrot.human.channels.teams import TeamsHitlConfig, setup_teams_hitl

app = web.Application()
manager = get_default_human_manager()

# Config reads from environment variables automatically.
config = TeamsHitlConfig()

# One call registers the webhook route and channel.
channel = await setup_teams_hitl(app, manager, config)

# Wires response/cancel handlers on all channels.
await manager.startup()
```

### 3. Expose the webhook

Your aiohttp app must be reachable at `config.route` (default:
`/api/teams-hitl/messages`).  If you use a reverse proxy or API gateway,
ensure HTTPS termination is in place — the Bot Framework validates the
JWT from Teams and rejects non-HTTPS endpoints in production.

---

## Per-Agent Override (OQ-9)

By default, all HITL interactions use the single shared HITL bot identity
(registered as `"teams"` on the manager).

When a specific agent or tier must present a **distinct Teams identity**
(e.g. for brand separation), create a second `TeamsHumanChannel` with
dedicated credentials and register it under a keyed name:

```python
# Default shared identity
config_default = TeamsHitlConfig()   # uses MSTEAMS_HITL_APP_ID etc.
await setup_teams_hitl(app, manager, config_default, channel_name="teams")

# Per-agent override — e.g. for "HR Escalation Bot"
config_hr = TeamsHitlConfig(
    app_id=os.environ["HR_BOT_APP_ID"],
    app_password=os.environ["HR_BOT_APP_PASSWORD"],
    # ...
)
await setup_teams_hitl(app, manager, config_hr, channel_name="teams:hr-agent")
```

In the interaction or tier config, reference the channel by key:

```python
interaction = HumanInteraction(
    channel="teams:hr-agent",
    ...
)
```

The default `"teams"` key is used for all interactions that do not specify
a named override.

---

## Interaction Types

All six `InteractionType` values are supported and rendered as Adaptive Cards:

| Type | Card UI |
|---|---|
| `FREE_TEXT` | Multiline `Input.Text` + Submit |
| `APPROVAL` | Approve (positive) / Reject (destructive) submit buttons |
| `SINGLE_CHOICE` | Compact `Input.ChoiceSet` + Submit |
| `MULTI_CHOICE` | Expanded multi-select `Input.ChoiceSet` + Submit |
| `FORM` | Per-field `Input.*` elements mapped from `form_schema` |
| `POLL` | Expanded single-select `Input.ChoiceSet` + Vote button |

Every card submit payload includes:

```json
{
    "hitl": true,
    "interaction_id": "<uuid>",
    // type-specific fields
}
```

### Policy-bound interactions (escalation)

When `interaction.policy is not None` and `TeamsHumanChannel.render_reject_button`
is `True` (the default), an "↑ Escalar" button is appended to the card:

```json
{
    "type": "Action.Submit",
    "title": "↑ Escalar",
    "style": "destructive",
    "data": {
        "hitl": true,
        "interaction_id": "<uuid>",
        "value": "__escalate__"
    }
}
```

The `ESCALATE_OPTION_KEY` sentinel (`"__escalate__"`) is intercepted by
`manager.receive_response` and routed to `advance_chain(cause="reject")`.

---

## FORM Schema Field Mapping (OQ-5)

`form_schema` fields are mapped to Adaptive Card `Input.*` elements by their
`type` key:

| Schema `type` | Adaptive Card element |
|---|---|
| `"string"` (default) | `Input.Text` (single-line) |
| `"text"` / `"textarea"` | `Input.Text` (multiline) |
| `"integer"` / `"number"` | `Input.Number` |
| `"boolean"` | `Input.Toggle` |
| `"choice"` / `"select"` | `Input.ChoiceSet` (compact, single) |
| `"multi_choice"` / `"multi_select"` | `Input.ChoiceSet` (expanded, multi) |
| `"date"` | `Input.Date` |
| `"time"` | `Input.Time` |
| Unknown | `Input.Text` (fallback) |

Fields support `label`, `placeholder`, and `required` keys.

---

## Cancel / Update

`cancel_interaction(interaction_id, recipient)` replaces the live card with a
disabled "expired" card via `update_activity`.  Idempotent: calling twice is
safe (returns `False` on the second call when no sent record exists).

---

## ConversationReference Cache

- Key: `hitl:teams:convref:{email}` → JSON-serialised `ConversationReference`
- TTL: 30 days (configurable via `TeamsHitlConfig.convref_ttl`)
- Refreshed on every inbound contact (OQ-4)
- `service_url` updated from latest activity to avoid pinning stale URLs

---

## Sent Activity Map

- Key: `hitl:teams:sent:{interaction_id}` → `{conversation_reference, activity_id, recipient}`
- TTL: 7 days (hardcoded in `SentActivityStore`)
- Used for cross-worker access and cancel/update

---

## Troubleshooting

### `send_interaction` returns `False` immediately

1. Check that the recipient email resolves via Graph (`User.Read.All` permission).
2. Check that the HITL bot is installed org-wide in Teams.
3. Look for `ProactiveDeliveryError` in the logs.

### Card submits are not received

1. Verify the webhook URL (`/api/teams-hitl/messages`) is reachable from the
   Bot Framework service.
2. Verify the app ID and password match the Bot Channel Registration.
3. Check the `Authorization` header is forwarded by your reverse proxy.

### Late replies after timeout

Expected behavior: the channel sends an in-thread ack ("solicitud ya expirada")
and discards the response.  The tombstone key `hitl:result:{interaction_id}`
must be set by the manager when it resolves an interaction.

---

## Security Notes

- Never log `app_password`, `graph_client_secret`, or Redis credentials.
- `respondent` identity always comes from the BF-validated
  `activity.from_property.aad_object_id`.  Card payload is untrusted.
- `is_valid_respondent` in the manager enforces that the respondent is in
  `interaction.target_humans`.

---

## See Also

- Spec: `sdd/specs/hitl-teams-channel.spec.md`
- Reference implementation: `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py`
- Tests: `packages/ai-parrot-integrations/tests/test_teams_channel.py`
- Integration tests: `packages/ai-parrot-integrations/tests/test_teams_hitl_integration.py`
