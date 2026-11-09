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
async def test_scoped_optimize_of_inner_section_publishes_changes(tmp_path: Path) -> None:
    """Scoping to a non-root section applies its changes instead of restoring the base tree."""
    toolkit = await _tree_with_document(tmp_path)
    before_tree = await toolkit.get_tree("guide")
    before = (await toolkit.get_generation("guide"))["id"]
    inner = before_tree["structure"][0]["nodes"][0]
    untouched = before_tree["structure"][0]["nodes"][-1]
    assert untouched["title"] == "Second section"

    report = await toolkit.optimize("guide", node_id=inner["node_id"], apply=True, llm_passes=False)

    assert report["errors"] == []
    assert report["generation_after"] == before + 1
    after_tree = await toolkit.get_tree("guide")
    assert after_tree["structure"][0]["nodes"][0] != inner
    assert after_tree["structure"][0]["nodes"][-1] == untouched


@pytest.mark.asyncio
async def test_scoped_optimize_keeps_concept_ids_outside_scope(tmp_path: Path) -> None:
    """Sibling concept ids outside the scoped node are never re-deduplicated by an apply."""
    toolkit = await _tree_with_document(tmp_path)
    before_tree = await toolkit.get_tree("guide")
    inner = before_tree["structure"][0]["nodes"][0]
    outside = [n["concept_id"] for n in before_tree["structure"][0]["nodes"][1:]]
    assert len(set(outside)) < len(outside)  # the fixture has duplicate sibling concept ids

    report = await toolkit.optimize("guide", node_id=inner["node_id"], apply=True, llm_passes=False)

    assert report["errors"] == []
    after_tree = await toolkit.get_tree("guide")
    assert [n["concept_id"] for n in after_tree["structure"][0]["nodes"][1:]] == outside


@pytest.mark.asyncio
async def test_dry_run_llm_results_are_reused_by_apply(tmp_path: Path) -> None:
    """The content-addressed LLM cache is shared across calls, so an apply repeats no model call."""
    from parrot.knowledge.pageindex.optimizer_llm import HeadingProposals, KeyItemProposals, SummaryOut

    adapter = MagicMock(client=MagicMock(), model="test-model")

    async def structured(prompt: str, output_model: type, **kwargs: object) -> object:
        """Return an empty, schema-valid proposal for each pass."""
        if output_model is HeadingProposals:
            return HeadingProposals(seqs=[])
        if output_model is KeyItemProposals:
            return KeyItemProposals(items=[])
        return SummaryOut(summary="short summary")

    adapter.ask_structured = AsyncMock(side_effect=structured)
    adapter.ask = AsyncMock(return_value="description")
    toolkit = PageIndexToolkit(
        adapter=adapter,
        storage_dir=tmp_path,
        optimize_on_import=False,
        optimizer_settings={"target_leaf_tokens": 20, "min_leaf_tokens": 0},
    )
    await toolkit.create_tree("guide")
    await toolkit.insert_markdown("guide", "# Guide\n\n## A\n\n" + "Alpha text sentence. " * 30)

    dry = await toolkit.optimize("guide")
    calls_after_dry_run = adapter.ask_structured.await_count
    applied = await toolkit.optimize("guide", apply=True)

    assert dry["llm_passes"] == "ran"
    assert dry["llm_calls_estimated"] > 0
    assert calls_after_dry_run > 0
    assert adapter.ask_structured.await_count == calls_after_dry_run
    assert applied["errors"] == []


@pytest.mark.asyncio
async def test_locked_nodes_make_no_llm_calls(tmp_path: Path) -> None:
    """Locked subtrees are excluded from the LLM passes, so no model call is spent on them."""
    adapter = MagicMock(client=MagicMock(), model="test-model")
    adapter.ask_structured = AsyncMock(side_effect=AssertionError("locked node sent to the model"))
    adapter.ask = AsyncMock(return_value="description")
    toolkit = PageIndexToolkit(
        adapter=adapter,
        storage_dir=tmp_path,
        optimize_on_import=False,
        optimizer_settings={"target_leaf_tokens": 20, "min_leaf_tokens": 0},
    )
    await toolkit.create_tree("guide")
    await toolkit.insert_markdown("guide", "# Guide\n\n## A\n\n" + "Alpha text sentence. " * 30)
    root = (await toolkit.get_tree("guide"))["structure"][0]
    await toolkit.update_node("guide", root["node_id"], locked=True)

    report = await toolkit.optimize("guide", apply=True)

    assert adapter.ask_structured.await_count == 0
    assert report["errors"] == []
    assert report["llm_calls_made"] == 0


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


@pytest.mark.asyncio
async def test_optimize_apply_with_empty_leaf(tmp_path: Path) -> None:
    """A published tree with an empty first leaf re-optimizes; the leaf survives as a root alias (FEAT-853)."""
    toolkit = await _tree_with_document(tmp_path)
    tree = toolkit._store.load("guide")
    root = tree["structure"][0]
    used_ids = {node.get("node_id") for node in structure_to_list(tree["structure"])}
    preface_id = next(f"{n:04d}" for n in range(9000, 10000) if f"{n:04d}" not in used_ids)
    root["nodes"].insert(
        0,
        {
            "title": "Preface",
            "concept_id": "guide/preface",
            "node_id": preface_id,
            "doc_id": root["doc_id"],
            "revision": root["revision"],
            "span": [root["span"][0], root["span"][0]],
            "owned": [],
            "nodes": [],
        },
    )
    toolkit._store.save("guide", tree)

    report = await toolkit.optimize("guide", apply=True, llm_passes=False)

    assert report["errors"] == []
    published_root = (await toolkit.get_tree("guide"))["structure"][0]
    assert "guide/preface" in published_root.get("aliases", [])
    assert any(action["reason"] == "empty" for action in report["merged"])
