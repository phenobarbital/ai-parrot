"""`DirectSymbolPolicy` — the no-traversal, no-LLM fast path (spec §5.1).

Symbol-table lookup → node body + immediate `Rationale` children. No
vector search, no general graph traversal, no LLM call. This is the
policy R1 short-circuits to, and the one that makes §4.4's escalation
argument work in the first place.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import aiosqlite
from pydantic import BaseModel, ConfigDict

from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind, UniversalNode
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader
from parrot.knowledge.retrieval.digest import derive_digest
from parrot.knowledge.retrieval.features import extract_features
from parrot.knowledge.retrieval.models import (
    ContextBundle,
    ContextUnit,
    EdgeRef,
    Evidence,
    EvidenceOrigin,
    NodeRef,
    RetrievalBudget,
    RetrievalRequest,
)
from parrot.knowledge.retrieval.pin import read_at_rev
from parrot.knowledge.retrieval.policies.base import Seed, Subgraph
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex

logger = logging.getLogger(__name__)


def build_node_id_index(
    nodes: Iterable[UniversalNode], symbols: DerivedSymbolIndex
) -> dict[tuple[str, str], str]:
    """Build the ``(path, qualname) -> node_id`` index `DirectSymbolPolicy` needs.

    `DerivedSymbolIndex.resolve()` (TASK-2276) returns qualname-carrying
    `NodeRef`s with no `node_id` attached, but `DirectSymbolPolicy` needs
    the L0 `node_id` back (to fetch `domain_tags` via
    `reader.get_node()`). This index bridges that gap, using the SAME
    qualname-derivation rule the policy uses when it fabricates a
    `NodeRef` for a rationale child: the `DerivedSymbolIndex`-computed
    qualname for ``SYMBOL`` nodes, falling back to the node's own
    ``title`` for non-``SYMBOL`` nodes (``RATIONALE`` has no qualname of
    its own).

    Args:
        nodes: The same L0 nodes `symbols` was built from — must include
            every node `DirectSymbolPolicy` might need to assemble
            (symbols AND their rationale children).
        symbols: The `DerivedSymbolIndex` built from `nodes`.

    Returns:
        ``(source_uri, qualname_or_title) -> node_id``.
    """
    index: dict[tuple[str, str], str] = {}
    for node in nodes:
        qualname = symbols.qualname_of(node.node_id) or node.title
        index[(node.source_uri, qualname)] = node.node_id
    return index


def _rationale_children(reader: SQLiteGraphReader, node_id: str) -> list[dict]:
    """Return payload dicts of nodes with an inbound EXPLAINS edge to `node_id`.

    ``EXPLAINS`` points ``rationale --explains--> symbol``
    (`extractors/code.py:506-512`), so a symbol's rationale children are
    found by walking *inbound* edges of that kind — never outbound.

    `SQLiteGraphReader` exposes no public, edge-kind-generic inbound
    traversal (`children()` is CONTAINS-only, `who_extends()` is
    EXTENDS/DEFINES-only for Odoo), and adding one would be an L0 change
    out of scope (spec §1.2: consumed read-only). This mirrors
    `who_extends`'s exact `self._g.in_edges(idx)` pattern against the
    reader's already-loaded in-memory graph, without modifying
    `sqlite_reader.py`.

    Args:
        reader: An already-``load()``ed `SQLiteGraphReader`.
        node_id: The symbol node's L0 ``node_id``.

    Returns:
        Payload dicts for every ``RATIONALE`` node explaining `node_id`.
    """
    idx = reader._idx_by_id.get(node_id)
    if idx is None:
        return []
    out: list[dict] = []
    for u, _v, kind in reader._g.in_edges(idx):
        if kind != "explains":
            continue
        rationale_node_id = reader._g[u]
        payload = reader._payload_by_id.get(rationale_node_id)
        if payload is not None:
            out.append(payload)
    return out


async def read_file_sha1(reader: Any, source_uri: str) -> str | None:
    """Read the per-file ``sha1`` for `source_uri` from the ``files`` table.

    Correctness fix (found in code review): ``domain_tags["sha1"]`` is
    populated ONLY on module nodes (`extractors/code.py:155-157`).
    Falling back to it for a `DigestScope.FILE`-eligible node that isn't a
    module (chiefly `RATIONALE` nodes, per spec §3.5.1) silently starves
    `derive_digest` of a `file_sha1`, which then falls through to
    `DigestScope.SUMMARY` instead — a real-but-hidden weakening of INV-2
    for exactly the node kind the spec calls out as the load-bearing case.
    This reads the `files` table directly so `FILE` scope is actually
    reachable for non-module nodes.

    `SQLiteGraphReader` exposes no public accessor for the ``files``
    table — this reads its already-open connection directly (``_conn``,
    private), the same precedent as `_rationale_children`'s ``_g`` access,
    rather than modifying `sqlite_reader.py` (out of scope, spec §1.2).

    Args:
        reader: The `SQLiteGraphReader` (or reader-shaped test double —
            duck-typed callers that lack ``_conn`` degrade to ``None``
            rather than raising).
        source_uri: The node's ``source_uri``.

    Returns:
        The stored ``sha1``, or ``None`` if unavailable — callers then
        fall back to `DigestScope.SUMMARY`, same as before this fix, never
        worse.
    """
    conn = getattr(reader, "_conn", None)
    if conn is None:
        return None
    try:
        async with conn.execute(
            "SELECT sha1 FROM files WHERE source_uri = ?", (source_uri,)
        ) as cur:
            row = await cur.fetchone()
    except aiosqlite.Error:
        logger.debug("read_file_sha1: could not query files table for %r", source_uri)
        return None
    return row["sha1"] if row is not None else None


class DirectSymbolPolicy(BaseModel):
    """Symbol-table lookup → node body + immediate rationale children.

    No vector search, no FTS call, no traversal beyond the symbol's own
    inbound ``EXPLAINS`` edges. Target p50 < 15 ms (spec §5.1) — not an
    acceptance criterion here (spec §13); T13 measures it.

    Attributes:
        kind: Discriminator for the future `RetrievalPolicy` union
            (spec §5.0).
        symbols: The `DerivedSymbolIndex` to resolve query tokens against.
        reader: An already-``load()``ed `SQLiteGraphReader` for node
            payloads (`domain_tags`, rationale traversal).
        node_id_by_qualname: ``(path, qualname) -> node_id`` — bridges
            `DerivedSymbolIndex.resolve()`'s qualname-carrying `NodeRef`s
            back to L0 ``node_id``s, needed to fetch `domain_tags` via
            `reader.get_node()`. Build with `build_node_id_index`.
        repo: Repository name this policy serves (must match a pin in the
            request's `WorkspacePin`).
        repo_path: Local filesystem working-tree path, for `read_at_rev`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["direct_symbol"] = "direct_symbol"
    symbols: DerivedSymbolIndex
    reader: SQLiteGraphReader
    node_id_by_qualname: dict[tuple[str, str], str]
    repo: str
    repo_path: Path

    async def seed(self, req: RetrievalRequest, graph: Any = None) -> tuple[Seed, ...]:
        """Resolve `req.query` via the symbol index. No vector search, no FTS.

        Args:
            req: The retrieval request.
            graph: Unused — `DirectSymbolPolicy` needs no graph traversal
                to seed (accepted for `RetrievalPolicyProtocol` shape).

        Returns:
            One `Seed` per distinct resolved anchor.
        """
        del graph
        features = extract_features(req.query, self.symbols)
        return tuple(Seed(node=node, score=1.0) for node in features.resolved_symbols)

    async def expand(
        self, seeds: tuple[Seed, ...], graph: Any, budget: RetrievalBudget
    ) -> Subgraph:
        """Expand each seed to its immediate rationale children — nothing else.

        Args:
            seeds: Seed anchors from `seed`.
            graph: Unused (the reader is bound on `self`).
            budget: The request's `RetrievalBudget`.

        Returns:
            A `Subgraph` containing every seed plus its rationale
            children (deduplicated), truncated if `budget.deadline_ms`
            was exhausted mid-expansion.
        """
        del graph
        start = time.monotonic()
        nodes = list(seeds)
        edge_paths: list[tuple[EdgeRef, ...]] = [() for _ in seeds]
        truncated = False

        for seed in seeds:
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > budget.deadline_ms:
                truncated = True
                break

            node_id = self.node_id_by_qualname.get((seed.node.path, seed.node.qualname))
            if node_id is None:
                continue
            for payload in _rationale_children(self.reader, node_id):
                rationale_ref = self._node_ref_from_payload(payload, seed.node.rev)
                edge = EdgeRef(
                    source=rationale_ref,
                    target=seed.node,
                    kind=EdgeKind.EXPLAINS,
                    derivation="ast",
                )
                nodes.append(Seed(node=rationale_ref, score=seed.score))
                edge_paths.append((edge,))

        node_refs = tuple(item.node for item in nodes)
        return Subgraph(nodes=node_refs, edge_paths=tuple(edge_paths), truncated=truncated)

    async def prune(self, subgraph: Subgraph, budget: RetrievalBudget) -> Subgraph:
        """Trim to `budget.max_expansion_nodes` — budget trim only, no scoring.

        Args:
            subgraph: The `Subgraph` from `expand`.
            budget: The request's `RetrievalBudget`.

        Returns:
            `subgraph`, trimmed to at most `budget.max_expansion_nodes`
            nodes if it exceeds that bound.
        """
        if len(subgraph.nodes) <= budget.max_expansion_nodes:
            return subgraph
        limit = budget.max_expansion_nodes
        return Subgraph(
            nodes=subgraph.nodes[:limit],
            edge_paths=subgraph.edge_paths[:limit],
            truncated=True,
        )

    async def assemble(self, subgraph: Subgraph, budget: RetrievalBudget) -> ContextBundle:
        """Read content at the pinned rev and build the `ContextBundle`.

        Every unit's `Evidence.digest` is computed over the exact bytes
        served (TASK-2273), read at the pinned rev via `read_at_rev`
        (TASK-2275) — never the working tree — so INV-2 closure holds by
        construction.

        Args:
            subgraph: The (pruned) `Subgraph` to assemble.
            budget: The request's `RetrievalBudget` — `deadline_ms`
                bounds this stage too (INV-5).

        Returns:
            The final `ContextBundle`. `truncated=True` if the deadline
            was hit before every node was assembled, or if `subgraph`
            itself already carried `truncated=True`.
        """
        start = time.monotonic()
        units: list[ContextUnit] = []
        truncated = subgraph.truncated

        for node, edge_path in zip(subgraph.nodes, subgraph.edge_paths, strict=True):
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > budget.deadline_ms:
                truncated = True
                break

            node_id = self.node_id_by_qualname.get((node.path, node.qualname))
            payload = self.reader.get_node(node_id) if node_id else None
            if payload is None:
                continue

            unit = await self._assemble_unit(node, edge_path, payload)
            if unit is not None:
                units.append(unit)

        token_total = sum(u.token_estimate for u in units)
        elapsed_ms = (time.monotonic() - start) * 1000
        return ContextBundle(
            units=tuple(units),
            decision=None,
            truncated=truncated,
            token_total=token_total,
            elapsed_ms=elapsed_ms,
        )

    async def _assemble_unit(
        self, node: NodeRef, edge_path: tuple[EdgeRef, ...], payload: dict
    ) -> ContextUnit | None:
        """Build one `ContextUnit` for `node`, reading content at the pinned rev."""
        domain_tags = payload.get("domain_tags") or {}
        lineno = domain_tags.get("lineno")
        end_lineno = domain_tags.get("end_lineno")

        source_bytes: bytes | None = None
        try:
            source_bytes = await read_at_rev(self.repo_path, node.rev, node.path)
        except LookupError:
            logger.warning(
                "DirectSymbolPolicy: could not read %r at rev %r — skipping unit",
                node.path,
                node.rev,
            )
            return None

        universal_node = UniversalNode(
            node_id=payload["node_id"],
            kind=NodeKind(payload["kind"]),
            title=payload["title"],
            source_uri=payload["source_uri"],
            summary=payload.get("summary"),
            domain_tags=domain_tags,
        )
        file_sha1 = domain_tags.get("sha1")
        if file_sha1 is None:
            # domain_tags["sha1"] only exists on module nodes; for other
            # kinds (chiefly RATIONALE), read the real per-file sha1 so
            # FILE scope is reachable rather than silently degrading to
            # SUMMARY (correctness fix, code review).
            file_sha1 = await read_file_sha1(self.reader, payload["source_uri"])
        digest, digest_scope = derive_digest(
            universal_node,
            source_bytes=source_bytes,
            file_sha1=file_sha1,
        )

        line_span: tuple[int, int] | None = None
        if lineno is not None and end_lineno is not None:
            lines = source_bytes.splitlines(keepends=True)
            text = b"".join(lines[int(lineno) - 1 : int(end_lineno)]).decode(
                "utf-8", errors="replace"
            )
            line_span = (int(lineno), int(end_lineno))
        else:
            text = payload.get("summary") or payload.get("title") or ""

        origin = (
            EvidenceOrigin.L1_RATIONALE
            if node.kind == NodeKind.RATIONALE
            else EvidenceOrigin.L0_SOURCE
        )

        evidence = Evidence(
            node=node,
            digest=digest,
            digest_scope=digest_scope,
            line_span=line_span,
            edge_path=edge_path,
            origin=origin,
            score=1.0,
        )
        return ContextUnit(text=text, evidence=evidence, token_estimate=len(text.split()))

    def _node_ref_from_payload(self, payload: dict, rev: str) -> NodeRef:
        """Build a `NodeRef` for a rationale-child payload dict."""
        qualname = self.symbols.qualname_of(payload["node_id"]) or payload["title"]
        return NodeRef(
            repo=self.repo,
            rev=rev,
            path=payload["source_uri"],
            kind=NodeKind(payload["kind"]),
            symbol_type=payload.get("domain_tags", {}).get("symbol_type"),
            qualname=qualname,
        )
