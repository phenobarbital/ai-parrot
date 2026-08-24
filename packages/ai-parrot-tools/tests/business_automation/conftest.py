"""Shared fixtures for BusinessAutomationToolkit tests (FEAT-453 TASK-2390).

An "acme-books" fixture domain is used throughout — never a real site name
— matching the anonymized-fixtures convention the rest of the feature uses.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot_tools.business_automation.models import BusinessOperation, OperationKind
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
from parrot_tools.scraping import (
    FlowNode,
    FlowResult,
    ParamSpec,
    ScrapingFlow,
    TemplatePlan,
)


@pytest.fixture
def invoice_template() -> TemplatePlan:
    return TemplatePlan(
        name="invoice_flow",
        objective_template="Issue an invoice for {{client}}",
        url_template="http://acme-books.test/invoices/new",
        params=[ParamSpec(name="client", type="string")],
        steps_template=[
            {"action": "navigate", "url": "{{url}}"},
            {"action": "fill", "selector": "#client", "value": "{{client}}"},
        ],
    )


@pytest.fixture
def business_flows() -> dict:
    return {
        "issue_invoice_flow": ScrapingFlow(
            name="issue_invoice_flow", nodes=[FlowNode(id="n1", plan_ref="invoice_flow")]
        ),
        "draft_invoice_flow": ScrapingFlow(
            name="draft_invoice_flow", nodes=[FlowNode(id="n1", plan_ref="invoice_flow")]
        ),
    }


@pytest.fixture
def business_operations() -> dict:
    return {
        "issue_invoice": BusinessOperation(
            name="issue_invoice",
            description="Issue an invoice (legal effect — gated)",
            kind=OperationKind.SUBMIT,
            flow_ref="issue_invoice_flow",
        ),
        "draft_invoice": BusinessOperation(
            name="draft_invoice",
            description="Assemble an invoice draft (no legal effect)",
            kind=OperationKind.DRAFT,
            flow_ref="draft_invoice_flow",
        ),
    }


@pytest.fixture
def approving_human_manager():
    """A minimal HumanInteractionManager stand-in that always approves."""

    class _ApprovingHumanManager:
        def __init__(self) -> None:
            self.calls = []

        async def request_human_input(self, interaction, channel):
            self.calls.append((interaction, channel))
            return SimpleNamespace(timed_out=False, consolidated_value=True)

    return _ApprovingHumanManager()


class SpyConfirmationGuard:
    """Records every confirm() call; returns a fixed decision."""

    def __init__(self, *, allow: bool = True, status: str = "confirmed", reason: str = "ok"):
        self.confirm_calls = []
        self._allow = allow
        self._status = status
        self._reason = reason

    async def confirm(self, *, tool, parameters, permission_context=None):
        self.confirm_calls.append((tool, parameters))
        return SimpleNamespace(allowed=self._allow, status=self._status, reason=self._reason, parameters=parameters)


@pytest.fixture
def spy_guard():
    return SpyConfirmationGuard()


def _make_toolkit(
    tmp_path, invoice_template, business_flows, business_operations, human_manager=None
) -> BusinessAutomationToolkit:
    toolkit = BusinessAutomationToolkit(
        plans_dir=tmp_path,
        browser=None,
        human_manager=human_manager,
        operations=business_operations,
        flows=business_flows,
        templates={"invoice_flow": invoice_template},
    )
    # Bypass the real browser/FlowExecutor lifecycle for unit tests: mark the
    # toolkit as already-opened and inject a fake executor whose run()
    # always reports success. Tests that care about _open()/_ensure_open()
    # itself (e.g. the fail-closed gate test) do NOT call this helper.
    toolkit._opened = True
    toolkit._flow_executor = AsyncMock()
    toolkit._flow_executor.run = AsyncMock(return_value=FlowResult(flow_name="fake", success=True))
    return toolkit


@pytest.fixture
def toolkit(tmp_path, invoice_template, business_flows, business_operations, spy_guard):
    tk = _make_toolkit(tmp_path, invoice_template, business_flows, business_operations)
    tk._confirmation_guard = spy_guard
    return tk


@pytest.fixture
def plans_dir(tmp_path):
    return tmp_path
