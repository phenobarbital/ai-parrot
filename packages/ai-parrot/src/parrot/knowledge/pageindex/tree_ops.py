"""Mutation helpers for PageIndex trees.

A tree is a dict ``{doc_name, structure: [node, ...]}`` where each
``node`` is a dict with optional ``nodes`` (children). These helpers
splice subtrees into existing trees, delete nodes by id, and renumber
``node_id`` across the whole tree so ids remain contiguous after any
mutation.

OKF Integration (FEAT-238):
    ``splice_subtree`` automatically assigns ``concept_id`` values to new
    nodes that arrive without one.  ``reindex_node_ids`` intentionally
    leaves ``concept_id`` untouched — it is a *stable* identity anchor and
    must never be overwritten by a ``node_id`` renumber pass.
"""
from __future__ import annotations

from typing import Any, Optional

from .utils import find_node_by_id, write_node_id


def reindex_node_ids(tree: dict[str, Any]) -> None:
    """Reassign sequential 4-digit ``node_id`` values across the tree.

    Only ``node_id`` is modified.  OKF fields (``concept_id``, ``type``,
    ``source``, ``relates_to``) are never touched — ``concept_id`` in
    particular is a stable identity anchor that must survive renumbering.
    """
    structure = tree.get("structure")
    if structure is None:
        return
    write_node_id(structure)


def make_folder_node(name: str) -> dict[str, Any]:
    """Build a synthetic inner node representing a directory."""
    return {"title": name, "summary": "", "nodes": []}


def _coerce_subtree(subtree: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise a subtree value to a list of root nodes to splice."""
    if isinstance(subtree, dict):
        if "structure" in subtree:
            structure = subtree.get("structure") or []
            if isinstance(structure, list):
                return list(structure)
            if isinstance(structure, dict):
                return [structure]
            return []
        return [subtree]
    if isinstance(subtree, list):
        return list(subtree)
    raise TypeError(f"Unsupported subtree type: {type(subtree).__name__}")


def _assign_okf_concept_ids(target: dict[str, Any]) -> None:
    """Assign ``concept_id`` to any nodes that are missing it.

    Walks the full target tree depth-first.  Nodes that already carry a
    ``concept_id`` are skipped — their value is preserved.  Nodes without
    one receive a deterministic slug derived from their ``title`` and
    parent path, using the OKF ``derive_concept_id`` helper.

    If the OKF subpackage is not installed or importable this is a no-op
    (backward compatibility for environments without the OKF extras).

    Args:
        target: PageIndex tree dict with a ``structure`` list.
            Modified in place.
    """
    try:
        from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id
    except ImportError:
        return

    def _walk(nodes: list[dict[str, Any]], parent_path: str) -> None:
        for node in nodes:
            if not node.get("concept_id"):
                title = node.get("title", "")
                node["concept_id"] = derive_concept_id(title, parent_path)
            children = node.get("nodes") or []
            if children:
                _walk(children, node["concept_id"])

    structure = target.get("structure") or []
    _walk(structure, "")


def splice_subtree(
    target: dict[str, Any],
    subtree: dict[str, Any] | list[dict[str, Any]],
    parent_node_id: Optional[str] = None,
) -> list[str]:
    """Insert ``subtree`` under ``parent_node_id`` (or at root if None).

    Returns the new ``node_id`` of each freshly spliced root node, taken
    after the tree-wide reindex.

    After splicing and reindexing, ``assign_concept_ids`` is called on
    the whole target tree so that any new nodes arriving without a
    ``concept_id`` receive one.  Existing ``concept_id`` values on all
    nodes (pre-existing and newly spliced) are preserved.
    """
    new_roots = _coerce_subtree(subtree)
    if not new_roots:
        return []

    target.setdefault("structure", [])
    structure = target["structure"]

    if parent_node_id is None:
        if not isinstance(structure, list):
            raise TypeError("target['structure'] must be a list at the root")
        structure.extend(new_roots)
    else:
        parent = find_node_by_id(structure, parent_node_id)
        if parent is None:
            raise KeyError(f"parent_node_id {parent_node_id!r} not found")
        children = parent.setdefault("nodes", [])
        if not isinstance(children, list):
            raise TypeError(
                f"parent node {parent_node_id} has non-list 'nodes' field"
            )
        children.extend(new_roots)

    reindex_node_ids(target)
    _assign_okf_concept_ids(target)
    return [node.get("node_id") for node in new_roots if node.get("node_id")]


def delete_node(tree: dict[str, Any], node_id: str) -> bool:
    """Remove the node with ``node_id`` and all its descendants.

    Returns ``True`` if a node was removed, ``False`` if not found.
    """
    structure = tree.get("structure")
    if structure is None:
        return False

    if _remove_from_list(structure, node_id):
        reindex_node_ids(tree)
        return True
    return False


def _remove_from_list(node_list: list[dict[str, Any]], node_id: str) -> bool:
    for i, node in enumerate(node_list):
        if node.get("node_id") == node_id:
            del node_list[i]
            return True
        children = node.get("nodes")
        if isinstance(children, list) and _remove_from_list(children, node_id):
            return True
    return False
