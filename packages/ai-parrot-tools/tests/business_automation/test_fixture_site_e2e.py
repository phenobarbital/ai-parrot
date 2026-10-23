"""End-to-end integration tests against a real browser, a real
`ExecutionPlanToolkit`/`ToolManager`/`WorkingMemoryToolkit` stack, and the
real `local_fixture_site` (FEAT-455, Module 3).

Proves two of FEAT-453's own review-remediation mechanisms end to end,
not just via mocked-driver/mocked-executor unit tests:

- AC-12: `make_import_progress_listener()` (ingest.py) correctly receives
  REAL `node_completed` events from a REAL `AgentsFlow` run (not a
  manually-invoked callback), and re-building the plan after a simulated
  mid-run kill registers each remaining row exactly once.
- AC-8/AC-20: a real `ConfirmationGuard` + a real `BusinessAutomationToolkit`
  SUBMIT-kind operation genuinely pauses before any browser session opens,
  and completes against the real fixture site only after approval.

See this task's Completion Note for the two significant Codebase Contract
corrections found while implementing (`ExecutionPlanToolkit.plan_execute()`
does not accept a pre-built `ExecutionPlan` at all — `_run_plan()` is the
real integration point; `run_operation()` itself is fire-and-forget, so a
plan node's tool call needs a poll-to-completion wrapper mirroring
`smoke.py`'s own `run_smoke_check()` pattern) and the deliberate choice to
reuse FEAT-453's own `_ApprovingHumanManager` stand-in rather than build a
full `HumanChannel` protocol implementation from scratch.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest
from parrot.human.manager import HumanInteractionManager
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit
from parrot.tools.manager import ToolManager
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from parrot_tools.business_automation.ingest import (
    build_import_plan,
    make_import_progress_listener,
)
from parrot_tools.business_automation.models import BusinessOperation, OperationKind
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
from parrot_tools.scraping import FlowNode, ScrapingFlow, TemplatePlan
from playwright.async_api import async_playwright

from tests.scraping.fixtures.local_site import local_fixture_site

__all__ = ["local_fixture_site"]  # re-exported fixture


@pytest.fixture
async def real_browser():
    """A real, launched (raw) Playwright ``Browser``.

    ``BusinessAutomationToolkit``'s ``FlowExecutor``/``SessionManager``
    need the raw ``Browser`` object (``.new_context()``) — a different
    layer than TASK-2408's ``real_playwright_driver`` (an ``AbstractDriver``
    wrapper). Skips (not fails) when Chromium is not installed.
    """
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — any launch failure means "skip"
        pytest.skip(f"Real Chromium is not available in this environment: {exc}")

    try:
        yield browser
    finally:
        await browser.close()
        await playwright.stop()


@pytest.fixture
def three_row_xlsx(tmp_path):
    path = tmp_path / "statement.xlsx"
    pd.DataFrame(
        [
            {"client": "ACME", "amount": "100.00"},
            {"client": "Beta Corp", "amount": "42.50"},
            {"client": "Gamma LLC", "amount": "7.25"},
        ]
    ).to_excel(path, index=False)
    return path


def _record_row_plumbing(local_fixture_site) -> tuple:
    """A test-local DRAFT operation navigating to ``/cookie-check`` per row.

    Deliberately does NOT reuse the acme-books fixtures' own
    ``clients_flow`` (``http://acme-books.test/...`` — never resolvable);
    this points at the real, local fixture site instead.
    """
    template = TemplatePlan(
        name="record_row_flow",
        objective_template="Record one row",
        url_template=str(local_fixture_site.make_url("/cookie-check")),
        steps_template=[{"action": "navigate", "url": "{{url}}"}],
    )
    flow = ScrapingFlow(name="record_row_flow", nodes=[FlowNode(id="n1", plan_ref="record_row_flow")])
    operation = BusinessOperation(
        name="record_row",
        description="Test-only DRAFT operation for AC-12 resume verification",
        kind=OperationKind.DRAFT,
        flow_ref="record_row_flow",
    )
    return operation, flow, template


def _make_run_operation_tool(toolkit: BusinessAutomationToolkit):
    """Wrap ``BusinessAutomationToolkit.run_operation()`` with a
    poll-to-completion loop — mirrors ``smoke.py``'s own
    ``run_smoke_check()`` pattern (FEAT-453 TASK-2395). ``run_operation()``
    itself only returns ``{"status": "started", "run_id": ...}``
    immediately (background execution); a plan node's tool call needs to
    wait for the actual per-row outcome, or ``AgentsFlow`` would mark every
    node "done" the instant the browser run merely *starts*.
    """

    async def _run_and_wait(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await toolkit.run_operation(name, params or {})
        if result.get("status") != "started":
            return result
        run_id = result["run_id"]
        for _ in range(200):  # bounded: 200 * 0.1s = 20s ceiling per row
            record = toolkit._runs.get(run_id, {})
            if record.get("status") != "running":
                return record
            await asyncio.sleep(0.1)
        return toolkit._runs.get(run_id, {"status": "timeout"})

    return _run_and_wait


class TestExpenseImportResumesFromCheckpoint:
    """AC-12: a mid-run kill must resume without re-registering rows."""

    async def test_no_duplicate_registrations_after_simulated_kill(
        self, local_fixture_site, real_browser, three_row_xlsx
    ):
        operation, flow, template = _record_row_plumbing(local_fixture_site)
        toolkit = BusinessAutomationToolkit(
            plans_dir=three_row_xlsx.parent,
            browser=real_browser,
            operations={"record_row": operation},
            flows={"record_row_flow": flow},
            templates={"record_row_flow": template},
        )

        bundle = await build_import_plan(three_row_xlsx, period="2026-Q1", operation="record_row")
        assert bundle.plan is not None and len(bundle.plan.nodes) == 3
        digest = bundle.import_run.statement_digest
        listener = make_import_progress_listener("record_row", digest)

        # Simulate a mid-run kill: the 2nd tool call (row index 1) raises,
        # so AgentsFlow never dispatches row 2 (it depends on row 1) —
        # preferred over actually cancelling a background task per the
        # spec's own Open Questions (far less flaky).
        real_tool = _make_run_operation_tool(toolkit)
        call_count = {"n": 0}

        async def _flaky_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated mid-run kill")
            return await real_tool(name, params)

        manager = ToolManager()
        manager.register_tool(
            name="run_operation",
            description="Run a named business operation and wait for its outcome",
            input_schema={"type": "object", "properties": {}},
            function=_flaky_tool,
        )
        ep_toolkit = ExecutionPlanToolkit(
            tool_manager=manager,
            working_memory=WorkingMemoryToolkit(),
            soft_timeout=30.0,
            on_node_event=listener,
        )

        await ep_toolkit._run_plan(bundle.plan, source="plan_name")

        # Exactly row 0 completed before the simulated kill.
        resumed = await build_import_plan(three_row_xlsx, period="2026-Q1", operation="record_row")
        assert resumed.already_completed_rows == 1
        assert resumed.remaining_row_count == 2
        assert len(resumed.plan.nodes) == 2

        # Run the remainder with a non-flaky tool this time.
        manager2 = ToolManager()
        manager2.register_tool(
            name="run_operation",
            description="Run a named business operation and wait for its outcome",
            input_schema={"type": "object", "properties": {}},
            function=_make_run_operation_tool(toolkit),
        )
        ep_toolkit2 = ExecutionPlanToolkit(
            tool_manager=manager2,
            working_memory=WorkingMemoryToolkit(),
            soft_timeout=30.0,
            on_node_event=listener,
        )
        await ep_toolkit2._run_plan(resumed.plan, source="plan_name")

        # No duplicates, no gaps: all 3 rows completed exactly once.
        final = await build_import_plan(three_row_xlsx, period="2026-Q1", operation="record_row")
        assert final.fully_completed is True
        assert final.already_completed_rows == 3


class TestSubmitGateEndToEnd:
    """AC-8/AC-20: a SUBMIT operation pauses before any browser session
    opens, and completes against the real fixture site only after
    approval.

    Uses FEAT-453's own ``_ApprovingHumanManager``-style stand-in
    (``tests/business_automation/conftest.py``) rather than a full real
    ``HumanChannel`` protocol implementation: `run_operation()`'s own
    sequential code structure (already proven by FEAT-453's
    `test_denied_submit_never_opens_browser`/
    `test_fails_closed_without_human_manager`) guarantees the confirmation
    check completes *before* `_ensure_open()` regardless of how long
    approval takes — the additional value this real-browser test adds is
    that a REAL post-approval browser session actually opens and reaches
    the real fixture site, not a faster/slower approval round trip. The
    approving stand-in itself asserts the browser is NOT open at the
    moment it's invoked, for an active (not just structural) proof.
    """

    async def test_submit_pauses_then_completes_on_approval(self, local_fixture_site, real_browser, tmp_path):
        template = TemplatePlan(
            name="submit_flow",
            objective_template="Submit and visit",
            url_template=str(local_fixture_site.make_url("/cookie-check")),
            steps_template=[{"action": "navigate", "url": "{{url}}"}],
        )
        flow = ScrapingFlow(name="submit_flow", nodes=[FlowNode(id="n1", plan_ref="submit_flow")])
        operation = BusinessOperation(
            name="confirm_and_visit",
            description="Test-only SUBMIT operation for AC-8/AC-20 verification",
            kind=OperationKind.SUBMIT,
            flow_ref="submit_flow",
        )

        approval_calls = []

        class _AssertNotOpenYetApprovingManager:
            """Mirrors conftest.py's ``_ApprovingHumanManager`` exactly,
            plus an active assertion that the toolkit's browser session is
            not open at the moment approval is requested."""

            def __init__(self, toolkit_ref: dict[str, BusinessAutomationToolkit]) -> None:
                self._toolkit_ref = toolkit_ref

            async def request_human_input(self, interaction, channel):
                toolkit = self._toolkit_ref["toolkit"]
                approval_calls.append(toolkit._opened)
                from types import SimpleNamespace

                return SimpleNamespace(timed_out=False, consolidated_value=True)

        toolkit_ref: dict[str, BusinessAutomationToolkit] = {}
        human_manager = _AssertNotOpenYetApprovingManager(toolkit_ref)
        toolkit = BusinessAutomationToolkit(
            plans_dir=tmp_path,  # unused: overrides given below
            browser=real_browser,
            human_manager=human_manager,
            operations={"confirm_and_visit": operation},
            flows={"submit_flow": flow},
            templates={"submit_flow": template},
        )
        toolkit_ref["toolkit"] = toolkit

        assert toolkit._opened is False

        result = await toolkit.run_operation("confirm_and_visit", {})
        assert result["status"] == "started"

        run_id = result["run_id"]
        for _ in range(100):  # bounded: 100 * 0.1s = 10s ceiling
            record = toolkit._runs.get(run_id, {})
            if record.get("status") != "running":
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("SUBMIT operation never finished running")

        # The gate was actually invoked, and — checked from INSIDE the
        # approval callback itself, not just by post-hoc ordering — the
        # browser was NOT open at that moment.
        assert approval_calls == [False]
        # The browser opened and the real navigation happened only AFTER
        # approval was recorded.
        assert toolkit._opened is True
        assert record.get("status") == "done"


class TestHumanInteractionManagerIsUnused:
    """Sanity guard: a real ``HumanInteractionManager`` is importable and
    constructible with no arguments — confirming the Codebase Contract's
    verified signature, even though the test above uses the lighter
    approving stand-in instead (see that class's docstring)."""

    def test_constructs_with_no_arguments(self):
        manager = HumanInteractionManager()
        assert manager.channels == {}
