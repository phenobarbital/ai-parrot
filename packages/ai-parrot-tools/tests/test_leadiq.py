"""Unit tests for LeadIQToolkit (FEAT-304).

No real network calls are made — ``HTTPService.session`` (composed as
``toolkit.http``) is always mocked to return canned GraphQL payloads.
"""
import importlib
from unittest.mock import AsyncMock, patch

import pytest

from parrot.tools.abstract import ToolResult
from parrot_tools import TOOL_REGISTRY
from parrot_tools.leadiq.tool import LeadIQToolkit, LeadIQSearchInput


# ===========================
# Fixtures
# ===========================

@pytest.fixture
def toolkit():
    """LeadIQToolkit instance with an explicit (already Base64) API key."""
    return LeadIQToolkit(api_key="Zm9vOg==")


@pytest.fixture
def company_payload():
    """Minimal SearchCompany GraphQL response mirroring api.leadiq.com."""
    return {
        "data": {
            "searchCompany": {
                "totalResults": 1,
                "hasMore": False,
                "results": [
                    {
                        "name": "PetSmart",
                        "domain": "petsmart.com",
                        "industry": "Retail",
                        "country": "US",
                        "address": "19601 N 27th Ave, Phoenix, AZ",
                        "linkedinId": "162423",
                        "linkedinUrl": "https://www.linkedin.com/company/petsmart",
                        "numberOfEmployees": 50000,
                        "employeeRange": "10001+",
                        "foundedYear": 1986,
                        "locationInfo": {
                            "formattedAddress": "19601 N 27th Ave, Phoenix, AZ",
                            "street1": "19601 N 27th Ave",
                            "street2": None,
                            "city": "Phoenix",
                            "areaLevel1": "AZ",
                            "country": "US",
                            "postalCode": "85027",
                        },
                        "naicsCode": {
                            "code": "453910",
                            "description": "Pet Stores",
                        },
                        "technologies": [
                            {"name": "Shopify", "category": "Ecommerce"},
                            {"name": "Salesforce", "category": "CRM"},
                        ],
                        "specialities": ["Pet Retail", "Grooming"],
                    }
                ],
            }
        }
    }


@pytest.fixture
def empty_company_payload():
    """SearchCompany GraphQL response with no matches."""
    return {
        "data": {
            "searchCompany": {
                "totalResults": 0,
                "hasMore": False,
                "results": [],
            }
        }
    }


@pytest.fixture
def employee_payload():
    """Minimal GroupedAdvancedSearch GraphQL response."""
    return {
        "data": {
            "groupedAdvancedSearch": {
                "totalCompanies": 1,
                "companies": [
                    {
                        "company": {
                            "id": "company-1",
                            "name": "PetSmart",
                            "industry": "Retail",
                            "domain": "petsmart.com",
                            "employeeCount": 50000,
                            "city": "Phoenix",
                            "country": "US",
                            "state": "AZ",
                        },
                        "people": [
                            {
                                "id": "person-1",
                                "name": "Jane Doe",
                                "title": "VP Marketing",
                                "company": {"id": "company-1", "name": "PetSmart"},
                            },
                            {
                                "id": "person-2",
                                "name": "John Smith",
                                "title": "Director of Sales",
                                "company": {"id": "company-1", "name": "PetSmart"},
                            },
                        ],
                        "totalContactsInCompany": 2,
                    }
                ],
            }
        }
    }


@pytest.fixture
def flat_payload():
    """Minimal FlatAdvancedSearch GraphQL response."""
    return {
        "data": {
            "flatAdvancedSearch": {
                "totalPeople": 2,
                "people": [
                    {
                        "id": "person-1",
                        "name": "Jane Doe",
                        "title": "VP Marketing",
                        "company": {
                            "id": "company-1",
                            "name": "PetSmart",
                            "industry": "Retail",
                            "domain": "petsmart.com",
                            "employeeCount": 50000,
                            "city": "Phoenix",
                            "country": "US",
                            "state": "AZ",
                        },
                    },
                    {
                        "id": "person-2",
                        "name": "John Smith",
                        "title": "Director of Sales",
                        "company": {
                            "id": "company-1",
                            "name": "PetSmart",
                            "industry": "Retail",
                            "domain": "petsmart.com",
                            "employeeCount": 50000,
                            "city": "Phoenix",
                            "country": "US",
                            "state": "AZ",
                        },
                    },
                ],
            }
        }
    }


