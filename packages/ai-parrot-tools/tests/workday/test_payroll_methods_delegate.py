"""FEAT-232 TASK-1515 — payroll toolkit methods delegate to the composable."""
import json
import pytest

from parrot_tools.workday.tool import WorkdayToolkit


class _FakeComposable:
    def __init__(self):
        self.fetch_calls = []

    async def fetch(self, operation_type, **params):
        self.fetch_calls.append((operation_type, params))
        if operation_type == "get_payroll_balances":
            return {"Total": {"Amount": "100"}}
        return [{"row": 1}]


@pytest.fixture
def toolkit(monkeypatch):
    tk = WorkdayToolkit()
    tk._initialized = True  # skip wd_start
    fake = _FakeComposable()

    async def fake_get_composable(self, operation_type):
        return fake

    monkeypatch.setattr(WorkdayToolkit, "_get_composable", fake_get_composable)
    tk._fake = fake
    return tk


@pytest.mark.asyncio
async def test_payroll_balances_delegates(toolkit):
    res = await toolkit.wd_get_payroll_balances("12345", start_date="2026-01-01")
    op, params = toolkit._fake.fetch_calls[0]
    assert op == "get_payroll_balances"
    assert params["worker_id"] == "12345" and params["start_date"] == "2026-01-01"
    json.dumps(res)  # JSON-serializable, no DataFrame


@pytest.mark.asyncio
async def test_payroll_results_delegates(toolkit):
    res = await toolkit.wd_get_payroll_results("12345", include_details=True)
    op, params = toolkit._fake.fetch_calls[0]
    assert op == "get_payroll_results" and params["include_details"] is True
    assert isinstance(res, list)
    json.dumps(res)


@pytest.mark.asyncio
async def test_company_payment_dates_delegates(toolkit):
    res = await toolkit.wd_get_company_payment_dates("2026-01-01", "2026-01-31", pay_group_id="PG1")
    op, params = toolkit._fake.fetch_calls[0]
    assert op == "get_company_payment_dates"
    assert params["start_date"] == "2026-01-01" and params["pay_group_id"] == "PG1"
    json.dumps(res)
