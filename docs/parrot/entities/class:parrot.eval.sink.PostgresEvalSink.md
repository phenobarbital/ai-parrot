---
type: Wiki Entity
title: PostgresEvalSink
id: class:parrot.eval.sink.PostgresEvalSink
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist ``EvalReport`` objects to Postgres via asyncpg.
relates_to:
- concept: class:parrot.eval.sink.EvalReportSink
  rel: extends
---

# PostgresEvalSink

Defined in [`parrot.eval.sink`](../summaries/mod:parrot.eval.sink.md).

```python
class PostgresEvalSink(EvalReportSink)
```

Persist ``EvalReport`` objects to Postgres via asyncpg.

Schema:
    - ``eval_runs`` — one row per run (config + summary JSONB)
    - ``eval_results`` — one row per (task, attempt) pair (scores + trajectory JSONB)
    - ``eval_baselines`` — reserved for baseline regression gate
    - ``judge_cache`` — reserved for LLM-as-judge caching

DDL is idempotent (``CREATE TABLE IF NOT EXISTS``) so the sink
self-provisions on first use.

Args:
    dsn: asyncpg-compatible connection string.  Falls back to
        ``EVAL_DB_DSN`` from ``navconfig`` if not provided.

## Methods

- `async def persist(self, report: Any) -> str` — Write *report* to ``eval_runs`` + ``eval_results``.
