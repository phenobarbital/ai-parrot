---
type: Wiki Summary
title: parrot.eval.sink
id: mod:parrot.eval.sink
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persistence sinks for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.sink.EvalReportSink
  rel: defines
- concept: class:parrot.eval.sink.PostgresEvalSink
  rel: defines
---

# `parrot.eval.sink`

Persistence sinks for the Generic Agent Evaluation Harness.

FEAT-217 — Module 10.

``EvalReportSink``
    Abstract base that ``EvalRunner`` optionally calls after a run to
    persist the report.  Returns a ``run_id`` string.

``PostgresEvalSink``
    Writes ``eval_runs`` + ``eval_results`` rows using asyncpg and JSONB.
    Idempotent ``CREATE TABLE IF NOT EXISTS`` DDL so the sink self-provisions
    on first use.  Also creates ``eval_baselines`` and ``judge_cache`` tables
    for future use (schema reserved; population deferred).

The DSN is read from ``navconfig`` (``EVAL_DB_DSN`` key) or passed
explicitly to ``PostgresEvalSink.__init__``.

## Classes

- **`EvalReportSink(ABC)`** — Abstract persistence sink for ``EvalReport`` objects.
- **`PostgresEvalSink(EvalReportSink)`** — Persist ``EvalReport`` objects to Postgres via asyncpg.
