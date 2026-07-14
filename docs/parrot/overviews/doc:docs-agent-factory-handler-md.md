---
type: Wiki Overview
title: AgentFactory HTTP API
id: doc:docs-agent-factory-handler-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reference for the `AgentFactoryHandler` endpoint and the HITL flow needed
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
---

# AgentFactory HTTP API

Reference for the `AgentFactoryHandler` endpoint and the HITL flow needed
to drive it from a chat interface.

## Overview

The AgentFactory is a meta-agent that turns a natural-language description
into a registered, ready-to-use agent. It orchestrates an LLM **router**, one
of three **specialist builders** (`rag`, `tool_agent`, `clone`), and a final
**finalize** step that writes the YAML to `agents/<category>/` and reloads
the `AgentRegistry`.

Every run goes through two human-in-the-loop checkpoints:

- **pre-delegation** — the user approves which specialist will draft the
  agent before the factory pays for the specialist's LLM tokens.
- **pre-finalize** — the user reviews the generated YAML before it is
  persisted and the registry is reloaded.

Both gates can time out (`TimeoutAction.CANCEL`), guaranteeing the factory
never burns LLM tokens past a checkpoint the user abandoned.

## Base URL

```
/api/v1/agents/factory
```

The route is registered automatically by `BotManager`. No host wiring
required as long as `BotManager.setup_routes(app)` ran at startup.

## Endpoints

### Create a new agent (POST)

Drives the full factory flow synchronously: route → pre-delegation HITL →
specialist build → pre-finalize HITL → finalize. The HTTP response holds
the terminal `FactoryResult`.

**Endpoint:** `POST /api/v1/agents/factory`

**Request body**

```jsonc
{
  // required — natural-language description of the agent to build
  "description": "Create an agent that generates and posts LinkedIn content, finding recent news and never duplicating content.",

  // optional — short-circuit the router toward CloneAgentBuilder.
  // Equivalent to telling the LLM 'clone X then mutate it'.
  "clone_from": "ATTBot",

  // optional — pin a builder or pass auxiliary info to the router.
  // 'builder' must be one of: rag | tool_agent | clone.
  "hints": {
    "builder": "tool_agent",
    "integrations": ["linkedin"]
  },

  // optional — subdirectory under agents/ where the YAML is written
  // (defaults to "general"). Useful to group agents per tenant/domain.
  "category": "marketing",

  // optional — LLM provider tag used to back the router & builders.
  // Falls back to "google" / Gemini Flash.
  "use_llm": "google",
  "llm": null,

  // optional — bypass both HITL checkpoints. Returns the agent
  // unattended. Intended for scripts / CI; DO NOT enable for end-user
  // chat traffic.
  "auto_approve": false,

  // optional — only relevant when auto_approve is false. Selects which
  // registered channel the HumanInteractionManager dispatches gates to.
  // Defaults to "web" so the WebHumanChannel can stream prompts over
  // the existing user socket.
  "human_channel": "web",

  // optional — recipient ids the channel routes to. For the web
  // channel this is the authenticated user id.
  "human_targets": ["alice@acme.example"]
}
```

**Response — 200 OK (status: success)**

```jsonc
{
  "status": "success",
  "router_decision": {
    "builder": "tool_agent",
    "reasoning": "User requested LinkedIn integration with no native toolkit; tool_agent will register an OpenAPI toolkit.",
    "detected_integrations": ["linkedin"]
  },
  "definition": {
    "name": "LinkedInContentBot",
    "class_name": "BasicAgent",
    "module": "parrot.bots.agent",
    "enabled": true,
    "system_prompt": "You are a LinkedIn content assistant…",
    "model": {"provider": "google", "model": "gemini-2.5-flash", "temperature": 0.4, "max_tokens": 4096},
    "tools": {"tools": [], "toolkits": ["openapi_linkedin"], "mcp_servers": []},
    "tags": ["requires_approval"]
  },
  "yaml_path": "/srv/parrot/agents/marketing/linkedincontentbot.yaml",
  "provisioning": [
    {"kind": "openapi_toolkit", "name": "openapi_linkedin", "details": {"service": "linkedin", "operations": 27, "auth_type": "bearer"}}
  ]
}
```

**Response — 202 Accepted (status: cancelled_by_user | timeout)**

The factory ran but the user bailed or did not respond. `cancelled_at`
tells the chat UI which gate stopped the flow.

```jsonc
{
  "status": "cancelled_by_user",     // or "timeout"
  "cancelled_at": "pre_delegation",  // or "pre_finalize"
  "router_decision": { /* … */ },
  "definition": { /* present only when cancelled_at == "pre_finalize" */ }
}
```

If the user cancels at `pre_finalize`, the response still carries the
`definition` and `provisioning` records — the chat UI can offer to keep
provisioned resources (e.g. the vector-store table) or surface them for
cleanup.

**Response — 400 Bad Request**

Returned when `description` is missing or the JSON body is invalid.

```json
{"status": "error", "message": "description is required"}
```

**Response — 500 Internal Server Error (status: failed)**

The orchestrator raised an unrecoverable error. The body mirrors the
`FactoryResult` shape with `status: "failed"` and a free-text `error`.

