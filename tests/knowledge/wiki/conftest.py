"""Shared pytest fixtures for the wiki test suite (FEAT-260).

Provides reusable fixtures for:
- ``wiki_config`` — a :class:`WikiConfig` backed by ``tmp_path``
- ``sample_source`` / ``sample_sources`` — markdown files in a temp dir
- ``mock_pi`` / ``mock_gi`` / ``mock_okf`` — mocked toolkits for use in
  unit and integration tests that must not make real LLM API calls
- ``sample_pdf`` / ``undecodable_file`` / ``mixed_corpus`` /
  ``mock_aiohttp_pdf`` — FEAT-451 document-acquisition fixtures, shared
  by the loader-backed ingest unit and integration tests
"""

import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``arangodb`` marker (FEAT-400, TASK-2063).

    Real-ArangoDB integration tests are opt-in via ``TEST_ARANGODB_HOST``
    — the marker just documents/groups them (e.g. ``-m "not arangodb"``),
    the actual skip is a ``pytest.mark.skipif`` in the test module itself.
    """
    config.addinivalue_line(
        "markers",
        "arangodb: integration tests requiring a real ArangoDB instance "
        "(set TEST_ARANGODB_HOST to enable; skipped otherwise)",
    )


@pytest.fixture(autouse=True)
def isolated_parrot_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``PARROT_HOME`` at a temp dir for every wiki test (FEAT-450).

    The global namespace registry lives at ``PARROT_HOME/wikis.json``.
    Without this, a developer's real ``~/.parrot/wikis.json`` would
    federate their own namespaces into the test suite's queries.

    Returns:
        The isolated parrot home (usually empty).
    """
    home = tmp_path_factory.mktemp("parrot-home")
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


@pytest.fixture
def wiki_config(tmp_path: Path) -> WikiConfig:
    """WikiConfig pointing to an isolated tmp_path storage directory.

    Args:
        tmp_path: Pytest-provided temporary directory (unique per test).

    Returns:
        :class:`WikiConfig` for a wiki named ``"test-wiki"``.
    """
    return WikiConfig(
        wiki_name="test-wiki",
        storage_dir=tmp_path / "wiki-storage",
    )


@pytest.fixture
def sample_source(tmp_path: Path) -> Path:
    """Single markdown source file.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        Path to a file with representative neural-network content.
    """
    src = tmp_path / "sources" / "article.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        "# Neural Networks\n\n"
        "A neural network is a computational model inspired by the structure "
        "of the human brain.  It consists of layers of interconnected nodes "
        "that process information and learn from data.\n"
    )
    return src


@pytest.fixture
def sample_sources(tmp_path: Path) -> Path:
    """Two markdown source files for combined-search integration tests.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        Path to the directory containing ``article1.md`` and ``article2.md``.
    """
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / "article1.md").write_text(
        "# Neural Networks\n\n" "A neural network is a computational model inspired by the human brain."
    )
    (sources_dir / "article2.md").write_text(
        "# Deep Learning\n\n"
        "Deep learning extends neural networks with many hidden layers, enabling "
        "powerful representations of complex patterns in data."
    )
    return sources_dir


@pytest.fixture
def mock_pi():
    """Mock ``PageIndexToolkit`` that never calls a real LLM.

    Returns:
        MagicMock configured with async methods for the toolkit interface.
    """
    pi = MagicMock()
    pi.search = AsyncMock(
        return_value=[
            {"node_id": "n1", "title": "Neural Networks", "score": 0.9, "summary": "A neural network is..."},
            {"node_id": "n2", "title": "Deep Learning", "score": 0.7, "summary": "Deep learning extends..."},
        ]
    )
    # Real PageIndexToolkit contract: insert_markdown returns
    # {"tree_name", "new_node_ids"}; insert_content adds "title"/"summary".
    pi.insert_markdown = AsyncMock(return_value={"tree_name": "test-wiki", "new_node_ids": ["m1"]})
    pi.insert_content = AsyncMock(
        return_value={
            "tree_name": "test-wiki",
            "new_node_ids": ["n1", "n2", "n3"],
            "title": "Neural Networks",
            "summary": "A neural network is a computational model.",
        }
    )
    pi.create_tree = AsyncMock(return_value={"tree_name": "test-wiki"})
    pi.delete_tree = AsyncMock(return_value={"status": "deleted"})
    return pi


