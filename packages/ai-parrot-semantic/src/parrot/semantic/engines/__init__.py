"""Single native compiler entry point; caches contain pre-governance output only."""

from __future__ import annotations

import asyncio
import json

from ..cache import CompileCache
from ..loader import LoadedModel
from ..models import CompiledQuery, SemanticQuery
from .native import NativeCompiler


def _cache_key(query: SemanticQuery, model: LoadedModel, dialect: str) -> str:
    """Return the versioned, canonical key for pre-governance compilation."""
    return json.dumps(
        [
            model.model_digest,
            model.policy_digest,
            query.canonical_json(),
            dialect,
            model.compiler_version,
            model.policy.connection,
        ],
        separators=(",", ":"),
    )


async def compile(
    query: SemanticQuery,
    model: LoadedModel,
    dialect: str,
    *,
    cache: CompileCache | None = None,
) -> CompiledQuery:
    """Compile under to_thread, or return immutable pre-governance cache output."""
    cache_key = _cache_key(query, model, dialect)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)
    if cache is not None:
        cache.put(compiled)
    return compiled
