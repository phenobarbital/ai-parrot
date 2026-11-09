"""Bookstore integration coverage for the PageIndex tree optimizer."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from click.testing import CliRunner

from parrot.knowledge.bookstore import cli as bookstore_cli
from parrot.knowledge.bookstore.library import Bookstore


def test_optimize_book_and_cli(monkeypatch: Any) -> None:
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
