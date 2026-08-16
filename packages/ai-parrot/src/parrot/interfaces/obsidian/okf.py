"""OKF (Open Knowledge Format) metadata inside Obsidian note frontmatter.

Design (Phase D of the Obsidian integration): Obsidian owns the top-level
frontmatter namespace (``tags``, ``aliases``, ``cssclasses``, user keys) —
those keys round-trip untouched. OKF owns exactly ONE top-level key,
``okf``, whose subtree mirrors :class:`ConceptFrontmatter` field order and
is always regenerated wholesale by the single sanctioned writer
(:func:`apply_okf`), reusing the serialization discipline of
``parrot.knowledge.okf.frontmatter`` (fixed field order, sorted tags,
``sort_keys=False``, optional ``source`` omitted when None).

Determinism scope: byte-determinism is guaranteed for the ``okf:`` subtree
given the same node dict — whole-file determinism is impossible because
the user owns the native keys around it. Hand-edits to the ``okf`` block
are invalid and are overwritten on the next projection;
:func:`validate_okf` surfaces such drift first.

``relates_to`` targets may be written Obsidian-style (``[[note]]``) —
they are resolved through the shared :class:`VaultIndex` and normalized
to stable note ids (vault-relative path without ``.md``, matching the
FEAT-392 node-ID convention).
"""
import re
from typing import Any, Optional

import frontmatter as fm
import yaml
from pydantic import ValidationError

from parrot.knowledge.okf.frontmatter import (
    ConceptFrontmatter,
    _to_yaml_dict,
)
from parrot.knowledge.okf.ontology import (
    ConceptType,
    RelatesTo,
    RelationType,
    SourceProvenance,
)

from .index import VaultIndex
from .models import ObsidianNote

#: The single top-level frontmatter key owned by OKF.
OKF_KEY = "okf"

_WIKILINK_TARGET = re.compile(r"^\[\[([^\[\]\|#]+)(?:#[^\[\]\|]*)?(?:\|[^\[\]]*)?\]\]$")


def _build_model(node: dict, tree_name: str) -> ConceptFrontmatter:
    """Build a ConceptFrontmatter from a node dict (same rules as the
    sanctioned ``project_frontmatter`` writer)."""
    return ConceptFrontmatter(
        type=ConceptType(node.get("type", ConceptType.SECTION.value)),
        title=node.get("title", ""),
        id=node["concept_id"],
        node_id=str(node.get("node_id", "")),
        resource=node.get(
            "resource", f"pageindex://{tree_name}/{node['concept_id']}"
        ),
        tags=sorted(node.get("categories", []) or node.get("tags", [])),
        timestamp=str(node.get("timestamp", "")),
        summary=node.get("summary", "") or "",
        relates_to=[RelatesTo(**r) for r in (node.get("relates_to") or [])],
        source=(
            SourceProvenance(**node["source"]) if node.get("source") else None
        ),
    )


def project_okf_block(node: dict, tree_name: str) -> str:
    """Deterministic YAML for the ``okf:`` subtree.

    Args:
        node: Node dict with at least ``concept_id`` and ``title``
            (same shape ``project_frontmatter`` accepts).
        tree_name: Tree/vault name used for the default resource URI.

    Returns:
        A YAML string of the form ``okf:\\n  type: ...`` — byte-identical
        for identical inputs (single-writer determinism guarantee, scoped
        to this subtree).
    """
    payload = {OKF_KEY: _to_yaml_dict(_build_model(node, tree_name))}
    return yaml.dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )


def read_okf(note: ObsidianNote) -> Optional[ConceptFrontmatter]:
    """Extract and validate a note's ``okf`` frontmatter block.

    Args:
        note: A parsed Obsidian note.

    Returns:
        The validated :class:`ConceptFrontmatter`, or ``None`` when the
        note carries no ``okf`` key.

    Raises:
        ValueError: If the ``okf`` block exists but is malformed.
    """
    block = note.frontmatter.get(OKF_KEY)
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ValueError(
            f"okf frontmatter in {note.path} must be a mapping, "
            f"got {type(block).__name__}"
        )
    try:
        return ConceptFrontmatter(
            type=ConceptType(block.get("type", ConceptType.SECTION.value)),
            title=block.get("title", note.title),
            id=str(block.get("id", "")),
            node_id=str(block.get("node_id", "")),
            resource=str(block.get("resource", "")),
            tags=list(block.get("tags") or []),
            timestamp=str(block.get("timestamp", "")),
            summary=block.get("summary", "") or "",
            relates_to=[
                RelatesTo(
                    concept=r["concept"], rel=r.get("rel", "references")
                )
                for r in (block.get("relates_to") or [])
                if isinstance(r, dict) and "concept" in r
            ],
            source=(
                SourceProvenance(**block["source"])
                if block.get("source")
                else None
            ),
        )
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Malformed okf frontmatter in {note.path}: {exc}") from exc


