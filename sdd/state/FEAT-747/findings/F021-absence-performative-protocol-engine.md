---
id: F021
query_id: Q011
type: wiki_query
intent: "Verify absence: performative / speech-act / interaction-protocol state machine anywhere in the codebase."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FW-012
---

# F021 — ABSENCE CONFIRMED: no performative, speech-act, FIPA or Contract-Net concept in the knowledge graph

## Summary

A free wiki query for 'performative speech act FIPA contract net protocol' returned only unrelated hits (Nova Sonic audio 'speech' frames in `tests/clients/test_nova_protocol_frames.py`, `bots/flows/core/types.py` ranked on the word 'protocol'). No page, symbol, decision or memory mentions `performative`, `speech act`, `FIPA`, `inform/request/cfp` semantics, `not_understood`, or a per-conversation protocol state machine. Combined with FW-002/FW-003 (every inter-agent call is question-text → awaited answer) this confirms the brainstorm's first VERIFY item: there is no speech-act typing and no interaction-protocol engine. The nearest structural precedents are `AgentSwarmToolkit.ask_agent`'s status enum (`ok|timeout|error|schema_error|hop_limit|unknown_agent|self_ask_rejected`, FW-003) and the flows FSM `AgentTaskMachine` (FW-011).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/types.py`
  lines: n/a
  symbol: `Flow Primitives — Types Module (false-positive hit on 'protocol')`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/core/types.py (score=0.69)

- path: `packages/ai-parrot/tests/clients/test_nova_protocol_frames.py`
  lines: n/a
  symbol: `Nova Sonic frames (false-positive hit on 'speech')`
  wiki_page_id: file:packages/ai-parrot/tests/clients/test_nova_protocol_frames.py (score=0.40)

## Notes

`[cross-lane: type=grep, intent=repo-wide grep performative|speech_act|in_reply_to|conversation_id|not_understood to close the absence claim at line level]` (Q023 covers this).

[citation-check: verified] absent: performative (core, server, integrations), speech_act, not_understood, contract_net, FIPA
