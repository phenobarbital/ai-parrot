"""Pytest fixtures for the PageIndex embedding latency benchmark.

Provides a lightweight compliance tree fixture backed by the corpus built
in TASK-1550.  When the pre-built tree is absent, the fixture falls back to
a small synthetic in-memory tree so that benchmark infrastructure tests can
still run offline.

Usage in test files::

    from benchmarks.pageindex_embedding_latency.conftest_tree import (
        compliance_tree_nodes,
        compliance_tree_oracle,
    )

    def test_something(compliance_tree_nodes):
        assert len(compliance_tree_nodes) > 0

Or via pytest plugin auto-discovery (add this module to conftest.py imports).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pytest

# Default paths for the pre-built corpus
_DEFAULT_STORAGE_DIR = Path(__file__).parents[2] / "corpus/compliance_soc2_hipaa/trees"
_DEFAULT_TREE_NAME = "nist_800_53"

# ---------------------------------------------------------------------------
# Synthetic fallback tree
# ---------------------------------------------------------------------------

_SYNTHETIC_NODES: dict[str, dict[str, Any]] = {
    f"node_{i:04d}": {
        "title": f"Control AC-{i}",
        "summary": (
            f"Access control requirement {i}: enforce least-privilege "
            "for all system accounts."
        ),
        "children": [],
    }
    for i in range(1, 21)
}


def _load_tree_nodes(
    storage_dir: Path = _DEFAULT_STORAGE_DIR,
    tree_name: str = _DEFAULT_TREE_NAME,
) -> dict[str, dict[str, Any]]:
    """Load node dictionaries from a pre-built PageIndex tree JSON file.

    Falls back to :data:`_SYNTHETIC_NODES` if the file is absent.

    Args:
        storage_dir: Directory containing ``<tree_name>.json``.
        tree_name: Tree file stem (without ``.json``).

    Returns:
        Mapping of ``node_id → node_dict``.
    """
    tree_file = storage_dir / f"{tree_name}.json"
    if tree_file.exists():
        try:
            data = json.loads(tree_file.read_text())
            nodes = data.get("nodes", {})
            if nodes:
                return nodes  # type: ignore[return-value]
        except Exception:  # noqa: BLE001
            pass
    return _SYNTHETIC_NODES


def _build_oracle(
    nodes: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Build a trivial recall oracle from node data.

    Each node's title+summary becomes the query text; the node itself is the
    only relevant result.

    Args:
        nodes: Node dictionary as returned by :func:`_load_tree_nodes`.

    Returns:
        Mapping ``{query_text: [node_id]}``.
    """
    oracle: dict[str, list[str]] = {}
    for node_id, node in list(nodes.items())[:20]:
        title = node.get("title", "")
        summary = node.get("summary", "")
        query = f"{title} {summary}".strip()
        if query:
            oracle[query] = [node_id]
    return oracle


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def compliance_tree_nodes() -> dict[str, dict[str, Any]]:
    """Session-scoped fixture: compliance tree nodes dict.

    Loads from the pre-built corpus tree when available, otherwise falls
    back to a 20-node synthetic tree for CI / offline environments.

    Returns:
        Mapping of ``node_id → node_dict`` with ``title``, ``summary``,
        and ``children`` keys.
    """
    return _load_tree_nodes()


@pytest.fixture(scope="session")
def compliance_tree_oracle(
    compliance_tree_nodes: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Session-scoped fixture: recall oracle built from tree nodes.

    Returns:
        Mapping ``{query_text: [relevant_node_id, …]}``.
    """
    return _build_oracle(compliance_tree_nodes)


@pytest.fixture(scope="session")
def synthetic_tree_nodes() -> dict[str, dict[str, Any]]:
    """Session-scoped fixture: always-available synthetic tree (20 nodes).

    Use this fixture when tests must be fully offline (no corpus files).

    Returns:
        Mapping of synthetic ``node_id → node_dict``.
    """
    return _SYNTHETIC_NODES.copy()