@pytest.fixture
def mock_gi():
    """Mock ``GraphIndexToolkit`` that never calls a real graph database.

    Returns:
        MagicMock configured with async methods for the toolkit interface.
    """
    gi = MagicMock()
    gi.search_hybrid = AsyncMock(
        return_value=[
            {"node_id": "g1", "title": "Graph: Neural Networks", "score": 0.85, "summary": "Graph node..."},
        ]
    )
    gi.create_node = AsyncMock(return_value={"node_id": "wp-001", "status": "created"})
    gi.link_nodes = AsyncMock(return_value={"status": "ok"})
    gi.get_neighborhood = AsyncMock(return_value={"neighbours": []})
    return gi


@pytest.fixture
def mock_okf():
    """Mock ``OKFToolkit`` that returns a clean lint report.

    Returns:
        MagicMock configured with async methods for the OKFToolkit interface.
    """
    okf = MagicMock()
    okf.lint_knowledge_base = AsyncMock(
        return_value={
            "orphan_nodes": 0,
            "missing_types": [],
            "stale_days": 90,
        }
    )
    return okf


@pytest.fixture
def wiki_toolkit(
    wiki_config: WikiConfig,
    mock_pi,
    mock_gi,
    mock_okf,
) -> LLMWikiToolkit:
    """Fully wired ``LLMWikiToolkit`` with all mocked dependencies.

    Args:
        wiki_config: Per-test wiki configuration.
        mock_pi: Mocked PageIndexToolkit.
        mock_gi: Mocked GraphIndexToolkit.
        mock_okf: Mocked OKFToolkit.

    Returns:
        :class:`LLMWikiToolkit` ready for integration tests.
    """
    return LLMWikiToolkit(mock_pi, mock_gi, mock_okf, wiki_config)


