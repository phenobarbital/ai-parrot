---
id: FC-002
query_id: Q007
type: grep
intent: "List every caller of CrewRedis / crew_redis (the surface a dual storage must keep working)."
executed_at: 2026-11-09T17:17:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-002 — CrewRedis is used ONLY by BotManager (6 call sites) + 3 test files

## Summary

`grep CrewRedis|crew_redis` over `packages/` (excluding `redis_persistence.py` itself) shows a single
production consumer: `BotManager` in `packages/ai-parrot-server/src/parrot/manager/manager.py`, which
constructs `self.crew_redis = CrewRedis() if self.enable_crews else None` (line 271) and calls only six
methods: `save_crew` (3284), `load_crew` (3342, 3534), `load_crew_by_id` (3345), `delete_crew` (3422),
`ping` (3469), `get_all_crews` (3474), `list_all_crews` (3517). No handler touches `crew_redis` directly
(CrewHandler goes through BotManager). Tests: `test_crew_redis_legacy_payloads.py` (real Redis db 15),
`tests/manager/test_load_bots_experts.py` and `packages/ai-parrot/tests/test_botmanager_flags.py`
(both patch `parrot.manager.manager.CrewRedis`). A stale `packages/ai-parrot-server/build/lib/` copy of
manager.py also matches and must be ignored.

## Citations

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 98
  symbol: `import CrewRedis`
  excerpt: |
    from ..handlers.crew.redis_persistence import CrewRedis

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 241-271
  symbol: `BotManager.__init__ (enable_crews)`
  excerpt: |
    enable_crews: When True, initialize ``CrewRedis`` and call ...
    self.crew_redis = CrewRedis() if self.enable_crews else None

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3276-3284
  symbol: `BotManager.add_crew -> crew_redis.save_crew`
  excerpt: |
    if self.crew_redis is None: ...
        await self.crew_redis.save_crew(crew_def)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3337-3345
  symbol: `BotManager.get_crew -> load_crew / load_crew_by_id`
  excerpt: |
    crew_def = await self.crew_redis.load_crew(identifier, tenant)
        crew_def = await self.crew_redis.load_crew_by_id(identifier, tenant)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3415-3422
  symbol: `BotManager.remove_crew -> delete_crew`
  excerpt: |
    await self.crew_redis.delete_crew(crew_def.name, crew_def.tenant)

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3464-3474
  symbol: `BotManager.load_crews (startup) -> ping + get_all_crews`
  excerpt: |
    if not await self.crew_redis.ping(): ...
    crew_defs = await self.crew_redis.get_all_crews()

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 3512-3534
  symbol: `BotManager (sync/list) -> list_all_crews + load_crew`
  excerpt: |
    remote_entries = await self.crew_redis.list_all_crews()
    crew_def = await self.crew_redis.load_crew(name, tenant)

- path: `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py`
  lines: 1-22
  symbol: `store fixture`
  excerpt: |
    """``CrewRedis`` must keep already-stored crews loadable.
    from parrot.handlers.crew.redis_persistence import CrewRedis
    def store() -> CrewRedis:
        return CrewRedis(redis_url="redis://localhost:6379/15")

- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  lines: 177-192
  symbol: `test_enable_crews_false_no_crew_redis / test_enable_crews_true_creates_crew_redis`
  excerpt: |
    with patch("parrot.manager.manager.CrewRedis") as mock_crew_redis, ...
    assert bm.crew_redis is None
    mock_crew_redis.assert_not_called()
    ...
    assert bm.crew_redis is mock_crew_redis.return_value

- path: `packages/ai-parrot-server/tests/manager/test_load_bots_experts.py`
  lines: 17
  symbol: `monkeypatch CrewRedis`
  excerpt: |
    monkeypatch.setattr(manager_module, "CrewRedis", MagicMock())

## Notes

- Methods of CrewRedis NEVER called in production: `list_crews`, `crew_exists`, `get_crew_metadata`,
  `update_crew_metadata`, `close`, `clear_all_crews`. A Postgres store only strictly needs the 7 used ones
  (+ `close` for shutdown hygiene, which BotManager does not call today).
- `test_botmanager_flags.py` asserts `bm.crew_redis is mock_crew_redis.return_value` — if BotManager starts
  holding a composite/dual store, the attribute name `crew_redis` (or these tests) must be kept/updated.
- `packages/ai-parrot-server/build/lib/...` is a stale build artifact (different line numbers); ignore.