# ===========================
# Tests
# ===========================

@pytest.mark.asyncio
async def test_toolkit_exposes_three_tools(toolkit):
    names = {t.name for t in toolkit.get_tools()}
    assert names == {
        "leadiq_search_company",
        "leadiq_search_employees",
        "leadiq_search_flat",
    }


def test_composed_http_service_accepts_json(toolkit):
    """Regression test: the composed HTTPService must request/parse JSON.

    ``HTTPService.session`` branches on ``self.accept`` (not the response's
    actual Content-Type) to decide whether to parse the body as JSON or
    plain text. Without ``accept="application/json"`` explicitly set on the
    composed member, real (non-mocked) LeadIQ API calls would come back as
    a raw string and every ``_process_*_response`` call would blow up with
    a ``TypeError`` on ``result["data"]`` — invisible to tests that mock
    ``toolkit.http.session`` directly.
    """
    assert toolkit.http.accept == "application/json"


@pytest.mark.asyncio
async def test_headers_use_basic_auth_verbatim(toolkit, company_payload):
    mock_session = AsyncMock(return_value=(company_payload, None))
    with patch.object(toolkit.http, "session", new=mock_session):
        await toolkit.search_company(company_name="PetSmart")

    mock_session.assert_called_once()
    _, kwargs = mock_session.call_args
    assert kwargs["headers"]["Authorization"] == "Basic Zm9vOg=="
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["apollo-require-preflight"] == "true"