def apply_okf(
    raw_text: str,
    node: dict,
    tree_name: str,
    mirror_tags: bool = False,
) -> str:
    """Return the full new note text with the ``okf`` block (re)projected.

    Native frontmatter keys are preserved (values re-serialized, original
    key order kept); the ``okf`` mapping is regenerated wholesale and
    always emitted last; the markdown body is untouched.

    Args:
        raw_text: Current full note text (frontmatter included).
        node: OKF node dict (``concept_id``, ``title``, ``type``,
            ``summary``, ``tags``/``categories``, ``relates_to``, ...).
        tree_name: Tree/vault name for the default resource URI.
        mirror_tags: When True, OKF tags are additionally merged into the
            native ``tags:`` list as ``okf/<tag>`` so Obsidian tag search
            sees them.

    Returns:
        The complete new file text.
    """
    try:
        post = fm.loads(raw_text)
        native = dict(post.metadata)
        body = post.content
    except (yaml.YAMLError, ValueError):
        native = {}
        body = raw_text
    native.pop(OKF_KEY, None)

    model = _build_model(node, tree_name)
    if mirror_tags and model.tags:
        mirrored = [f"okf/{tag}" for tag in sorted(model.tags)]
        existing = native.get("tags")
        if isinstance(existing, str):
            existing = [part.strip() for part in existing.split(",") if part.strip()]
        elif not isinstance(existing, list):
            existing = []
        keep = [tag for tag in existing if not str(tag).startswith("okf/")]
        native["tags"] = keep + mirrored

    sections: list[str] = []
    if native:
        sections.append(
            yaml.dump(
                native,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        )
    sections.append(project_okf_block(node, tree_name))
    frontmatter_block = "".join(sections)
    return f"---\n{frontmatter_block}---\n{body if body.startswith(chr(10)) else chr(10) + body}"


def normalize_relates_target(
    target: str, index: Optional[VaultIndex] = None
) -> Optional[str]:
    """Normalize a relates_to target, resolving ``[[wikilink]]`` syntax.

    Args:
        target: A concept id, note path, or ``[[wikilink]]`` string.
        index: Optional vault index for wikilink/path resolution.

    Returns:
        The stable note id (vault-relative path, no ``.md``) when the
        target resolves; the verbatim target when no index is given; or
        ``None`` when an index is given and the target does not resolve.
    """
    match = _WIKILINK_TARGET.match(target.strip())
    raw = match.group(1).strip() if match else target.strip()
    if index is None:
        return raw
    return index.resolve(raw)


def validate_okf(
    note: ObsidianNote, index: Optional[VaultIndex] = None
) -> list[str]:
    """Lint a note's ``okf`` frontmatter block.

    Args:
        note: Parsed Obsidian note.
        index: Optional vault index — when given, ``relates_to`` targets
            are checked for resolvability.

    Returns:
        Human-readable findings; empty when the block is absent or valid.
    """
    findings: list[str] = []
    block = note.frontmatter.get(OKF_KEY)
    if block is None:
        return findings
    if not isinstance(block, dict):
        return [f"{note.path}: okf block is not a mapping"]

    raw_type = block.get("type")
    if raw_type is not None:
        try:
            ConceptType(raw_type)
        except ValueError:
            findings.append(
                f"{note.path}: unknown okf type {raw_type!r} "
                f"(open vocabulary maps to 'Other' on import)"
            )
    if not block.get("id"):
        findings.append(f"{note.path}: okf block is missing 'id'")
    if not block.get("summary"):
        findings.append(f"{note.path}: okf block is missing 'summary'")

    for row in block.get("relates_to") or []:
        if not isinstance(row, dict) or "concept" not in row:
            findings.append(
                f"{note.path}: relates_to entry {row!r} needs a 'concept'"
            )
            continue
        rel = row.get("rel", "references")
        try:
            RelationType(rel)
        except ValueError:
            findings.append(
                f"{note.path}: unknown relates_to rel {rel!r}"
            )
        if index is not None:
            resolved = normalize_relates_target(str(row["concept"]), index)
            if resolved is None:
                findings.append(
                    f"{note.path}: relates_to target {row['concept']!r} "
                    f"does not resolve to any note"
                )
    return findings


__all__ = [
    "OKF_KEY",
    "apply_okf",
    "normalize_relates_target",
    "project_okf_block",
    "read_okf",
    "validate_okf",
]
