---
id: FW-013
query_id: Q013
type: wiki_page
intent: "Spawn-ephemeral-subagent tool (delegation tool to deny)"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-013 — Delegation tool exists: `SpawnSubAgentTool(AbstractTool)` in `parrot/tools/spawn.py:88` (FEAT-208, 4 tasks done) built on BotManager ownership-aware methods

## Summary

FEAT-208 `spawn-ephemeral-subagent-tool` is complete (TASK-1387 ephemeral ownership generalization, TASK-1388 BotManager ownership-aware methods, TASK-1389 `SpawnSubAgentTool` implementation, TASK-1390 export & registration). The class lives at `packages/ai-parrot/src/parrot/tools/spawn.py:88` (`class SpawnSubAgentTool(AbstractTool)`). This is the concrete tool the manifest's `tools_deny: [spawn_agent]` invariant must block; the registered tool *name* string was not confirmed by this lane.

## Citations

- path: `sdd/tasks/index/spawn-ephemeral-subagent-tool.json`
  symbol: `FEAT-208 TASK-1389 spawn-subagent-tool`
  wiki_page_id: file:sdd/tasks/index/spawn-ephemeral-subagent-tool.json
  score: 1.00
  excerpt: |
    {"id": "TASK-1389", "slug": "spawn-subagent-tool", "title": "SpawnSubAgentTool implementation",
     "status": "done", "file": "sdd/tasks/completed/TASK-1389-spawn-subagent-tool.md"}

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 88
  symbol: `SpawnSubAgentTool`
  excerpt: |
    class SpawnSubAgentTool(AbstractTool):

## Notes

[cross-lane: type=grep, intent=confirm SpawnSubAgentTool.name value and whether any per-agent tool deny-list exists (Q039)]
