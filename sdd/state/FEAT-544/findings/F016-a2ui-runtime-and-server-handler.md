---
id: F016
query_id: Q016
type: grep
intent: Server-side A2UI action dispatch
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: null
depth: 0
---

# F016 — A2UIRuntime + server A2UIHandler

## Summary

`A2UIRuntime.dispatch()` normalises a renderer→agent envelope; `_dispatch_action` stores `dataModel` per (session, surface) in a SurfaceStateStore (size-capped) and converts the action into an agent turn: `userMessage` verbatim or a system turn `{"type":"a2ui_action","action":<envelope>}` — i.e. actions are routed to the LLM agent, not to arbitrary HTTP endpoints. The server transport is `POST /api/v1/agents/{agent_id}/a2ui` (`handlers/a2ui.py`), which is agent-scoped, authenticated via navigator_auth and separate from AgentTalk. `agent.py` passes `a2ui_envelope` through in responses.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py`
  lines: 76-135
  symbol: `A2UIRuntime`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/runtime/dispatch.py`
  lines: 365-412
  symbol: `A2UIRuntime._dispatch_action / _build_action_turn`
  excerpt: |
    payload = serialize(action)
    payload["action"].pop("dataModel", None)
    return json.dumps({"type": "a2ui_action", "action": payload}, sort_keys=True)
- path: `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`
  lines: 1-60
  symbol: `A2UIHandler`
  excerpt: |
    POST /api/v1/agents/{agent_id}/a2ui — dispatch one or more R->A envelopes.
- path: `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`
  lines: 156-240
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 2612-2614
- path: `packages/ai-parrot/src/parrot/a2a/models.py`
  lines: 336
  symbol: `A2UI_MEDIA_TYPE`
  excerpt: |
    A2UI_MEDIA_TYPE = "application/a2ui+json"
