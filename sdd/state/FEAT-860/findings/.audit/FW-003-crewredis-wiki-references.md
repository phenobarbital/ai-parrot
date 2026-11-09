---
id: FW-003
query_id: Q003
type: wiki_related
intent: "Find who references CrewRedis (BotManager, CrewHandler, tests)."
executed_at: 2026-11-09T17:13:11Z
duration_ms: 200
parent_id: FW-001
depth: 1
---

# FW-003 — Wiki reference edges to CrewRedis are incomplete (only an example and one test)

## Summary

`wiki_related` on the redis_persistence.py page returns three edges: `examples/crew/redis_persistence_example.py`
(references, in), `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py` (references, in)
and the containing directory. BotManager (`manager.py`) and `test_botmanager_flags.py` (which patches
`parrot.manager.manager.CrewRedis`) are known users but carry no extracted edge, so the graph cannot be
trusted for the full caller list.

## Citations

- path: `examples/crew/redis_persistence_example.py`
  excerpt: |
    rel=references, direction=in, provenance=extracted
- path: `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py`
  excerpt: |
    rel=references, direction=in — "CrewRedis must keep already-stored crews loadable."
- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  lines: 32-41
  symbol: `_make_manager`
  excerpt: |
    with patch("parrot.manager.manager.CrewRedis"), patch("parrot.manager.manager.agent_registry"):
        return BotManager(**kwargs)

## Notes

[cross-lane: type=grep, intent=enumerate every CrewRedis / crew_redis caller (Q007) — the wiki edge set is incomplete]
