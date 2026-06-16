"""Deterministic sidecar and index.md generation for OKF.

This module is the "single writer" that projects the authoritative JSON tree
onto disk.  It:

- Generates frontmatter-enriched sidecars (``<flattened_concept_id>.md``) for
  every node in the tree.
- Writes a root-level ``index.md`` listing of the JSON ToC.

Both outputs are **pure functions of the JSON** — regenerating from the same
tree MUST produce byte-identical files.  Single-writer; no hand-edits survive.

Design notes (from spec §2.2, D1, D8):
- Sidecar filenames are ``<flattened_concept_id>.md``.
  Slashes in concept_id are encoded as ``--`` (double-dash) for filesystem
  compatibility, because ``_NODE_ID_RE`` only allows ``[A-Za-z0-9_-]{1,64}``.
- Body content is preserved verbatim; only the frontmatter header is
  prepended/replaced.
- Old ``<node_id>.md`` sidecars are cleaned up when a concept_id sidecar is
  written.
"""

from typing import Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.okf.frontmatter import project_frontmatter
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename  # noqa: F401 — re-exported for backward compat
from parrot.knowledge.pageindex.utils import structure_to_list


class ProjectionReport(BaseModel):
    """Report returned by project_sidecars().

    Attributes:
        tree_name: Name of the tree that was projected.
        nodes_projected: Number of nodes written.
        files_written: Concept_id-keyed filenames written.
        old_files_removed: Legacy node_id-keyed filenames removed.
    """

    tree_name: str
    nodes_projected: int = 0
    files_written: list[str] = Field(default_factory=list)
    old_files_removed: list[str] = Field(default_factory=list)



def project_sidecar(node: dict, tree_name: str, body: str) -> str:
    """Combine projected frontmatter and existing body into a sidecar string.

    Args:
        node: OKF-enriched PageIndex node dict (must have ``concept_id``).
        tree_name: PageIndex tree name (used in resource URI).
        body: Existing sidecar body content (preserved verbatim).

    Returns:
        Complete sidecar string: frontmatter + blank line + body.
    """
    frontmatter = project_frontmatter(node, tree_name)
    return f"{frontmatter}\n{body}"


def _strip_frontmatter(content: str) -> str:
    """Strip existing YAML frontmatter from sidecar content.

    If ``content`` starts with ``---`` (LF or CRLF), extract and discard
    everything up to and including the closing ``---``.  Return the remaining
    body.

    CRLF line-endings are normalised to LF before processing so the same
    logic handles Windows-authored sidecars without special cases.

    Args:
        content: Sidecar file content (may or may not have frontmatter).

    Returns:
        Body content with frontmatter stripped, or content unchanged.
    """
    # Normalise CRLF → LF so the rest of the function only needs to handle LF.
    content = content.replace("\r\n", "\n")
    if not content.startswith("---\n"):
        return content
    # Find the closing "---" on its own line (must be followed by \n or EOF).
    # Using "\n---\n" avoids matching "---more-text" as a closing delimiter.
    second_start = content.find("\n---\n", 4)
    if second_start == -1:
        # Tolerate "---" at the very end of the string (no trailing newline)
        if content.endswith("\n---"):
            second_start = len(content) - 4
            return content[second_start + 4:]
        return content
    return content[second_start + 5:].lstrip("\n")


def project_sidecars(
    tree: dict,
    tree_name: str,
    content_store: NodeContentStore,
) -> ProjectionReport:
    """Regenerate all sidecars from the authoritative JSON tree.

    For each node in the tree:
    1. Derive the flat concept_id filename.
    2. Load the existing body (try concept_id key first, then node_id).
    3. Combine frontmatter + body and write via ``content_store.save()``.
    4. Remove the old ``<node_id>.md`` file if a different key was used.

    This function is byte-deterministic: two runs on the same tree JSON
    produce identical file contents.

    Args:
        tree: OKF-enriched PageIndex tree dict (all nodes must have
            ``concept_id``).
        tree_name: PageIndex tree name.
        content_store: NodeContentStore instance for reading/writing sidecars.

    Returns:
        ``ProjectionReport`` with counts and filenames of written/removed files.
    """
    report = ProjectionReport(tree_name=tree_name)
    nodes = structure_to_list(tree.get("structure", []))

    for node in nodes:
        concept_id = node.get("concept_id")
        node_id = str(node.get("node_id", ""))
        if not concept_id:
            continue

        flat_id = flatten_concept_id_for_filename(concept_id)

        # Load existing body — try flat concept_id first, then node_id
        existing = content_store.load(tree_name, flat_id)
        old_key: Optional[str] = None
        if existing is None and node_id:
            existing = content_store.load(tree_name, node_id)
            if existing is not None:
                old_key = node_id

        body = _strip_frontmatter(existing or "")

        # Write sidecar with frontmatter
        sidecar_content = project_sidecar(node, tree_name, body)
        content_store.save(tree_name, flat_id, sidecar_content)
        report.files_written.append(flat_id)
        report.nodes_projected += 1

        # Clean up old node_id.md if a different file was used
        if old_key and old_key != flat_id:
            removed = content_store.delete_node(tree_name, old_key)
            if removed:
                report.old_files_removed.append(old_key)

    return report


def generate_index_md(tree: dict, tree_name: str) -> str:
    """Generate a deterministic root-level index.md view of the JSON ToC.

    Lists **top-level concepts only** — children are intentionally omitted to
    keep the index concise (per OKF spec §6: "root index lists all top-level
    concepts with links").  Deeply nested sub-concepts are discoverable via
    their parent's sidecar body or ``get_related`` traversal.

    No YAML frontmatter in ``index.md`` (per OKF §6).  Entries are ordered
    by their position in the ``structure`` list (preserving JSON ToC order).

    Args:
        tree: OKF-enriched PageIndex tree dict.
        tree_name: PageIndex tree name (used in links).

    Returns:
        Deterministic Markdown string for the ``index.md`` file.
    """
    lines: list[str] = [
        f"# {tree_name}",
        "",
        "<!-- Auto-generated index. Do not edit. -->",
        "",
    ]
    top_level = tree.get("structure", [])
    for node in top_level:
        cid = node.get("concept_id", "")
        title = node.get("title", "")
        summary = node.get("summary", "")
        flat = flatten_concept_id_for_filename(cid) if cid else ""
        if flat:
            lines.append(f"## [{title}]({flat}.md)")
        else:
            lines.append(f"## {title}")
        if summary:
            lines.append("")
            lines.append(summary)
        lines.append("")

    return "\n".join(lines)
