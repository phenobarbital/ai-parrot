"""GraphIndex persistence backend registry — the only composition root (FEAT-540 M7)."""

from __future__ import annotations

import importlib
import inspect
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from parrot._imports import lazy_import
from parrot.knowledge.graphindex.protocols import GraphPersistence
from parrot.knowledge.graphindex.schema import CommitReceipt

logger = logging.getLogger(__name__)


class GraphBackendSpec(BaseModel):
    """Registry entry: lazy factory path, required options, declared capabilities.

    Attributes:
        name: Registry key.
        factory: ``"module:callable"`` — imported on first use.
        required_options: Option names ``create_graph_persistence`` must receive (non-``None``).
        capabilities: Declared optional capabilities (``incremental`` | ``source_coherence`` |
            ``temporal`` | ``embeddings`` | ``hybrid``).
        extra: pip extra named in the ImportError message when a driver is absent.
        project_options: Optional ``"module:callable"`` mapping a project config to factory options.
    """

    name: str
    factory: str
    required_options: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    extra: str | None = None
    project_options: str | None = None


_REGISTRY: dict[str, GraphBackendSpec] = {}


def register_graph_backend(spec: GraphBackendSpec) -> None:
    """Register or replace a backend spec.

    Args:
        spec: The backend entry to store under ``spec.name``.
    """
    _REGISTRY[spec.name] = spec


def graph_backend_names() -> tuple[str, ...]:
    """Return the registered backend names in registration order."""
    return tuple(_REGISTRY)


def graph_backend_spec(name: str) -> GraphBackendSpec:
    """Return the spec registered under ``name``.

    Args:
        name: Backend name.

    Returns:
        The registered spec.

    Raises:
        ValueError: When ``name`` is unknown; the message lists the known backends.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown graph backend {name!r}; known: {', '.join(_REGISTRY)}") from None


def _import_factory(spec: GraphBackendSpec) -> Any:
    """Import ``spec.factory`` lazily, mapping a missing driver to the extra's install hint."""
    module_path, _, attr = spec.factory.partition(":")
    if not module_path or not attr:
        raise ValueError(f"graph backend {spec.name!r} has an invalid factory path {spec.factory!r}")
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        missing = exc.name
        # A missing third-party driver maps to the extra's install hint; our own modules re-raise unchanged.
        if missing and missing.split(".")[0] != "parrot":
            lazy_import(missing, extra=spec.extra)
        raise
    return getattr(module, attr)


async def create_graph_persistence(backend: str, **options: Any) -> GraphPersistence:
    """Resolve ``backend`` through the registry and build it.

    Args:
        backend: Registered backend name.
        **options: Backend options; every ``required_options`` entry must be present and non-``None``.

    Returns:
        The constructed persistence.

    Raises:
        ValueError: Unknown backend or a missing required option (named).
        ImportError: A driver is absent; the message names the pip extra.
    """
    spec = graph_backend_spec(backend)
    missing = [o for o in spec.required_options if options.get(o) is None]
    if missing:
        raise ValueError(f"graph backend {backend!r} requires option(s): {', '.join(missing)}")
    factory = _import_factory(spec)
    result = factory(**options)
    if inspect.isawaitable(result):
        result = await result
    return result


