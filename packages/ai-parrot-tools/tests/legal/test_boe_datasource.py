"""Unit tests for BOEDataSource (TASK-2373). No network access — aiohttp is mocked."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot_loaders.extractors.base import ExtractionResult
from parrot_tools.legal.boe.datasource import BOEDataSource

FIXTURE = Path(__file__).parent / "fixtures" / "boe_consolidated_sample.xml"
FIXTURE_BOE_ID = "BOE-A-2015-10566"


def _mock_aiohttp_response(body: str, status: int = 200):
    """Build a mocked aiohttp.ClientSession returning `body` as text.

    Follows the project convention (see
    packages/ai-parrot/tests/test_odoo_json2_transport.py).
    """
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=body)
    response.raise_for_status = MagicMock()
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.closed = False
    session.get = MagicMock(return_value=response)
    session.close = AsyncMock(return_value=None)
    return session


@pytest.fixture
def fixture_xml() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def source():
    return BOEDataSource(
        name="boe",
        config={"base_url": "https://example.invalid", "boe_ids": [FIXTURE_BOE_ID]},
    )


class TestBOEDataSource:
    async def test_extract_returns_extraction_result(self, source, fixture_xml):
        """extract() returns a well-formed ExtractionResult (HTTP mocked)."""
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await source.extract()

        assert isinstance(result, ExtractionResult)
        assert result.source_name == "boe"
        assert result.extracted_at is not None
        assert result.total == len(result.records)
        # fields=None => "both": one norma + N articulos.
        assert any("boe_id" in rec.data for rec in result.records)
        assert any("articulo_key" in rec.data for rec in result.records)

    async def test_field_projection(self, source, fixture_xml):
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await source.extract(fields=["boe_id"])

        assert result.records, "expected at least the norma record"
        for rec in result.records:
            assert set(rec.data) <= {"boe_id"}

    async def test_articulo_field_projection_returns_only_articulos(self, source, fixture_xml):
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await source.extract(fields=["articulo_key", "versions"])

        assert result.records
        for rec in result.records:
            assert "articulo_key" in rec.data
            assert set(rec.data) <= {"articulo_key", "versions"}

    async def test_parser_errors_surface(self, source):
        """Malformed upstream payload populates errors instead of raising."""
        session = _mock_aiohttp_response("<not-valid-boe/>")
        with patch("aiohttp.ClientSession", return_value=session):
            result = await source.extract()

        assert isinstance(result.errors, list)
        assert result.errors

    async def test_list_fields(self, source):
        fields = await source.list_fields()
        assert "boe_id" in fields
        assert "articulo_key" in fields

    async def test_since_filter_excludes_older_norms(self, source, fixture_xml):
        """A `since` date after fecha_publicacion (2015-10-02) excludes the norm."""
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            result = await source.extract(filters={"since": "2099-01-01"})

        assert result.records == []

    async def test_sends_identifying_user_agent(self, source, fixture_xml):
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            await source.extract()

        _, kwargs = session.get.call_args
        assert "ai-parrot" in kwargs["headers"]["User-Agent"]

    async def test_caches_parsed_norm_across_calls(self, source, fixture_xml):
        """The pipeline calls extract() once per entity — the norm must not be re-fetched."""
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            await source.extract(fields=["boe_id"])
            await source.extract(fields=["articulo_key"])

        assert session.get.call_count == 1

    async def test_no_boe_ids_returns_empty_result(self):
        source = BOEDataSource(name="boe", config={})
        result = await source.extract()
        assert result.records == []
        assert result.errors == []

    async def test_extract_relations_returns_modifica_and_deroga(self, source, fixture_xml):
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            relations = await source.extract_relations()

        assert any(r["type"] == "modifica" for r in relations)
        assert any(r["type"] == "deroga" for r in relations)

    async def test_extract_relations_reuses_parse_cache(self, source, fixture_xml):
        """extract() then extract_relations() on the SAME instance -> one fetch."""
        session = _mock_aiohttp_response(fixture_xml)
        with patch("aiohttp.ClientSession", return_value=session):
            await source.extract()
            await source.extract_relations()

        assert session.get.call_count == 1

    async def test_extract_relations_no_boe_ids_returns_empty(self):
        source = BOEDataSource(name="boe", config={})
        assert await source.extract_relations() == []
