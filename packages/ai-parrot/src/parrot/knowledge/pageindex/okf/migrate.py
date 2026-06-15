"""okf-migrate: Retrofit existing PageIndex trees with OKF fields.

This module provides ``okf_migrate()`` — the main migration command that
enriches a bare PageIndex tree with OKF fields:

1. Derives ``concept_id`` for every node via ``assign_concept_ids()``.
2. Classifies ``type`` via LLM with content-addressed caching; falls back
   to ``ConceptType.SECTION`` when LLM is unavailable or the adapter is
   ``None``.
3. Builds ``source`` provenance from ``doc_name`` + ``start_index``/``end_index``.
4. Parses sidecar body markdown links → ``relates_to`` candidates
   (``rel: references``).
5. Renames sidecars ``<node_id>.md`` → ``<flattened_concept_id>.md`` with
   projected frontmatter.
6. Generates root ``index.md``.
7. Saves the enriched tree JSON.
8. Emits a ``MigrationReport``.

The command is **idempotent**: re-running on an already-migrated tree
produces identical output.  Content-addressed type cache ensures LLM is
called at most once per (model_id, title, summary) tuple.

Design notes (spec §3 Module 6, D3, D8, D10):
- Only explicit markdown links become ``relates_to``; LLM-inferred edges
  are deferred to the HITL-gated pass.
- ``force_reclassify=True`` bypasses the content-addressed cache.
- Cache is persisted as a JSON sidecar alongside the tree.
"""

import hashlib
import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.concept_id import assign_concept_ids
from parrot.knowledge.pageindex.okf.graph import parse_markdown_links
from parrot.knowledge.pageindex.okf.ontology import ConceptType, SourceProvenance
from parrot.knowledge.pageindex.okf.projection import (
    flatten_concept_id_for_filename,
    generate_index_md,
    project_sidecars,
)
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "__okf_type_cache"


class MigrationReport(BaseModel):
    """Report produced by ``okf_migrate()``.

    Attributes:
        tree_name: Name of the migrated tree.
        nodes_processed: Total nodes processed.
        types_histogram: Count of each ConceptType assigned.
        links_resolved: Number of markdown links successfully resolved.
        links_broken: Number of markdown links with unknown targets.
        slug_collisions: Number of concept_id collisions resolved with suffixes.
        files_renamed: Number of sidecar files renamed to concept_id keys.
    """

    tree_name: str
    nodes_processed: int = 0
    types_histogram: dict[str, int] = Field(default_factory=dict)
    links_resolved: int = 0
    links_broken: int = 0
    slug_collisions: int = 0
    files_renamed: int = 0


def _cache_key(model_id: str, title: str, summary: str) -> str:
    """Compute content-addressed cache key for type classification.

    Args:
        model_id: LLM model identifier (e.g. ``"gpt-4o"``).
        title: Node title string.
        summary: Node summary string.

    Returns:
        Hexdigest of sha1(model_id + title + summary).
    """
    raw = f"{model_id}:{title}:{summary}"
    return hashlib.sha1(raw.encode()).hexdigest()


async def _classify_type(
    node: dict,
    adapter: Any,
    cache: dict[str, str],
    force_reclassify: bool = False,
) -> str:
    """Classify a node's type via LLM with content-addressed caching.

    Falls back to ``ConceptType.SECTION`` when:
    - ``adapter`` is ``None`` (no LLM configured).
    - The LLM call fails.
    - ``adapter`` has no usable classification capability.

    Args:
        node: PageIndex node dict with ``title`` and ``summary``.
        adapter: LLM adapter (any object with an async ``classify_type()``
            or ``completion()`` method), or ``None``.
        cache: In-memory cache dict (key → ConceptType.value string).
        force_reclassify: If ``True``, bypass cache even if key present.

    Returns:
        ``ConceptType.value`` string (e.g. ``"Control"``, ``"Section"``).
    """
    title = node.get("title", "")
    summary = node.get("summary", "")
    model_id = getattr(adapter, "model_id", "") if adapter else ""
    key = _cache_key(model_id, title, summary)

    if not force_reclassify and key in cache:
        return cache[key]

    if adapter is None:
        result = ConceptType.SECTION.value
        cache[key] = result
        return result

    try:
        # Try adapter.classify_type() if available (custom adapters)
        if hasattr(adapter, "classify_type"):
            raw = await adapter.classify_type(title=title, summary=summary)
        else:
            # Generic: send a classification prompt via adapter.completion()
            prompt = (
                f"Classify the following document section into exactly one type from "
                f"this list: {', '.join(t.value for t in ConceptType)}.\n\n"
                f"Title: {title}\nSummary: {summary}\n\nRespond with only the type name."
            )
            raw = await adapter.completion(prompt)
        # Validate and normalise
        for ct in ConceptType:
            if ct.value.lower() == raw.strip().lower():
                result = ct.value
                break
        else:
            logger.warning("LLM returned unknown type %r for %r; using Section", raw, title)
            result = ConceptType.SECTION.value
    except Exception as exc:
        logger.warning("Type classification failed for %r: %s; using Section", title, exc)
        result = ConceptType.SECTION.value

    cache[key] = result
    return result


