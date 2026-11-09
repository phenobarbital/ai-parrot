"""Toolkit integration of the PageIndex optimizer (FEAT-846 M4)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex import toolkit as toolkit_module
from parrot.knowledge.pageindex.optimizer_llm import run_llm_passes
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


async def _tree_with_document(tmp_path: Path, name: str = "guide") -> PageIndexToolkit:
    """Create a segment-backed tree that explicit optimization can process."""
    toolkit = PageIndexToolkit(
        storage_dir=tmp_path,
        optimize_on_import=False,
        optimizer_settings={"target_leaf_tokens": 20, "min_leaf_tokens": 0},
    )
    await toolkit.create_tree(name)
    await toolkit.insert_markdown(
        name,
        "# Guide\n\n"
        "## First section\n\n"
        "This section has enough repeated prose to create a deterministic optimizer report. " * 8
        + "\n\n## Second section\n\n"
        + "This is another section with enough text to produce segment-backed bodies. " * 8,
    )
    return toolkit


@pytest.mark.asyncio
async def test_optimize_dry_run_and_apply(tmp_path: Path) -> None:
    """Dry runs leave generations unchanged and a repeated apply is a no-op."""
    toolkit = await _tree_with_document(tmp_path)
    before = (await toolkit.get_generation("guide"))["id"]

    dry_run = await toolkit.optimize("guide", llm_passes=False)

    assert dry_run["dry_run"] is True
    assert dry_run["generation_before"] == dry_run["generation_after"] == before
    assert (await toolkit.get_generation("guide"))["id"] == before

    applied = await toolkit.optimize("guide", apply=True, llm_passes=False)
    repeated = await toolkit.optimize("guide", apply=True, llm_passes=False)

    assert applied["dry_run"] is False
    assert applied["generation_after"] == before + 1
    assert repeated["generation_before"] == repeated["generation_after"] == before + 1


@pytest.mark.asyncio
async def test_final_staging_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Final validation errors return a report and do not publish a partial candidate."""
    toolkit = await _tree_with_document(tmp_path)
    before = (await toolkit.get_generation("guide"))["id"]
    validations = 0

    def reject_after_staging(*args: object, **kwargs: object) -> list[str]:
        """Accept the planning check but reject the final staged candidate."""
        nonlocal validations
        validations += 1
        return [] if validations == 1 else ["final candidate rejected"]

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.validate_candidate", reject_after_staging)

    report = await toolkit.optimize("guide", apply=True, llm_passes=False)

    assert report["errors"] == ["final candidate rejected"]
    assert (await toolkit.get_generation("guide"))["id"] == before


@pytest.mark.asyncio
async def test_same_document_subtree_staging(tmp_path: Path) -> None:
    """A subtree optimize leaves bodies outside its selected document unchanged."""
    toolkit = await _tree_with_document(tmp_path)
    await toolkit.insert_markdown("guide", "# Separate\n\nIndependent document content. " * 20)
    before = toolkit._store.load("guide")
    first_root, second_root = before["structure"]
    second_refs = [node.get("body_ref") for node in structure_to_list([second_root])]

    report = await toolkit.optimize("guide", node_id=first_root["node_id"], apply=True, llm_passes=False)
    after = toolkit._store.load("guide")
    after_second = next(node for node in after["structure"] if node.get("doc_id") == second_root.get("doc_id"))

    assert report["errors"] == []
    assert [node.get("body_ref") for node in structure_to_list([after_second])] == second_refs


@pytest.mark.asyncio
async def test_optimize_stale_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale retry recreates the plan while retaining its LLM result cache."""
    toolkit = await _tree_with_document(tmp_path)
    cache_ids: list[int] = []

    async def stale_once(*args: object, **kwargs: object) -> None:
        """Advance the stored generation after the first plan to force one retry."""
        cache_ids.append(id(args[0].llm_cache))
        await run_llm_passes(*args, **kwargs)
        if len(cache_ids) == 1:
            concurrent = toolkit._store.load("guide")
            concurrent["generation"]["id"] += 1
            toolkit._store.save("guide", concurrent)

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.run_llm_passes", stale_once)

    report = await toolkit.optimize("guide", apply=True, llm_passes=False)

    assert report["errors"] == []
    assert len(cache_ids) == 2
    assert len(set(cache_ids)) == 1


@pytest.mark.asyncio
async def test_optimize_rejects_bad_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning validation failures are returned without publishing a generation."""
    toolkit = await _tree_with_document(tmp_path)
    before = (await toolkit.get_generation("guide"))["id"]
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.validate_candidate", lambda *args, **kwargs: ["invalid ownership"]
    )

    report = await toolkit.optimize("guide", apply=True, llm_passes=False)

    assert report["errors"] == ["invalid ownership"]
    assert (await toolkit.get_generation("guide"))["id"] == before


@pytest.mark.asyncio
async def test_optimize_without_model(tmp_path: Path) -> None:
    """The optimizer is exposed and runs deterministic passes without an LLM adapter."""
    toolkit = await _tree_with_document(tmp_path)

    report = await toolkit.optimize("guide")

    assert "pageindex_optimize" in toolkit.list_tool_names()
    assert "pageindex_optimize" not in toolkit.llm_dependent_tools
    assert report["llm_passes"] == "skipped (no model)"


@pytest.mark.asyncio
async def test_locked_semantics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Edits lock segment-backed nodes without invoking optimization."""
    toolkit = await _tree_with_document(tmp_path)
    original_plan = toolkit_module.plan_deterministic
    planner = MagicMock(wraps=original_plan)
    monkeypatch.setattr(toolkit_module, "plan_deterministic", planner)

    before = await toolkit.get_tree("guide")
    root = before["structure"][0]
    edited = root["nodes"][0]
    sibling = root["nodes"][1]

    manual_lock = await toolkit.update_node("guide", sibling["node_id"], locked=True)
    assert manual_lock["locked"] is True
    unlocked = await toolkit.update_node("guide", sibling["node_id"], locked=False)
    assert unlocked["locked"] is False

    await toolkit.update_node_content("guide", edited["node_id"], "Hand-edited body")
    assert planner.call_count == 0

    after_edit = await toolkit.get_tree("guide")
    edited_after = after_edit["structure"][0]["nodes"][0]
    assert edited_after["locked"] is True
    assert edited_after["locked_reason"] == "body_edited"
    edited_body_ref = edited_after["body_ref"]
    edited_body = toolkit._content_store.load_node("guide", edited_after)

    sibling_id = after_edit["structure"][0]["nodes"][1]["node_id"]
    await toolkit.optimize("guide", node_id=sibling_id, apply=True, llm_passes=False)
    await toolkit.optimize("guide", apply=True, llm_passes=False)

    after_optimizing = await toolkit.get_tree("guide")
    edited_after_optimizing = after_optimizing["structure"][0]["nodes"][0]
    assert edited_after_optimizing["body_ref"] == edited_body_ref
    assert toolkit._content_store.load_node("guide", edited_after_optimizing) == edited_body

    root_id = after_optimizing["structure"][0]["node_id"]
    descendant_id = after_optimizing["structure"][0]["nodes"][0]["node_id"]
    await toolkit.update_node("guide", root_id, locked=True)
    locked_tree = await toolkit.get_tree("guide")
    locked_descendants = locked_tree["structure"][0]["nodes"]

    excluded = await toolkit.optimize("guide", node_id=descendant_id, llm_passes=False)

    assert excluded["documents"] == []
    assert (await toolkit.get_tree("guide"))["structure"][0]["nodes"] == locked_descendants
