---
id: F015
query_id: Q003, Q004
type: wiki_related
intent: "Find who references CrewRedis (BotManager, CrewHandler, tests)."
executed_at: 2026-11-09T17:13:11Z
duration_ms: 200
parent_id: null
depth: 2
merged_from: [FW-003, FW-014]
---

# F015 — Wiki reference edges to CrewRedis are incomplete (only an example and one test)

## Summary

[FW-003] `wiki_related` on the redis_persistence.py page returns three edges: `examples/crew/redis_persistence_example.py`
(references, in), `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py` (references, in)
and the containing directory. BotManager (`manager.py`) and `test_botmanager_flags.py` (which patches
`parrot.manager.manager.CrewRedis`) are known users but carry no extracted edge, so the graph cannot be
trusted for the full caller list.

[FW-014] `test_botmanager_flags.py` pins: `BotManager(enable_crews=False).crew_redis is None` and CrewRedis is never
constructed; with `enable_crews=True`, `crew_redis` is the single `CrewRedis()` instance, built in `__init__`;
`on_startup` calls `load_crews()` only when `enable_crews` is true. Every test patches the module-level name
`parrot.manager.manager.CrewRedis`. A new storage that replaces `crew_redis` (or adds a sibling attribute) must
keep these contracts or update these tests, and the attribute name `crew_redis` is part of the tested surface.

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

- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  lines: 177-194
  symbol: `test_enable_crews_true_creates_crew_redis`
  excerpt: |
    bm = BotManager(enable_crews=True)
    assert bm.crew_redis is mock_crew_redis.return_value
    mock_crew_redis.assert_called_once()

- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  lines: 44-55
  symbol: `test_defaults_match_config`
  excerpt: |
    from parrot.conf import ENABLE_CREWS, ENABLE_DATABASE_BOTS, ENABLE_REGISTRY_BOTS, ENABLE_SWAGGER
    assert bm.enable_crews == ENABLE_CREWS

## Notes

[FW-003] [cross-lane: type=grep, intent=enumerate every CrewRedis / crew_redis caller (Q007) — the wiki edge set is incomplete]

[FW-014] Configuration precedent: flags are `parrot.conf` constants with a constructor override
(`test_explicit_override_ignores_config`), which suggests `CREW_STORAGE`/`CREW_STORAGE_MIGRATION` conf keys
with BotManager kwargs as overrides for the request's "migration=True" flag.
