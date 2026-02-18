"""PageIndex tree-search retriever for RAG."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .llm_adapter import PageIndexLLMAdapter
from .schemas import TreeSearchResult
from .utils import find_node_by_id, get_nodes

logger = logging.getLogger("parrot.pageindex")


class PageIndexRetriever:
    """Tree-search retriever using an LLM to navigate a PageIndex tree.

    Given a query, the retriever asks an LLM to reason over the tree
    structure and identify which nodes are most likely to contain
    relevant information.
    """

    def __init__(
        self,
        tree: dict | list,
        adapter: PageIndexLLMAdapter,
        expert_knowledge: Optional[str] = None,
    ):
        if isinstance(tree, dict):
            self.tree_data = tree
            self.structure = tree.get("structure", [])
        else:
            self.tree_data = {"structure": tree}
            self.structure = tree
        self.adapter = adapter
        self.expert_knowledge = expert_knowledge

    async def search(self, query: str) -> TreeSearchResult:
        """Execute LLM tree search to find relevant nodes."""
        tree_str = json.dumps(self.structure, indent=2, ensure_ascii=False)

        if self.expert_knowledge:
            prompt = f"""
You are given a question and a tree structure of a document.
You need to find all nodes that are likely to contain the answer.

Query: {query}

Document tree structure: {tree_str}

Expert Knowledge of relevant sections: {self.expert_knowledge}

Reply in the following JSON format:
{{
  "thinking": <reasoning about which nodes are relevant>,
  "node_list": [node_id1, node_id2, ...]
}}
"""
        else:
            prompt = f"""
You are given a query and the tree structure of a document.
You need to find all nodes that are likely to contain the answer.

Query: {query}

Document tree structure: {tree_str}

Reply in the following JSON format:
{{
  "thinking": <your reasoning about which nodes are relevant>,
  "node_list": [node_id1, node_id2, ...]
}}
"""

        result = await self.adapter.ask_structured(prompt, TreeSearchResult)
        if isinstance(result, TreeSearchResult):
            return result
        # Fallback
        return TreeSearchResult(thinking="", node_list=[])

    async def retrieve(
        self,
        query: str,
        pdf_pages: Optional[list[tuple[str, int]]] = None,
    ) -> str:
        """Search tree and return concatenated text of matching nodes.

        If nodes have 'text' fields, those are used directly.
        If pdf_pages is provided, text is extracted from page ranges.
        Otherwise returns node titles and summaries.
        """
        search_result = await self.search(query)

        if not search_result.node_list:
            logger.info("No relevant nodes found for query: %s", query[:100])
            return ""

        context_parts: list[str] = []
        for node_id in search_result.node_list:
            node = find_node_by_id(self.structure, node_id)
            if not node:
                continue

            if node.get("text"):
                context_parts.append(
                    f"## {node.get('title', 'Section')}\n{node['text']}"
                )
            elif pdf_pages and node.get("start_index") and node.get("end_index"):
                text = ""
                for page_idx in range(node["start_index"] - 1, node["end_index"]):
                    if 0 <= page_idx < len(pdf_pages):
                        text += pdf_pages[page_idx][0]
                if text:
                    context_parts.append(
                        f"## {node.get('title', 'Section')}\n{text}"
                    )
            else:
                summary = node.get("summary") or node.get("prefix_summary") or ""
                context_parts.append(
                    f"## {node.get('title', 'Section')}\n{summary}"
                )

        return "\n\n".join(context_parts)

    def get_tree_context(self, include_summaries: bool = True) -> str:
        """Return the tree structure as formatted context for system prompts.

        Args:
            include_summaries: If True, include node summaries in the context.

        Returns:
            Formatted string representation of the tree.
        """
        if include_summaries:
            nodes = get_nodes(self.structure)
            lines: list[str] = []
            for node in nodes:
                title = node.get("title", "")
                node_id = node.get("node_id", "")
                summary = node.get("summary", "")
                pages = ""
                if node.get("start_index") and node.get("end_index"):
                    pages = f" (pages {node['start_index']}-{node['end_index']})"
                line = f"[{node_id}] {title}{pages}"
                if summary:
                    line += f"\n    Summary: {summary}"
                lines.append(line)
            return "\n".join(lines)
        else:
            return json.dumps(self.structure, indent=2, ensure_ascii=False)

    def get_tree_json(self) -> dict:
        """Return the full tree data as a dictionary."""
        return self.tree_data

    @classmethod
    def from_json(
        cls,
        json_data: dict | str,
        adapter: PageIndexLLMAdapter,
        expert_knowledge: Optional[str] = None,
    ) -> PageIndexRetriever:
        """Create a retriever from a JSON file path or dict."""
        if isinstance(json_data, str):
            with open(json_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json_data
        return cls(tree=data, adapter=adapter, expert_knowledge=expert_knowledge)
