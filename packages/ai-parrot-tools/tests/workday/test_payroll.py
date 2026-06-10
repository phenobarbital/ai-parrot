"""Payroll methods — end-to-end through the composable (FEAT-232).

Rewritten from the legacy WorkdaySOAPClient-based test: the 3 payroll toolkit
methods now delegate to the vendored composable (TASK-1515), which routes through
the real payroll handlers (TASK-1514). This exercises
toolkit method -> _get_composable -> fetch -> handler -> call_operation,
mocking only the lowest layer (call_operation), with no live WSDL.
"""
import logging
import pytest

from parrot_tools.workday.tool import WorkdayToolkit
from parrot_tools.interfaces.workday.handlers.payroll import (
    PayrollBalancesType,
    PayrollResultsType,
    CompanyPaymentDatesType,
)


class _FakeComposable:
    """Stand-in composable: real handlers, mocked call_operation."""

    def __init__(self, response):
        self._response = response
        self.calls = []
        self._logger = logging.getLogger("test.payroll")
        self._handlers = {
            "get_payroll_balances": PayrollBalancesType(self),
            "get_payroll_results": PayrollResultsType(self),
            "get_company_payment_dates": CompanyPaymentDatesType(self),
        }

    async def call_operation(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        return self._response

    async def fetch(self, operation_type, **params):
        return await self._handlers[operation_type].execute(**params)


def _toolkit_with(monkeypatch, response):
    tk = WorkdayToolkit()
    tk._initialized = True
    fake = _FakeComposable(response)

    async def fake_get_composable(self, operation_type):
        return fake

    monkeypatch.setattr(WorkdayToolkit, "_get_composable", fake_get_composable)
    return tk, fake


@pytest.mark.asyncio
async def test_wd_get_payroll_balances(monkeypatch):
    tk, fake = _toolkit_with(monkeypatch, {"Payroll_Balance_Data": {"Balance_Item": "Test Balance"}})
    result = await tk.wd_get_payroll_balances(
        worker_id="12345", start_date="2023-01-01", end_date="2023-12-31",
        pay_component_group_ids=["PCG1"],
    )
    op, payload = fake.calls[0]
    assert op == "Get_Payroll_Balances"
    assert payload["Request_References"] == {
        "Worker_Reference": {"ID": [{"type": "Employee_ID", "_value_1": "12345"}]}
    }
    assert payload["Response_Filter"] == {"Start_Date": "2023-01-01", "End_Date": "2023-12-31"}
    assert payload["Request_Criteria"] == {
        "Pay_Component_Group_Reference": [
            {"ID": [{"type": "Pay_Component_Group_ID", "_value_1": "PCG1"}]}
        ]
    }
    assert result == {"Payroll_Balance_Data": {"Balance_Item": "Test Balance"}}


@pytest.mark.asyncio
async def test_wd_get_payroll_results(monkeypatch):
    tk, fake = _toolkit_with(monkeypatch, {"Payroll_Result_Data": [{"Period": "2023-01"}, {"Period": "2023-02"}]})
    result = await tk.wd_get_payroll_results(worker_id="12345", start_date="2023-01-01", include_details=True)
    op, payload = fake.calls[0]
    assert op == "Get_Payroll_Results"
    assert payload["Response_Filter"] == {"Start_Date": "2023-01-01"}
    assert payload["Response_Group"] == {"Include_Payroll_Result_Lines": True}
    assert len(result) == 2 and result[0]["Period"] == "2023-01"


@pytest.mark.asyncio
async def test_wd_get_company_payment_dates(monkeypatch):
    tk, fake = _toolkit_with(monkeypatch, {"Company_Payment_Dates_Data": [{"Payment_Date": "2023-01-15"}, {"Payment_Date": "2023-01-31"}]})
    result = await tk.wd_get_company_payment_dates(start_date="2023-01-01", end_date="2023-01-31", pay_group_id="PG1")
    op, payload = fake.calls[0]
    assert op == "Get_Company_Payment_Dates"
    assert payload["Request_Criteria"] == {
        "Start_Date": "2023-01-01", "End_Date": "2023-01-31",
        "Pay_Group_Reference": {"ID": [{"type": "Pay_Group_ID", "_value_1": "PG1"}]},
    }
    assert len(result) == 2 and result[0]["Payment_Date"] == "2023-01-15"
