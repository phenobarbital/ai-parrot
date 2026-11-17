---
id: FW-014
query_id: Q004
type: wiki_page
intent: "Read the BotManager flag tests to learn how crew_redis is created and how load_crews is gated."
executed_at: 2026-11-09T17:13:27Z
duration_ms: 300
parent_id: FW-013
depth: 2
---

# FW-014 — enable_crews gates both CrewRedis construction (in __init__) and load_crews (in on_startup); tests patch parrot.manager.manager.CrewRedis

## Summary

`test_botmanager_flags.py` pins: `BotManager(enable_crews=False).crew_redis is None` and CrewRedis is never
constructed; with `enable_crews=True`, `crew_redis` is the single `CrewRedis()` instance, built in `__init__`;
`on_startup` calls `load_crews()` only when `enable_crews` is true. Every test patches the module-level name
`parrot.manager.manager.CrewRedis`. A new storage that replaces `crew_redis` (or adds a sibling attribute) must
keep these contracts or update these tests, and the attribute name `crew_redis` is part of the tested surface.

## Citations

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

Configuration precedent: flags are `parrot.conf` constants with a constructor override
(`test_explicit_override_ignores_config`), which suggests `CREW_STORAGE`/`CREW_STORAGE_MIGRATION` conf keys
with BotManager kwargs as overrides for the request's "migration=True" flag.
