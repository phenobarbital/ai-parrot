"""Unit tests for `AcademicResearchToolkit.search_crossref` (FEAT-426 TASK-2238).

`habanero` is not installed in the base test environment (spec goal G6 —
fixtures only, no live network in CI), so these tests exercise
`AcademicResearchToolkit` against a fake `Crossref` class patched onto
`parrot_tools.research.academic.Crossref`.
"""
import pytest
from parrot_tools.research import academic as academic_module
from parrot_tools.research.academic import AcademicResearchToolkit


def _make_fake_crossref(payload: dict):
    """Build a fake `habanero.Crossref` plus the list of constructed instances."""
    created: list = []

    class _FakeCrossref:
        def __init__(self, mailto=None, **kwargs):
            self.mailto = mailto
            self.init_kwargs = kwargs
            self.kwargs = None
            created.append(self)

        def works(self, **kwargs):
            self.kwargs = kwargs
            return payload

    return _FakeCrossref, created


@pytest.fixture
def mock_habanero(monkeypatch, load_fixture):
    payload = load_fixture("crossref_works.json")
    fake_cls, created = _make_fake_crossref(payload)
    monkeypatch.setattr(academic_module, "Crossref", fake_cls)
    return created


@pytest.fixture
def capture_crossref_kwargs(monkeypatch):
    fake_cls, created = _make_fake_crossref({"message": {"items": []}})
    monkeypatch.setattr(academic_module, "Crossref", fake_cls)

    class _Proxy:
        def __getitem__(self, key):
            if not created:
                raise KeyError(key)
            return getattr(created[-1], key, None)

    return _Proxy()


@pytest.fixture
def capture_crossref_call(monkeypatch):
    fake_cls, created = _make_fake_crossref({"message": {"items": []}})
    monkeypatch.setattr(academic_module, "Crossref", fake_cls)

    class _Proxy:
        @property
        def kwargs(self):
            return created[-1].kwargs if created else {}

    return _Proxy()


@pytest.fixture
def mock_habanero_empty_title(monkeypatch):
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/empty", "title": [], "author": [],
                    "container-title": [], "issued": {},
                }
            ]
        }
    }
    fake_cls, created = _make_fake_crossref(payload)
    monkeypatch.setattr(academic_module, "Crossref", fake_cls)
    return created


class TestCrossref:
    async def test_search_maps_papers(self, mock_habanero):
        r = await AcademicResearchToolkit().search_crossref(
            "transformer time series"
        )
        assert r.status == "success" and r.result_type == "papers"
        assert r.papers and r.papers[0].source == "crossref"
        assert r.papers[0].doi and r.papers[0].title
        assert r.citation.source_name == "Crossref"

    async def test_uses_polite_pool(self, capture_crossref_kwargs):
        await AcademicResearchToolkit().search_crossref("x")
        assert capture_crossref_kwargs["mailto"]

    async def test_uses_bibliographic_query(self, capture_crossref_call):
        await AcademicResearchToolkit().search_crossref("x")
        assert "query_bibliographic" in capture_crossref_call.kwargs

    async def test_empty_title_list_does_not_raise(self, mock_habanero_empty_title):
        r = await AcademicResearchToolkit().search_crossref("x")
        assert r.status in {"success", "no_data"}

    async def test_missing_library_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(academic_module, "Crossref", None)
        r = await AcademicResearchToolkit().search_crossref("x")
        assert r.status == "error" and "ai-parrot-tools[research]" in r.error_message

    async def test_valid_year_range_applies_filter(self, capture_crossref_call):
        await AcademicResearchToolkit().search_crossref(
            "x", year_range="2020-2023"
        )
        assert capture_crossref_call.kwargs["filter"] == {
            "from-pub-date": "2020-01-01",
            "until-pub-date": "2023-12-31",
        }

    async def test_malformed_year_range_is_ignored_not_silent(
        self, capture_crossref_call, caplog
    ):
        """A malformed year_range must not be silently dropped (spec §2 /
        FEAT-426 code review): no filter is sent, but a warning is logged
        so the caller can see why the search ran unfiltered."""
        with caplog.at_level("WARNING"):
            r = await AcademicResearchToolkit().search_crossref(
                "x", year_range="not-a-range"
            )
        assert r.status in {"success", "no_data"}
        assert "filter" not in capture_crossref_call.kwargs
        assert any(
            "malformed year_range" in record.message
            for record in caplog.records
        )
