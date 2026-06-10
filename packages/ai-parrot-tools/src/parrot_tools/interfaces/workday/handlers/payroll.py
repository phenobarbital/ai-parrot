"""Workday Payroll read handlers (FEAT-232).

Single-call read handlers for the Workday Payroll WSDL, ported verbatim from the
former in-line ``WorkdaySOAPClient`` payroll methods in
``parrot_tools/workday/tool.py`` (operations + payload shapes preserved). Each
issues exactly one ``self.service.call_operation(operation=...)`` and returns a
JSON-serializable ``dict`` / ``list[dict]`` (no DataFrame) via zeep
``serialize_object`` — matching the legacy return shapes.

NOTE: operation names + payloads mirror the legacy implementation. The Payroll
WSDL (``payroll_v45_2.wsdl``) is not bundled in this checkout's ``env/workday/``;
unit tests mock ``call_operation`` and live calls require the WSDL to be present.
"""
from typing import Any, Dict, List, Optional

from zeep.helpers import serialize_object

from .base import WorkdayTypeBase


class PayrollBalancesType(WorkdayTypeBase):
    """Get_Payroll_Balances — payroll balances for a worker."""

    def _get_default_payload(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        *,
        worker_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        pay_component_group_ids: Optional[List[str]] = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "Request_References": {
                "Worker_Reference": {"ID": [{"type": "Employee_ID", "_value_1": worker_id}]}
            },
            "Response_Filter": {},
        }
        if start_date:
            request["Response_Filter"]["Start_Date"] = start_date
        if end_date:
            request["Response_Filter"]["End_Date"] = end_date
        if pay_component_group_ids:
            request["Request_Criteria"] = {
                "Pay_Component_Group_Reference": [
                    {"ID": [{"type": "Pay_Component_Group_ID", "_value_1": pcg_id}]}
                    for pcg_id in pay_component_group_ids
                ]
            }

        raw = await self.service.call_operation(operation="Get_Payroll_Balances", **request)
        return serialize_object(raw) if raw else {}


class PayrollResultsType(WorkdayTypeBase):
    """Get_Payroll_Results — historical / off-cycle payroll results for a worker."""

    def _get_default_payload(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        *,
        worker_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_details: bool = False,
        **_kwargs: Any,
    ) -> List[Dict[str, Any]]:
        request: Dict[str, Any] = {
            "Request_References": {
                "Worker_Reference": {"ID": [{"type": "Employee_ID", "_value_1": worker_id}]}
            },
            "Response_Filter": {},
        }
        if start_date:
            request["Response_Filter"]["Start_Date"] = start_date
        if end_date:
            request["Response_Filter"]["End_Date"] = end_date
        if include_details:
            request["Response_Group"] = {"Include_Payroll_Result_Lines": True}

        raw = await self.service.call_operation(operation="Get_Payroll_Results", **request)
        if not raw:
            return []
        serialized = serialize_object(raw)
        results = serialized.get("Payroll_Result_Data", []) if isinstance(serialized, dict) else []
        if not isinstance(results, list):
            results = [results]
        return results


class CompanyPaymentDatesType(WorkdayTypeBase):
    """Get_Company_Payment_Dates — company payment dates in a window."""

    def _get_default_payload(self) -> Dict[str, Any]:
        return {}

    async def execute(
        self,
        *,
        start_date: str,
        end_date: str,
        pay_group_id: Optional[str] = None,
        **_kwargs: Any,
    ) -> List[Dict[str, Any]]:
        request: Dict[str, Any] = {
            "Request_Criteria": {"Start_Date": start_date, "End_Date": end_date}
        }
        if pay_group_id:
            request["Request_Criteria"]["Pay_Group_Reference"] = {
                "ID": [{"type": "Pay_Group_ID", "_value_1": pay_group_id}]
            }

        raw = await self.service.call_operation(operation="Get_Company_Payment_Dates", **request)
        if not raw:
            return []
        serialized = serialize_object(raw)
        dates = serialized.get("Company_Payment_Dates_Data", []) if isinstance(serialized, dict) else []
        if not isinstance(dates, list):
            dates = [dates]
        return dates
