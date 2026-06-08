"""TASK-1506: WorkdayToolkit delegates to WorkdayComposable."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture()
def toolkit():
    from parrot_tools.workday.tool import WorkdayToolkit

    tk = WorkdayToolkit.__new__(WorkdayToolkit)
    tk.credentials = {
        "client_id": "test",
        "client_secret": "test",
        "token_url": "https://example.com/oauth2/token",
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


def _make_composable_mock(fetch_models_return=None, call_op_return=None):
    mock = AsyncMock()
    mock.fetch_models = AsyncMock(return_value=fetch_models_return or [])
    mock.call_operation = AsyncMock(return_value=call_op_return)
    mock.start = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_wd_get_worker_delegates_fetch_models(toolkit):
    """wd_get_worker calls fetch_models('get_workers')."""
    fake_model = MagicMock()
    fake_model.model_dump.return_value = {"worker_id": "W001", "name": "Alice"}
    composable = _make_composable_mock(fetch_models_return=[fake_model])

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_get_worker(worker_id="W001")

    composable.fetch_models.assert_awaited_once_with("get_workers", worker_id="W001")
    assert result == {"worker_id": "W001", "name": "Alice"}


@pytest.mark.asyncio
async def test_wd_get_worker_returns_empty_on_no_models(toolkit):
    composable = _make_composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_get_worker(worker_id="MISSING")
    assert result == {}


@pytest.mark.asyncio
async def test_wd_get_time_off_balance_delegates_fetch_models(toolkit):
    """wd_get_time_off_balance calls fetch_models('get_time_off_balances')."""
    fake_model = MagicMock()
    fake_model.model_dump.return_value = {"plan": "Vacation", "balance": 10}
    composable = _make_composable_mock(fetch_models_return=[fake_model])

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_get_time_off_balance(worker_id="W001")

    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_balances", worker_id="W001"
    )
    assert result == [{"plan": "Vacation", "balance": 10}]


@pytest.mark.asyncio
async def test_wd_get_time_off_balance_passes_plan_id(toolkit):
    composable = _make_composable_mock(fetch_models_return=[])
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        await toolkit.wd_get_time_off_balance(worker_id="W001", time_off_plan_id="PL01")

    composable.fetch_models.assert_awaited_once_with(
        "get_time_off_balances", worker_id="W001", time_off_plan_id="PL01"
    )


@pytest.mark.asyncio
async def test_wd_search_workers_delegates_call_operation(toolkit):
    composable = _make_composable_mock(call_op_return=None)
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_search_workers(search_text="Alice", max_results=10)

    composable.call_operation.assert_awaited_once()
    call_args = composable.call_operation.call_args
    assert call_args[0][0] == "Get_Workers"
    assert result == []


@pytest.mark.asyncio
async def test_wd_get_organization_delegates_call_operation(toolkit):
    composable = _make_composable_mock(call_op_return=None)
    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_get_organization(org_id="ORG001")

    composable.call_operation.assert_awaited_once()
    call_args = composable.call_operation.call_args
    assert call_args[0][0] == "Get_Organizations"
    assert result == {}


@pytest.mark.asyncio
async def test_wd_close_closes_composables(toolkit):
    """wd_close() closes all cached composables."""
    svc1 = AsyncMock()
    svc1.close = AsyncMock()
    svc2 = AsyncMock()
    svc2.close = AsyncMock()
    toolkit._composables = {"get_workers": svc1, "get_time_off_balances": svc2}

    with patch.object(toolkit, "_clients", {}):
        await toolkit.wd_close()

    svc1.close.assert_awaited_once()
    svc2.close.assert_awaited_once()
    assert toolkit._composables == {}


@pytest.mark.asyncio
async def test_result_is_json_serializable(toolkit):
    """Results from delegating methods must be JSON-serialisable."""
    import json

    fake_model = MagicMock()
    fake_model.model_dump.return_value = {"id": "W001", "name": "Alice", "score": 42.0}
    composable = _make_composable_mock(fetch_models_return=[fake_model])

    with patch.object(toolkit, "_get_composable", new=AsyncMock(return_value=composable)):
        result = await toolkit.wd_get_worker(worker_id="W001")

    assert json.dumps(result)  # no TypeError
