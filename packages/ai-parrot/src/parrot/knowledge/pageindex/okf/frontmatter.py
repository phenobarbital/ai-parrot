"""Frontmatter model and deterministic YAML projection for OKF sidecars.

The frontmatter is the deterministic mirror of the authoritative JSON node
onto each sidecar ``.md`` file.  The projection is:

- **Pure function**: same JSON node → same YAML bytes every time.
- **Single-writer**: only ``project_frontmatter`` writes frontmatter; no
  hand-edits to sidecar frontmatter are valid (they will be overwritten).
- **Byte-deterministic**: field order is fixed, values are verbatim from JSON.

Design notes (from spec §2.2, D1, D11):
- ``summary`` reuses the FEAT-199 embedding target text — one source, zero divergence.
- ``tags`` are sorted alphabetically for determinism.
- Optional fields (``source``, ``url``) are omitted when ``None``.
- Frontmatter delimiters are ``---\\n`` (start) and ``---\\n`` (end).
"""

from typing import Optional

import yaml
from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelatesTo,
    SourceProvenance,
)


class ConceptFrontmatter(BaseModel):
    """Pydantic v2 model for the deterministic frontmatter projection.

    Field order here determines YAML output order (dict insertion order,
    Python 3.7+, preserved by ``model_dump()``).

    Attributes:
        type: Ontological type (controlled vocabulary).
        title: Human-readable concept title.
        id: Stable concept_id (link target, filename stem).
        node_id: Structural position in the tree (volatile, for debugging only).
        resource: Canonical URI ``pageindex://<tree>/<concept_id>``.
        tags: Alphabetically sorted free-namespace tags.
        timestamp: ISO-8601 timestamp string from the node.
        summary: Embedding target text (reuses FEAT-199 value, D11).
        relates_to: Typed edge list.
        source: Optional per-node provenance.
    """

    type: ConceptType
    title: str
    id: str = Field(..., description="concept_id — stable link target")
    node_id: str = Field(..., description="Mirrored for debugging; NOT a link target")
    resource: str = Field(..., description="pageindex://<tree>/<concept_id>")
    tags: list[str] = Field(default_factory=list)
    timestamp: str = Field(default="")
    summary: str = Field(..., description="Reuses FEAT-199 embedding target text (D11)")
    relates_to: list[RelatesTo] = Field(default_factory=list)
    source: Optional[SourceProvenance] = None


def _to_yaml_dict(fm: ConceptFrontmatter) -> dict:
    """Convert a ConceptFrontmatter into a plain dict for YAML serialisation.

    Preserves field order.  Optional ``source`` field is omitted when ``None``
    (not serialised as ``source: null``).

    Args:
        fm: Populated ConceptFrontmatter instance.

    Returns:
        Ordered dict ready for ``yaml.dump``.
    """
    d: dict = {
        "type": fm.type.value,
        "title": fm.title,
        "id": fm.id,
        "node_id": fm.node_id,
        "resource": fm.resource,
        "tags": sorted(fm.tags),  # alphabetical for determinism
        "timestamp": fm.timestamp,
        "summary": fm.summary,
        "relates_to": [
            {"concept": r.concept, "rel": r.rel.value} for r in fm.relates_to
        ],
    }
    if fm.source is not None:
        src: dict = {"document": fm.source.document}
        if fm.source.pages is not None:
            src["pages"] = fm.source.pages
        if fm.source.url is not None:
            src["url"] = fm.source.url
        d["source"] = src
    return d


def project_frontmatter(node: dict, tree_name: str) -> str:
    """Produce a byte-deterministic YAML frontmatter string from a node dict.

    The output starts with ``---\\n`` and ends with ``---\\n``.  Given the same
    ``node`` dict and ``tree_name``, this function MUST return byte-identical
    output every time it is called (idempotency / determinism guarantee).

    Fields extracted from ``node``:
    - ``type`` (or ``"Section"`` as fallback)
    - ``title``
    - ``concept_id``
    - ``node_id``
    - ``summary`` (or empty string)
    - ``categories`` → ``tags`` (sorted)
    - ``timestamp`` (or empty string)
    - ``relates_to`` list
    - ``source`` dict (optional)

    Args:
        node: PageIndex node dict (must have ``concept_id``, ``title``,
            ``node_id``).
        tree_name: Name of the PageIndex tree, used to build the resource URI.

    Returns:
        YAML frontmatter string delimited by ``---\\n``.
    """
    fm = ConceptFrontmatter(
        type=ConceptType(node.get("type", ConceptType.SECTION.value)),
        title=node.get("title", ""),
        id=node["concept_id"],
        node_id=str(node.get("node_id", "")),
        resource=f"pageindex://{tree_name}/{node['concept_id']}",
        tags=sorted(node.get("categories", []) or node.get("tags", [])),
        timestamp=str(node.get("timestamp", "")),
        summary=node.get("summary", "") or "",
        relates_to=[
            RelatesTo(**r) for r in (node.get("relates_to") or [])
        ],
        source=(
            SourceProvenance(**node["source"])
            if node.get("source")
            else None
        ),
    )
    yaml_body = yaml.dump(
        _to_yaml_dict(fm),
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{yaml_body}---\n"


def parse_frontmatter(text: str) -> ConceptFrontmatter:
    """Parse YAML frontmatter from a sidecar string back into a model.

    The ``text`` must begin with ``---\\n`` and contain a closing ``---``.

    Args:
        text: Sidecar file content starting with YAML frontmatter.

    Returns:
        Parsed ``ConceptFrontmatter`` instance.

    Raises:
        ValueError: If the frontmatter block cannot be found or parsed.
    """
    if not text.startswith("---"):
        raise ValueError("Text does not start with YAML frontmatter delimiter '---'")

    # Find closing delimiter
    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("No closing '---' found in frontmatter")

    yaml_block = "\n".join(lines[1:end_idx])
    data = yaml.safe_load(yaml_block)
    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter YAML did not parse to a dict: {data!r}")

    # Reconstruct model
    relates_to = [
        RelatesTo(concept=r["concept"], rel=r.get("rel", "references"))
        for r in (data.get("relates_to") or [])
    ]
    source = None
    if data.get("source"):
        source = SourceProvenance(**data["source"])

    return ConceptFrontmatter(
        type=ConceptType(data["type"]),
        title=data.get("title", ""),
        id=data["id"],
        node_id=str(data.get("node_id", "")),
        resource=data.get("resource", ""),
        tags=data.get("tags") or [],
        timestamp=str(data.get("timestamp", "")),
        summary=data.get("summary", "") or "",
        relates_to=relates_to,
        source=source,
    )
