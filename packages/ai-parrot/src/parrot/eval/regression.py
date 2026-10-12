"""pass^k regression gate over eval_baselines (FEAT-652, Module 6)."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from parrot.eval.runner import EvalReport
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL

logger = logging.getLogger(__name__)
OVERALL_TAG = ""


class RegressionVerdict(BaseModel):
    """Outcome of comparing one report against stored baselines, per tag."""

    dataset_name: str
    tolerance: float
    overall_baseline: float | None = None
    overall_candidate: float | None = None
    regressed_tags: list[str] = Field(default_factory=list)
    passed: bool


class BaselineStore(ABC):
    """Latest pass^k per (dataset, tag); ``""`` is the overall figure."""

    @abstractmethod
    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None:
        """Return the latest recorded pass^k for ``(dataset_name, tag)`` or ``None``."""

    @abstractmethod
    async def record(self, report: EvalReport) -> None:
        """Record ``report.pass_k`` under ``""`` and every ``per_tag`` entry under its tag."""


class InMemoryBaselineStore(BaselineStore):
    """Process-local baseline store keeping the last written value per key."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], float] = {}

    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None:
        """Return the stored baseline for ``(dataset_name, tag)``."""
        return self._rows.get((dataset_name, tag))

    async def record(self, report: EvalReport) -> None:
        """Store the overall figure and every per-tag figure of ``report``."""
        if report.pass_k is not None:
            self._rows[(report.dataset_name, OVERALL_TAG)] = report.pass_k
        for tag, value in report.per_tag.items():
            self._rows[(report.dataset_name, tag)] = value


async def check_regression(report: EvalReport, store: BaselineStore, *, tolerance: float = 0.05) -> RegressionVerdict:
    """Compare a report with stored baselines per tag; never records.

    A tag regresses iff ``baseline - candidate > tolerance``, evaluated
    independently per tag. Tags without a baseline never regress.

    Args:
        report: The candidate evaluation report.
        store: Baseline store to read from.
        tolerance: Allowed drop before a tag counts as regressed.

    Returns:
        The per-tag verdict.
    """
    candidates: dict[str, float | None] = {OVERALL_TAG: report.pass_k, **report.per_tag}
    regressed: list[str] = []
    overall_baseline: float | None = None
    for tag, candidate in candidates.items():
        baseline = await store.get_baseline(report.dataset_name, tag)
        if tag == OVERALL_TAG:
            overall_baseline = baseline
        if candidate is None or baseline is None:
            continue
        if baseline - candidate > tolerance:
            regressed.append(tag)
    return RegressionVerdict(
        dataset_name=report.dataset_name,
        tolerance=tolerance,
        overall_baseline=overall_baseline,
        overall_candidate=report.pass_k,
        regressed_tags=regressed,
        passed=not regressed,
    )


class PostgresBaselineStore(BaselineStore):
    """asyncpg over ``eval_baselines`` (DDL from the sink); latest row by ``captured_at``."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or PostgresEvalSink._resolve_dsn()
        self.logger = logging.getLogger(__name__)
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _ensure_schema(self, conn) -> None:
        """Run the schema DDL at most once per instance (serialized, so concurrent callers never race)."""
        if self._schema_ready:
            return
        async with self._schema_lock:
            if not self._schema_ready:
                await conn.execute(_SCHEMA_DDL)
                self._schema_ready = True

    def _require_dsn(self) -> str:
        if not self._dsn:
            raise RuntimeError("PostgresBaselineStore: no DSN configured. Set EVAL_DB_DSN or pass dsn=.")
        return self._dsn

    async def get_baseline(self, dataset_name: str, tag: str = OVERALL_TAG) -> float | None:
        """Return the latest stored pass^k for ``(dataset_name, tag)``."""
        dsn = self._require_dsn()
        import asyncpg  # lazy, optional dependency

        conn = await asyncpg.connect(dsn)
        try:
            await self._ensure_schema(conn)
            row = await conn.fetchrow(
                "SELECT pass_k FROM eval_baselines WHERE dataset_name = $1 AND tag = $2 "
                "ORDER BY captured_at DESC, id DESC LIMIT 1",
                dataset_name,
                tag,
            )
        finally:
            await conn.close()
        return None if row is None or row["pass_k"] is None else float(row["pass_k"])

    async def record(self, report: EvalReport) -> None:
        """Insert one baseline row for the overall figure and one per tag."""
        dsn = self._require_dsn()
        rows: list[tuple[str, float]] = []
        if report.pass_k is not None:
            rows.append((OVERALL_TAG, report.pass_k))
        rows.extend(report.per_tag.items())
        import asyncpg  # lazy, optional dependency

        conn = await asyncpg.connect(dsn)
        try:
            await self._ensure_schema(conn)
            for tag, value in rows:
                await conn.execute(
                    "INSERT INTO eval_baselines (dataset_name, tag, run_id, pass_k) VALUES ($1, $2, $3, $4)",
                    report.dataset_name,
                    tag,
                    report.run_id,
                    value,
                )
        finally:
            await conn.close()
