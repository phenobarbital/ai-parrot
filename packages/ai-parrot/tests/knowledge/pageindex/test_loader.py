"""Unit tests for parrot.knowledge.pageindex.loader.PageIndexLoader.

The toolkit (and its LLM adapter) are replaced with an in-memory fake so the
loader's orchestration — tree creation, per-file import dispatch, and the
tree → Document projection — is exercised without any real LLM calls.
"""
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.pageindex.loader import PageIndexLoader
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


class _FakeToolkit:
    """Minimal stand-in for PageIndexToolkit recording imports."""

    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.imported: list[str] = []
        self.pdf_imported: list[str] = []
        self._existing: list[str] = []
        self._tree = {
            "doc_name": "doc",
            "structure": [
                {
                    "node_id": "0000",
                    "title": "Root",
                    "summary": "root summary",
                    "nodes": [
                        {
                            "node_id": "0001",
                            "title": "Child",
                            "summary": "child summary",
                            "nodes": [],
                        }
                    ],
                }
            ],
        }

    async def list_trees(self) -> list[str]:
        return list(self._existing)

    async def create_tree(self, tree_name: str, doc_name=None) -> dict:
        self.created.append(tree_name)
        self._existing.append(tree_name)
        return {"tree_name": tree_name}

    async def delete_tree(self, tree_name: str) -> dict:
        self.deleted.append(tree_name)
        if tree_name in self._existing:
            self._existing.remove(tree_name)
        return {"tree_name": tree_name}

    async def import_file(self, tree_name, file_path, **kwargs) -> dict:
        self.imported.append(str(file_path))
        return {"new_node_ids": ["0000", "0001"]}

    async def import_pdf(self, tree_name, pdf_path, **kwargs) -> dict:
        self.pdf_imported.append(str(pdf_path))
        return {"new_node_ids": ["0000", "0001"]}

    async def get_tree(self, tree_name) -> dict:
        return self._tree


def _make_loader(tmp_path, **kwargs) -> PageIndexLoader:
    loader = PageIndexLoader(
        storage_dir=tmp_path,
        adapter=MagicMock(),
        **kwargs,
    )
    loader.toolkit = _FakeToolkit()
    # Sidecars are empty in the fake → content falls back to node summary.
    loader._content_store = MagicMock()
    loader._content_store.load.return_value = None
    return loader


class TestConstruction:
    def test_is_abstract_loader_subclass(self):
        assert issubclass(PageIndexLoader, AbstractLoader)

    def test_storage_dir_required(self):
        with pytest.raises(ValueError, match="storage_dir"):
            PageIndexLoader(adapter=MagicMock())


class TestLoad:
    @pytest.mark.asyncio
    async def test_load_returns_document_per_node(self, tmp_path):
        loader = _make_loader(tmp_path)
        (tmp_path / "a.md").write_text("# hello", encoding="utf-8")

        docs = await loader.load([tmp_path / "a.md"])

        assert len(docs) == 2  # root + child
        assert all(isinstance(d, Document) for d in docs)
        node_ids = {d.metadata["node_id"] for d in docs}
        assert node_ids == {"0000", "0001"}

    @pytest.mark.asyncio
    async def test_load_uses_summary_when_no_sidecar(self, tmp_path):
        loader = _make_loader(tmp_path)
        (tmp_path / "a.md").write_text("# hello", encoding="utf-8")

        docs = await loader.load([tmp_path / "a.md"])

        by_id = {d.metadata["node_id"]: d for d in docs}
        assert by_id["0000"].page_content == "root summary"
        assert by_id["0001"].page_content == "child summary"

    @pytest.mark.asyncio
    async def test_child_metadata_records_parent(self, tmp_path):
        loader = _make_loader(tmp_path)
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        docs = await loader.load([tmp_path / "a.md"])
        child = next(d for d in docs if d.metadata["node_id"] == "0001")
        assert child.metadata["parent_id"] == "0000"
        assert child.metadata["tree_name"] == loader.tree_name

    @pytest.mark.asyncio
    async def test_pdf_routes_to_import_pdf(self, tmp_path):
        loader = _make_loader(tmp_path)
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        await loader.load([pdf])

        assert loader.toolkit.pdf_imported == [str(pdf)]
        assert loader.toolkit.imported == []

    @pytest.mark.asyncio
    async def test_reset_tree_deletes_existing(self, tmp_path):
        loader = _make_loader(tmp_path)
        loader.toolkit._existing = [loader.tree_name]
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        await loader.load([tmp_path / "a.md"])

        assert loader.tree_name in loader.toolkit.deleted

    @pytest.mark.asyncio
    async def test_build_tree_returns_native_tree(self, tmp_path):
        loader = _make_loader(tmp_path)
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        tree = await loader.build_tree([tmp_path / "a.md"])

        assert tree["doc_name"] == "doc"
        assert tree["structure"][0]["node_id"] == "0000"
        assert loader.tree is tree