@pytest.mark.asyncio
async def test_auth_headers_reach_the_real_outgoing_request(toolkit, company_payload):
    """End-to-end regression test for the FEAT-304 header-drop bug.

    Every other test in this module mocks ``toolkit.http.session`` directly,
    which only proves LeadIQToolkit *calls* session() with the right
    headers — it can't catch a bug inside session() itself that silently
    discards those headers before building the real HTTP request (as
    happened previously: ``HTTPService.session()`` reassigned its local
    ``headers`` variable to ``self.headers`` before ever reading the
    caller-supplied dict). This test instead patches ``httpx.AsyncClient``
    — one layer below ``session()`` — so it exercises the real header-merge
    logic end-to-end.
    """

    class _FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        text = "{}"

    class _FakeAsyncClient:
        captured = {}

        def __init__(self, **kwargs):
            _FakeAsyncClient.captured["init_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, **kwargs):
            return _FakeResponse()

    from parrot.interfaces.http import HTTPService

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        with patch.object(
            HTTPService,
            "process_response",
            AsyncMock(return_value=(company_payload, None)),
        ):
            result = await toolkit.search_company(company_name="PetSmart")

    sent_headers = _FakeAsyncClient.captured["init_kwargs"]["headers"]
    assert sent_headers["Authorization"] == "Basic Zm9vOg=="
    assert sent_headers["Content-Type"] == "application/json"
    assert sent_headers["apollo-require-preflight"] == "true"
    assert result.success is True


@pytest.mark.asyncio
async def test_missing_api_key_returns_error_toolresult():
    tk = LeadIQToolkit(api_key=None)
    with patch("parrot_tools.leadiq.tool.config.get", return_value=None):
        result = await tk.search_company(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.status == "error"
    assert result.error is not None


@pytest.mark.asyncio
async def test_search_company_flattens_response(toolkit, company_payload):
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(company_payload, None))
    ):
        result = await toolkit.search_company(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.result["name"] == "PetSmart"
    assert result.result["domain"] == "petsmart.com"
    assert result.result["industry"] == "Retail"
    assert result.result["naics_code"] == "453910"
    assert result.result["technologies"] == ["Shopify", "Salesforce"]
    assert result.metadata["search_type"] == "company"
    assert result.metadata["source"] == "LeadIQ"


@pytest.mark.asyncio
async def test_search_employees_returns_person_rows(toolkit, employee_payload):
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(employee_payload, None))
    ):
        result = await toolkit.search_employees(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert isinstance(result.result, list)
    assert len(result.result) == 2
    for row in result.result:
        assert row["company_name"] == "PetSmart"
        assert "company" not in row
        assert "name" in row
    assert result.metadata["count"] == 2
    assert result.metadata["search_type"] == "employees"


@pytest.mark.asyncio
async def test_search_flat_returns_person_rows(toolkit, flat_payload):
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(flat_payload, None))
    ):
        result = await toolkit.search_flat(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert isinstance(result.result, list)
    assert len(result.result) == 2
    for row in result.result:
        assert row["company_name"] == "PetSmart"
        assert "company" not in row
        assert "name" in row
    assert result.metadata["count"] == 2
    assert result.metadata["search_type"] == "flat"


@pytest.mark.asyncio
async def test_no_results_company(toolkit, empty_company_payload):
    with patch.object(
        toolkit.http,
        "session",
        new=AsyncMock(return_value=(empty_company_payload, None)),
    ):
        result = await toolkit.search_company(company_name="Nonexistent Co")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.result["found"] is False
    assert result.result["total_results"] == 0


@pytest.mark.asyncio
async def test_search_employees_flags_ambiguous_empty_on_unexpected_structure(
    toolkit,
):
    """`_process_employee_response` (ported verbatim) returns ``None`` both
    for "no companies found" and for a malformed/unexpected response shape.
    Rather than silently reporting an empty list identically to a genuine
    zero-results search, the tool must flag this case via
    ``metadata["ambiguous_empty"]`` so callers/observability can tell the
    difference from a real "0 employees" result.
    """
    malformed_payload = {"data": {"unexpectedKey": {}}}
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(malformed_payload, None))
    ):
        result = await toolkit.search_employees(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.result == []
    assert result.metadata["ambiguous_empty"] is True


@pytest.mark.asyncio
async def test_search_employees_no_ambiguous_flag_on_normal_results(
    toolkit, employee_payload
):
    """A well-formed, non-empty response must NOT carry the ambiguous flag."""
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(employee_payload, None))
    ):
        result = await toolkit.search_employees(company_name="PetSmart")

    assert "ambiguous_empty" not in result.metadata


@pytest.mark.asyncio
async def test_search_flat_flags_ambiguous_empty_on_unexpected_structure(toolkit):
    """Same ``ambiguous_empty`` contract as employees, for the flat search."""
    malformed_payload = {"data": {"unexpectedKey": {}}}
    with patch.object(
        toolkit.http, "session", new=AsyncMock(return_value=(malformed_payload, None))
    ):
        result = await toolkit.search_flat(company_name="PetSmart")

    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.result == []
    assert result.metadata["ambiguous_empty"] is True


def test_registry_entry_resolves():
    assert TOOL_REGISTRY["leadiq"] == "parrot_tools.leadiq.tool.LeadIQToolkit"
    mod_path, _, cls = TOOL_REGISTRY["leadiq"].rpartition(".")
    assert getattr(importlib.import_module(mod_path), cls) is LeadIQToolkit


def test_search_input_schema_defaults_and_limit_bounds():
    schema = LeadIQSearchInput(company_name="PetSmart")
    assert schema.limit == 100
    with pytest.raises(ValueError):
        LeadIQSearchInput(company_name="PetSmart", limit=0)
    with pytest.raises(ValueError):
        LeadIQSearchInput(company_name="PetSmart", limit=101)
