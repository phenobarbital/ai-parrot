"""Bookstore integration coverage for the PageIndex tree optimizer."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.pageindex import cli as pageindex_cli


def test_optimize_book_and_cli(monkeypatch: Any, tmp_path: Path) -> None:
    """Apply refreshes structural card fields while dry-run and CLI wiring stay safe."""
    card = SimpleNamespace(
        book_id="handbook",
        tree_name="handbook",
        toc=["old"],
        toc_digest="old digest",
        chapter_count=1,
        page_count=2,
    )

    def copy_card(*, update: dict[str, Any]) -> SimpleNamespace:
        values = vars(card) | update
        values.pop("model_copy", None)
        return SimpleNamespace(**values)

    card.model_copy = copy_card
    location = SimpleNamespace(scope="project")
    report = {
        "tree_name": "handbook",
        "dry_run": False,
        "nodes_before": 2,
        "nodes_after": 3,
        "merged": [],
        "expanded": [{"title": "Part Two"}],
        "llm_passes": "skipped (disabled)",
        "errors": [],
    }
    optimized_tree = {
        "structure": [
            {
                "node_id": "0001",
                "title": "Part One",
                "start_index": 1,
                "end_index": 4,
                "nodes": [
                    {
                        "node_id": "0002",
                        "title": "Chapter A",
                        "start_index": 2,
                        "end_index": 3,
                    }
                ],
            },
            {
                "node_id": "0003",
                "title": "Part Two",
                "start_index": 5,
                "end_index": 9,
            },
        ]
    }
    toolkit = SimpleNamespace(
        optimize=AsyncMock(side_effect=[report | {"dry_run": True}, report]),
        get_tree=AsyncMock(return_value=optimized_tree),
    )
    catalog = MagicMock()
    store = Bookstore.__new__(Bookstore)
    store.adapter = None
    monkeypatch.setattr(store, "resolve_book", lambda book_id: (card, location))
    monkeypatch.setattr(store, "_toolkit", lambda scope: toolkit)
    monkeypatch.setattr(store, "_ready_toolkit", AsyncMock(return_value=toolkit))
    monkeypatch.setattr(store, "_book_operation_lock", lambda *args, **kwargs: contextlib.nullcontext())
    monkeypatch.setattr(store, "_catalog", lambda scope: catalog)

    dry_run_report = asyncio.run(store.optimize_book("handbook"))

    assert dry_run_report["dry_run"] is True
    toolkit.get_tree.assert_not_awaited()
    catalog.upsert.assert_not_called()

    applied_report = asyncio.run(store.optimize_book("handbook", apply=True, llm_passes=False))

    assert applied_report == report
    toolkit.optimize.assert_any_await("handbook", apply=False, llm_passes=False)
    toolkit.optimize.assert_any_await("handbook", apply=True, llm_passes=False)
    toolkit.get_tree.assert_awaited_once_with("handbook")
    updated = catalog.upsert.call_args.args[0]
    assert [entry.title for entry in updated.toc] == ["Part One", "Chapter A", "Part Two"]
    assert updated.toc_digest != card.toc_digest
    assert updated.chapter_count == 2
    assert updated.page_count == 9

    cli_store = SimpleNamespace(optimize_book=AsyncMock(return_value=report))
    open_store = MagicMock(return_value=cli_store)
    monkeypatch.setattr(bookstore_cli, "_open_bookstore", open_store)

    result = CliRunner().invoke(
        bookstore_cli.bookstore,
        ["optimize", "handbook", "--global", "--apply", "--no-llm", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == report
    open_store.assert_called_once_with(llm_spec=None, scope_needed="global", use_llm=False)
    cli_store.optimize_book.assert_awaited_once_with("handbook", apply=True, llm_passes=False)

    pageindex_toolkit = SimpleNamespace(optimize=AsyncMock(return_value=report))
    toolkit_factory = MagicMock(return_value=pageindex_toolkit)
    monkeypatch.setattr("parrot.knowledge.pageindex.PageIndexToolkit", toolkit_factory)

    dry_run_result = CliRunner().invoke(
        pageindex_cli.pageindex,
        ["optimize", "handbook", "--storage-dir", str(tmp_path), "--target-tokens", "1200"],
    )

    assert dry_run_result.exit_code == 0, dry_run_result.output
    assert "dry-run: handbook" in dry_run_result.output
    assert "nodes: 2 -> 3; merged: 0; expanded: 1" in dry_run_result.output
    assert "llm: skipped (disabled)" in dry_run_result.output
    toolkit_factory.assert_called_once_with(storage_dir=str(tmp_path), llm_client=None)
    pageindex_toolkit.optimize.assert_awaited_once_with(
        "handbook",
        node_id=None,
        apply=False,
        target_leaf_tokens=1200,
    )

    apply_result = CliRunner().invoke(
        pageindex_cli.pageindex,
        ["optimize", "handbook", "--storage-dir", str(tmp_path), "--node", "0001", "--apply", "--json"],
    )

    assert apply_result.exit_code == 0, apply_result.output
    assert json.loads(apply_result.output) == report
    assert toolkit_factory.call_count == 2
    pageindex_toolkit.optimize.assert_awaited_with(
        "handbook",
        node_id="0001",
        apply=True,
        target_leaf_tokens=None,
    )

    fake_client = object()
    resolve_adapter = MagicMock(return_value=(object(), None, fake_client))
    monkeypatch.setattr("parrot.knowledge.bookstore._llm.resolve_adapter", resolve_adapter)

    llm_result = CliRunner().invoke(
        pageindex_cli.pageindex,
        [
            "optimize",
            "handbook",
            "--storage-dir",
            str(tmp_path),
            "--llm",
            "test:model",
            "--json",
        ],
    )

    assert llm_result.exit_code == 0, llm_result.output
    resolve_adapter.assert_called_once_with("test:model")
    toolkit_factory.assert_called_with(storage_dir=str(tmp_path), llm_client=fake_client)
