---
id: F016
query_id: Q054
type: git_log
intent: "Recent activity on A2A surfaces (core + server)."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FG-005
---

# F016 — A2A history (180 days): FEAT-272 v1.0 protocol compatibility (Jul 2026), A2UI extensions, MCP-as-agent PBAC wiring

## Summary

~30 commits 2026-06-27 → 2026-10-22. Dominant: **FEAT-272 a2a-protocol-compatibility** (2026-07-10, TASK-1712..1718): v1.0 data models/enums, AgentCard v1.0, REST routes + version negotiation, JSON-RPC methods/error codes, push-notification config store, A2AClient v1.0, "mesh & router v1.0 compatibility". Then FEAT-469 A2UI agent functions (agent-card extension, inbound `DataPart` dispatch, Aug 29), FEAT-668 lazy imports (Oct 14), TASK-2610 mcp-as-agent "identity/PBAC wiring" (Sep 1), FEAT-271 msagent-a2a. June: unified credential broker replaced the A2AServer credential gate. A2A is the mature inter-agent surface today: JSON-RPC + agent cards + free-text tasks — exactly what both brainstorms want to bypass for parrot-to-parrot traffic. A "mesh & router" exists (TASK-1718) — relevant to routing/addressing.

## Citations

- sha: `cf98ee289` date: 2026-07-10 author: Jesus — feat(a2a-protocol-compatibility): TASK-1712 — v1.0 data models, core types & enums

- sha: `764af73c0` date: 2026-07-10 author: Jesus — TASK-1713 — AgentCard v1.0 structure

- sha: `c5be9d9b9` date: 2026-07-10 author: Jesus — TASK-1714 — v1.0 REST routes & version negotiation

- sha: `094fda527` date: 2026-07-10 author: Jesus — TASK-1715 — v1.0 JSON-RPC methods & error codes

- sha: `b8166d1bf` date: 2026-07-10 author: Jesus — TASK-1717 — A2AClient v1.0 upgrade

- sha: `2006296c5` date: 2026-07-10 author: Jesus — TASK-1718 — mesh & router v1.0 compatibility

- sha: `f2d210169` date: 2026-07-10 author: Jesus — port JSON-RPC streaming + extra coverage from feat-272

- sha: `aa7ae59de` date: 2026-08-29 author: Jesus — feat(a2ui-agent-functions): TASK-2572 A2A agent card extension, inbound DataPart dispatch, queued renderer calls

- sha: `dcd09421a` date: 2026-09-01 author: Jesus Lara — feat(mcp-as-agent): TASK-2610 — integration tests, SDK interop, docs, and identity/PBAC wiring

- sha: `05bf98da5` date: 2026-06-29 author: Jesus Lara — feat(unified-credential-broker): TASK-1672 — replace A2AServer credential gate with broker calls

- sha: `dc347e0dc` date: 2026-10-14 author: Jesus Lara — feat(a2ui-lazy-imports): TASK-4292 — server handlers defer heavy imports

- sha: `ae7ebda97` date: 2026-10-22 author: Jesus Lara — feat(bots-agent-tech-debt): TASK-4617 — guard the nine post-super configure sites

- path: `packages/ai-parrot/src/parrot/bots/a2a_agent.py`
  excerpt: |
    (touched by TASK-4617; the bot-side A2A agent class)

- path: `packages/ai-parrot/src/parrot/a2a/`
  excerpt: |
    (core A2A models/client — FEAT-272 TASK-1712/1713/1717)

- path: `packages/ai-parrot-server/src/parrot/a2a/`
  excerpt: |
    (server routes/JSON-RPC/mesh+router — FEAT-272 TASK-1714/1715/1718)

- path: `sdd/specs/a2a-protocol-compatibility.spec.md`
  symbol: `FEAT-272`

## Notes

- "mesh & router v1.0" (TASK-1718) suggests an existing A2A routing layer — check whether it already does capability/skill-based routing between parrot agents.
- [cross-lane: type=grep, intent=grep 'class .*Mesh|class .*Router' under packages/ai-parrot-server/src/parrot/a2a and packages/ai-parrot/src/parrot/a2a]
