"""TASK-1509: get_my_time_off_eligibility read tool tests."""
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


def _eligibility_mock(data: dict):
    m = MagicMock()
    m.model_dump.return_value = data
    return m


# ---------------------------------------------------------------------------
# get_tools() exposure
# ---------------------------------------------------------------------------

def test_get_tools_exposes_get_my_time_off_eligibility():
    from parrot_tools.workday.tool import WorkdayToolkit

    names = {t.name for t in WorkdayToolkit().get_tools()}
    assert "get_my_time_off_eligibility" in names


def test_get_tools_exposes_all_11_homologated_tools():
    """After TASK-1508 + TASK-1509, all 11 homologated tools are present."""
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
        "request_my_time_off",
        "get_my_time_off_eligibility",
    ]
    for m in expected:
        assert m in names, f"Missing tool: {m}"


# ---------------------------------------------------------------------------
# delegation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delegates_to_fetch_models(toolkit):
    eligibility_data = {
        "time_off_type_id": "PTO",
        "name": "Paid Time Off",
        "description": None,
        "unit": "Hours",
    }
    composable = AsyncMock()
    composable.fetch_models = AsyncMock(
        return_value=[_eligibility_mock(eligibility_data)]
    )

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_my_time_off_eligibility(worker_id="W001")

    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_eligibility", worker_id="W001"
    )
    assert result == [eligibility_data]
    json.dumps(result)


@pytest.mark.asyncio
async def test_returns_list(toolkit):
    composable = AsyncMock()
    composable.fetch_models = AsyncMock(return_value=[])

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_my_time_off_eligibility(worker_id="W001")

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_multiple_types_returned(toolkit):
    types = [
        {"time_off_type_id": "PTO", "name": "PTO", "description": None, "unit": "Hours"},
        {"time_off_type_id": "SICK", "name": "Sick Leave", "description": None, "unit": "Days"},
    ]
    composable = AsyncMock()
    composable.fetch_models = AsyncMock(
        return_value=[_eligibility_mock(t) for t in types]
    )

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.get_my_time_off_eligibility(worker_id="W001")

    assert len(result) == 2
    assert result[0]["time_off_type_id"] == "PTO"
    assert result[1]["time_off_type_id"] == "SICK"
    json.dumps(result)


# ---------------------------------------------------------------------------
# TimeOffEligibilityType handler — unit tests
# ---------------------------------------------------------------------------

def test_handler_execute_is_coroutine():
    import inspect
    from parrot_tools.interfaces.workday.handlers.time_off_eligibility import (
        TimeOffEligibilityType,
    )

    assert inspect.iscoroutinefunction(TimeOffEligibilityType.execute)


@pytest.mark.asyncio
async def test_handler_execute_calls_get_time_off_types():
    from parrot_tools.interfaces.workday.handlers.time_off_eligibility import (
        TimeOffEligibilityType,
    )

    captured = {}
    service_mock = AsyncMock()
    service_mock.call_operation = AsyncMock(return_value=None)

    handler = TimeOffEligibilityType.__new__(TimeOffEligibilityType)
    handler.service = service_mock

    result = await handler.execute(worker_id="W001")

    service_mock.call_operation.assert_awaited_once()
    op_name = service_mock.call_operation.call_args[0][0]
    assert op_name == "Get_Time_Off_Types"
    import pandas as pd
    assert isinstance(result, pd.DataFrame)


@pytest.mark.asyncio
async def test_handler_execute_empty_response_returns_empty_df():
    import pandas as pd
    from parrot_tools.interfaces.workday.handlers.time_off_eligibility import (
        TimeOffEligibilityType,
    )

    service_mock = AsyncMock()
    service_mock.call_operation = AsyncMock(return_value=None)

    handler = TimeOffEligibilityType.__new__(TimeOffEligibilityType)
    handler.service = service_mock

    df = await handler.execute(worker_id="W001")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


# ---------------------------------------------------------------------------
# TimeOffEligibility model — unit tests
# ---------------------------------------------------------------------------

def test_model_fields():
    from parrot_tools.interfaces.workday.models.time_off_eligibility import TimeOffEligibility

    m = TimeOffEligibility(
        time_off_type_id="PTO",
        name="Paid Time Off",
        unit="Hours",
    )
    assert m.time_off_type_id == "PTO"
    assert m.name == "Paid Time Off"
    assert m.unit == "Hours"
    assert m.description is None


def test_model_dump_json_serializable():
    from parrot_tools.interfaces.workday.models.time_off_eligibility import TimeOffEligibility

    m = TimeOffEligibility(time_off_type_id="PTO", name="Paid Time Off")
    data = m.model_dump(mode="json")
    json.dumps(data)
