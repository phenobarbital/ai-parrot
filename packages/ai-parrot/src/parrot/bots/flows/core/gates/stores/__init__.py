"""Gate store backends and resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.launcher import parrot_home

from ..models import GateError, GateErrorCode, GateStore
from .redis import RedisGateStore
from .sqlite import SQLiteGateStore


def resolve_gate_store(
    *, backend: str | None = None, redis_client: Any = None, sqlite_path: Path | None = None
) -> GateStore:
    """Pick a store: explicit backend → Redis if a client is given → SQLite default (AC3)."""
    selected_backend = backend or ("redis" if redis_client is not None else "sqlite")
    if selected_backend == "helix":
        raise GateError(GateErrorCode.STORE_UNAVAILABLE, "HelixDB store not implemented (FEAT-890 §8 Q1)")
    if selected_backend == "redis":
        if redis_client is None:
            raise GateError(GateErrorCode.STORE_UNAVAILABLE, "Redis store requires a configured Redis client")
        return RedisGateStore(redis_client)
    if selected_backend == "sqlite":
        return SQLiteGateStore(sqlite_path or parrot_home() / "gates.sqlite")
    raise GateError(GateErrorCode.STORE_UNAVAILABLE, f"Unsupported gate store backend: {selected_backend}")


__all__ = ["RedisGateStore", "SQLiteGateStore", "resolve_gate_store"]
