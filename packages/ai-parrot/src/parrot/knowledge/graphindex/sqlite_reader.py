"""SQLiteGraphReader — read side of the SQLite GraphIndex artefact (FEAT-240).

HOT: graph topology loaded into an in-memory rustworkx ``PyDiGraph`` for
instant, deterministic navigation after a single ``await reader.load()``
call.  All HOT navigation methods (``list_models``, ``children``,
``who_extends``, ``find_model``) are synchronous and O(degree) once loaded.

COLD: source bodies resolved on demand from disk via line spans stamped in
``domain_tags``, bounded by a configurable LRU cache.  Lexical search runs
over FTS5/BM25 through the open ``aiosqlite`` connection.

No embeddings or semantic similarity are involved in this component.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import aiosqlite
import orjson
import rustworkx as rx

logger = logging.getLogger(__name__)


def _loads_tags(raw: Optional[str]) -> dict:
    """Deserialize a ``domain_tags`` JSON string from the DB.

    Args:
        raw: JSON string from the ``domain_tags`` column, or ``None``.

    Returns:
        Parsed dict, or empty dict on parse failure.
    """
    if not raw:
        return {}
    try:
        return orjson.loads(raw)
    except Exception:
        return {}


class SQLiteGraphReader:
    """Read-only navigator over a per-tenant SQLite GraphIndex artefact.

    Call ``await reader.load()`` once before using any navigation or search
    method.  The HOT navigation methods are synchronous (pure in-memory graph
    traversal) while COLD methods (``search_symbols``, ``get_source``) are
    async because they touch SQLite or the filesystem.

    Args:
        db_path: Path to the ``<tenant_id>.db`` artefact produced by
            ``SQLitePersistence``.
        repo_root: Root directory to resolve ``source_uri`` paths for
            ``get_source``.  When ``None``, ``get_source`` falls back to
            returning the node's stored ``summary``.
        body_cache_size: Maximum entries in the COLD source-body LRU cache.
            Older entries are evicted when the cache is full.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        repo_root: Optional[Path] = None,
        body_cache_size: int = 256,
    ) -> None:
        self._db_path = Path(db_path)
        self._repo_root = Path(repo_root) if repo_root else None
        self._conn: Optional[aiosqlite.Connection] = None
        # rustworkx in-memory graph — node payload is the node_id string
        self._g: rx.PyDiGraph = rx.PyDiGraph()
        # node_id (str) → rustworkx vertex index (int)
        self._idx_by_id: dict[str, int] = {}
        # node_id (str) → full payload dict
        self._payload_by_id: dict[str, dict] = {}
        # model_name (str) → canonical node_id (str)
        self._model_index: dict[str, str] = {}
        self._loaded: bool = False
        # COLD body LRU (node_id → source slice)
        self._body_cache: OrderedDict[str, str] = OrderedDict()
        self._body_cache_size = body_cache_size

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load topology (nodes + edges) into the in-memory rustworkx graph.

        Opens the SQLite database in read-only mode.  Idempotent: subsequent
        calls return immediately if already loaded.

        Raises:
            aiosqlite.OperationalError: If the database file does not exist or
                cannot be opened.
        """
        if self._loaded:
            return
        self._conn = await aiosqlite.connect(
            f"file:{self._db_path}?mode=ro", uri=True
        )
        self._conn.row_factory = aiosqlite.Row

        async with self._conn.execute(
            "SELECT node_id, kind, title, source_uri, parent_id, summary,"
            " content_ref, provenance, domain_tags FROM nodes"
        ) as cur:
            async for row in cur:
                tags = _loads_tags(row["domain_tags"])
                payload = {
                    "node_id": row["node_id"],
                    "kind": row["kind"],
                    "title": row["title"],
                    "source_uri": row["source_uri"],
                    "parent_id": row["parent_id"],
                    "summary": row["summary"],
                    "content_ref": row["content_ref"],
                    "provenance": row["provenance"],
                    "domain_tags": tags,
                }
                idx = self._g.add_node(row["node_id"])
                self._idx_by_id[row["node_id"]] = idx
                self._payload_by_id[row["node_id"]] = payload
                if (
                    tags.get("symbol_type") == "odoo_model"
                    and tags.get("model_name")
                ):
                    self._model_index[tags["model_name"]] = row["node_id"]

        async with self._conn.execute(
            "SELECT source_id, target_id, kind FROM edges"
        ) as cur:
            async for row in cur:
                u = self._idx_by_id.get(row["source_id"])
                v = self._idx_by_id.get(row["target_id"])
                if u is not None and v is not None:
                    self._g.add_edge(u, v, row["kind"])

        self._loaded = True
        logger.info(
            "SQLiteGraphReader.load: %d nodes / %d edges from %s",
            self._g.num_nodes(),
            self._g.num_edges(),
            self._db_path,
        )

    async def close(self) -> None:
        """Close the underlying aiosqlite connection.

        Safe to call multiple times.
        """
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal guard
    # ------------------------------------------------------------------

    def _require_loaded(self) -> None:
        """Raise RuntimeError when ``load()`` has not been awaited.

        Raises:
            RuntimeError: When the reader is not yet loaded.
        """
        if not self._loaded:
            raise RuntimeError(
                "SQLiteGraphReader.load() must be awaited before navigation"
            )

    # ------------------------------------------------------------------
    # HOT navigation (sync, in-memory)
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[dict]:
        """Return the payload dict for a node by its ``node_id``.

        Args:
            node_id: The unique node identifier.

        Returns:
            Payload dict, or ``None`` if not found.
        """
        return self._payload_by_id.get(node_id)

    def list_models(self) -> list[str]:
        """Return sorted list of canonical Odoo model names.

        Raises:
            RuntimeError: When called before ``load()``.

        Returns:
            Sorted list of model technical names (e.g. ``["res.partner", ...]``).
        """
        self._require_loaded()
        return sorted(self._model_index)

    def children(
        self, node_id: str, *, symbol_type: Optional[str] = None
    ) -> list[dict]:
        """Return CONTAINS children of a node, optionally filtered by symbol_type.

        Traverses ``out_edges`` of the given node and returns payloads of nodes
        reachable via ``kind == "contains"`` edges.

        Args:
            node_id: Source node id.
            symbol_type: When provided, only children whose
                ``domain_tags["symbol_type"]`` matches are returned.

        Raises:
            RuntimeError: When called before ``load()``.

        Returns:
            List of child payload dicts.
        """
        self._require_loaded()
        idx = self._idx_by_id.get(node_id)
        if idx is None:
            return []
        out: list[dict] = []
        for (_u, v, kind) in self._g.out_edges(idx):
            if kind != "contains":
                continue
            child_node_id = self._g[v]
            payload = self._payload_by_id.get(child_node_id)
            if payload is None:
                continue
            if symbol_type and payload["domain_tags"].get("symbol_type") != symbol_type:
                continue
            out.append(payload)
        return out

    def who_extends(
        self, model_name: str, *, include_definers: bool = False
    ) -> list[dict]:
        """Return classes whose EXTENDS (and optionally DEFINES) point to the model.

        Args:
            model_name: Canonical Odoo model technical name.
            include_definers: When ``True``, also includes classes with a
                ``DEFINES`` edge to the canonical node.

        Raises:
            RuntimeError: When called before ``load()``.

        Returns:
            List of contributor payload dicts, each augmented with
            ``"relation"`` (edge kind) and ``"module"`` (top path segment).
        """
        self._require_loaded()
        canon_id = self._model_index.get(model_name)
        if canon_id is None:
            return []
        idx = self._idx_by_id[canon_id]
        wanted = {"extends"} | ({"defines"} if include_definers else set())
        out: list[dict] = []
        for (u, _v, kind) in self._g.in_edges(idx):
            if kind not in wanted:
                continue
            contributor_node_id = self._g[u]
            payload = self._payload_by_id.get(contributor_node_id)
            if payload is None:
                continue
            entry = dict(payload)
            entry["relation"] = kind
            entry["module"] = self._module_of(payload["source_uri"])
            out.append(entry)
        return out

    def find_model(self, model_name: str) -> Optional[dict]:
        """Aggregate view: canonical node + all contributors' fields + methods.

        Combines ``who_extends(include_definers=True)`` with ``children()``
        calls on each contributor to build a unified view of the model.

        Args:
            model_name: Canonical Odoo model technical name.

        Raises:
            RuntimeError: When called before ``load()``.

        Returns:
            ``{"model_name", "canonical_id", "contributors", "fields", "methods"}``
            or ``None`` if the model is not found.
        """
        self._require_loaded()
        canon_id = self._model_index.get(model_name)
        if canon_id is None:
            return None
        contributors = self.who_extends(model_name, include_definers=True)
        fields: list[dict] = []
        methods: list[dict] = []
        for c in contributors:
            module = self._module_of(c["source_uri"])
            for child in self.children(c["node_id"]):
                st = child["domain_tags"].get("symbol_type")
                entry = {**child, "module": module}
                if st == "odoo_field":
                    fields.append(entry)
                elif st == "function":
                    methods.append(entry)
        return {
            "model_name": model_name,
            "canonical_id": canon_id,
            "contributors": contributors,
            "fields": fields,
            "methods": methods,
        }

    # ------------------------------------------------------------------
    # COLD / lexical (async, I/O)
    # ------------------------------------------------------------------

    async def search_symbols(
        self, query: str, *, limit: int = 20
    ) -> list[dict]:
        """FTS5/BM25 lexical search over title + summary.

        Automatically calls ``load()`` if not yet loaded.  BM25 scores from
        SQLite FTS5 are negative; results are returned in ascending score order
        (best matches first).

        Args:
            query: FTS5 MATCH expression (e.g. ``"partner"`` or
                ``"res.partner"``).
            limit: Maximum number of results to return.

        Returns:
            List of result dicts with keys ``"node_id"``, ``"kind"``,
            ``"title"``, ``"source_uri"``, ``"summary"``, ``"score"``,
            ``"domain_tags"``.
        """
        await self.load()
        sql = (
            "SELECT n.node_id, n.kind, n.title, n.source_uri, n.summary,"
            " n.domain_tags, bm25(nodes_fts) AS score"
            " FROM nodes_fts JOIN nodes n ON n.node_id = nodes_fts.node_id"
            " WHERE nodes_fts MATCH ? ORDER BY score LIMIT ?"
        )
        out: list[dict] = []
        async with self._conn.execute(sql, (query, limit)) as cur:
            async for row in cur:
                out.append({
                    "node_id": row["node_id"],
                    "kind": row["kind"],
                    "title": row["title"],
                    "source_uri": row["source_uri"],
                    "summary": row["summary"],
                    "score": row["score"],
                    "domain_tags": _loads_tags(row["domain_tags"]),
                })
        return out

    async def get_source(self, node_id: str) -> Optional[str]:
        """Resolve a symbol's source slice from disk (COLD), LRU-cached.

        Uses ``domain_tags["lineno"]`` and ``domain_tags["end_lineno"]`` to
        read the exact line range from ``repo_root / source_uri``.  Falls back
        to the stored ``summary`` when ``repo_root`` is not configured or the
        file cannot be read.

        Args:
            node_id: The node to resolve source for.

        Returns:
            Source slice string, or ``None`` if the node is not found and no
            summary is available.
        """
        payload = self._payload_by_id.get(node_id)
        if payload is None:
            return None
        if node_id in self._body_cache:
            self._body_cache.move_to_end(node_id)
            return self._body_cache[node_id]

        tags = payload["domain_tags"]
        lineno = tags.get("lineno")
        end = tags.get("end_lineno")
        body: Optional[str] = None
        if self._repo_root and lineno and end:
            path = self._repo_root / payload["source_uri"]
            body = await asyncio.to_thread(self._read_span, path, lineno, end)
        if body is None:
            body = payload.get("summary")

        if body is not None:
            self._body_cache[node_id] = body
            self._body_cache.move_to_end(node_id)
            if len(self._body_cache) > self._body_cache_size:
                self._body_cache.popitem(last=False)
        return body

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_span(path: Path, lineno: int, end: int) -> Optional[str]:
        """Read a line-span slice from a source file (blocking).

        Args:
            path: Absolute path to the source file.
            lineno: 1-based start line (inclusive).
            end: 1-based end line (inclusive).

        Returns:
            Source slice string, or ``None`` if the file cannot be read.
        """
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return None
        return "".join(lines[lineno - 1 : end])

    @staticmethod
    def _module_of(source_uri: str) -> str:
        """Heuristic: return the top path segment as the Odoo module name.

        Returns an empty string for synthetic ``odoo-model://`` URIs.

        Args:
            source_uri: Node ``source_uri`` value.

        Returns:
            Top path segment string, or empty string.
        """
        if not source_uri or source_uri.startswith("odoo-model://"):
            return ""
        parts = Path(source_uri).parts
        return parts[0] if parts else ""
