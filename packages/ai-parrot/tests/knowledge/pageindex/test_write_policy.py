"""FEAT-876 M2 — PageIndexToolkit write-policy hook."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.pageindex import PageIndexToolkit, PageIndexWriteDenied
from parrot.knowledge.pageindex import toolkit as toolkit_module

_MUTATION_RE = re.compile(r"\btree_lock\(|\._mutate\(|\._write\(")


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    # tiktoken may download encodings on first use; approximate with char count.
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path)


@pytest.fixture
def ro_toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(storage_dir=tmp_path, read_only=True)


def _public_async_methods() -> dict[str, str]:
    """Return ``{name: source}`` for every public coroutine defined on PageIndexToolkit."""
    source = textwrap.dedent(inspect.getsource(PageIndexToolkit))
    cls = ast.parse(source).body[0]
    assert isinstance(cls, ast.ClassDef)
    return {
        node.name: ast.get_source_segment(source, node) or ""
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_")
    }


def _tree_bytes(storage_dir: Path, tree_name: str) -> bytes:
    return (storage_dir / f"{tree_name}.json").read_bytes()


def test_write_tools_matches_every_mutating_tool() -> None:
    """Every public coroutine that locks or mutates is in write_tools; no read tool is."""
    methods = _public_async_methods()
    mutating = {name for name, src in methods.items() if _MUTATION_RE.search(src)}
    assert mutating, "AST scan found no mutating coroutine"
    for name in mutating:
        assert f"pageindex_{name}" in PageIndexToolkit.write_tools, name
    # every write tool names a real public coroutine
    for tool_name in PageIndexToolkit.write_tools:
        assert tool_name.removeprefix("pageindex_") in methods, tool_name
    # reads stay out
    for read in ("get_generation", "get_tree", "list_trees", "search", "retrieve", "outline", "read_pages"):
        assert f"pageindex_{read}" not in PageIndexToolkit.write_tools
    # each write tool calls the hook before anything else
    for tool_name in PageIndexToolkit.write_tools:
        assert "self._authorize_write(" in methods[tool_name.removeprefix("pageindex_")], tool_name


def test_write_denied_is_permission_error() -> None:
    assert issubclass(PageIndexWriteDenied, PermissionError)


def test_default_toolkit_exposes_write_tools(toolkit: PageIndexToolkit) -> None:
    names = {tool.name for tool in toolkit.get_tools()}
    assert {"pageindex_create_tree", "pageindex_add_node"} <= names


async def test_read_only_hides_and_refuses(ro_toolkit: PageIndexToolkit, tmp_path: Path) -> None:
    names = {tool.name for tool in ro_toolkit.get_tools()}
    assert not names & PageIndexToolkit.write_tools
    assert "pageindex_list_trees" in names
    with pytest.raises(PageIndexWriteDenied):
        await ro_toolkit.create_tree("t")
    assert not (tmp_path / "t.json").exists()


async def test_read_only_refuses_mutate_backstop(toolkit: PageIndexToolkit, tmp_path: Path) -> None:
    await toolkit.create_tree("t")
    ro = PageIndexToolkit(storage_dir=tmp_path, read_only=True)

    async def _apply(txn: Any) -> None:
        raise AssertionError("apply must not run")

    with pytest.raises(PageIndexWriteDenied):
        await ro._mutate("t", _apply)


async def test_authorize_write_called_before_lock(
    toolkit: PageIndexToolkit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await toolkit.create_tree("t")
    await toolkit.add_node("t", "Alpha", body="alpha body text")
    before = _tree_bytes(tmp_path, "t")

    def _deny(tree_name: str, op: str) -> None:
        raise PageIndexWriteDenied(f"denied {op} on {tree_name}")

    def _no_lock(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("tree_lock must not be entered after a denied write")

    monkeypatch.setattr(toolkit, "_authorize_write", _deny)
    monkeypatch.setattr(toolkit_module, "tree_lock", _no_lock)
    monkeypatch.setattr("parrot.knowledge.pageindex.generation.tree_lock", _no_lock)

    with pytest.raises(PageIndexWriteDenied):
        await toolkit.add_node("t", "Beta", body="beta")
    with pytest.raises(PageIndexWriteDenied):
        await toolkit.delete_tree("t")
    with pytest.raises(PageIndexWriteDenied):
        await toolkit.rename_tree("t", "u")
    with pytest.raises(PageIndexWriteDenied):
        await toolkit.optimize("t", apply=True, llm_passes=False)
    with pytest.raises(PageIndexWriteDenied):
        await toolkit.vacuum_tree("t")

    assert _tree_bytes(tmp_path, "t") == before
    assert not (tmp_path / "u.json").exists()


async def test_rename_authorizes_both_endpoints(
    toolkit: PageIndexToolkit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await toolkit.create_tree("a")
    calls: list[tuple[str, str]] = []

    def _record(tree_name: str, op: str) -> None:
        calls.append((tree_name, op))

    monkeypatch.setattr(toolkit, "_authorize_write", _record)
    await toolkit.rename_tree("a", "b")
    assert ("a", "rename_tree") in calls
    assert ("b", "rename_tree") in calls
    assert (tmp_path / "b.json").exists()


async def test_optimize_dry_run_is_not_a_write(toolkit: PageIndexToolkit, ro_toolkit: PageIndexToolkit) -> None:
    await toolkit.create_tree("t")
    await toolkit.add_node("t", "Alpha", body="alpha body text")
    # A dry run is a read: must not raise PageIndexWriteDenied.
    await ro_toolkit.optimize("t", llm_passes=False)
    with pytest.raises(PageIndexWriteDenied):
        await ro_toolkit.optimize("t", apply=True, llm_passes=False)
