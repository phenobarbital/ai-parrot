---
id: FC-009
query_id: Q014
type: glob
intent: "Find existing tests for crew definition persistence."
executed_at: 2026-11-09T17:29:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# FC-009 — Crew-definition persistence has almost no tests (one Redis deserialize test); PgUISurfaceStore has the reusable fake-AsyncDB + live-DSN-gated test pattern

## Summary

`find packages/*/tests` for `*crew*{redis,persist,storage,definition}*` returns only
`packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py` (4 tests of
`CrewRedis._deserialize_crew` stripping unknown keys; no Redis I/O — `Redis.from_url` is lazy), plus two
Google-key tests unrelated to storage (`test_crew_handler_google_key.py`,
`test_crew_from_definition_google_key.py`). `save_crew/load_crew/list_all_crews/delete_crew` and
`BotManager.load_crews/sync_crews` have NO round-trip tests. The best Postgres test precedent is
`PgUISurfaceStore`: `tests/handlers/test_ui_surfaces_store.py` monkeypatches `store._get_db` with an
in-memory `_FakeAsyncDB` (offline unit tests incl. `test_ensure_schema_idempotent`), and
`test_ui_surfaces_store_live.py` runs against a real DB only when `NAVIGATOR_PG_DSN` is set (skipif).

## Citations

- path: `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py`
  lines: 16-38
  symbol: `store fixture / test_unknown_root_key_is_dropped`
  excerpt: |
    from parrot.handlers.crew.redis_persistence import CrewRedis
    @pytest.fixture
    def store() -> CrewRedis:
        """A store instance. ``Redis.from_url`` does not connect eagerly."""
        return CrewRedis(redis_url="redis://localhost:6379/15")
    def test_unknown_root_key_is_dropped(store):
        crew = store._deserialize_crew(_payload(tasks=[]))

- path: `packages/ai-parrot-server/tests/unit/test_crew_redis_legacy_payloads.py`
  lines: 39-59
  symbol: `test_unknown_key_inside_an_agent/tool_node/relation_is_dropped`
  excerpt: |
    def test_unknown_key_inside_an_agent_is_dropped(store):
    def test_unknown_key_inside_a_tool_node_is_dropped(store):
    def test_unknown_key_inside_a_relation_is_dropped(store):

- path: `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store.py`
  lines: 266-319
  symbol: `pg_store fixture / test_ensure_schema_idempotent`
  excerpt: |
    def pg_store(monkeypatch, fake_state):
        store = m.PgUISurfaceStore(dsn="postgres://fake/test")
        monkeypatch.setattr(store, "_get_db", lambda: _FakeAsyncDB(fake_state))
    async def test_ensure_schema_idempotent(pg_store, fake_state):
    async def test_save_get_roundtrip_envelope_intact(pg_store):

- path: `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_store_live.py`
  lines: 3, 33-34, 69-76
  symbol: `live gate`
  excerpt: |
    Gated on ``NAVIGATOR_PG_DSN`` (skips cleanly when unset — no live database
    DSN = os.getenv("NAVIGATOR_PG_DSN", "")
    pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not DSN, reason="NAVIGATOR_PG_DSN not set (fs-scratch-pg)")]
    return m.PgUISurfaceStore(dsn=DSN)

- path: `packages/ai-parrot/tests/test_botmanager_flags.py`
  lines: 177-192
  symbol: `enable_crews flag tests`
  excerpt: |
    def test_enable_crews_false_no_crew_redis(): ... assert bm.crew_redis is None
    def test_enable_crews_true_creates_crew_redis(): ... mock_crew_redis.assert_called_once()

## Notes

- Redis tests in this repo use a real localhost Redis db 15 + skip-if-unreachable (fakeredis is not
  installed) — a migration test (Redis → Postgres) needs either a fake for both sides or a dual live gate.
- `_FakeAsyncDB` from `test_ui_surfaces_store.py` is test-local; a crew store test would copy or extract it.
- `test_botmanager_flags.py` will need updating if BotManager instantiates more than `CrewRedis`.
