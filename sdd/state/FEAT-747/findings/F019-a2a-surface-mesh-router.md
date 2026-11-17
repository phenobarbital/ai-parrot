---
id: F019
query_id: Q008
type: wiki_page
intent: "Orient: A2A client/server — the closest existing agent-to-agent protocol surface (agent cards, tasks)."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FW-009
---

# F019 — A2A stack: A2AClient + remote-agent/skill tools, A2AClientMixin (mesh, router, orchestrator, Matrix transport), A2AMeshDiscovery (get_by_skill/tag/search — remote only), A2AProxyRouter (LLM-free routing)

## Summary

`parrot/a2a/` is the closest existing inter-agent protocol. `client.py`: `A2AClient` (JSON-RPC over aiohttp: `discover` agent card, `get_skills`, `send_message`, `stream_message`, `invoke_skill`, tasks CRUD, push configs) plus `A2ARemoteAgentTool` (question → remote agent) and `A2ARemoteSkillTool` (a remote *skill* compiled into a typed local tool via `_create_skill_input_model(skill)` from the skill's `input_schema` — the precedent for 'contract → tool definition'). `mixin.py::A2AClientMixin` adds to any bot: `set_matrix_transport` (l.105), `set_mesh/discover_from_mesh(skill, tag, register_as_tools)` (l.146), `set_router/route_to_agent`, `set_orchestrator/orchestrate`, `fan_out` (l.346), `pipeline` (l.368), `add_a2a_agent(url)` (l.396), `ask_remote_agent` (l.535), `invoke_remote_skill` (l.585). `mesh.py::A2AMeshDiscovery` is a **capability directory for remote A2A agents**: `get_by_skill(skill_id)`, `get_by_tag`, `search(query)` full-text, health checks, priority; it is separate from `AgentRegistry` (FW-001) and covers remote endpoints only. `router.py::A2AProxyRouter` routes 'without LLM processing' by skill/tag/regex/round-robin and can `fan_out`/`pipeline`. `bots/flows/agents/a2a_orchestrator.py` is an A2A-enhanced orchestrator. So 'discover by capability without an LLM' exists for remote A2A agents; the gap is a unified local+remote index on `AgentRegistry` with locality/cost ranking.

## Citations

- path: `packages/ai-parrot/src/parrot/a2a/client.py`
  lines: 1-15
  symbol: `A2AClient / A2ARemoteAgentTool / A2ARemoteSkillTool / _create_skill_input_model`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/client.py (score=0.94)
  excerpt: |
    import aiohttp
    from ..tools.abstract import AbstractTool, AbstractToolArgsSchema
    class A2ARemoteSkillTool: Wraps a specific skill from a remote A2A agent as a tool.
    def _create_skill_input_model(skill): Dynamically create a Pydantic model from an AgentSkill's input_schema.

- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 34
  symbol: `A2AClientMixin`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/mixin.py (score=0.85)
  excerpt: |
    class A2AClientMixin:

- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 105
  symbol: `A2AClientMixin.set_matrix_transport`

- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 146
  symbol: `A2AClientMixin.discover_from_mesh`
  excerpt: |
    async def discover_from_mesh(self, skill, tag, register_as_tools)

- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 346-396
  symbol: `A2AClientMixin.fan_out / pipeline / add_a2a_agent`

- path: `packages/ai-parrot/src/parrot/a2a/mixin.py`
  lines: 535-585
  symbol: `A2AClientMixin.ask_remote_agent / invoke_remote_skill`

- path: `packages/ai-parrot/src/parrot/a2a/mesh.py`
  lines: n/a (API outline)
  symbol: `A2AMeshDiscovery`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/mesh.py (score=0.49)
  excerpt: |
    get_by_skill(skill_id); get_by_tag(tag); search(query); list_healthy; list_by_priority; register(url); from_config(config_path)

- path: `packages/ai-parrot/src/parrot/a2a/router.py`
  lines: n/a (API outline)
  symbol: `A2AProxyRouter`
  wiki_page_id: file:packages/ai-parrot/src/parrot/a2a/router.py (score=0.42)
  excerpt: |
    Proxy/Gateway for routing requests to A2A agents without LLM processing: route_by_skill/route_by_tag/route_by_regex/route_round_robin; fan_out; pipeline

- path: `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py`
  lines: n/a
  symbol: `A2A-Enhanced Orchestrator Agent`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py (score=0.43)

- path: `docs/architecture/02-a2a.md`
  lines: n/a
  symbol: `A2A architecture chapter`
  wiki_page_id: file:docs/architecture/02-a2a.md (score=0.90)

## Notes

TASK-2572 added Agent Card extension + inbound `DataPart` dispatch (structured, non-text payloads over A2A). TASK-1709 'A2A Bot Startup + Discovery Registry + Security' and FEAT-260 (audit ledger) show the A2A bridge already has the serving-side policy/audit hooks the parent spec lists as missing. `[cross-lane: type=read, intent=bots/a2a_agent.py + a2a/mesh.py register()/get_by_skill — entry fields to compare with the proposed registry contract entry]`.

[citation-check: verified] a2a/client.py A2AClient 40, A2ARemoteAgentTool 543, _create_skill_input_model 630, A2ARemoteSkillTool 695; a2a/mixin.py A2AClientMixin 34, set_matrix_transport 105, discover_from_mesh 146, fan_out 346, pipeline 368, add_a2a_agent 396, ask_remote_agent 535, invoke_remote_skill 585; a2a/mesh.py A2AMeshDiscovery 136; a2a/router.py A2AProxyRouter 191
