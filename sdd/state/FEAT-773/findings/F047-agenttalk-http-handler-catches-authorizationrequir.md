---
id: F047
query_id: Q047-F2
type: read
intent: "Follow-up: where the server emits the auth_required envelope for the web chat (handlers/agent.py)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-054
depth: 2
merged_from: [FC-055]
---

# F047 — AgentTalk HTTP handler catches AuthorizationRequired and returns AuthRequiredEnvelope JSON (HTTP 200) so the web UI renders the Connect pill

## Summary

`handlers/agent.py:52` imports `AuthRequiredEnvelope`; `:1916-1927` `except AuthorizationRequired as exc:` → `AuthRequiredEnvelope(provider, tool_name, auth_url, scopes, message=str(exc))` → `web.json_response(envelope.model_dump(), status=200)` ('the envelope IS the agent's reply'). Adjacent `HumanInteractionInterrupt` path (FEAT-204) returns a paused envelope. `bots/mixins/intent_router.py:850,1015` recognises an `auth_required` state. `handlers/user.py:501` uses a different `auth_required` message for WS auth.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py`
  lines: 1916-1927
  symbol: `AgentTalk handler`
  excerpt: |
    except AuthorizationRequired as exc:
        envelope = AuthRequiredEnvelope(provider=exc.provider, tool_name=exc.tool_name, auth_url=exc.auth_url, scopes=exc.scopes or [], message=str(exc))
        return web.json_response(envelope.model_dump(), status=200)

## Notes

Note: this catch handles the *exception* (raised when a toolkit's `_pre_execute` runs outside ToolManager's catch, or re-raised); when ToolManager converts it to a ToolResult the LLM sees `authorization_required` instead. `CredentialRequired` (broker seam) is NOT caught here — grep showed no handler for it in server handlers.
