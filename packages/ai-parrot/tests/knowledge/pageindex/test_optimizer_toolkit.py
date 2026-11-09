"""Toolkit integration of the PageIndex optimizer (FEAT-846 M4)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.segments import segment_pages
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list


@pytest.mark.asyncio
async def test_optimize_on_import_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Optimize PDF, Markdown, and ebook imports while preserving the opt-out path."""
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"%PDF-1.4 optimizer fixture")
    pdf_options: list[dict] = []
    markdown_options: list[dict | None] = []

    async def fake_pdf_builder(doc: str, adapter: object, options: dict, **kwargs: object) -> dict:
        """Return a segment-backed PDF build result and capture options."""
        pdf_options.append(dict(options))
        return {
            "doc_name": "document.pdf",
            "doc_description": "legacy description",
            "structure": [
                {
                    "title": "PDF chapter",
                    "summary": "legacy summary",
                    "node_id": "0000",
                    "start_index": 1,
                    "end_index": 1,
                }
            ],
            "_segments": segment_pages([(1, "# PDF chapter\n\nPDF body text.")]),
        }

    async def fake_markdown_builder(
        md_text: str, adapter: object, options: dict | None = None, doc_name: str = "document.md"
    ) -> dict:
        """Return a text-backed Markdown tree and capture options."""
        markdown_options.append(options)
        return {
            "doc_name": doc_name,
            "structure": [
                {
                    "title": "Markdown chapter",
                    "summary": "legacy summary",
                    "node_id": "0000",
                    "text": md_text,
                    "nodes": [],
                }
            ],
        }

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", fake_pdf_builder)
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.md_to_tree", fake_markdown_builder)
    monkeypatch.setattr(PageIndexToolkit, "_run_t3_classification", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )

    adapter = MagicMock(client=MagicMock(), model="test-model")
    adapter.ask = AsyncMock(return_value="framed optimized description")
    enabled = PageIndexToolkit(
        adapter=adapter,
        storage_dir=tmp_path / "enabled",
        optimizer_settings={"llm_passes": False, "min_leaf_tokens": 0, "target_leaf_tokens": 10000},
    )
    for tree_name in ("pdf", "markdown", "ebook"):
        await enabled.create_tree(tree_name)

    pdf_result = await enabled.import_pdf("pdf", str(pdf), with_summaries=True, with_doc_description=True)
    await enabled.insert_markdown("markdown", "# Markdown chapter\n\nMarkdown body text.")
    await enabled.insert_ebook(
        "ebook",
        [
            {
                "section_id": "chapter",
                "title": "Ebook chapter",
                "content": "Ebook body text.",
                "toc_order": 0,
                "source_uri": "book.epub",
            }
        ],
    )

    assert pdf_options[0]["if_add_node_summary"] == "no"
    assert pdf_options[0]["if_add_doc_description"] == "no"
    assert markdown_options[0] == {"if_add_node_summary": "no"}
    assert pdf_result["doc_description"] == "framed optimized description"
    for tree_name in ("pdf", "markdown", "ebook"):
        nodes = structure_to_list(enabled._store.load(tree_name)["structure"])
        assert nodes
        assert all(node.get("optimizer", {}).get("passes", {}).get("summary") for node in nodes)
        assert all(node.get("body_ref") for node in nodes if node.get("owned"))

    disabled = PageIndexToolkit(adapter=None, storage_dir=tmp_path / "disabled", optimize_on_import=False)
    await disabled.create_tree("pdf")
    await disabled.create_tree("markdown")
    disabled_pdf = await disabled.import_pdf("pdf", str(pdf), with_summaries=True, with_doc_description=True)
    await disabled.insert_markdown("markdown", "# Markdown chapter\n\nMarkdown body text.")

    assert pdf_options[1]["if_add_node_summary"] == "yes"
    assert pdf_options[1]["if_add_doc_description"] == "yes"
    assert markdown_options[1] is None
    assert disabled_pdf["doc_description"] == "legacy description"
    for tree_name in ("pdf", "markdown"):
        nodes = structure_to_list(disabled._store.load(tree_name)["structure"])
        assert all("optimizer" not in node for node in nodes)
        assert [node.get("summary") for node in nodes] == ["legacy summary"]
