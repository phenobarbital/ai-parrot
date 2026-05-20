"""Tests for PageIndexToolkit.import_folder hierarchy preservation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.pageindex.ingest import IngestedMarkdown
from parrot.pageindex.toolkit import PageIndexToolkit


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    client_response = MagicMock()
    client_response.output = "analysis prose"
    client_response.structured_output = None
    a.client = MagicMock()
    a.client.ask = AsyncMock(return_value=client_response)
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="analysis prose")
    a.ask_structured = AsyncMock(side_effect=_struct_factory())
    return a


def _struct_factory():
    counter = {"i": 0}

    async def _factory(*args, **kwargs):
        counter["i"] += 1
        n = counter["i"]
        return IngestedMarkdown(
            title=f"Doc {n}",
            summary=f"summary {n}",
            markdown=(
                f"# Doc {n}\n\n"
                f"Introduction text for document number {n} with enough "
                f"length so the thinning step retains the node.\n\n"
                f"## Body\n"
                f"Detailed body content for doc {n} including more text "
                f"so the section stays after the markdown tree builder runs.\n"
            ),
        )

    return _factory


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))
    monkeypatch.setattr("parrot.pageindex.utils.count_tokens", _approx)
    monkeypatch.setattr("parrot.pageindex.md_builder.count_tokens", _approx)


@pytest.fixture
def toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(
        adapter=_adapter(),
        storage_dir=tmp_path / "store",
        lightweight_model="light",
        folder_concurrency=2,
    )


@pytest.fixture
def sample_folder(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\nFirst doc\n", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("# B\nNested doc\n", encoding="utf-8")
    (sub / "img.bin").write_bytes(b"\xff\xfe\xfd\xfc\x80\x81\x82")
    (root / ".hidden").write_text("ignored", encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_import_folder_mirrors_directory_layout(
    toolkit: PageIndexToolkit, sample_folder: Path,
):
    await toolkit.create_tree("kb")
    result = await toolkit.import_folder("kb", str(sample_folder))

    assert len(result["imported"]) == 2  # a.md and sub/b.md
    assert any("img.bin" in p for p in result["skipped"])

    tree = await toolkit.get_tree("kb")

    titles_root = [n["title"] for n in tree["structure"]]
    assert "sub" in titles_root

    sub_node = next(n for n in tree["structure"] if n["title"] == "sub")
    sub_children_titles = [c["title"] for c in sub_node.get("nodes", [])]
    assert any("Doc" in t for t in sub_children_titles)


@pytest.mark.asyncio
async def test_import_folder_persists_once(
    toolkit: PageIndexToolkit, sample_folder: Path, tmp_path: Path,
):
    await toolkit.create_tree("kb")
    await toolkit.import_folder("kb", str(sample_folder))
    # tree file should exist after the import
    assert (tmp_path / "store" / "kb.json").is_file()


@pytest.mark.asyncio
async def test_import_folder_skips_hidden_files(
    toolkit: PageIndexToolkit, sample_folder: Path,
):
    await toolkit.create_tree("kb")
    result = await toolkit.import_folder("kb", str(sample_folder))
    assert not any(".hidden" in p for p in result["imported"])


@pytest.mark.asyncio
async def test_import_folder_rejects_non_directory(
    toolkit: PageIndexToolkit, tmp_path: Path,
):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x")
    await toolkit.create_tree("kb")
    with pytest.raises(NotADirectoryError):
        await toolkit.import_folder("kb", str(f))
