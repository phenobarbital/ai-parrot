"""JudgeCache backends (FEAT-652, Module 4)."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from parrot.eval.judge.models import JudgeVerdict
from parrot.eval.sink import PostgresEvalSink, _SCHEMA_DDL

logger = logging.getLogger(__name__)


class JudgeCache(ABC):
    """Async key -> verdict store."""

    @abstractmethod
    async def get(self, key: str) -> JudgeVerdict | None:
        """Return the cached verdict for ``key`` or ``None``."""

    @abstractmethod
    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None:
        """Store (or overwrite) the verdict for ``key``."""


class InMemoryJudgeCache(JudgeCache):
    """Dict-backed cache for tests and local runs."""

    def __init__(self) -> None:
        self._store: dict[str, JudgeVerdict] = {}

    async def get(self, key: str) -> JudgeVerdict | None:
        """Return the cached verdict for ``key`` or ``None``."""
        return self._store.get(key)

    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None:
        """Store the verdict for ``key``."""
        self._store[key] = verdict


class PostgresJudgeCache(JudgeCache):
    """asyncpg-backed cache over the ``judge_cache`` table created by ``PostgresEvalSink._SCHEMA_DDL``."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or PostgresEvalSink._resolve_dsn()
        self.logger = logging.getLogger(__name__)

    def _require_dsn(self) -> str:
        if not self._dsn:
            raise RuntimeError("PostgresJudgeCache: no DSN configured. Set EVAL_DB_DSN or pass dsn=.")
        return self._dsn

    async def get(self, key: str) -> JudgeVerdict | None:
        """Return the cached verdict for ``key`` or ``None``."""
        dsn = self._require_dsn()
        import asyncpg  # lazy, optional dependency (same as PostgresEvalSink)

        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(_SCHEMA_DDL)
            row = await conn.fetchrow("SELECT verdict FROM judge_cache WHERE cache_key = $1", key)
        finally:
            await conn.close()
        if row is None:
            return None
        raw = row["verdict"]
        if isinstance(raw, (str, bytes)):
            raw = json.loads(raw)
        return JudgeVerdict.model_validate(raw)

    async def set(self, key: str, verdict: JudgeVerdict, *, judge_model_version: str, rubric_version: str) -> None:
        """Upsert the verdict for ``key``."""
        dsn = self._require_dsn()
        import asyncpg  # lazy, optional dependency (same as PostgresEvalSink)

        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(_SCHEMA_DDL)
            await conn.execute(
                "INSERT INTO judge_cache (cache_key, judge_model_version, rubric_version, verdict) "
                "VALUES ($1, $2, $3, $4::jsonb) "
                "ON CONFLICT (cache_key) DO UPDATE SET verdict = EXCLUDED.verdict, "
                "judge_model_version = EXCLUDED.judge_model_version, "
                "rubric_version = EXCLUDED.rubric_version",
                key,
                judge_model_version,
                rubric_version,
                verdict.model_dump_json(),
            )
        finally:
            await conn.close()
