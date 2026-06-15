"""In-memory knowledge graph for OKF concept-level traversal.

Builds an adjacency structure keyed by ``concept_id`` from two sources:

1. **Typed ``relates_to`` edges** in the authoritative JSON (gold edges).
2. **Untyped prose markdown hyperlinks** parsed from sidecar bodies (noise
   edges with ``rel: references``).

The graph is built at load time and held in memory — there is no ArangoDB
dependency (D4; phase-2 persistence is separate).  Broken links (targets that
are not known concept_ids) are **tolerated and collected** for lint, never
fatal (OKF §5.3/§9).

Design notes:
- Multi-hop traversal via ``trace()`` follows a chain of typed relation types,
  e.g.  ``[maps_to, satisfied_by]``.
- ``parse_markdown_links`` skips fenced code blocks (` ``` `).
- ``build_graph`` is a convenience factory that loads bodies via a callable
  and constructs the full graph.
"""

import re
from typing import Any, Callable, Optional

from parrot.knowledge.pageindex.okf.ontology import RelationType
from parrot.knowledge.pageindex.okf.projection import flatten_concept_id_for_filename
from parrot.knowledge.pageindex.utils import structure_to_list


# Markdown link pattern: [text](target) where target is the link destination
_MD_LINK_RE = re.compile(r"\[(?:[^\[\]]*)\]\(([^)]+)\)")
# Fenced code block delimiter
_FENCE_RE = re.compile(r"^```", re.MULTILINE)


def parse_markdown_links(body: str) -> list[str]:
    """Extract markdown hyperlink targets from body text.

    Links inside fenced code blocks are skipped.  Leading slashes are
    stripped from targets (bundle-relative links per OKF §5.1).

    Args:
        body: Markdown body string.

    Returns:
        List of link target strings (concept_id candidates), deduplicated
        and ordered by appearance.
    """
    if not body:
        return []

    # Split body on fenced code block delimiters.
    # Tokens at even indices (0, 2, 4, …) are outside code fences.
    # Tokens at odd indices (1, 3, 5, …) are inside code fences.
    tokens = _FENCE_RE.split(body)
    seen: dict[str, None] = {}  # ordered dedup via insertion order
    for idx, token in enumerate(tokens):
        if idx % 2 == 1:
            # Inside a fenced code block — skip
            continue
        for match in _MD_LINK_RE.finditer(token):
            target = match.group(1).strip()
            # Strip leading slash (bundle-relative reference)
            if target.startswith("/"):
                target = target[1:]
            # Skip empty, external URLs, and anchor-only links
            if not target or target.startswith("http") or target.startswith("#"):
                continue
            seen[target] = None
    return list(seen.keys())


