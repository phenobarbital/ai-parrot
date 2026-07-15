---
type: Wiki Summary
title: parrot.knowledge.pageindex.tree_ops
id: mod:parrot.knowledge.pageindex.tree_ops
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mutation helpers for PageIndex trees.
relates_to:
- concept: func:parrot.knowledge.pageindex.tree_ops.delete_node
  rel: defines
- concept: func:parrot.knowledge.pageindex.tree_ops.make_folder_node
  rel: defines
- concept: func:parrot.knowledge.pageindex.tree_ops.reindex_node_ids
  rel: defines
- concept: func:parrot.knowledge.pageindex.tree_ops.splice_subtree
  rel: defines
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.tree_ops`

Mutation helpers for PageIndex trees.

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

## Functions

- `def reindex_node_ids(tree: dict[str, Any]) -> None` — Reassign sequential 4-digit ``node_id`` values across the tree.
- `def make_folder_node(name: str) -> dict[str, Any]` — Build a synthetic inner node representing a directory.
- `def splice_subtree(target: dict[str, Any], subtree: dict[str, Any] | list[dict[str, Any]], parent_node_id: Optional[str]=None) -> list[str]` — Insert ``subtree`` under ``parent_node_id`` (or at root if None).
- `def delete_node(tree: dict[str, Any], node_id: str) -> bool` — Remove the node with ``node_id`` and all its descendants.
