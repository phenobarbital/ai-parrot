"""Agent Studio repositories (spec §2.5/§2.5a). Raw parametrised SQL over the host asyncdb pool."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from .models import StudioStorageError

logger = logging.getLogger("Parrot.AgentStudio.Storage")
NAVIGATOR_SCHEMA = "navigator"


@asynccontextmanager
async def studio_transaction(pool: Any) -> AsyncIterator[Any]:
    """The ONLY way repositories open a transaction (asyncdb pg: transaction()/commit()/rollback())."""
    async with pool.acquire() as conn:
        await conn.transaction()
        try:
            yield conn
        except BaseException:
            await conn.rollback()
            raise
        await conn.commit()


async def _exec(conn: Any, sql: str, *args: Any) -> Any:
    """conn.execute wrapper: raise StudioStorageError when asyncdb returns an error tuple."""
    outcome = await conn.execute(sql, *args)
    if isinstance(outcome, (list, tuple)) and len(outcome) == 2:
        result, error = outcome
        if error:
            logger.error("studio statement failed: %s", error)
            raise StudioStorageError(str(error))
        return result
    return outcome


async def _fetch_all(conn: Any, sql: str, *args: Any) -> list[Any]:
    """conn.fetch_all wrapper normalising asyncdb's ``None`` (zero rows) to ``[]``."""
    rows = await conn.fetch_all(sql, *args)
    return list(rows or [])
