"""Fail-closed + confirmation-window tests for the SUBMIT gate (Decision D2).

FEAT-453 TASK-2390.
"""

from unittest.mock import AsyncMock

from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
from parrot_tools.scraping import FlowResult

from .conftest import SpyConfirmationGuard


class TestSubmitGate:
    async def test_submit_requires_confirmation(self, toolkit, spy_guard):
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert spy_guard.confirm_calls, "SUBMIT ran without a confirmation ask"

    async def test_draft_runs_unattended(self, toolkit, spy_guard):
        await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        assert not spy_guard.confirm_calls

    async def test_fails_closed_without_human_manager(
        self, plans_dir, invoice_template, business_flows, business_operations
    ):
        tk = BusinessAutomationToolkit(
            plans_dir=plans_dir,
            browser=None,
            human_manager=None,
            operations=business_operations,
            flows=business_flows,
            templates={"invoice_flow": invoice_template},
        )
        result = await tk.run_operation("issue_invoice", {"client": "ACME"})
        assert result["status"] == "cancelled"
        assert tk._opened is False, "browser opened despite a denied gate"

    async def test_draft_does_not_require_human_manager(
        self, plans_dir, invoice_template, business_flows, business_operations
    ):
        tk = BusinessAutomationToolkit(
            plans_dir=plans_dir,
            browser=None,
            human_manager=None,
            operations=business_operations,
            flows=business_flows,
            templates={"invoice_flow": invoice_template},
        )
        tk._opened = True
        tk._flow_executor = AsyncMock()
        tk._flow_executor.run = AsyncMock(return_value=FlowResult(flow_name="fake", success=True))
        result = await tk.run_operation("draft_invoice", {"client": "ACME"})
        assert result["status"] == "started"

    async def test_window_disabled_for_submit(self, toolkit, spy_guard):
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert len(spy_guard.confirm_calls) == 2, "second identical submit rode a window hit"

    async def test_confirm_window_seconds_is_zero_in_routing_meta(self, toolkit, spy_guard):
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        tool_stub, _params = spy_guard.confirm_calls[0]
        assert tool_stub.routing_meta["confirm_window_seconds"] == 0
        assert tool_stub.routing_meta["requires_confirmation"] is True

    async def test_denied_submit_never_opens_browser(
        self, plans_dir, invoice_template, business_flows, business_operations
    ):
        tk = BusinessAutomationToolkit(
            plans_dir=plans_dir,
            browser=None,
            human_manager=None,
            operations=business_operations,
            flows=business_flows,
            templates={"invoice_flow": invoice_template},
        )
        tk._confirmation_guard = SpyConfirmationGuard(allow=False, status="cancelled", reason="denied")
        result = await tk.run_operation("issue_invoice", {"client": "ACME"})
        assert result["status"] == "cancelled"
        assert tk._opened is False
        assert tk._flow_executor is None