class KnowledgeGraph:
    """In-memory adjacency graph keyed by concept_id.

    Builds from ``relates_to`` edges in the JSON tree and from markdown
    hyperlinks in sidecar bodies (via ``build_graph``).

    Broken links (target concept_id unknown) are collected in ``_broken``
    but never raise an exception.

    Attributes:
        _adj: Adjacency dict ``{source_concept_id: [edge_dict, ...]}``.
        _concepts: Set of all known concept_ids.
        _broken: List of broken edge dicts.
    """

    def __init__(self, tree: dict[str, Any]) -> None:
        """Build the knowledge graph from a PageIndex tree dict.

        Processes all ``relates_to`` edges from the JSON.  To also add
        prose-link edges from sidecar bodies, call ``build_graph`` instead.

        Args:
            tree: PageIndex tree dict with ``structure`` list.
        """
        self._adj: dict[str, list[dict]] = {}
        self._concepts: set[str] = set()
        self._broken: list[dict] = []
        self._build(tree)

    def _build(self, tree: dict[str, Any]) -> None:
        """Collect all concept_ids, then process relates_to edges.

        Args:
            tree: PageIndex tree dict.
        """
        nodes = structure_to_list(tree.get("structure", []))

        # Pass 1: collect all concept_ids
        for node in nodes:
            cid = node.get("concept_id")
            if cid:
                self._concepts.add(cid)
                if cid not in self._adj:
                    self._adj[cid] = []

        # Pass 2: add relates_to edges
        for node in nodes:
            src = node.get("concept_id")
            if not src:
                continue
            for rel_entry in node.get("relates_to") or []:
                self._add_edge(src, rel_entry)

    def _add_edge(self, src: str, rel_entry: dict) -> None:
        """Add a single edge to the adjacency dict.

        Broken edges (unknown target) are collected in ``_broken``.

        Args:
            src: Source concept_id.
            rel_entry: Dict with ``concept`` (target) and ``rel`` (relation type).
        """
        target = rel_entry.get("concept", "")
        rel = rel_entry.get("rel", RelationType.REFERENCES.value)

        edge = {"concept": target, "rel": rel, "source": src}

        if src not in self._adj:
            self._adj[src] = []
        self._adj[src].append({"concept": target, "rel": rel})

        if target not in self._concepts:
            self._broken.append(edge)

    def add_prose_links(self, concept_id: str, body: str) -> None:
        """Add prose hyperlink edges from a sidecar body.

        Links are added with ``rel: references``.  This method is called by
        ``build_graph`` after the graph is initialised from JSON.

        Args:
            concept_id: Source concept_id.
            body: Sidecar body markdown.
        """
        if not body:
            return
        links = parse_markdown_links(body)
        for link in links:
            # Skip if already a relates_to edge to the same target
            existing = {e["concept"] for e in self._adj.get(concept_id, [])}
            if link in existing:
                continue
            self._add_edge(concept_id, {"concept": link, "rel": RelationType.REFERENCES.value})

    def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
    ) -> list[dict]:
        """Return neighbors of a concept, optionally filtered by relation type.

        Args:
            concept_id: Source concept_id to look up.
            rel: Optional relation type string to filter by.

        Returns:
            List of edge dicts ``{"concept": ..., "rel": ...}``.  Empty list
            if concept_id is unknown or has no edges.
        """
        edges = self._adj.get(concept_id, [])
        if rel is None:
            return list(edges)
        return [e for e in edges if e.get("rel") == rel]

    def trace(
        self,
        concept_id: str,
        rel_chain: list[str],
    ) -> list[list[str]]:
        """Multi-hop traversal following a chain of typed relations.

        At each hop, expand only edges whose ``rel`` matches the next type
        in ``rel_chain``.  All paths are returned.

        Args:
            concept_id: Starting concept_id.
            rel_chain: Ordered list of relation types to follow.

        Returns:
            List of paths.  Each path is a list of concept_ids from
            ``concept_id`` through all hops (inclusive).  Empty list if
            no paths found.
        """
        if not rel_chain:
            return [[concept_id]]

        next_rel = rel_chain[0]
        rest = rel_chain[1:]
        current_neighbors = self.neighbors(concept_id, rel=next_rel)
        paths: list[list[str]] = []
        for neighbor in current_neighbors:
            tgt = neighbor["concept"]
            if rest:
                sub_paths = self.trace(tgt, rest)
                for sub in sub_paths:
                    paths.append([concept_id] + sub)
            else:
                paths.append([concept_id, tgt])
        return paths

    def broken_links(self) -> list[dict]:
        """Return all edges whose target concept_id is unknown.

        Returns:
            List of broken edge dicts ``{"concept": ..., "rel": ..., "source": ...}``.
        """
        return list(self._broken)

    def concepts(self) -> set[str]:
        """Return the set of all known concept_ids.

        Returns:
            Set of concept_id strings.
        """
        return set(self._concepts)


def build_graph(
    tree: dict[str, Any],
    content_loader: Callable[[str], Optional[str]],
) -> KnowledgeGraph:
    """Build a full knowledge graph including prose link edges.

    Constructs a ``KnowledgeGraph`` from the tree JSON and then augments it
    with prose-link edges extracted from sidecar bodies via ``content_loader``.

    Args:
        tree: PageIndex tree dict with ``structure`` list.
        content_loader: Callable mapping ``concept_id -> Optional[str]``.
            Returns sidecar body content or ``None`` if not found.

    Returns:
        Fully built ``KnowledgeGraph``.
    """
    graph = KnowledgeGraph(tree)
    nodes = structure_to_list(tree.get("structure", []))
    for node in nodes:
        cid = node.get("concept_id")
        if not cid:
            continue
        # Try loading by flattened concept_id (primary), then bare concept_id
        flat = flatten_concept_id_for_filename(cid)
        body = content_loader(flat) or content_loader(cid)
        if body:
            graph.add_prose_links(cid, body)
    return graph
