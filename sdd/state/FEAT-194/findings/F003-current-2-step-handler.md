---
id: F003
queries: [Q008, Q009, Q027]
confidence: high
---

# The "2-step flow" is a separate POST endpoint, not a limitation of the bot

`InfographicTalk` (handlers/infographic.py:55-475) extends `AgentTalk`
and registers an entirely separate route family:

- `POST /api/v1/agents/infographic/{agent_id}` — generate (the 2nd step)
- `GET  /api/v1/agents/infographic/templates` — list templates
- `POST /api/v1/agents/infographic/templates` — register templates (PBAC)
- mirrors for themes

The body is `{"query": ..., "template": "basic" (default), "theme": ...}`.
The handler calls `agent.get_infographic(question, template, theme,
accept=<negotiated mime>, user_id, session_id, use_vector_context,
use_conversation_history, ctx=None, **extra_kwargs)` after a strict
allowlist filter for kwargs (`_GENERATE_RESERVED_KEYS`).

Content negotiation order (lines 454-474): `?format=` query param >
`Accept` header > default `text/html`.

**Auto-save as Artifact** (lines 244-304): every successful infographic is
saved fire-and-forget via `artifact_store.save_artifact()` with
`artifact_type=ArtifactType.INFOGRAPHIC`, `created_by=ArtifactCreator.AGENT`,
and the full `InfographicResponse.model_dump()` as the definition. This is
already wired and ships today (FEAT-103 in the agent-artifact-persistency
spec).

**AgentTalk** (handlers/agent.py) — the main `/api/v1/agents/chat/{agent_id}`
endpoint — does **NOT** call `get_infographic()`. Its `post()` calls
`bot.ask(question, output_mode=OutputMode.<x>, structured_output=..., ...)`
directly (line 1550-1563) for the normal path. There is a `followup()`
path (lines 1533-1547) gated on `followup_turn_id` + `followup_data` —
this is the existing mechanism by which the frontend issues "design the
infographic now" after seeing the textual answer; it is the 2-step
behaviour the user wants to eliminate.

`output_mode` is parsed from `data["output_mode"]` (lines 1367, 1381-1383)
or query/headers (`_get_output_mode`, lines 441-474). When set to
`"infographic"` and passed to `bot.ask()`, the LLM gets the
`INFOGRAPHIC_SYSTEM_PROMPT` (via `get_output_prompt(mode)`) but the
HTML-rendering step is NOT executed — that lives only inside
`get_infographic()`.

## Citations
- packages/ai-parrot/src/parrot/handlers/infographic.py:135-242 —
  `_generate_infographic()`
- packages/ai-parrot/src/parrot/handlers/infographic.py:244-304 —
  `_auto_save_infographic_artifact()` fire-and-forget
- packages/ai-parrot/src/parrot/handlers/agent.py:1550-1563 — AgentTalk
  POST calls `bot.ask(question, output_mode=..., ...)`
- packages/ai-parrot/src/parrot/handlers/agent.py:1533-1547 — current
  `followup()` path (the 2-step we want to eliminate)
- recent git log: `bfcf0253 feat(get-infographic-handler): TASK-650 —
  InfographicTalk HTTP Handler`
