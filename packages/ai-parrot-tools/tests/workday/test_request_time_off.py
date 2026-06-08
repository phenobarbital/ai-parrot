"""TASK-1508: request_my_time_off write tool tests."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd


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


# ---------------------------------------------------------------------------
# get_tools() exposure
# ---------------------------------------------------------------------------

def test_get_tools_exposes_request_my_time_off():
    from parrot_tools.workday.tool import WorkdayToolkit

    names = {t.name for t in WorkdayToolkit().get_tools()}
    assert "request_my_time_off" in names


# ---------------------------------------------------------------------------
# dry_run=True — no SOAP call, structured return
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_no_composable_call(toolkit):
    with patch.object(toolkit, "_get_composable") as mock_gc:
        result = await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
            dry_run=True,
        )
    mock_gc.assert_not_called()
    assert result["dry_run"] is True
    assert result["worker_id"] == "W001"
    assert result["start_date"] == "2026-06-10"
    assert result["time_off_type"] == "PTO"


@pytest.mark.asyncio
async def test_dry_run_json_serializable(toolkit):
    with patch.object(toolkit, "_get_composable"):
        result = await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
            dry_run=True,
        )
    json.dumps(result)


@pytest.mark.asyncio
async def test_dry_run_defaults_true(toolkit):
    """dry_run parameter defaults to True."""
    with patch.object(toolkit, "_get_composable") as mock_gc:
        result = await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
        )
    mock_gc.assert_not_called()
    assert result["dry_run"] is True


# ---------------------------------------------------------------------------
# dry_run=False — submits via composable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_calls_composable_fetch(toolkit):
    status_df = pd.DataFrame([{"submitted": True, "event_id": "EVT-001", "error": None}])
    composable = AsyncMock()
    composable.fetch = AsyncMock(return_value=status_df)

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
            dry_run=False,
        )

    composable.fetch.assert_awaited_once()
    call_kwargs = composable.fetch.call_args
    assert call_kwargs[0][0] == "request_time_off"
    assert call_kwargs[1]["worker_id"] == "W001"
    assert call_kwargs[1]["start_date"] == "2026-06-10"
    assert call_kwargs[1]["time_off_type"] == "PTO"


@pytest.mark.asyncio
async def test_submit_returns_dict(toolkit):
    status_df = pd.DataFrame([{"submitted": True, "event_id": "EVT-001", "error": None}])
    composable = AsyncMock()
    composable.fetch = AsyncMock(return_value=status_df)

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
            dry_run=False,
        )

    assert isinstance(result, dict)
    assert result.get("submitted") is True
    json.dumps(result)


@pytest.mark.asyncio
async def test_submit_passes_comment(toolkit):
    status_df = pd.DataFrame([{"submitted": True, "event_id": None, "error": None}])
    composable = AsyncMock()
    composable.fetch = AsyncMock(return_value=status_df)

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        await toolkit.request_my_time_off(
            worker_id="W001",
            start_date="2026-06-10",
            end_date="2026-06-12",
            time_off_type="PTO",
            comment="Family event",
            dry_run=False,
        )

    call_kwargs = composable.fetch.call_args[1]
    assert call_kwargs["comment"] == "Family event"


# ---------------------------------------------------------------------------
# RequestTimeOffType handler — unit tests
# ---------------------------------------------------------------------------

def test_handler_operation_name():
    from parrot_tools.interfaces.workday.handlers.time_off_request import RequestTimeOffType

    h = RequestTimeOffType.__new__(RequestTimeOffType)
    assert h._operation_name() == "Request_Time_Off"


def test_handler_build_request_structure():
    from parrot_tools.interfaces.workday.handlers.time_off_request import RequestTimeOffType

    h = RequestTimeOffType.__new__(RequestTimeOffType)
    req = h.build_request(
        worker_id="W001",
        start_date="2026-06-10",
        end_date="2026-06-12",
        time_off_type="PTO",
    )
    assert "Time_Off_Request_Data" in req
    data = req["Time_Off_Request_Data"]
    assert data["Worker_Reference"]["ID"][0]["_value_1"] == "W001"
    lines = data["Time_Off_Request_Line_Data"]
    assert len(lines) == 1
    assert lines[0]["Start_Date"] == "2026-06-10"
    assert lines[0]["End_Date"] == "2026-06-12"
    assert lines[0]["Time_Off_Type_Reference"]["ID"][0]["_value_1"] == "PTO"


def test_handler_build_request_with_comment():
    from parrot_tools.interfaces.workday.handlers.time_off_request import RequestTimeOffType

    h = RequestTimeOffType.__new__(RequestTimeOffType)
    req = h.build_request(
        worker_id="W001",
        start_date="2026-06-10",
        end_date="2026-06-12",
        time_off_type="PTO",
        comment="Holiday",
    )
    assert req["Time_Off_Request_Data"]["Comment"] == "Holiday"


def test_handler_parse_ack_returns_dataframe():
    import pandas as pd
    from parrot_tools.interfaces.workday.handlers.time_off_request import RequestTimeOffType

    h = RequestTimeOffType.__new__(RequestTimeOffType)
    df = h.parse_ack(None)
    assert isinstance(df, pd.DataFrame)
    assert df.iloc[0]["submitted"] == True  # noqa: E712 — numpy bool, not `is`
