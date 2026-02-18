"""PageIndex tree builder for Markdown documents."""
from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace as config
from typing import Any

from .llm_adapter import PageIndexLLMAdapter
from .utils import (
    count_tokens,
    create_clean_structure_for_description,
    write_node_id,
)


logger = logging.getLogger("parrot.pageindex")

# --- Markdown Header Regex ---
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")


def _parse_header_level(line: str) -> tuple[int, str] | None:
    """Parse a markdown header line into (level, title)."""
    m = _HEADER_RE.match(line.strip())
    if m:
        return len(m.group(1)), m.group(2).strip()
    return None


# ======================== Markdown Parsing ========================

def parse_markdown_structure(md_text: str) -> list[dict]:
    """Parse markdown text into a flat list of section entries."""
    lines = md_text.split("\n")
    sections: list[dict] = []
    current_text: list[str] = []
    counters: dict[int, int] = {}

    for line_num, line in enumerate(lines, 1):
        parsed = _parse_header_level(line)
        if parsed:
            level, title = parsed
            if current_text and sections:
                sections[-1]["text"] = "\n".join(current_text).strip()
                sections[-1]["token_count"] = count_tokens(sections[-1]["text"])
            current_text = []

            # Build structure index
            counters[level] = counters.get(level, 0) + 1
            for deeper in list(counters.keys()):
                if deeper > level:
                    del counters[deeper]

            parts = []
            for lv in sorted(counters.keys()):
                if lv <= level:
                    parts.append(str(counters[lv]))
            structure = ".".join(parts) if parts else str(level)

            sections.append({
                "structure": structure,
                "title": title,
                "level": level,
                "line_num": line_num,
                "text": "",
                "token_count": 0,
            })
        else:
            current_text.append(line)

    if current_text and sections:
        sections[-1]["text"] = "\n".join(current_text).strip()
        sections[-1]["token_count"] = count_tokens(sections[-1]["text"])

    return sections


def sections_to_tree(sections: list[dict]) -> list[dict]:
    """Convert flat section list to hierarchical tree."""
    if not sections:
        return []

    root_nodes: list[dict] = []
    stack: list[tuple[int, dict]] = []

    for section in sections:
        node: dict[str, Any] = {
            "title": section["title"],
            "line_num": section.get("line_num"),
            "text": section.get("text", ""),
            "token_count": section.get("token_count", 0),
        }

        level = section["level"]

        while stack and stack[-1][0] >= level:
            stack.pop()

        if stack:
            parent = stack[-1][1]
            if "nodes" not in parent:
                parent["nodes"] = []
            parent["nodes"].append(node)
        else:
            root_nodes.append(node)

        stack.append((level, node))

    return root_nodes


# ======================== Tree Thinning ========================

def _count_tree_tokens(node: dict) -> int:
    """Count total tokens in a node and its children."""
    total = node.get("token_count", 0)
    for child in node.get("nodes", []):
        total += _count_tree_tokens(child)
    return total


def thin_tree(
    tree: list[dict],
    max_token_threshold: int = 200,
) -> list[dict]:
    """Remove nodes below the token threshold."""
    thinned: list[dict] = []
    for node in tree:
        total_tokens = _count_tree_tokens(node)
        if total_tokens < max_token_threshold:
            continue

        new_node = {k: v for k, v in node.items() if k != "nodes"}
        if "nodes" in node:
            children = thin_tree(node["nodes"], max_token_threshold)
            if children:
                new_node["nodes"] = children

        thinned.append(new_node)
    return thinned


# ======================== Summary Generation ========================

async def generate_node_summary_md(
    node: dict,
    adapter: PageIndexLLMAdapter,
) -> str:
    """Generate a summary for a markdown node."""
    text = node.get("text", "")
    if not text.strip():
        return ""

    prompt = f"""You are given a section of a document. Generate a concise description of the main points covered.

Section Title: {node.get('title', 'Untitled')}
Section Text: {text}

Directly return the description. Do not include any other text."""

    return await adapter.ask(prompt)


async def generate_prefix_summaries(
    tree: list[dict],
    adapter: PageIndexLLMAdapter,
) -> None:
    """Generate prefix summaries for all nodes."""
    async def process_node(node: dict) -> None:
        if node.get("text") and node["text"].strip():
            summary = await generate_node_summary_md(node, adapter)
            node["summary"] = summary

        children = node.get("nodes", [])
        if children:
            tasks = [process_node(child) for child in children]
            await asyncio.gather(*tasks)

            child_summaries = [c.get("summary", "") for c in children if c.get("summary")]
            if child_summaries:
                combined = "; ".join(child_summaries[:5])
                node["prefix_summary"] = (
                    f"{node.get('summary', '')}\nSubsections cover: {combined}"
                )

    tasks = [process_node(node) for node in tree]
    await asyncio.gather(*tasks)


# ======================== Public API ========================

async def md_to_tree(
    md_text: str,
    adapter: PageIndexLLMAdapter,
    options: dict | config | None = None,
    doc_name: str = "document.md",
) -> dict:
    """Build a PageIndex tree from markdown text.

    Args:
        md_text: Full markdown document text.
        adapter: LLM adapter wrapping any AbstractClient.
        options: Configuration dict or SimpleNamespace.
        doc_name: Document identifier.

    Returns:
        Dictionary with doc_name and structure (the tree).
    """
    default_opts = {
        "if_add_node_id": "yes",
        "if_add_node_summary": "yes",
        "if_add_doc_description": "no",
        "max_page_num_each_node": 10,
        "max_token_num_each_node": 20000,
        "toc_check_page_num": 20,
        "model": "gpt-4o",
    }

    if isinstance(options, config):
        user_opts = vars(options)
    elif isinstance(options, dict):
        user_opts = options
    else:
        user_opts = {}

    merged = {**default_opts, **user_opts}
    opt = config(**merged)

    sections = parse_markdown_structure(md_text)
    tree = sections_to_tree(sections)

    if not tree:
        logger.warning("No markdown headers found")
        return {"doc_name": doc_name, "structure": []}

    tree = thin_tree(tree, max_token_threshold=50)

    if opt.if_add_node_id == "yes":
        write_node_id(tree)

    if opt.if_add_node_summary == "yes":
        await generate_prefix_summaries(tree, adapter)

    if opt.if_add_doc_description == "yes":
        from .builder import generate_doc_description
        clean_struct = create_clean_structure_for_description(tree)
        doc_description = await generate_doc_description(clean_struct, adapter)
        return {
            "doc_name": doc_name,
            "doc_description": doc_description,
            "structure": tree,
        }

    return {"doc_name": doc_name, "structure": tree}