def _build_source(node: dict, doc_name: str) -> SourceProvenance:
    """Build SourceProvenance from node page-span fields.

    Args:
        node: PageIndex node dict; may have ``start_index`` and ``end_index``.
        doc_name: Document filename from the tree's ``doc_name`` field.

    Returns:
        ``SourceProvenance`` instance.
    """
    pages: Optional[list[int]] = None
    si = node.get("start_index")
    ei = node.get("end_index")
    if si is not None and ei is not None:
        pages = [int(si), int(ei)]
    elif si is not None:
        pages = [int(si)]
    return SourceProvenance(document=doc_name or "unknown", pages=pages)


def _load_type_cache(content_store: NodeContentStore, tree_name: str) -> dict[str, str]:
    """Load the persisted type cache from a sidecar JSON file.

    Args:
        content_store: NodeContentStore for the tree.
        tree_name: Tree name.

    Returns:
        Cache dict (key → type value string), possibly empty.
    """
    raw = content_store.load(tree_name, _CACHE_FILENAME)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _save_type_cache(
    content_store: NodeContentStore,
    tree_name: str,
    cache: dict[str, str],
) -> None:
    """Persist the type cache to a sidecar JSON file.

    Args:
        content_store: NodeContentStore for the tree.
        tree_name: Tree name.
        cache: Cache dict to persist.
    """
    content_store.save(tree_name, _CACHE_FILENAME, json.dumps(cache, sort_keys=True))


async def okf_migrate(
    tree_name: str,
    tree_store: JSONTreeStore,
    content_store: NodeContentStore,
    adapter: Any,
    *,
    force_reclassify: bool = False,
) -> MigrationReport:
    """Retrofit an existing PageIndex tree with OKF fields.

    Steps:
    1. Load authoritative JSON.
    2. Assign concept_ids (idempotent, deterministic).
    3. For each node: classify type (cached), build source, parse links.
    4. Save enriched tree JSON.
    5. Project sidecars (rename to concept_id keys).
    6. Write root index.md.
    7. Return MigrationReport.

    Args:
        tree_name: Name of the PageIndex tree to migrate.
        tree_store: ``JSONTreeStore`` instance.
        content_store: ``NodeContentStore`` instance.
        adapter: LLM adapter for type classification, or ``None`` for fallback.
        force_reclassify: If ``True``, ignore existing type cache entries.

    Returns:
        ``MigrationReport`` with migration statistics.
    """
    report = MigrationReport(tree_name=tree_name)

    # 1. Load tree
    tree = tree_store.load(tree_name)
    doc_name = tree.get("doc_name", "")

    # 2. Assign concept_ids (idempotent)
    assign_concept_ids(tree)
    nodes_after = structure_to_list(tree.get("structure", []))
    post_ids = [n.get("concept_id", "") for n in nodes_after]
    # Count slug collisions: a node received a dedup suffix when its id
    # matches "<base>-<N>" AND the bare "<base>" also exists in the set.
    # This handles multi-digit suffixes (-10, -11, …) and avoids false
    # positives on naturally-numeric titles (e.g. "ir-4" only flagged
    # if a sibling "ir" also exists).
    _DEDUP_SUFFIX_RE = re.compile(r"^(.*)-(\d+)$")
    post_ids_set = set(post_ids)
    report.slug_collisions = sum(
        1
        for cid in post_ids
        if cid and (m := _DEDUP_SUFFIX_RE.match(cid)) and m.group(1) in post_ids_set
    )

    # 3. Load type cache
    cache = _load_type_cache(content_store, tree_name)

    # 4. Enrich each node
    nodes = structure_to_list(tree.get("structure", []))
    all_concept_ids: set[str] = {n.get("concept_id", "") for n in nodes if n.get("concept_id")}

    for node in nodes:
        # Type classification
        node_type = await _classify_type(node, adapter, cache, force_reclassify)
        node["type"] = node_type

        # Track type histogram
        report.types_histogram[node_type] = report.types_histogram.get(node_type, 0) + 1

        # Source provenance
        node["source"] = _build_source(node, doc_name).model_dump(exclude_none=True)

        # Parse body markdown links → relates_to candidates
        node_id = str(node.get("node_id", ""))
        concept_id = node.get("concept_id", "")
        flat_id = flatten_concept_id_for_filename(concept_id) if concept_id else node_id

        body = content_store.load(tree_name, flat_id) or ""
        if not body and node_id:
            body = content_store.load(tree_name, node_id) or ""

        links = parse_markdown_links(body) if body else []

        # Build relates_to: start with existing explicit edges, add prose links
        existing_relates = node.get("relates_to") or []
        existing_targets = {r["concept"] for r in existing_relates}

        new_edges = list(existing_relates)
        for link in links:
            if link in existing_targets:
                continue
            new_edges.append({"concept": link, "rel": "references"})
            if link in all_concept_ids:
                report.links_resolved += 1
            else:
                report.links_broken += 1
            existing_targets.add(link)

        node["relates_to"] = new_edges
        report.nodes_processed += 1

    # 5. Save type cache
    _save_type_cache(content_store, tree_name, cache)

    # 6. Save enriched tree
    tree_store.save(tree_name, tree)

    # 7. Project sidecars (rename node_id.md → concept_id.md)
    proj_report = project_sidecars(tree, tree_name, content_store)
    report.files_renamed = len(proj_report.old_files_removed)

    # 8. Write root index.md
    index_content = generate_index_md(tree, tree_name)
    content_store.save(tree_name, "index", index_content)

    return report
