---
id: FC-003
query_id: Q023
type: grep
intent: "Verify VERIFY-claim: no performative / speech-act / conversation threading fields anywhere in core."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — Absence: no performative, speech act, protocol state or Contract Net anywhere

## Summary

Case-insensitive grep over `packages/ai-parrot/src/parrot`, `packages/ai-parrot-server/src/parrot`, `packages/ai-parrot-integrations/src/parrot` (`*.py`): `performative` 0, `speech_act` 0, `not_understood` 0, `contract_net` 0, `FIPA` 0. `in_reply_to` has 6 hits, all the Matrix `m.in_reply_to` relation (reply threading for human clients). `conversation_id` has 99 hits, clustered in MS Teams / msagentsdk / MCP context / reminder tool — platform conversation ids, not a protocol thread id. The VERIFY claim holds: there is no speech-act typing and no per-conversation protocol state machine in ai-parrot.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py`
  lines: 341-402
  symbol: `MatrixAppService.send_reply_as_agent`
  excerpt: |
    Sets the ``m.in_reply_to`` relation so Matrix clients render the ...
    content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to_event_id}}

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/mention.py`
  lines: 102
  symbol: `build_reply_relation`
  excerpt: |
    "m.in_reply_to": {"event_id": reply_to_event_id}

- path: `packages/ai-parrot/src/parrot/core/hooks/messaging.py`
  lines: 231
  symbol: `MSTeamsHook`
  excerpt: |
    "conversation_id": conversation.get("id"),


## Notes

Files with `conversation_id`: core/hooks/messaging.py, mcp/context.py, mcp/integration.py, tools/reminder.py, integrations/msagentsdk/{resume,_patches,agent}.py, integrations/msteams/{formdesigner_turn,formdesigner_wizard,formdesigner_mixin,models,wrapper,dialogs/orchestrator,commands/agent_commands}.py, integrations/matrix/{appservice,crew/session_models,crew/mention}.py.
