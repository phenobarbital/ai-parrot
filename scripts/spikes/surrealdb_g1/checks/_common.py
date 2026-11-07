"""Shared helpers for G1 checks: metadata decorator, connection, and timing."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from harness import Check, SpikeContext


def g1_check(check_id: str, title: str, *, blocking: bool) -> Callable[[Check], Check]:
    """Attach runner metadata to a check coroutine."""

    def decorate(fn: Check) -> Check:
        fn.check_id = check_id  # type: ignore[attr-defined]
        fn.title = title  # type: ignore[attr-defined]
        fn.blocking = blocking  # type: ignore[attr-defined]
        return fn

    return decorate


@asynccontextmanager
async def connect(ctx: SpikeContext, namespace: str, database: str, *, reset: bool = False) -> AsyncIterator[Any]:
    """Open an authenticated WebSocket client scoped to a namespace and database.

    With ``reset=True`` the database is dropped and recreated first, so a check is re-runnable
    against a server that still holds state from a previous run.
    """
    from surrealdb import AsyncSurreal

    url = ctx.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    db = AsyncSurreal(url)
    await db.connect()
    try:
        await db.signin({"username": ctx.username, "password": ctx.password})
        await db.use(namespace, database)
        if reset:
            await db.query(f"REMOVE DATABASE IF EXISTS {database}; DEFINE DATABASE {database};").execute()
        yield db
    finally:
        await db.close()


async def execute(db: Any, query: str, variables: dict[str, Any] | None = None) -> list[Any]:
    """Execute every statement in a SurrealQL query and return their values."""
    return await db.query(query, variables).execute()


async def apply_schema(db: Any) -> list[Any]:
    """Apply the draft KnowledgeStore schema to the current database."""
    schema = Path(__file__).resolve().parents[1] / "schema.surql"
    return await execute(db, schema.read_text(encoding="utf-8"))


class Timer:
    """Measure a ``with`` block in wall-clock milliseconds."""

    ms: float

    def __enter__(self) -> "Timer":
        """Start the timer."""
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        """Record elapsed milliseconds."""
        self.ms = (time.perf_counter() - self._start) * 1000.0
