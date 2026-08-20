"""Unit tests for `AcademicResearchToolkit.get_paper_details` (FEAT-426 TASK-2241).

Reuses the fake-library patterns from the sibling test modules
(`test_academic_crossref.py`, `test_academic_pubmed.py`,
`test_academic_arxiv.py`, `test_academic_s2.py`) — no live network calls.
"""
import types

import pytest
from parrot_tools.research import academic as academic_module
from parrot_tools.research.academic import _S2_PAPER_URL, AcademicResearchToolkit


def _make_fake_crossref(payload: dict):
    class _FakeCrossref:
        def __init__(self, mailto=None, **kwargs):
            self.mailto = mailto

        def works(self, ids=None, **kwargs):
            return payload

    return _FakeCrossref


@pytest.fixture
def mock_habanero(monkeypatch):
    payload = {
        "message": {
            "DOI": "10.1093/nar/gkaa1100",
            "title": ["A Study of Nucleic Acid Research"],
            "author": [{"given": "Jane", "family": "Doe"}],
            "container-title": ["Nucleic Acids Research"],
            "issued": {"date-parts": [[2020]]},
            "URL": "https://doi.org/10.1093/nar/gkaa1100",
        }
    }
    monkeypatch.setattr(
        academic_module, "Crossref", _make_fake_crossref(payload)
    )
    return payload


@pytest.fixture
def mock_habanero_empty(monkeypatch):
    monkeypatch.setattr(
        academic_module, "Crossref", _make_fake_crossref({"message": {}})
    )


@pytest.fixture
def mock_all_sources(monkeypatch):
    """Patch Crossref, Entrez, arxiv, and `_make_api_request` all at once,
    each recording into a shared `call_log` when invoked."""
    call_log: list = []

    class _FakeCrossref:
        def __init__(self, mailto=None, **kwargs):
            pass

        def works(self, ids=None, **kwargs):
            call_log.append("crossref")
            return {"message": {"DOI": ids, "title": ["X"], "source": "crossref"}}

    class _FakeHandle:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeEntrez:
        email = None
        api_key = None
        tool = None

        @staticmethod
        def esearch(**kwargs):
            return _FakeHandle({"IdList": []})

        @staticmethod
        def efetch(db=None, id=None, retmode=None, **kwargs):
            call_log.append("pubmed")
            return _FakeHandle({
                "PubmedArticle": [{
                    "MedlineCitation": {
                        "PMID": id, "Article": {"ArticleTitle": "X"},
                    },
                    "PubmedData": {"ArticleIdList": []},
                }]
            })

        @staticmethod
        def read(handle):
            return handle.payload

    class _FakeArxivResult:
        def __init__(self):
            self.title = "X"
            self.authors = []
            self.published = None
            self.pdf_url = "https://arxiv.org/pdf/2103.14030"
            self.entry_id = "http://arxiv.org/abs/2103.14030"
            self.categories = []
            self.summary = ""

    class _FakeArxivSearch:
        def __init__(self, id_list=None, **kwargs):
            self.id_list = id_list

    class _FakeArxivClient:
        def results(self, search):
            call_log.append("arxiv")
            return [_FakeArxivResult()]

    fake_arxiv = types.SimpleNamespace(
        Search=_FakeArxivSearch, Client=_FakeArxivClient,
    )

    async def _fake_request(self, url, params=None, headers=None):
        call_log.append("semantic_scholar")
        return {"paperId": "649def34f8be52c8b66281af98ae884c09aef38b", "title": "X"}, None

    monkeypatch.setattr(academic_module, "Crossref", _FakeCrossref)
    monkeypatch.setattr(academic_module, "Entrez", _FakeEntrez)
    monkeypatch.setattr(academic_module, "arxiv", fake_arxiv)
    monkeypatch.setattr(
        academic_module.AcademicResearchToolkit, "_make_api_request", _fake_request
    )
    return call_log


@pytest.fixture
def call_log(mock_all_sources):
    return mock_all_sources


class TestGetPaperDetails:
    @pytest.mark.parametrize("ident,expected", [
        ("10.1093/nar/gkaa1100", "crossref"),
        ("33095870", "pubmed"),
        ("2103.14030", "arxiv"),
        ("649def34f8be52c8b66281af98ae884c09aef38b", "semantic_scholar"),
    ])
    def test_detects_source(self, ident, expected):
        assert AcademicResearchToolkit()._detect_source(ident) == expected

    def test_accepts_prefixed_ids(self):
        tk = AcademicResearchToolkit()
        assert tk._detect_source("DOI:10.1093/nar/gkaa1100") == "crossref"
        assert tk._detect_source("PMID:33095870") == "pubmed"

    async def test_returns_single_paper(self, mock_habanero):
        r = await AcademicResearchToolkit().get_paper_details(
            "10.1093/nar/gkaa1100"
        )
        assert r.result_type == "papers" and len(r.papers) == 1
        assert r.citation.doi == "10.1093/nar/gkaa1100"

    async def test_explicit_source_overrides(self, mock_all_sources, call_log):
        await AcademicResearchToolkit().get_paper_details(
            "2103.14030", source="semantic_scholar"
        )
        assert call_log[-1] == "semantic_scholar"

    async def test_invalid_source_is_error(self):
        r = await AcademicResearchToolkit().get_paper_details(
            "10.1/x", source="bogus"
        )
        assert r.status == "error" and "bogus" in r.error_message

    async def test_unrecognised_id_is_error(self):
        r = await AcademicResearchToolkit().get_paper_details("!!!")
        assert r.status == "error"

    async def test_not_found_is_no_data(self, mock_habanero_empty):
        r = await AcademicResearchToolkit().get_paper_details("10.9999/nope")
        assert r.status == "no_data"

    async def test_s2_paper_lookup_url(self, monkeypatch):
        captured = {}

        async def _fake_request(self, url, params=None, headers=None):
            captured["url"] = url
            return {"paperId": "649def34f8be52c8b66281af98ae884c09aef38b", "title": "X"}, None

        monkeypatch.setattr(
            academic_module.AcademicResearchToolkit, "_make_api_request", _fake_request
        )
        await AcademicResearchToolkit().get_paper_details(
            "649def34f8be52c8b66281af98ae884c09aef38b"
        )
        assert captured["url"] == f"{_S2_PAPER_URL}649def34f8be52c8b66281af98ae884c09aef38b"
