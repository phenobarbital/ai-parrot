"""`DerivedSymbolIndex` — in-process qualname index over L0 nodes (OQ-7).

Spec §3.5.2. §4.2's original premise was false: ``graphindex/resolve.py``
is a cross-domain embedding-similarity stage, not a symbol table, and there
is no ``qualname`` field anywhere in L0. This index is instead built
in-process, at load time, from nodes already resident in the
``rustworkx.PyDiGraph`` — no L0 write, no new persistence (consistent with
the "derive, don't store" decision, spec §3.5).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.retrieval.models import NodeRef

logger = logging.getLogger(__name__)


class DerivedSymbolIndex:
    """A qualname → `NodeRef` lookup index derived from resident L0 nodes.

    Built once at load time over the nodes already in memory. Every
    qualname suffix (full dotted path, and every trailing sub-path) is
    registered, so a lookup by either the full qualname
    (``"module.PayRateEngine.resolve"``) or a trailing segment
    (``"resolve"``, ``"PayRateEngine.resolve"``) hits the same entries.

    Ambiguity is never resolved silently: if more than one symbol shares a
    looked-up suffix, `resolve` returns all of them (spec §3.5.2 —
    `anchor_count` in the classifier counts these distinct candidates, so
    ambiguity naturally routes a query toward ``COMPARATIVE``/``RELATIONAL``
    instead of guessing).
    """

    def __init__(
        self,
        suffix_index: Mapping[str, tuple[NodeRef, ...]],
        qualnames: Mapping[str, str],
    ) -> None:
        """Construct from already-computed index structures.

        Prefer `DerivedSymbolIndex.build` — this constructor exists mainly
        so tests can assemble fixtures directly.

        Args:
            suffix_index: ``qualname_suffix -> matching NodeRefs``.
            qualnames: ``node_id -> full derived qualname`` (kept for
                introspection/cross-checking, not used by `resolve`).
        """
        self._suffix_index = dict(suffix_index)
        self._qualnames = dict(qualnames)

    @classmethod
    def build(
        cls,
        nodes: Iterable[UniversalNode],
        *,
        repo: str,
        rev: str,
    ) -> DerivedSymbolIndex:
        """Build the index over a set of resident L0 nodes.

        Synchronous and I/O-free — this runs over nodes already in RAM
        (spec §3.5.2). Only ``SYMBOL`` nodes are indexed; other node kinds
        (``RATIONALE``, ``CONCEPT``, ...) have no qualname and are skipped.

        Args:
            nodes: All L0 nodes resident for one graph (module + class +
                function nodes, among others).
            repo: Repository name to stamp onto every emitted `NodeRef`.
            rev: Concrete git SHA to stamp onto every emitted `NodeRef` —
                typically ``WorkspacePin.rev_of(repo)`` at request time.

        Returns:
            A populated `DerivedSymbolIndex`.
        """
        by_id = {node.node_id: node for node in nodes}
        qualname_cache: dict[str, str] = {}

        def compute_qualname(node: UniversalNode, visiting: frozenset[str]) -> str:
            """Walk the `parent_id` chain to the module root, joining titles.

            Guards against a cyclic/self-referential `parent_id` chain: a
            node already on the current walk path breaks the recursion by
            returning its own title instead of looping forever.
            """
            cached = qualname_cache.get(node.node_id)
            if cached is not None:
                return cached
            if node.node_id in visiting:
                logger.warning(
                    "DerivedSymbolIndex: cyclic parent_id chain detected at "
                    "node_id=%r — breaking cycle",
                    node.node_id,
                )
                return node.title

            parent = by_id.get(node.parent_id) if node.parent_id else None
            if parent is None:
                qualname = node.title
            else:
                parent_qualname = compute_qualname(
                    parent, visiting | {node.node_id}
                )
                qualname = f"{parent_qualname}.{node.title}"

            qualname_cache[node.node_id] = qualname
            return qualname

        suffix_index: dict[str, list[NodeRef]] = {}
        qualnames: dict[str, str] = {}

        for node in nodes:
            if node.kind != NodeKind.SYMBOL:
                continue

            qualname = compute_qualname(node, frozenset())
            qualnames[node.node_id] = qualname

            # Cross-check against L0's one-level domain_tags["qualified_name"]
            # (code.py:351, function nodes only) — seed-and-verify, never
            # override: derivation wins on disagreement (spec §3.5.2).
            l0_qualified_name = node.domain_tags.get("qualified_name")
            if l0_qualified_name is not None and l0_qualified_name != qualname:
                logger.debug(
                    "DerivedSymbolIndex: derived qualname %r disagrees with "
                    "L0 domain_tags['qualified_name'] %r for node_id=%r — "
                    "derivation wins",
                    qualname,
                    l0_qualified_name,
                    node.node_id,
                )

            symbol_type = node.domain_tags.get("symbol_type")
            ref = NodeRef(
                repo=repo,
                rev=rev,
                path=node.source_uri,
                kind=node.kind,
                symbol_type=symbol_type,
                qualname=qualname,
            )

            parts = qualname.split(".")
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                suffix_index.setdefault(suffix, []).append(ref)

        frozen_suffix_index = {key: tuple(refs) for key, refs in suffix_index.items()}
        return cls(frozen_suffix_index, qualnames)

    def resolve(
        self, name: str, *, symbol_type: str | None = None
    ) -> tuple[NodeRef, ...]:
        """Resolve `name` (full qualname or trailing segment) to NodeRefs.

        Args:
            name: A full dotted qualname or any trailing segment of one
                (e.g. ``"resolve"`` or ``"PayRateEngine.resolve"``).
            symbol_type: Optional filter — one of ``"module"``, ``"class"``,
                ``"function"``.

        Returns:
            ALL matching `NodeRef`s. Ambiguity is surfaced, never resolved
            by picking a winner — empty tuple if nothing matches.
        """
        candidates = self._suffix_index.get(name, ())
        if symbol_type is not None:
            candidates = tuple(c for c in candidates if c.symbol_type == symbol_type)
        return candidates

    def qualname_of(self, node_id: str) -> str | None:
        """Return the derived qualname for `node_id`, if it was indexed."""
        return self._qualnames.get(node_id)
