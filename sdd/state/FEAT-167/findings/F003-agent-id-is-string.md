---
id: F003
query_id: Q007+Q008
type: grep+read
intent: Confirm agent_id is universally a string (registry name), not a UUID
confidence: high
---

# F003 — `agent_id` is a string registry name across the codebase

## Evidence
- `packages/ai-parrot/src/parrot/agents/demo.py:161` — `agent_id: str = "hitl_demo"`
- `packages/ai-parrot/src/parrot/bots/search.py:69` — `agent_id: str = 'web_search_agent'`
- `packages/ai-parrot/src/parrot/bots/product.py:53` — `agent_id: str = 'product_report'`
- `packages/ai-parrot/src/parrot/bots/agent.py:54` — `agent_id: Optional[str] = None`
- `packages/ai-parrot/src/parrot/bots/agent.py:83` — `agent_id: str = 'agent'`
- `packages/ai-parrot/src/parrot/handlers/agent.py:90` — `agent_id: str,` (route parameter)

## Implications for FEAT-167
1. **Manually-coded agents (subclasses of `Agent`)** carry a `str` `agent_id`, often a slug like `"web_search_agent"`. They do **not** have a UUID `chatbot_id`.
2. **AgentRegistry-registered bots** are looked up by the same string slug (`agent_id`).
3. **DB-backed `BotModel` bots** have a UUID `chatbot_id` (see `models/bots.py:110-115`).

Therefore the `PromptLibrary` row must be able to bind to *either*:
- a UUID `chatbot_id` (DB-backed bots), OR
- a string `agent_id` (registry/code-defined agents).

## Recommended representation
Two non-null-mutually-exclusive columns with a CHECK constraint:
```sql
chatbot_id UUID NULL,
agent_id   VARCHAR NULL,
CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL))   -- exactly one set
```
Plus index on `agent_id`.

## Citations
- `packages/ai-parrot/src/parrot/agents/demo.py:161`
- `packages/ai-parrot/src/parrot/bots/search.py:69`
- `packages/ai-parrot/src/parrot/bots/product.py:53`
- `packages/ai-parrot/src/parrot/bots/agent.py:54,83`
- `packages/ai-parrot/src/parrot/handlers/agent.py:90`
- `packages/ai-parrot/src/parrot/registry/registry.py:228` (AgentRegistry)
