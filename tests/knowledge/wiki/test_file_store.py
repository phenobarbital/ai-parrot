"""Backend-specific tests for InMemoryWikiStore (OKF file directory).

The generic behavioural contract is covered by the parametrized suite
in ``test_store.py``; this file pins what is unique to the file
backend: durability across instances, OKF-conformance of the on-disk
bundle, frontmatter edge round-trips, and the factory/config wiring.
"""

import json
from pathlib import Path

import pytest
import yaml

from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.store import (
    SQLiteWikiStore,
    WikiPageRecord,
    create_wiki_store,
)


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    return tmp_path / "pages"


def _page(cid: str, **kw) -> WikiPageRecord:
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.title()),
        "category": kw.pop("category", "summary"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


def _read_front(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"no frontmatter in {path}"
    _, front_raw, body = text.split("---\n", 2)
    return yaml.safe_load(front_raw), body


class TestFactory:
    def test_sqlite_backend(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, backend="sqlite")
        assert isinstance(store, SQLiteWikiStore)

    def test_memory_backend(self, tmp_path: Path):
        store = create_wiki_store(tmp_path, backend="memory")
        assert isinstance(store, InMemoryWikiStore)
        assert store.bundle_dir == tmp_path / "pages"

    def test_unknown_backend_is_hard_error(self, tmp_path: Path):
        with pytest.raises(ValueError, match="Unknown wiki storage backend"):
            create_wiki_store(tmp_path, backend="magnetic-tape")

    def test_config_rejects_unknown_backend(self, tmp_path: Path):
        with pytest.raises(Exception):
            WikiConfig(
                wiki_name="w", storage_dir=tmp_path, storage_backend="nope"
            )


class TestBundleOnDisk:
    """The storage directory must be a valid OKF bundle at all times."""

    @pytest.mark.asyncio
    async def test_page_file_layout_and_frontmatter(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages(
            [_page("neural-networks", category="summary", node_id="0001",
                   source_id="src-1")]
        )
        path = bundle_dir / "summaries" / "neural-networks.md"
        assert path.exists()
        front, body = _read_front(path)
        # OKF v0.1 required field + queryable fields
        assert front["type"] == "Wiki Summary"
        assert front["id"] == "neural-networks"
        assert front["title"] == "Neural-Networks"
        # machine fields ride along (OKF tolerates unknown keys)
        assert front["node_id"] == "0001"
        assert front["source_id"] == "src-1"
        assert front["token_count"] > 0
        assert "Body of neural-networks." in body

    @pytest.mark.asyncio
    async def test_index_md_regenerated(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="my-wiki")
        await store.upsert_pages([_page("a"), _page("b")])
        index = (bundle_dir / "index.md").read_text(encoding="utf-8")
        assert index.startswith("# my-wiki")
        assert "summaries/a.md" in index and "summaries/b.md" in index
        await store.delete_page("b")
        index = (bundle_dir / "index.md").read_text(encoding="utf-8")
        assert "summaries/b.md" not in index

    @pytest.mark.asyncio
    async def test_edges_round_trip_via_relates_to(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages([_page("a"), _page("b")])
        await store.add_edges([("a", "b", "references")])
        front, _ = _read_front(bundle_dir / "summaries" / "a.md")
        assert front["relates_to"] == [{"concept": "b", "rel": "references"}]

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages([_page("a")])
        path = bundle_dir / "summaries" / "a.md"
        assert path.exists()
        await store.delete_page("a")
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_category_change_moves_file(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages([_page("a", category="summary")])
        await store.upsert_pages([_page("a", category="entity")])
        assert not (bundle_dir / "summaries" / "a.md").exists()
        assert (bundle_dir / "entities" / "a.md").exists()

    @pytest.mark.asyncio
    async def test_slash_concept_id_flattened(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages([_page("guides/getting-started")])
        assert (bundle_dir / "summaries" / "guides--getting-started.md").exists()


class TestPersistenceAcrossInstances:
    """A brand-new instance must rebuild all indexes from the bundle."""

    @pytest.mark.asyncio
    async def test_pages_edges_survive_reload(self, bundle_dir: Path):
        first = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await first.upsert_pages(
            [
                _page("nn", title="Neural Networks",
                      body="A neural network is a computational model."),
                _page("dl", title="Deep Learning", category="entity"),
            ]
        )
        await first.add_edges([("dl", "nn", "references")])
        await first.upsert_embedding("nn", [1.0, 0.0], model="m")

        second = InMemoryWikiStore(bundle_dir, wiki_name="w")
        page = await second.get_page("nn")
        assert page is not None
        assert page["body"].startswith("A neural network")
        assert page["category"] == "summary"
        hits = await second.search_fts("neural computational")
        assert hits and hits[0]["concept_id"] == "nn"
        out = await second.neighbors("dl", direction="out")
        assert [n["concept_id"] for n in out] == ["nn"]
        inbound = await second.neighbors("nn", direction="in")
        assert [n["concept_id"] for n in inbound] == ["dl"]
        vec_hits = await second.search_vector([1.0, 0.0])
        assert vec_hits and vec_hits[0]["concept_id"] == "nn"

    @pytest.mark.asyncio
    async def test_open_string_category_survives_reload(self, bundle_dir: Path):
        """Categories outside the OKF WIKI_* vocabulary (e.g. 'answer')
        must load back intact — no closed-enum crash."""
        first = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await first.upsert_pages([_page("q1", category="answer")])
        second = InMemoryWikiStore(bundle_dir, wiki_name="w")
        page = await second.get_page("q1")
        assert page is not None and page["category"] == "answer"

    @pytest.mark.asyncio
    async def test_unparseable_file_skipped(self, bundle_dir: Path):
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "garbage.md").write_text("no frontmatter here")
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        assert (await store.stats())["pages"] == 0

    @pytest.mark.asyncio
    async def test_embeddings_sidecar_is_json(self, bundle_dir: Path):
        store = InMemoryWikiStore(bundle_dir, wiki_name="w")
        await store.upsert_pages([_page("a")])
        await store.upsert_embedding("a", [0.5, 0.5], model="mini")
        raw = json.loads(
            (bundle_dir / ".embeddings.json").read_text(encoding="utf-8")
        )
        assert raw["a"]["model"] == "mini"


class TestToolkitMemoryBackend:
    """LLMWikiToolkit on storage_backend='memory' — no wiki.db anywhere."""

    @pytest.fixture
    def mem_toolkit(self, tmp_path, mock_pi, mock_gi, mock_okf):
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path / "wiki-storage",
            storage_backend="memory",
        )
        return LLMWikiToolkit(mock_pi, mock_gi, mock_okf, config)

    @pytest.mark.asyncio
    async def test_full_cycle_without_sqlite(self, mem_toolkit, tmp_path):
        storage = tmp_path / "wiki-storage"
        await mem_toolkit.create_wiki("test-wiki")

        created = await mem_toolkit.create_page(
            "test-wiki", "Neural Networks",
            "A neural network is a computational model.",
            category="summary",
        )
        assert created["status"] == "created"

        results = await mem_toolkit.search("test-wiki", "neural network")
        assert results and results[0]["source"] == "lexical"

        page = await mem_toolkit.read_page("test-wiki", created["page_id"])
        assert "computational model" in page["content"]

        lint = await mem_toolkit.lint("test-wiki")
        assert "orphan_sources" in lint

        out = tmp_path / "okf-out"
        export = await mem_toolkit.export_okf("test-wiki", str(out))
        assert export["files_written"] == 1

        deleted = await mem_toolkit.delete_page(
            "test-wiki", created["page_id"]
        )
        assert deleted["status"] == "deleted"

        # The whole cycle ran without creating any SQLite database.
        assert not list(storage.rglob("*.db"))
        # Sources registry is the JSON manifest.
        assert mem_toolkit._sources.backend == "json"  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_ingest_source_memory_backend(
        self, mem_toolkit, tmp_path, sample_source
    ):
        report = await mem_toolkit.ingest_source(
            "test-wiki", str(sample_source)
        )
        assert report["status"] == "ok"
        assert report["pages_created"] == 3
        # manifest file exists, wiki.db does not
        assert (
            tmp_path / "wiki-storage" / "sources" / ".manifest.json"
        ).exists()
        assert not (tmp_path / "wiki-storage" / "wiki.db").exists()
