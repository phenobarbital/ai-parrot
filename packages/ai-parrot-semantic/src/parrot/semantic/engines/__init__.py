"""Single compiler dispatch selected by a model policy."""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from ..models import CompiledQuery, SemanticQuery

if TYPE_CHECKING:
    from ..cache import CompileCache
    from ..loader import LoadedModel

_LOCKS: dict[str, asyncio.Lock] = {}


def cache_key(query: SemanticQuery, model: "LoadedModel", dialect: str) -> str:
    """Build a subject-independent key for pre-governance compilation."""
    parts = [
        model.model_digest,
        model.policy_digest,
        query.canonical_json(),
        dialect,
        f"{model.policy.engine}:{model.engine_version}",
        model.policy.connection or "",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def compile(
    query: SemanticQuery,
    model: "LoadedModel",
    dialect: str,
    *,
    cache: "CompileCache | None" = None,
) -> CompiledQuery:
    """Compile pre-governance SQL, optionally reusing a cache entry."""
    key = cache_key(query, model, dialect)
    if cache is not None and (hit := cache.get(key)) is not None:
        return hit
    if model.policy.engine == "native":
        from .native import NativeCompiler

        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)
    else:
        from .sidemantic_engine import compile_sidemantic

        # sidemantic 0.12.0 produced identical SQL in a 128-call, 32-thread spike; no lock is required.
        compiled = await asyncio.to_thread(compile_sidemantic, query, model, dialect)
    compiled = compiled.model_copy(update={"cache_key": key})
    if cache is not None:
        cache.put(compiled)
    return compiled
