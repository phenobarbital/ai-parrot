# F004 — Reusable patterns and other callers
- Redis SET NX + TTL dedup already exists: packages/ai-parrot-integrations/src/parrot/integrations/slack/dedup.py:168 `RedisEventDeduplicator.is_duplicate` → `await self._redis.set(key, "1", nx=True, ex=self._ttl)`
- pg advisory xact lock example: packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py:397
- Redis settings helper: scheduler/sanitize.py `sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=6)` (manager.py:1700)
- Headless caller: packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:526, `start_headless(dsn=..., use_redis=config.scheduler.redis)` with listeners on (default) plus its own EVENT_JOB_EXECUTED/ERROR listeners. It is single-process, so the lock must be optional there.
- Tests: packages/ai-parrot-server/tests/scheduler/{test_headless,test_run_now,test_manager_sanitization,test_sanitize}.py. None cover the listeners on aiohttp, multi-worker behaviour, or redis serialization.
- History: af9e3cde70 (FEAT-467 TASK-2520, run-now + last-result; fixed the missing await in _update_schedule_run), 2017c501f4 (FEAT-422 TASK-2209, start_headless), 21b5fa6e82 (sanitize).