@pytest.fixture
def arango_params() -> dict[str, Any]:
    """ArangoDB connection params for a real test instance.

    Read from ``TEST_ARANGODB_*`` env vars (never ``ARANGODB_*`` —
    keeps integration-test credentials separate from any real
    ``.env``-configured wiki), falling back to the local-dev defaults.
    """
    return {
        "host": os.environ.get("TEST_ARANGODB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("TEST_ARANGODB_PORT", "8529")),
        "username": os.environ.get("TEST_ARANGODB_USERNAME", "root"),
        "password": os.environ.get("TEST_ARANGODB_PASSWORD", ""),
    }


@pytest.fixture
async def arango_test_db(arango_params: dict[str, Any]):
    """Initialized ``ArangoDBWikiStore`` against a fresh, disposable database.

    Args:
        arango_params: Connection params (see :func:`arango_params`).

    Yields:
        A connected :class:`ArangoDBWikiStore` for a uniquely-named
        ``test_wiki_<hex>`` database, dropped again on teardown.
    """
    from asyncdb import AsyncDB

    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

    db_name = f"test_wiki_{uuid.uuid4().hex[:8]}"
    store = ArangoDBWikiStore(arango_params, database=db_name, wiki_name="integration_test")
    await store.initialize()
    try:
        yield store
    finally:
        await store.close()
        admin_db = AsyncDB("arangodb", params={**arango_params, "database": "_system"})
        await admin_db.connection()
        try:
            await admin_db.drop_database(db_name)
        finally:
            await admin_db.close()


# ---------------------------------------------------------------------------
# FEAT-451: document-acquisition fixtures (loader-backed `ingest`).
#
# No binary fixture is ever committed to the repo — PDFs are built at
# runtime with ``pymupdf`` (already a core dep, precedent:
# ``pageindex/pdf_to_markdown.py``), DOCX with ``python-docx`` (an
# ``ai-parrot-loaders`` extra — guarded with ``pytest.importorskip`` so
# the suite still collects cleanly without it installed).
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A small 2-page PDF with Author/Title set, written via pymupdf.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        Path to the generated PDF.
    """
    import pymupdf

    doc = pymupdf.open()
    try:
        for text in ("Page one body text.", "Page two body text."):
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.set_metadata({"author": "Legal Dept", "title": "Contrato Marco 2026"})
        path = tmp_path / "contrato.pdf"
        doc.save(str(path))
    finally:
        doc.close()
    return path


@pytest.fixture
def undecodable_file(tmp_path: Path) -> Path:
    """Random bytes with a ``.pdf`` suffix — must be skipped, never triaged.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        Path to a file that is not valid PDF content.
    """
    path = tmp_path / "bad.pdf"
    path.write_bytes(os.urandom(256))
    return path


@pytest.fixture
def mixed_corpus(tmp_path: Path, sample_pdf: Path, undecodable_file: Path) -> Path:
    """A folder with ``.md`` (with and without frontmatter), ``.pdf``,
    ``.docx``, and one undecodable file — the full skip-and-report
    surface in one corpus.

    Args:
        tmp_path: Pytest-provided temporary directory.
        sample_pdf: FEAT-451 PDF fixture (copied in by content).
        undecodable_file: FEAT-451 undecodable-file fixture (copied in
            by content).

    Returns:
        Path to the mixed corpus directory.
    """
    docx = pytest.importorskip("docx", reason="python-docx not installed")

    folder = tmp_path / "mixed_corpus"
    folder.mkdir()
    (folder / "plain.md").write_text(
        "# Plain\n\nA plain markdown source, no frontmatter.",
        encoding="utf-8",
    )
    (folder / "with_frontmatter.md").write_text(
        "---\ntitle: Contrato\nauthor: Legal\n---\n" "# Body\n\nMarkdown content with leading YAML frontmatter.",
        encoding="utf-8",
    )
    (folder / "contrato.pdf").write_bytes(sample_pdf.read_bytes())

    document = docx.Document()
    document.add_heading("DOCX Source", level=1)
    document.add_paragraph("A DOCX document with a durable decision.")
    document.save(str(folder / "decision.docx"))

    (folder / "bad.pdf").write_bytes(undecodable_file.read_bytes())
    return folder


class _FakeAiohttpContentStream:
    """Async ``resp.content.iter_chunked()`` double (FEAT-451)."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _FakeAiohttpResponse:
    """Async-context-manager ``aiohttp`` response double (FEAT-451)."""

    def __init__(self, *, status: int, headers: dict, chunks: list[bytes], url: str) -> None:
        self.status = status
        self.headers = headers
        self.content = _FakeAiohttpContentStream(chunks)
        self.url = url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeAiohttpGetContextManager:
    def __init__(self, response: _FakeAiohttpResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class _FakeAiohttpSession:
    def __init__(self, response: _FakeAiohttpResponse) -> None:
        self._response = response

    def get(self, _url: str, **_kwargs: Any):
        return _FakeAiohttpGetContextManager(self._response)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def mock_aiohttp_pdf(monkeypatch: pytest.MonkeyPatch, sample_pdf: Path):
    """Mock an aiohttp fetch that streams back ``sample_pdf``'s real bytes
    with ``Content-Type: application/pdf`` (also used by TASK-2354).

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        sample_pdf: FEAT-451 PDF fixture — its bytes are the mocked body.
    """
    body = sample_pdf.read_bytes()
    response = _FakeAiohttpResponse(
        status=200,
        headers={"Content-Type": "application/pdf"},
        chunks=[body],
        url="https://example.test/doc.pdf",
    )
    session = _FakeAiohttpSession(response)
    monkeypatch.setattr(
        "parrot.knowledge.wiki.documents.aiohttp.ClientSession",
        lambda **kwargs: session,
    )
