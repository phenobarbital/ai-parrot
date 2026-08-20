"""`VectorSeedPolicy` — hybrid BM25 ∥ dense seeding, fused with RRF.

Spec §5.2, as corrected by OQ-9. **T6 seeds over what exists; T6b (durable
pgvector/HNSW) is deferred**, gated on T13 measuring a real miss — do NOT
build that here, and do NOT build a latency gate: the p50 < 120 ms target
is provisional (spec §13), since ``faiss.IndexFlatL2`` is an exhaustive
scan.

Two legs run concurrently (`asyncio.gather`) — a sequential seed would
double the stage §4.4's escalation cost model assumes is the expensive
one:

- **Lexical** — `SQLiteGraphReader.search_symbols()` (FTS5/BM25). Indexes
  **title + summary only, not bodies** — this caps recall and is a real
  limitation, not an oversight.
- **Dense** — an embedder exposing ``async search_similar(query_text,
  top_k) -> list[tuple[node_id, distance]]`` (the shape
  `GraphIndexEmbedder.search_similar` has, spec §14.2) over the in-process
  `faiss.IndexFlatL2`.

Fused with the existing `HybridPageIndexSearch._rrf_fuse` formula
(`pageindex/hybrid_search.py:277`) — reused verbatim, not reinvented.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind, UniversalNode
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.retrieval.digest import derive_digest
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

#: Matches `pageindex/hybrid_search.py`'s `_RRF_K` default exactly — the
#: two RRF implementations must not drift.
_RRF_K = 60

#: Word-character runs — everything FTS5's MATCH syntax treats as
#: punctuation (backticks, parens, quotes, dots, ``()``) is a token
#: separator, not part of a token.
_FTS_TOKEN_RE = re.compile(r"\w+")


def _sanitize_fts_query(query: str) -> str:
    """Turn free text into a safe, broad FTS5 MATCH expression.

    `req.query` may carry markdown-style code quoting
    (``` `Foo.bar()` ```), dotted qualified names, or other punctuation a
    caller used to mark up a symbol name — none of that is valid FTS5
    query syntax on its own (bareword tokens next to punctuation raise a
    parse error). Tokens are extracted and joined with ``OR`` rather than
    implicit ``AND``: title/summary are indexed per-row, so a query naming
    two different symbols (e.g. ``PayRateEngine.resolve``) should surface
    rows matching *either* token, ranked by BM25 — not only rows matching
    every token at once.

    Args:
        query: The raw query text.

    Returns:
        A sanitized ``token1 OR token2 OR ...`` string safe to pass to
        ``nodes_fts MATCH``, or ``""`` if `query` has no word tokens.
    """
    tokens = _FTS_TOKEN_RE.findall(query)
    return " OR ".join(tokens)


def _node_ref_from_payload(
    payload: dict, *, repo: str, rev: str, symbols: DerivedSymbolIndex
) -> NodeRef:
    """Build a `NodeRef` from a `search_symbols`/`get_node` payload dict."""
    qualname = symbols.qualname_of(payload["node_id"]) or payload["title"]
    return NodeRef(
        repo=repo,
        rev=rev,
        path=payload["source_uri"],
        kind=NodeKind(payload["kind"]),
        symbol_type=(payload.get("domain_tags") or {}).get("symbol_type"),
        qualname=qualname,
    )


class VectorSeedPolicy(BaseModel):
    """Hybrid BM25 ∥ dense seeding, fused with RRF; `expand` is depth-1 CONTAINS.

    Attributes:
        kind: Discriminator for the future `RetrievalPolicy` union
            (spec §5.0).
        symbols: The `DerivedSymbolIndex` for qualname derivation.
        reader: An object exposing `SQLiteGraphReader`'s ``search_symbols``/
            ``get_node``/``children`` methods (an already-``load()``ed
            `SQLiteGraphReader` in production), or ``None`` when the
            workspace's backend has no lexical leg (e.g. an ArangoDB-backed
            workspace — FTS5 exists only on SQLite). Typed loosely (not
            `SQLiteGraphReader` directly, same rationale as `embedder`) so
            a lightweight test double can stand in.
        supports_fts: Whether `reader` (when present) actually has a
            usable ``nodes_fts`` table. ``False`` degrades to dense-only
            even when `reader` is present (e.g. reader kept only for
            node-metadata lookups on a backend without FTS5).
        embedder: An object exposing ``async search_similar(query_text,
            top_k) -> list[tuple[str, float]]`` (the shape
            `GraphIndexEmbedder` has) — ``None`` when no dense leg is
            available. Typed loosely (not `GraphIndexEmbedder` directly)
            so a lightweight test double can stand in without pulling in
            a real embedding model.
        node_id_by_qualname: ``(path, qualname) -> node_id``, built by
            `build_node_id_index` — same bridge `DirectSymbolPolicy` uses.
        repo: Repository name this policy serves.
        rev: Concrete git SHA this policy's `symbols`/`reader` were built
            at — typically ``WorkspacePin.rev_of(repo)``. Search results
            carry no rev of their own, so it is stamped here (mirroring
            how `DirectSymbolPolicy` gets it implicitly via seed
            `NodeRef`s already produced by a rev-scoped
            `DerivedSymbolIndex`).
        repo_path: Local filesystem working-tree path, for `read_at_rev`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["vector_seed"] = "vector_seed"
    symbols: DerivedSymbolIndex
    reader: Any | None
    supports_fts: bool = True
    embedder: Any | None = None
    node_id_by_qualname: dict[tuple[str, str], str]
    repo: str
    rev: str
    repo_path: Path

    async def seed(
        self, req: RetrievalRequest, graph: Any = None, *, top_k: int = 20
    ) -> tuple[Seed, ...]:
        """Seed via BM25 ∥ dense, fused with RRF. Degrades gracefully.

        Runs both legs concurrently via `asyncio.gather` — never
        sequentially. If only one leg is available, that leg alone is
        used (no failure).

        Args:
            req: The retrieval request.
            graph: Unused (reader/embedder are bound on `self`).
            top_k: Maximum results per leg, and of the fused output.

        Returns:
            Fused `Seed`s, best-first by RRF score.
        """
        del graph
        node_meta: dict[str, dict] = {}
        tasks: list[Any] = []

        lexical_enabled = self.reader is not None and self.supports_fts
        dense_enabled = self.embedder is not None

        if lexical_enabled:
            tasks.append(self._lexical_leg(req.query, top_k, node_meta))
        if dense_enabled:
            tasks.append(self._dense_leg(req.query, top_k, node_meta))

        if not tasks:
            logger.warning("VectorSeedPolicy: no leg available (no reader, no embedder)")
            return ()

        rankings = await asyncio.gather(*tasks)
        fused = HybridPageIndexSearch._rrf_fuse(list(rankings), k=_RRF_K)

        seeds: list[Seed] = []
        for node_id, score in fused[:top_k]:
            payload = node_meta.get(node_id)
            if payload is None and self.reader is not None:
                payload = self.reader.get_node(node_id)
            if payload is None:
                continue
            node_ref = _node_ref_from_payload(
                payload, repo=self.repo, rev=self.rev, symbols=self.symbols
            )
            seeds.append(Seed(node=node_ref, score=score))
        return tuple(seeds)

    async def _lexical_leg(
        self, query: str, top_k: int, node_meta: dict[str, dict]
    ) -> list[str]:
        """FTS5/BM25 leg — title + summary only, not bodies.

        `search_symbols` already returns best-first order (ascending BM25
        score, per its own docstring) — no re-sorting needed, but this is
        exactly the kind of sign convention worth being explicit about
        rather than assumed.
        """
        assert self.reader is not None  # narrowed by caller (`lexical_enabled`)
        sanitized = _sanitize_fts_query(query)
        if not sanitized:
            return []
        results = await self.reader.search_symbols(sanitized, limit=top_k)
        for result in results:
            node_meta.setdefault(result["node_id"], result)
        return [r["node_id"] for r in results]

    async def _dense_leg(self, query: str, top_k: int, node_meta: dict[str, dict]) -> list[str]:
        """FAISS `FlatL2` leg — ascending L2 distance (smaller = more similar).

        `search_similar` already returns best-first order; distances are
        NOT scores (smaller is better) and must never be compared
        directly against BM25's negative scores — RRF sidesteps this by
        fusing on rank, not raw score, which is exactly why rank order
        (not the raw numbers) must be verified best-first per leg.
        """
        assert self.embedder is not None  # narrowed by caller (`dense_enabled`)
        hits = await self.embedder.search_similar(query, top_k=top_k)
        node_ids: list[str] = []
        for node_id, _distance in hits:
            node_ids.append(node_id)
            if node_id not in node_meta and self.reader is not None:
                payload = self.reader.get_node(node_id)
                if payload is not None:
                    node_meta[node_id] = payload
        return node_ids

    async def expand(
        self, seeds: tuple[Seed, ...], graph: Any, budget: RetrievalBudget
    ) -> Subgraph:
        """Expand each seed one hop over `EdgeKind.CONTAINS` only.

        Args:
            seeds: Seed anchors from `seed`.
            graph: Unused (the reader is bound on `self`).
            budget: The request's `RetrievalBudget`.

        Returns:
            A `Subgraph` of every seed plus its depth-1 CONTAINS children.
        """
        del graph
        if self.reader is None:
            return Subgraph(nodes=tuple(s.node for s in seeds), truncated=False)

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
            for child_payload in self.reader.children(node_id):
                child_ref = _node_ref_from_payload(
                    child_payload, repo=self.repo, rev=seed.node.rev, symbols=self.symbols
                )
                edge = EdgeRef(
                    source=seed.node, target=child_ref, kind=EdgeKind.CONTAINS, derivation="ast"
                )
                nodes.append(Seed(node=child_ref, score=seed.score))
                edge_paths.append((edge,))

        node_refs = tuple(item.node for item in nodes)
        return Subgraph(nodes=node_refs, edge_paths=tuple(edge_paths), truncated=truncated)

    async def prune(self, subgraph: Subgraph, budget: RetrievalBudget) -> Subgraph:
        """Trim to `budget.max_expansion_nodes` — budget trim only.

        Args:
            subgraph: The `Subgraph` from `expand`.
            budget: The request's `RetrievalBudget`.

        Returns:
            `subgraph`, trimmed if it exceeds `budget.max_expansion_nodes`.
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

        Args:
            subgraph: The (pruned) `Subgraph` to assemble.
            budget: The request's `RetrievalBudget`.

        Returns:
            The final `ContextBundle`.
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
            payload = self.reader.get_node(node_id) if (self.reader and node_id) else None
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
        """Build one `ContextUnit`, reading content at the pinned rev."""
        domain_tags = payload.get("domain_tags") or {}
        lineno = domain_tags.get("lineno")
        end_lineno = domain_tags.get("end_lineno")

        try:
            source_bytes = await read_at_rev(self.repo_path, node.rev, node.path)
        except LookupError:
            logger.warning(
                "VectorSeedPolicy: could not read %r at rev %r — skipping unit",
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
        digest, digest_scope = derive_digest(
            universal_node,
            source_bytes=source_bytes,
            file_sha1=domain_tags.get("sha1"),
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
