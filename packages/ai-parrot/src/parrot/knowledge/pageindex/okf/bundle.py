"""OKF v0.1 bundle import/export for PageIndex.

Provides two public functions:

- :func:`export_okf_bundle` — Writes a PageIndex tree as an OKF v0.1 compliant
  directory bundle.  Files are grouped by concept type (``policies/``,
  ``controls/``, etc.), ``pageindex://`` URIs are rewritten to relative
  markdown paths, and AI-Parrot-specific fields (``node_id``, ``resource``)
  are stripped from frontmatter.

- :func:`import_okf_bundle` — Reads an OKF bundle directory into a new
  PageIndex tree.  YAML frontmatter is parsed from each ``.md`` file; unknown
  ``type`` values are mapped to :data:`ConceptType.OTHER`.  Markdown
  hyperlinks in bodies are resolved to ``relates_to`` edges.

Round-trip guarantee: export → import preserves ``concept_id``, ``type``,
``relates_to``, and body content.

Design notes (spec §2, §3 Modules 3 & 4):
- Export follows the ``project_sidecars()`` iteration pattern.
- Import uses two passes: first to collect concept_ids, second to resolve links.
- ``index.md`` files are generated on export and skipped on import.
- URI rewriting handles only ``pageindex://`` scheme URIs; absolute URLs and
  anchor-only links are left unchanged.
"""

import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id
from parrot.knowledge.pageindex.okf.graph import parse_markdown_links
from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
)
from parrot.knowledge.pageindex.okf.projection import (
    flatten_concept_id_for_filename,
    generate_index_md,
)
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list

logger = logging.getLogger(__name__)

