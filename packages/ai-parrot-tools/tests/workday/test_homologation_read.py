"""TASK-1507: homologated read tools — 9 agent-facing methods."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture()
def toolkit():
    from parrot_tools.workday.tool import WorkdayToolkit

    tk = WorkdayToolkit.__new__(WorkdayToolkit)
    tk.credentials = {
        "client_id": "test",
        "client_secret": "test",
        "token_url": "https://example.com/token",
        "refresh_token": "test",
    }
    tk.tenant_name = "test"
    tk.report_username = "user"
    tk.report_password = "pass"
    tk.report_owner = "owner"
    tk.workday_url = "https://wd2-impl.workday.com"
    tk.timeout = 30
    tk._clients = {}
    tk._composables = {}
    tk.soap_client = None
    tk._initialized = True
    tk._http_client = None
    tk.wsdl_paths = {}
    return tk


def _worker_mock(data: dict):
    m = MagicMock()
    m.model_dump.return_value = data
    return m


def _composable_mock(fetch_models_return=None, call_op_return=None):
    mock = AsyncMock()
    mock.fetch_models = AsyncMock(return_value=fetch_models_return or [])
    mock.call_operation = AsyncMock(return_value=call_op_return)
    mock.start = AsyncMock()
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# get_tools() exposure
# ---------------------------------------------------------------------------

def test_get_tools_exposes_all_9_read_methods():
    from parrot_tools.workday.tool import WorkdayToolkit

    names = {t.name for t in WorkdayToolkit().get_tools()}
    expected = [
        "find_employee_id_by_name",
        "get_current_user_info",
        "get_more_employee_data",
        "get_personal_information",
        "get_direct_reports",
        "get_time_off_balance",
        "get_current_user_time_off_balance",
        "get_current_user_time_off_history",
        "get_today_date_and_day_of_week",
    ]
    for m in expected:
        assert m in names, f"Missing tool: {m}"


# ---------------------------------------------------------------------------
# get_today_date_and_day_of_week — no SOAP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_today_date_and_day_of_week_no_soap():
    from parrot_tools.workday.tool import WorkdayToolkit

    tk = WorkdayToolkit.__new__(WorkdayToolkit)
    tk._initialized = False
    res = await tk.get_today_date_and_day_of_week()
    assert "date" in res and "day_of_week" in res
    assert len(res["date"]) == 10  # ISO-8601: YYYY-MM-DD
    json.dumps(res)  # JSON-serializable


@pytest.mark.asyncio
async def test_get_today_no_composable_call(toolkit):
    with patch.object(toolkit, "_get_composable") as mock_gc:
        await toolkit.get_today_date_and_day_of_week()
    mock_gc.assert_not_called()


# ---------------------------------------------------------------------------
# find_employee_id_by_name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_employee_id_by_name_returns_list(toolkit):
    composable = _composable_mock(call_op_return=None)
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        with patch.object(toolkit, "_parse_workers_response", return_value=[]):
            result = await toolkit.find_employee_id_by_name(name="Alice")
    assert isinstance(result, list)
    json.dumps(result)


@pytest.mark.asyncio
async def test_find_employee_id_by_name_call_operation(toolkit):
    composable = _composable_mock(call_op_return=None)
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        with patch.object(toolkit, "_parse_workers_response", return_value=[]):
            await toolkit.find_employee_id_by_name(name="Bob")
    composable.call_operation.assert_awaited_once()
    call_args = composable.call_operation.call_args
    assert call_args[0][0] == "Get_Workers"


# ---------------------------------------------------------------------------
# get_current_user_info
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_user_info_delegates_fetch_models(toolkit):
    worker_data = {"worker_id": "W001", "first_name": "Alice", "last_name": "Smith"}
    composable = _composable_mock(fetch_models_return=[_worker_mock(worker_data)])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_current_user_info(worker_id="W001")
    composable.fetch_models.assert_awaited_once_with("get_workers", worker_id="W001")
    assert result == worker_data
    json.dumps(result)


@pytest.mark.asyncio
async def test_get_current_user_info_empty(toolkit):
    composable = _composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_current_user_info(worker_id="MISSING")
    assert result == {}


# ---------------------------------------------------------------------------
# get_personal_information
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_personal_information_subset_fields(toolkit):
    full_model = {
        "worker_id": "W001",
        "first_name": "Alice",
        "last_name": "Smith",
        "formatted_name": "Alice Smith",
        "email": "alice@example.com",
        "some_other_field": "ignored",
    }
    composable = _composable_mock(fetch_models_return=[_worker_mock(full_model)])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_personal_information(worker_id="W001")
    assert result["worker_id"] == "W001"
    assert result["first_name"] == "Alice"
    assert "some_other_field" not in result
    json.dumps(result)


# ---------------------------------------------------------------------------
# get_direct_reports
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_direct_reports_delegates_call_operation(toolkit):
    composable = _composable_mock(call_op_return=None)
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        with patch.object(toolkit, "_parse_workers_response", return_value=[{"id": "1"}]):
            result = await toolkit.get_direct_reports(worker_id="MGR01")
    composable.call_operation.assert_awaited_once()
    call_args = composable.call_operation.call_args
    assert call_args[0][0] == "Get_Workers"
    assert result == [{"id": "1"}]


# ---------------------------------------------------------------------------
# get_time_off_balance / get_current_user_time_off_balance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_time_off_balance_delegates_fetch_models(toolkit):
    balance_data = {"plan": "Vacation", "balance": 10.0}
    composable = _composable_mock(fetch_models_return=[_worker_mock(balance_data)])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_time_off_balance(worker_id="W001")
    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_balances", worker_id="W001"
    )
    assert result == [balance_data]
    json.dumps(result)


@pytest.mark.asyncio
async def test_get_time_off_balance_passes_plan_id(toolkit):
    composable = _composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        await toolkit.get_time_off_balance(worker_id="W001", time_off_plan_id="PL01")
    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_balances", worker_id="W001", time_off_plan_id="PL01"
    )


@pytest.mark.asyncio
async def test_get_current_user_time_off_balance(toolkit):
    composable = _composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_current_user_time_off_balance(worker_id="W001")
    assert result == []
    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_balances", worker_id="W001"
    )


# ---------------------------------------------------------------------------
# get_current_user_time_off_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_user_time_off_history_delegates_fetch_models(toolkit):
    req_data = {"time_request_id": "TR001", "start_date": "2026-06-01", "status": "Approved"}
    composable = _composable_mock(fetch_models_return=[_worker_mock(req_data)])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_current_user_time_off_history(
            worker_id="W001", start_date="2026-06-01", end_date="2026-06-08"
        )
    composable.fetch_models.assert_awaited_once_with(
        "get_time_requests",
        worker_id="W001",
        start_date="2026-06-01",
        end_date="2026-06-08",
    )
    assert result == [req_data]
    json.dumps(result)


@pytest.mark.asyncio
async def test_get_current_user_time_off_history_no_dates(toolkit):
    composable = _composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        await toolkit.get_current_user_time_off_history(worker_id="W001")
    composable.fetch_models.assert_awaited_once_with("get_time_requests", worker_id="W001")
