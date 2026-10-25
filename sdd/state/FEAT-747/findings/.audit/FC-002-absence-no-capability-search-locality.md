---
id: FC-002
query_id: Q022
type: grep
intent: "Verify VERIFY-claim: registry has no capability search / locality ranking; also find remote/a2a kinds."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-002 — Absence: no capability search, locality or remote kind in AgentRegistry

## Summary

Pattern `find_capability|capabilit|locality|kind\s*[:=]|remote_agent|RemoteAgent|a2a` (case-insensitive) over `registry/registry.py` and `registry/storage.py`: **zero matches**. A looser probe `remote|endpoint|url|capabilities|tags|categories` on `registry.py` matches only `tags` (lines 63, 247, 532, 574, 591, 613, 766, 1045, 1333, 1396, 1452, 1464-1466). The VERIFY claim holds: AgentRegistry indexes agents by name and tag only; there is no capability id, no category hash, no locality tier and no remote/a2a kind on the entry.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1450-1452
  symbol: `AgentRegistry.get_bots_by_tag`
  excerpt: |
    def get_bots_by_tag(self, tag: str) -> List[BotMetadata]:
        return [metadata for metadata in self._registered_agents.values() if tag in metadata.tags]

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 1459-1469
  symbol: `AgentRegistry.get_registration_info`
  excerpt: |
    "by_tags": {
        tag: [name for name, metadata in self._registered_agents.items() if tag in metadata.tags]
        for tag in set().union(*(metadata.tags for metadata in self._registered_agents.values()))


## Notes

`capabilit` DOES match inside `registry/capabilities/` (excluded from this probe) — that sub-package is the FEAT-070 `CapabilityRegistry` for datasets/tools (FC-019), a natural seed for `find_capability` but it does not index agents today.
