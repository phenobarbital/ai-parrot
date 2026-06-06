"""Persistence sinks for the Generic Agent Evaluation Harness.

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
"""
from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EvalReportSink ABC
# ---------------------------------------------------------------------------


class EvalReportSink(ABC):
    """Abstract persistence sink for ``EvalReport`` objects.

    ``EvalRunner`` calls ``sink.persist(report)`` after a run completes
    if a sink is configured.  The sink returns a ``run_id`` string that
    is written back into the report.
    """

    @abstractmethod
    async def persist(self, report: Any) -> str:
        """Persist *report* and return the assigned run identifier.

        Args:
            report: An ``EvalReport`` instance.

        Returns:
            A ``run_id`` string (UUID or database-generated).
        """
        ...


# ---------------------------------------------------------------------------
# PostgresEvalSink
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id          TEXT        PRIMARY KEY,
    dataset_name    TEXT        NOT NULL,
    config          JSONB       NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    summary         JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS eval_results (
    id          BIGSERIAL   PRIMARY KEY,
    run_id      TEXT        NOT NULL REFERENCES eval_runs(run_id) ON DELETE CASCADE,
    task_id     TEXT        NOT NULL,
    attempt     INTEGER     NOT NULL DEFAULT 1,
    passed      BOOLEAN     NOT NULL,
    scores      JSONB       NOT NULL DEFAULT '[]',
    trajectory  JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS eval_baselines (
    id              BIGSERIAL   PRIMARY KEY,
    dataset_name    TEXT        NOT NULL,
    tag             TEXT        NOT NULL DEFAULT '',
    run_id          TEXT        NOT NULL,
    pass_k          FLOAT,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS judge_cache (
    id                  BIGSERIAL   PRIMARY KEY,
    cache_key           TEXT        NOT NULL UNIQUE,
    judge_model_version TEXT        NOT NULL DEFAULT '',
    rubric_version      TEXT        NOT NULL DEFAULT '',
    verdict             JSONB       NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresEvalSink(EvalReportSink):
    """Persist ``EvalReport`` objects to Postgres via asyncpg.

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
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or self._resolve_dsn()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _resolve_dsn() -> str | None:
        """Read DSN from navconfig.

        Returns:
            DSN string or ``None`` if not configured.
        """
        try:
            from navconfig import config  # type: ignore[import]
            return config("EVAL_DB_DSN", default=None)
        except Exception:
            return None

    async def _ensure_schema(self, conn: Any) -> None:
        """Run idempotent DDL to create all eval tables.

        Args:
            conn: An asyncpg connection.
        """
        await conn.execute(_SCHEMA_DDL)

    async def persist(self, report: Any) -> str:
        """Write *report* to ``eval_runs`` + ``eval_results``.

        Args:
            report: ``EvalReport`` Pydantic model.

        Returns:
            The ``run_id`` assigned to this run.

        Raises:
            RuntimeError: If no DSN is configured.
            asyncpg.PostgresError: On database errors.
        """
        if not self._dsn:
            raise RuntimeError(
                "PostgresEvalSink: no DSN configured. "
                "Set EVAL_DB_DSN in environment or pass dsn= to constructor."
            )

        import asyncpg  # type: ignore[import]

        run_id = getattr(report, "run_id", None) or str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Build summary JSONB
        summary = {
            "pass_k": getattr(report, "pass_k", None),
            "pass_at_1": getattr(report, "pass_at_1", None),
            "total_tasks": getattr(report, "total_tasks", 0),
            "total_attempts": getattr(report, "total_attempts", 0),
            "per_tag": getattr(report, "per_tag", {}),
            "p50_latency_ms": getattr(report, "p50_latency_ms", None),
            "p95_latency_ms": getattr(report, "p95_latency_ms", None),
        }
        config_dict = {}
        cfg = getattr(report, "config", None)
        if cfg is not None:
            config_dict = cfg.model_dump() if hasattr(cfg, "model_dump") else dict(cfg)

        conn = await asyncpg.connect(self._dsn)
        try:
            await self._ensure_schema(conn)

            # Insert eval_run row
            await conn.execute(
                """
                INSERT INTO eval_runs (run_id, dataset_name, config, started_at,
                                       finished_at, summary)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb)
                ON CONFLICT (run_id) DO NOTHING
                """,
                run_id,
                getattr(report, "dataset_name", "unknown"),
                json.dumps(config_dict),
                now,
                now,
                json.dumps(summary),
            )

            # Insert eval_result rows
            results = getattr(report, "results", [])
            for result in results:
                trajectory = getattr(result, "trajectory", None)
                trajectory_dict = (
                    trajectory.model_dump() if hasattr(trajectory, "model_dump") else {}
                )
                scores = getattr(result, "scores", [])
                scores_list = [
                    s.model_dump() if hasattr(s, "model_dump") else dict(s)
                    for s in scores
                ]
                await conn.execute(
                    """
                    INSERT INTO eval_results
                        (run_id, task_id, attempt, passed, scores, trajectory)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
                    """,
                    run_id,
                    getattr(result, "task_id", ""),
                    getattr(result, "attempt", 1),
                    bool(getattr(result, "passed", False)),
                    json.dumps(scores_list),
                    json.dumps(trajectory_dict),
                )

            self.logger.info(
                "PostgresEvalSink: persisted run %s (%d results)",
                run_id,
                len(results),
            )
        finally:
            await conn.close()

        return run_id
