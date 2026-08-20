"""Unit tests for `AcademicResearchToolkit.search_pubmed` (FEAT-426 TASK-2239).

`biopython` is not installed in the base test environment (spec goal
G6 — fixtures only, no live network in CI), so these tests exercise
`AcademicResearchToolkit` against a fake `Bio.Entrez` module patched onto
`parrot_tools.research.academic.Entrez`.
"""
import pytest
from parrot_tools.research import academic as academic_module
from parrot_tools.research.academic import AcademicResearchToolkit


class _AttrStr(str):
    """Mimics Biopython's `StringElement` — a str subclass carrying XML
    attributes (e.g. `ArticleId.attributes["IdType"]`)."""

    def __new__(cls, value, **attrs):
        obj = super().__new__(cls, value)
        obj.attributes = attrs
        return obj


class _FakeHandle:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_fake_entrez(esearch_result: dict, efetch_result: dict):
    """Build a fake `Bio.Entrez` module recording call order."""
    call_order: list = []

    class _FakeEntrez:
        email = None
        api_key = None
        tool = None

        @staticmethod
        def esearch(db=None, term=None, retmax=None, **kwargs):
            call_order.append("esearch")
            return _FakeHandle(esearch_result)

        @staticmethod
        def efetch(db=None, id=None, retmode=None, **kwargs):
            call_order.append("efetch")
            return _FakeHandle(efetch_result)

        @staticmethod
        def read(handle):
            return handle.payload

    return _FakeEntrez, call_order


def _default_record():
    return {
        "MedlineCitation": {
            "PMID": "12345678",
            "Article": {
                "ArticleTitle": "CRISPR-based gene editing advances in 2024",
                "Abstract": {
                    "AbstractText": [
                        "Gene editing has advanced rapidly.",
                        "We demonstrate a novel CRISPR variant.",
                    ]
                },
                "Journal": {"Title": "Nature Genetics"},
                "AuthorList": [
                    {"ForeName": "Jane", "LastName": "Doe"},
                    {"ForeName": "John", "LastName": "Smith"},
                ],
            },
        },
        "PubmedData": {
            "ArticleIdList": [
                _AttrStr("12345678", IdType="pubmed"),
                _AttrStr("10.1038/s41588-024-01234-5", IdType="doi"),
            ]
        },
    }


@pytest.fixture
def mock_entrez(monkeypatch):
    fake_cls, call_order = _make_fake_entrez(
        esearch_result={"IdList": ["12345678"]},
        efetch_result={"PubmedArticle": [_default_record()]},
    )
    fake_cls._call_order = call_order
    monkeypatch.setattr(academic_module, "Entrez", fake_cls)
    return fake_cls


@pytest.fixture
def call_order(mock_entrez):
    return mock_entrez._call_order


@pytest.fixture
def mock_entrez_empty(monkeypatch):
    fake_cls, call_order = _make_fake_entrez(
        esearch_result={"IdList": []},
        efetch_result={"PubmedArticle": []},
    )
    fake_cls._call_order = call_order
    monkeypatch.setattr(academic_module, "Entrez", fake_cls)
    return fake_cls


@pytest.fixture
def mock_entrez_multipart(monkeypatch):
    fake_cls, call_order = _make_fake_entrez(
        esearch_result={"IdList": ["999"]},
        efetch_result={"PubmedArticle": [_default_record()]},
    )
    fake_cls._call_order = call_order
    monkeypatch.setattr(academic_module, "Entrez", fake_cls)
    return fake_cls


class TestPubMed:
    async def test_two_step_workflow(self, mock_entrez, call_order):
        await AcademicResearchToolkit().search_pubmed("crispr")
        assert call_order == ["esearch", "efetch"]

    async def test_sets_email(self, mock_entrez):
        await AcademicResearchToolkit().search_pubmed("crispr")
        assert mock_entrez.email

    async def test_maps_papers(self, mock_entrez):
        r = await AcademicResearchToolkit().search_pubmed("crispr")
        assert r.status == "success" and r.result_type == "papers"
        p = r.papers[0]
        assert p.source == "pubmed" and p.title and p.url.startswith("https://pubmed")

    async def test_empty_idlist_skips_efetch(self, mock_entrez_empty):
        r = await AcademicResearchToolkit().search_pubmed("zzzz")
        assert r.status == "no_data" and "efetch" not in mock_entrez_empty._call_order

    async def test_multipart_abstract_joined(self, mock_entrez_multipart):
        r = await AcademicResearchToolkit().search_pubmed("x")
        assert isinstance(r.papers[0].abstract, str)

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(academic_module, "Entrez", None)
        r = await AcademicResearchToolkit().search_pubmed("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message