class NullPersistence:
    """In-memory no-op backend (promoted from ``graphindex/loader.py:_NullPersistence``).

    The full pipeline runs against it without a database; nothing is stored and every read is empty.
    """

    def __init__(self) -> None:
        self._seq = 0

    async def persist_graph(self, ctx: Any, nodes: list[Any], edges: list[Any]) -> dict[str, Any]:
        """Accept and discard a full graph."""
        return {"nodes_persisted": 0, "edges_persisted": 0}

    async def replace_document_slice(
        self,
        ctx: Any,
        document_uri: str,
        nodes: list[Any],
        edges: list[Any],
    ) -> dict[str, Any]:
        """Accept and discard a document slice."""
        return {"nodes_replaced": 0, "edges_replaced": 0}

    async def load_graph(self, ctx: Any) -> tuple[list[Any], list[Any]]:
        """Return the (always empty) current graph."""
        return [], []

    async def apply_update(self, ctx: Any, update: Any) -> CommitReceipt:
        """Discard the update and return a receipt with a fresh commit id."""
        self._seq += 1
        return CommitReceipt(
            commit_id=f"null-{self._seq:08d}-{uuid.uuid4().hex[:8]}",
            op=update.op,
            node_ids=[n.node_id for n in update.nodes],
            edge_keys=[(e.source_id, e.target_id, e.kind.value) for e in update.edges],
            committed_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        )

    async def get_commit(self, ctx: Any, commit_id: str) -> dict[str, Any] | None:
        """Return ``None`` — nothing is recorded."""
        return None

    async def list_commits(
        self,
        ctx: Any,
        *,
        run_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return an empty history."""
        return []

    async def revert_commit(
        self,
        ctx: Any,
        commit_id: str,
        *,
        agent_id: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Refuse every revert — no commit is ever stored."""
        return {"error": f"revert_commit: unknown commit {commit_id!r}"}

    async def close(self) -> None:
        """No-op: nothing to release."""


async def _create_sqlite(*, db_dir: Any, **_: Any) -> GraphPersistence:
    """Build a ``SQLitePersistence`` rooted at ``db_dir``."""
    from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence

    return SQLitePersistence(Path(db_dir))


async def _create_null(**_: Any) -> GraphPersistence:
    """Build a ``NullPersistence``."""
    return NullPersistence()


async def _create_postgres(
    *,
    dsn: str | None = None,
    schema: str | None = None,
    pool: Any = None,
    **_: Any,
) -> GraphPersistence:
    """Build a ``PostgresPersistence``; ``dsn``/``schema`` fall back to ``GRAPHINDEX_PG_*`` settings.

    The DSN comes from the ``dsn`` option, else the ``GRAPHINDEX_PG_DSN`` setting
    (environment variable or navconfig). The graph tree is framework-free and no
    longer falls back to the ``parrot.conf`` database default, so deployments that
    relied on that default must set ``GRAPHINDEX_PG_DSN`` explicitly.

    Raises:
        ValueError: When no DSN (and no ``pool``) is available.
    """
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
    from parrot.knowledge.graphindex.pg_schema import resolve_pg_settings

    if pool is not None:
        settings = resolve_pg_settings(schema=schema)
        return PostgresPersistence(pool=pool, schema=settings.schema_name)
    settings = resolve_pg_settings(dsn=dsn, schema=schema)
    if not settings.dsn:
        raise ValueError(
            "graph backend 'postgres' requires option(s): dsn (or GRAPHINDEX_PG_DSN). Set the GRAPHINDEX_PG_DSN "
            "environment variable / navconfig setting or pass dsn=...; the parrot.conf database default is no "
            "longer used by the framework-free graph tree."
        )
    return PostgresPersistence(settings.dsn, schema=settings.schema_name)


_BASE = "parrot.knowledge.graphindex"

for _spec in (
    GraphBackendSpec(
        name="sqlite",
        factory=f"{_BASE}.backends:_create_sqlite",
        required_options=("db_dir",),
        capabilities=("incremental", "source_coherence"),
    ),
    GraphBackendSpec(name="null", factory=f"{_BASE}.backends:_create_null"),
    GraphBackendSpec(
        name="postgres",
        factory=f"{_BASE}.backends:_create_postgres",
        capabilities=("temporal", "embeddings", "hybrid", "incremental", "source_coherence"),
        extra="graphindex-postgres",
    ),
    GraphBackendSpec(
        name="arangodb",
        factory=f"{_BASE}.persist_arango:create_arango_persistence",
        extra="arangodb",
    ),
):
    register_graph_backend(_spec)
