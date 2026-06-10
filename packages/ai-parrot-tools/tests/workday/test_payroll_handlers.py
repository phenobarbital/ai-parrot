"""FEAT-232 — payroll composable handlers (mocked, no live WSDL)."""
import pytest

from parrot.conf import WORKDAY_WSDL_PAYROLL
from parrot_tools.interfaces.workday.config import get_wsdl_path
from parrot_tools.interfaces.workday.handlers.payroll import (
    PayrollBalancesType,
    PayrollResultsType,
    CompanyPaymentDatesType,
)


def test_payroll_ops_route_to_payroll_wsdl():
    for op in ("get_payroll_balances", "get_payroll_results", "get_company_payment_dates"):
        assert get_wsdl_path(op) == WORKDAY_WSDL_PAYROLL


class _FakeService:
    """Minimal stand-in providing call_operation + logger for the handler base."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def call_operation(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        return self._response


@pytest.mark.asyncio
async def test_payroll_balances_handler_builds_payload_and_returns_dict():
    svc = _FakeService({"Total": {"Amount": "100"}})
    handler = PayrollBalancesType(svc)
    result = await handler.execute(
        worker_id="12345", start_date="2026-01-01", end_date="2026-01-31",
        pay_component_group_ids=["PCG1"],
    )
    op, payload = svc.calls[0]
    assert op == "Get_Payroll_Balances"
    assert payload["Request_References"]["Worker_Reference"]["ID"][0]["_value_1"] == "12345"
    assert payload["Response_Filter"]["Start_Date"] == "2026-01-01"
    assert payload["Request_Criteria"]["Pay_Component_Group_Reference"][0]["ID"][0]["_value_1"] == "PCG1"
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_payroll_results_handler_returns_list():
    svc = _FakeService({"Payroll_Result_Data": [{"a": 1}, {"a": 2}]})
    handler = PayrollResultsType(svc)
    result = await handler.execute(worker_id="12345", include_details=True)
    op, payload = svc.calls[0]
    assert op == "Get_Payroll_Results"
    assert payload["Response_Group"]["Include_Payroll_Result_Lines"] is True
    assert isinstance(result, list) and len(result) == 2


@pytest.mark.asyncio
async def test_company_payment_dates_handler_returns_list():
    svc = _FakeService({"Company_Payment_Dates_Data": {"date": "2026-01-15"}})
    handler = CompanyPaymentDatesType(svc)
    result = await handler.execute(start_date="2026-01-01", end_date="2026-01-31", pay_group_id="PG1")
    op, payload = svc.calls[0]
    assert op == "Get_Company_Payment_Dates"
    assert payload["Request_Criteria"]["Start_Date"] == "2026-01-01"
    assert payload["Request_Criteria"]["Pay_Group_Reference"]["ID"][0]["_value_1"] == "PG1"
    assert isinstance(result, list) and len(result) == 1


@pytest.mark.asyncio
async def test_empty_responses():
    assert await PayrollBalancesType(_FakeService(None)).execute(worker_id="1") == {}
    assert await PayrollResultsType(_FakeService(None)).execute(worker_id="1") == []
    assert await CompanyPaymentDatesType(_FakeService(None)).execute(start_date="a", end_date="b") == []