# Pattern for pageindex:// URIs — captures tree name and concept_id
_PAGEINDEX_URI_RE = re.compile(
    r"pageindex://([^/\s\"'()]+)/([^\s\"'()]+)"
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ExportReport(BaseModel):
    """Result of an OKF bundle export operation.

    Attributes:
        tree_name: Name of the exported PageIndex tree.
        output_dir: Absolute path of the bundle directory.
        files_written: Number of ``.md`` files written (excludes ``index.md``).
        index_generated: Whether a root ``index.md`` was generated.
        uris_rewritten: Total number of ``pageindex://`` URIs rewritten.
    """

    tree_name: str
    output_dir: str
    files_written: int = 0
    index_generated: bool = False
    uris_rewritten: int = 0


class ImportReport(BaseModel):
    """Result of an OKF bundle import operation.

    Attributes:
        tree_name: Name of the newly created PageIndex tree.
        input_dir: Absolute path of the source bundle directory.
        nodes_created: Number of PageIndex nodes created.
        edges_created: Number of ``relates_to`` edges created.
        types_mapped: Mapping of raw ``type`` string → ``ConceptType.value``.
        unknown_types: List of raw ``type`` strings that were unmapped (→ OTHER).
    """

    tree_name: str
    input_dir: str
    nodes_created: int = 0
    edges_created: int = 0
    types_mapped: dict[str, str] = Field(default_factory=dict)
    unknown_types: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _type_to_dir(concept_type_value: str) -> str:
    """Map a ConceptType string value to an OKF bundle subdirectory name.

    Args:
        concept_type_value: e.g. ``"Policy"``, ``"Control"``, ``"Other"``.

    Returns:
        Lowercase plural, e.g. ``"policies"``, ``"controls"``, ``"others"``.
    """
    lowered = concept_type_value.lower()
    # Simple English pluralisation: words ending in -y → -ies, else append -s.
    if lowered.endswith("y"):
        return lowered[:-1] + "ies"
    return lowered + "s"


def _build_export_path(concept_id: str, concept_type_value: str) -> PurePosixPath:
    """Compute the bundle-relative file path for a concept.

    Args:
        concept_id: Concept identifier (may contain ``/``).
        concept_type_value: ConceptType string value.

    Returns:
        PurePosixPath like ``policies/access-control-policy.md``.
    """
    type_dir = _type_to_dir(concept_type_value)
    flat_stem = flatten_concept_id_for_filename(concept_id)
    return PurePosixPath(type_dir) / f"{flat_stem}.md"


def _rewrite_pageindex_uris(
    text: str,
    src_rel_path: PurePosixPath,
    concept_file_map: dict[str, PurePosixPath],
) -> tuple[str, int]:
    """Replace ``pageindex://`` URIs in text with relative markdown paths.

    Only URIs whose ``concept_id`` part exists in ``concept_file_map`` are
    rewritten; unknown URIs are left unchanged.  Absolute URLs, anchor-only
    links, and non-``pageindex`` URIs are not touched.

    Args:
        text: Source text (body content or frontmatter).
        src_rel_path: Bundle-relative path of the file being exported (used
            to compute relative paths).
        concept_file_map: Mapping of concept_id → bundle-relative file path.

    Returns:
        Tuple of (rewritten_text, count_of_replacements).
    """
    count = 0

    def _replace(m: re.Match) -> str:
        nonlocal count
        target_cid = m.group(2)
        if target_cid not in concept_file_map:
            return m.group(0)  # leave unchanged
        target_path = concept_file_map[target_cid]
        # Compute relative path from src_rel_path's parent to target_path
        rel = os.path.relpath(str(target_path), str(src_rel_path.parent))
        # os.path.relpath may use OS separator — normalise to forward slash
        rel = rel.replace(os.sep, "/")
        count += 1
        return rel

    rewritten = _PAGEINDEX_URI_RE.sub(_replace, text)
    return rewritten, count


def _export_frontmatter(node: dict, tree_name: str) -> str:
    """Produce OKF v0.1 compliant YAML frontmatter (strips node_id, resource).

    Only includes OKF-standard fields: ``type``, ``title``, ``id``, ``tags``,
    ``timestamp``, ``summary``, ``relates_to``, and optionally ``source``.

    Args:
        node: OKF-enriched PageIndex node dict.
        tree_name: Tree name (unused here — included for future extension).

    Returns:
        YAML frontmatter string delimited by ``---\\n``.
    """
    d: dict = {
        "type": node.get("type", ConceptType.SECTION.value),
        "title": node.get("title", ""),
        "id": node.get("concept_id", ""),
        "tags": sorted(node.get("categories", []) or node.get("tags", [])),
        "timestamp": str(node.get("timestamp", "")),
        "summary": node.get("summary", "") or "",
        "relates_to": [
            {"concept": r.get("concept", ""), "rel": r.get("rel", "references")}
            for r in (node.get("relates_to") or [])
        ],
    }
    if node.get("source"):
        src = node["source"]
        src_d: dict = {"document": src.get("document", "")}
        if src.get("pages") is not None:
            src_d["pages"] = src["pages"]
        if src.get("url") is not None:
            src_d["url"] = src["url"]
        d["source"] = src_d

    yaml_body = yaml.dump(
        d,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{yaml_body}---\n"


def _strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter block from content.

    Args:
        content: File content that may start with ``---``.

    Returns:
        Body text without the frontmatter header.
    """
    content = content.replace("\r\n", "\n")
    if not content.startswith("---\n"):
        return content
    second = content.find("\n---\n", 4)
    if second == -1:
        if content.endswith("\n---"):
            return content[len(content) - 4 + 4:]
        return content
    return content[second + 5:].lstrip("\n")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_okf_bundle(
    tree: dict,
    tree_name: str,
    content_store: NodeContentStore,
    output_dir: Path,
) -> ExportReport:
    """Export a PageIndex tree as an OKF v0.1 compliant directory bundle.

    Creates a directory hierarchy grouped by concept ``type``:
    ``policies/``, ``controls/``, ``sections/``, etc.  Each ``.md`` file
    contains OKF-standard YAML frontmatter (no ``node_id``, no
    ``pageindex://`` URIs) followed by the body content.

    A root ``index.md`` is generated via
    :func:`~parrot.knowledge.pageindex.okf.projection.generate_index_md`.

    Args:
        tree: OKF-enriched PageIndex tree dict.
        tree_name: Name of the tree (used in URI rewriting and index title).
        content_store: :class:`~parrot.knowledge.pageindex.content_store.NodeContentStore`
            for loading sidecar bodies.
        output_dir: Destination directory.  Created if absent.

    Returns:
        :class:`ExportReport` with counts of files written and URIs rewritten.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes = structure_to_list(tree.get("structure", []))
    report = ExportReport(tree_name=tree_name, output_dir=str(output_dir.resolve()))

    # Build concept_id → bundle-relative path map (needed for URI rewriting)
    concept_file_map: dict[str, PurePosixPath] = {}
    for node in nodes:
        cid = node.get("concept_id", "")
        concept_type_val = node.get("type", ConceptType.SECTION.value)
        if cid:
            concept_file_map[cid] = _build_export_path(cid, concept_type_val)

    total_uris = 0

    for node in nodes:
        cid = node.get("concept_id", "")
        if not cid:
            continue

        concept_type_val = node.get("type", ConceptType.SECTION.value)
        rel_path = _build_export_path(cid, concept_type_val)
        abs_path = output_dir / rel_path

        # Ensure type subdirectory exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Load sidecar body
        flat_key = flatten_concept_id_for_filename(cid)
        raw_body = content_store.load(tree_name, flat_key) or ""
        body = _strip_frontmatter(raw_body)

        # Rewrite pageindex:// URIs in body
        body, uri_count = _rewrite_pageindex_uris(body, rel_path, concept_file_map)
        total_uris += uri_count

        # Build OKF frontmatter (without node_id / resource)
        frontmatter = _export_frontmatter(node, tree_name)

        # Write the file
        abs_path.write_text(f"{frontmatter}\n{body}", encoding="utf-8")
        report.files_written += 1

    # Generate root index.md
    index_content = generate_index_md(tree, tree_name)
    (output_dir / "index.md").write_text(index_content, encoding="utf-8")
    report.index_generated = True

    report.uris_rewritten = total_uris
    logger.info(
        "Exported %d nodes to '%s' (URIs rewritten: %d)",
        report.files_written,
        output_dir,
        total_uris,
    )
    return report


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _map_concept_type(raw_type: str) -> tuple[ConceptType, bool]:
    """Map a raw type string to a ConceptType enum value.

    Args:
        raw_type: Raw ``type`` field value from OKF frontmatter.

    Returns:
        Tuple of (ConceptType, was_unknown) where ``was_unknown`` is True if
        the type was not in the enum and fell back to ``ConceptType.OTHER``.
    """
    try:
        return ConceptType(raw_type), False
    except ValueError:
        return ConceptType.OTHER, True


def _parse_yaml_frontmatter(content: str) -> Optional[dict]:
    """Parse YAML frontmatter from an OKF markdown file.

    Tolerates files without frontmatter (returns None).

    Args:
        content: File content (may start with ``---``).

    Returns:
        Parsed dict, or ``None`` if no valid frontmatter found.
    """
    content = content.replace("\r\n", "\n")
    if not content.startswith("---"):
        return None
    lines = content.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    yaml_block = "\n".join(lines[1:end_idx])
    try:
        data = yaml.safe_load(yaml_block)
        return data if isinstance(data, dict) else None
    except yaml.YAMLError as exc:
        logger.debug("YAML parse error in frontmatter: %s", exc)
        return None


def import_okf_bundle(
    input_dir: Path,
    tree_name: str,
    store: JSONTreeStore,
    content_store: NodeContentStore,
) -> ImportReport:
    """Import an OKF bundle directory into a new PageIndex tree.

    Reads all ``.md`` files in ``input_dir`` recursively (skipping
    ``index.md``).  For each file:

    1. Parses YAML frontmatter; unknown ``type`` values map to
       :data:`ConceptType.OTHER`.
    2. Creates a PageIndex node with the frontmatter data.
    3. Parses markdown links from the body and maps them to ``relates_to``
       edges using a ``stem → concept_id`` map built in a first pass.

    The resulting tree is saved via ``store`` and bodies via
    ``content_store``.

    Args:
        input_dir: Source OKF bundle directory.
        tree_name: Name to assign to the new PageIndex tree.
        store: :class:`~parrot.knowledge.pageindex.store.JSONTreeStore` for
            persisting the new tree.
        content_store: :class:`~parrot.knowledge.pageindex.content_store.NodeContentStore`
            for storing sidecar bodies.

    Returns:
        :class:`ImportReport` with counts of nodes and edges created.
    """
    input_dir = Path(input_dir)
    report = ImportReport(tree_name=tree_name, input_dir=str(input_dir.resolve()))

    # Collect all .md files (skip index.md)
    md_files: list[Path] = sorted(
        p for p in input_dir.rglob("*.md")
        if p.name.lower() != "index.md"
    )

    # -----------------------------------------------------------------------
    # Pass 1: collect stem → concept_id mapping
    # -----------------------------------------------------------------------
    stem_to_cid: dict[str, str] = {}
    file_data: list[tuple[Path, dict, str]] = []  # (path, fm_data, body)

    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        fm_data = _parse_yaml_frontmatter(content)
        if fm_data is None:
            fm_data = {}
        body = _strip_frontmatter(content)
        file_data.append((md_path, fm_data, body))

        # Register stem → concept_id  (concept_id may have slashes)
        concept_id = str(fm_data.get("id", "")).strip()
        if not concept_id:
            # Fall back to deriving from title
            title = str(fm_data.get("title", md_path.stem)).strip()
            concept_id = derive_concept_id(title)
        # Also register the file stem (flat key) for link resolution
        stem_to_cid[md_path.stem] = concept_id

    # -----------------------------------------------------------------------
    # Pass 2: build PageIndex nodes
    # -----------------------------------------------------------------------
    nodes: list[dict] = []

    for idx, (md_path, fm_data, body) in enumerate(file_data):
        # concept_id
        cid = str(fm_data.get("id", "")).strip()
        if not cid:
            title_raw = str(fm_data.get("title", md_path.stem)).strip()
            cid = derive_concept_id(title_raw)

        # type mapping
        raw_type = str(fm_data.get("type", "")).strip()
        mapped_type, was_unknown = _map_concept_type(raw_type)
        if raw_type:
            report.types_mapped[raw_type] = mapped_type.value
        if was_unknown and raw_type and raw_type not in report.unknown_types:
            report.unknown_types.append(raw_type)

        # node_id: sequential, zero-padded
        node_id = f"{idx + 1:04d}"

        # tags
        tags_raw = fm_data.get("tags", [])
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        # relates_to: from frontmatter YAML (first) + markdown links in body
        fm_relates: list[dict] = []
        for r in (fm_data.get("relates_to") or []):
            if isinstance(r, dict) and r.get("concept"):
                fm_relates.append({
                    "concept": str(r["concept"]),
                    "rel": str(r.get("rel", RelationType.REFERENCES.value)),
                })

        # Resolve markdown links from body → additional edges
        link_relates: list[dict] = []
        if body:
            links = parse_markdown_links(body)
            existing_targets = {r["concept"] for r in fm_relates}
            for link in links:
                # Try to resolve to a concept_id via stem map
                link_path = PurePosixPath(link)
                # Remove .md extension if present
                stem = link_path.stem if link_path.suffix.lower() == ".md" else link_path.name
                target_cid = stem_to_cid.get(stem)
                if target_cid and target_cid not in existing_targets:
                    link_relates.append({
                        "concept": target_cid,
                        "rel": RelationType.REFERENCES.value,
                    })
                    existing_targets.add(target_cid)

        all_relates = fm_relates + link_relates
        edges_for_node = len(all_relates)
        report.edges_created += edges_for_node

        node = {
            "node_id": node_id,
            "concept_id": cid,
            "type": mapped_type.value,
            "title": str(fm_data.get("title", cid)),
            "summary": str(fm_data.get("summary", "") or ""),
            "tags": tags,
            "timestamp": str(fm_data.get("timestamp", "") or ""),
            "relates_to": all_relates,
            "nodes": [],
        }
        if fm_data.get("source"):
            node["source"] = fm_data["source"]

        nodes.append(node)

        # Save sidecar body
        flat_key = flatten_concept_id_for_filename(cid)
        content_store.save(tree_name, flat_key, body)

    # -----------------------------------------------------------------------
    # Build and save tree
    # -----------------------------------------------------------------------
    tree: dict = {
        "tree_name": tree_name,
        "structure": nodes,
    }
    store.save(tree_name, tree)
    report.nodes_created = len(nodes)

    logger.info(
        "Imported %d nodes into tree '%s' (%d edges)",
        report.nodes_created,
        tree_name,
        report.edges_created,
    )
    return report
