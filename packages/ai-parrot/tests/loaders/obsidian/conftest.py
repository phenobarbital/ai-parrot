"""Fixtures for the Obsidian loader tests (FEAT-392)."""
from typing import Any, Optional

import pytest

from tests.interfaces.obsidian.conftest import fixture_vault  # noqa: F401


class StubPageIndex:
    """Minimal PageIndexToolkit stand-in recording every mutation."""

    def __init__(self) -> None:
        self.trees: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []
        self._counter = 0

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        if tree_name not in self.trees:
            raise KeyError(tree_name)
        return self.trees[tree_name]

    async def create_tree(
        self, tree_name: str, doc_name: Optional[str] = None
    ) -> dict[str, Any]:
        self.trees[tree_name] = {"tree_name": tree_name, "nodes": []}
        return {"tree_name": tree_name}

    async def add_node(
        self,
        tree_name: str,
        title: str,
        body: str = "",
        parent_node_id: Optional[str] = None,
        summary: Optional[str] = None,
        categories: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._counter += 1
        node_id = f"node-{self._counter}"
        self.trees.setdefault(
            tree_name, {"tree_name": tree_name, "nodes": []}
        )["nodes"].append(
            {
                "node_id": node_id,
                "title": title,
                "body": body,
                "categories": categories or [],
                "metadata": metadata or {},
            }
        )
        return {
            "tree_name": tree_name,
            "node_id": node_id,
            "parent_node_id": parent_node_id,
        }

    async def delete_node(self, tree_name: str, node_id: str) -> dict[str, Any]:
        self.deleted.append(node_id)
        tree = self.trees.get(tree_name) or {"nodes": []}
        tree["nodes"] = [
            node for node in tree["nodes"] if node["node_id"] != node_id
        ]
        return {"deleted": True}

    def node_titles(self, tree_name: str) -> list[str]:
        return [node["title"] for node in self.trees[tree_name]["nodes"]]

    def node_by_title(self, tree_name: str, title: str) -> dict[str, Any]:
        for node in self.trees[tree_name]["nodes"]:
            if node["title"] == title:
                return node
        raise KeyError(title)


@pytest.fixture
def stub_pageindex() -> StubPageIndex:
    return StubPageIndex()


@pytest.fixture
def source_manager(tmp_path):
    from parrot.knowledge.wiki.sources import SourceCollectionManager

    return SourceCollectionManager(tmp_path / "sources", backend="json")
