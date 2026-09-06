"""Convert source ebook relationships to a tree without Markdown inference."""

from __future__ import annotations

from typing import Any

from parrot.loaders.ebook import EbookSection


def ebook_tree(sections: list[EbookSection]) -> dict[str, Any]:
    """Validate relationships before building an exact source navigation tree."""
    by_id = {section.section_id: section for section in sections}
    if len(by_id) != len(sections):
        raise ValueError("Duplicate ebook section IDs")
    for section in sections:
        ancestors = {section.section_id}
        parent = section.parent_id
        while parent is not None:
            if parent not in by_id:
                raise ValueError(f"Missing ebook parent: {parent}")
            if parent in ancestors:
                raise ValueError("Cyclic ebook TOC")
            ancestors.add(parent)
            parent = by_id[parent].parent_id
    nodes = {
        section.section_id: {
            "node_id": section.section_id,
            "title": section.title,
            "summary": section.content[:200],
            "text": section.content,
            "metadata": section.model_dump(exclude={"content"}),
            "nodes": [],
        }
        for section in sections
    }
    roots: list[dict[str, Any]] = []
    for section in sorted(sections, key=lambda section: section.toc_order):
        siblings = roots if section.parent_id is None else nodes[section.parent_id]["nodes"]
        siblings.append(nodes[section.section_id])
    return {"structure": roots}
