---
id: FG-003
query_id: Q020
type: git_log
intent: "Recent changes to the Postgres result backend (FEAT-307 DDL evolution)."
executed_at: 2026-11-09T17:16:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# FG-003 — Recent history of PostgresResultStorage (backends/postgres.py)

## Summary

All four commits land on 2026-07-14: the per-agent result `fetch()` read API
(crew-per-agent-result-persistence), FEAT-307's save-path enhancement and its
TASK-1768 "Read Methods + DDL Migration" (+221 lines, with a 231-line unit test
`tests/unit/test_postgres_result_storage_read.py`), then a "fixed crew storage
backends" follow-up. No changes since; this is the nearest precedent for an
in-code DDL migration (adding columns to an existing table) on a crew Postgres
store.

## Citations

- sha: `024fcac0ae`
  date: 2026-07-14
  author: Jesus
  message: "feat(crew-per-agent-result-persistence): TASK-1766 — ResultStorage.fetch() read API in 3 backends"

- sha: `f87dd63a77`
  date: 2026-07-14
  author: Jesus
  message: "feat(agentcrew-saved-crews): TASK-1766 — PersistenceMixin Save Path Enhancement"

- sha: `381a17c380`
  date: 2026-07-14
  author: Jesus
  message: "feat(agentcrew-saved-crews): TASK-1768 — PostgresResultStorage Read Methods + DDL Migration"
  files: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py` (+221), `tests/unit/test_postgres_result_storage_read.py` (+231)

- sha: `a18da9ba18`
  date: 2026-07-14
  author: Jesus
  message: "Merge branch 'feat-FEAT-307-agentcrew-saved-crews' into dev"

- sha: `7a8e440d94`
  date: 2026-07-14
  author: Jesus
  message: "fixed crew storage backends"

## Notes

- The read test lives at the repo-root `tests/unit/`, not under `packages/<dist>/tests/` —
  check whether it still exists there before citing it as the test pattern.
- [cross-lane: type=read, intent=read _ensure_table / ALTER TABLE ADD COLUMN IF NOT EXISTS logic in backends/postgres.py as the DDL-migration precedent]
