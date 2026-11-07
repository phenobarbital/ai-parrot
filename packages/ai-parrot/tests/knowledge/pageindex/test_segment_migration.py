"""index_segments for legacy trees; revisions follow rename and delete (FEAT-840 / TASK-5310)."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.segments import validate_ownership
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.pageindex.utils import structure_to_list


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    response = MagicMock()
    response.output = "x"
    response.structured_output = None
    a.client = MagicMock()
    a.client.ask = AsyncMock(return_value=response)
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="x")
    return a


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.knowledge.pageindex.md_builder.count_tokens", _approx)
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine", lambda force_reresolve=False: None
    )


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, lightweight_model="light")


async def _legacy_tree(toolkit, name="old"):
    await toolkit.create_tree(name)
    a = await toolkit.add_node(name, "Handbook", body="Handbook intro paragraph.")
    await toolkit.add_node(name, "Install", body="Install step one.\n\nInstall step two.", parent_node_id=a["node_id"])
    await toolkit.add_node(name, "Notes", body="Standalone notes text.")
    return a


@pytest.mark.asyncio
async def test_index_segments_legacy_tree(toolkit, tmp_path):
    await _legacy_tree(toolkit)
    before = (await toolkit.get_generation("old"))["id"]
    result = await toolkit.index_segments("old")
    assert result["generation"] == before + 1 and len(result["documents"]) == 2
    assert {d["doc_id"] for d in result["documents"]} == {"handbook", "notes"}

    tree = await toolkit.get_tree("old")
    nodes = structure_to_list(tree["structure"])
    assert all(n.get("doc_id") and n.get("revision") and n.get("owned") is not None for n in nodes)
    doc = result["documents"][0]
    rev = SegmentStore(tmp_path).load_revision("old", doc["doc_id"], doc["revision"])
    assert rev.source.kind == "legacy" and all(s.page is None for s in rev.segments)
    assert [s.section for s in rev.segments] == [["Handbook"], ["Handbook", "Install"], ["Handbook", "Install"]]
    assert validate_ownership([n for n in nodes if n["doc_id"] == "handbook"], rev) == []

    install = next(n for n in nodes if n["title"] == "Install")
    read = await toolkit.read_segments("old", node_id=install["node_id"])
    assert [s["text"] for s in read["segments"]] == ["Install step one.", "Install step two."]


@pytest.mark.asyncio
async def test_index_segments_idempotent_and_root_only(toolkit):
    await _legacy_tree(toolkit)
    await toolkit.index_segments("old")
    generation = (await toolkit.get_generation("old"))["id"]
    again = await toolkit.index_segments("old")
    assert again["documents"] == [] and again["generation"] == generation
    assert (await toolkit.get_generation("old"))["id"] == generation

    await toolkit.create_tree("fresh")
    a = await toolkit.add_node("fresh", "Top", body="Top text.")
    child = await toolkit.add_node("fresh", "Child", body="Child text.", parent_node_id=a["node_id"])
    with pytest.raises(ValueError):
        await toolkit.index_segments("fresh", node_id=child["node_id"])
    with pytest.raises(KeyError):
        await toolkit.index_segments("fresh", node_id="9999")
    one = await toolkit.index_segments("fresh", node_id=a["node_id"])
    assert len(one["documents"]) == 1
    with pytest.raises(ValueError):
        await toolkit.index_segments("fresh", node_id=a["node_id"])


@pytest.mark.asyncio
async def test_rename_tree_copies_revisions(toolkit, tmp_path, monkeypatch):
    async def fake_build(doc, adapter, options=None, **kwargs):
        return {
            "doc_name": "doc.pdf",
            "structure": [{"title": "Ch 1", "node_id": "0000", "start_index": 1, "end_index": 1}],
            "_node_markdown": {},
            "_pages": [(1, "# Ch 1\n\nOnly page.")],
        }

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.build_page_index", fake_build)
    await toolkit.create_tree("src")
    await toolkit.create_tree("dst")
    await toolkit.import_pdf("src", str(pdf))
    before = await toolkit.read_pages("src", "doc", "1")
    await toolkit.rename_tree("src", "dst", overwrite=True)
    after = await toolkit.read_pages("dst", "doc", "1")
    assert [s["text"] for s in after["segments"]] == [s["text"] for s in before["segments"]]
    assert not (tmp_path / "src").exists()


@pytest.mark.asyncio
async def test_delete_tree_removes_segments(toolkit, tmp_path):
    await _legacy_tree(toolkit)
    await toolkit.index_segments("old")
    assert any((tmp_path / "old" / "segments").iterdir())
    await toolkit.delete_tree("old")
    assert not (tmp_path / "old" / "segments").exists()