```jsonc
{
  "status": "failed",
  "error": "Specialist tool_agent failed: spec URL returned 404",
  "router_decision": { /* … */ }
}
```

## HITL flow for a chat interface

The factory blocks the HTTP request while it waits for the user to clear
each gate. For a chat UI this is fine because the WebHumanChannel pushes
prompts over a WebSocket — the chat UI does not poll, it just renders
prompts as they arrive and POSTs the user's response.

### Prerequisites

1. `setup_web_hitl(app)` must run at startup. `BotManager` schedules this
   automatically as an `on_startup` callback, provided
   `app['user_socket_manager']` is already set when the manager initialises.
2. The chat client must be connected over the user socket so prompts can
   reach it. The socket name and authentication are owned by
   `UserSocketManager`.

### Sequence

```
chat-ui                  POST /api/v1/agents/factory
   │   description=…                  ▶ handler
   │   human_channel="web"
   │                                  ┌── route (LLM)
   │                                  │
   │                                  ▼
   │   ws: hitl_request               ┌── pre-delegation gate
   │ ◀────────────────────────────────┤   (HumanInteractionManager
   │   { interaction_id,              │    via WebHumanChannel)
   │     question,                    │
   │     options: [confirm,cancel] }  │
   │                                  │
   │   POST /api/v1/agents/hitl/respond
   │ ─────────────────────────────────▶   { interaction_id, value: "confirm" }
   │                                  │
   │                                  ▼
   │                                  ┌── specialist.build (LLM)
   │                                  │
   │                                  ▼
   │   ws: hitl_request               ┌── pre-finalize gate
   │ ◀────────────────────────────────┤   (shows the YAML for review)
   │                                  │
   │   POST /api/v1/agents/hitl/respond
   │ ─────────────────────────────────▶   { interaction_id, value: "confirm" }
   │                                  │
   │                                  ▼
   │                                  ┌── finalize_agent_registration
   │                                  │   (write YAML + reload registry)
   │                                  │
   │   HTTP 200                       ▼
   │ ◀────────────────────────────────  FactoryResult JSON
```

### Companion endpoint: submit a HITL response

The chat UI uses the **existing** HITL response endpoint to clear gates.
The factory does not need its own confirm/cancel route.

```
POST /api/v1/agents/hitl/respond
```

**Body**

```json
{
  "interaction_id": "<uuid from the ws hitl_request payload>",
  "value": "confirm"
}
```

`value` accepts `"confirm" | "approve" | "approved" | "yes" | "y" | true`
as approval (case-insensitive). Anything else — including `"cancel"` — is
treated as rejection.

### WebSocket payload the chat UI receives at each gate

```jsonc
{
  "type": "hitl_request",
  "interaction_id": "f4b2…",
  "source_agent": "agent_factory",
  "source_node": "pre_delegation",        // or "pre_finalize"
  "question": "I will use the **tool_agent** specialist…",
  "interaction_type": "approval",
  "options": [
    {"key": "confirm", "label": "Approve"},
    {"key": "cancel",  "label": "Cancel"}
  ],
  "timeout": 120                          // seconds remaining before auto-cancel
}
```

`source_node` lets the UI tailor the rendering — at `pre_finalize` the
`question` body already contains a `yaml`-fenced preview of the generated
agent definition, which the chat client can render with a YAML highlighter.

### Timeouts

Per-gate timeouts default to:

| Gate            | Default | Override env var                       |
|-----------------|---------|----------------------------------------|
| pre_delegation  | 120 s   | `FACTORY_HITL_DELEGATION_TIMEOUT`      |
| pre_finalize    | 600 s   | `FACTORY_HITL_FINALIZE_TIMEOUT`        |

A timed-out gate resolves the factory run with `status: "timeout"` and the
HTTP response unblocks immediately. The chat UI should surface this as
"the factory request expired" and offer to restart.

## Example: minimal chat client (TypeScript)

```ts
async function createAgent(description: string) {
  const res = await fetch("/api/v1/agents/factory", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      description,
      human_channel: "web",
      human_targets: [currentUserId()],
    }),
  });
  return res.json() as Promise<FactoryResult>;
}

// Wire the user socket to forward HITL prompts to the chat UI.
userSocket.on("hitl_request", (payload) => {
  chatThread.renderPrompt(payload, async (choice) => {
    await fetch("/api/v1/agents/hitl/respond", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",                    // session cookie
      body: JSON.stringify({
        interaction_id: payload.interaction_id,
        value: choice,                            // "confirm" | "cancel"
      }),
    });
  });
});
```

## Non-interactive usage

For scripts, CI checks, or callers that already approved through their own
UI (e.g. an internal admin panel), pass `auto_approve: true` and skip the
HITL plumbing entirely:

```bash
curl -X POST /api/v1/agents/factory \
  -H 'content-type: application/json' \
  -d '{
    "description": "A RAG bot for product manuals stored in PgVector",
    "category": "support",
    "auto_approve": true
  }'
```

The handler injects an in-memory channel that resolves both gates with
`confirm`. The factory still writes the YAML and reloads the registry, but
nothing is sent over WebSocket and no human ever sees a prompt.
