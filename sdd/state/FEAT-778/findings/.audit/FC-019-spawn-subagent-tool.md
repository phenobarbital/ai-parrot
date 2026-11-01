---
id: FC-019
query_id: Q038
type: grep
intent: "Locate the spawn-agent / delegation tool to be denied per expert."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-019 — Delegation tool is `SpawnSubAgentTool` in `parrot/tools/spawn.py`; it has a parent `allowed_tools` allowlist but no nesting-depth guard

## Summary

The literal names `spawn_agent`/`spawn_ephemeral` only appear in `memory/compaction/policies.py`; the real tool is `SpawnSubAgentTool(AbstractTool)` (380 lines) with `SpawnSubAgentInput`, constructor `allowed_tools` and `_compute_effective_tools()` (empty allowlist → warn and pass through requested tools; non-empty → intersect). No code prevents a spawned sub-agent from itself receiving the spawn tool, so "no expert delegates" must be enforced by excluding this tool from expert toolkits.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 39-45
  symbol: `SpawnSubAgentInput`
  excerpt: |
    class SpawnSubAgentInput(BaseModel):
        ... parent's allowed_tools allowlist for defense in depth.

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 88-158
  symbol: `SpawnSubAgentTool.__init__`
  excerpt: |
    class SpawnSubAgentTool(AbstractTool):
        def __init__(self, ..., allowed_tools: Optional[List[str]] = None, ...):
            self._allowed_tools: List[str] = list(allowed_tools or [])

- path: `packages/ai-parrot/src/parrot/tools/spawn.py`
  lines: 164-190
  symbol: `SpawnSubAgentTool._compute_effective_tools`
  excerpt: |
    If allowed_tools is empty (no allowlist configured), the requested tools pass through
    If allowed_tools is non-empty, only tools present in it are allowed.
    "SpawnSubAgentTool: no allowed_tools configured; "

- path: `packages/ai-parrot/src/parrot/memory/compaction/policies.py`
  lines: 1
  symbol: `spawn_agent mention`
  excerpt: |
    (only other file mentioning spawn_agent — compaction policy for tool output)

## Notes

Spec index: `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` (wiki lane).
