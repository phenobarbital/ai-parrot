"""Tests for the SmokeCheck canary mechanism (FEAT-453, Decision D4).

FEAT-453 TASK-2395. All tests run against a mocked FlowExecutor (never a
real third-party site) — matching every other business_automation test in
this feature (e.g. TASK-2390's own test suite), since the actual
site-specific canary plan is Deliverable X, out of repo.
"""
from unittest.mock import AsyncMock

import pytest
from parrot.scheduler.inprocess import InProcessScheduler
from parrot_tools.business_automation.models import BusinessOperation, OperationKind
from parrot_tools.business_automation.smoke import (
    SmokeCheck,
    register_smoke,
    run_smoke_check,
)
from parrot_tools.scraping import FlowNode, FlowResult, ScrapingFlow, TemplatePlan


@pytest.fixture
def dashboard_ping_operation():
    return BusinessOperation(
        name="dashboard_ping",
        description="Log in and read the dashboard (canary — never writes)",
        kind=OperationKind.READ,
        flow_ref="dashboard_ping_flow",
    )


@pytest.fixture
def issue_invoice_operation():
    return BusinessOperation(
        name="issue_invoice",
        description="Issue an invoice (legal effect — gated)",
        kind=OperationKind.SUBMIT,
        flow_ref="invoice_flow",
    )


@pytest.fixture
def toolkit(tmp_path, dashboard_ping_operation, issue_invoice_operation):
    from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit

    tk = BusinessAutomationToolkit(
        plans_dir=tmp_path,
        browser=None,
        human_manager=None,
        operations={
            "dashboard_ping": dashboard_ping_operation,
            "issue_invoice": issue_invoice_operation,
        },
        flows={
            "dashboard_ping_flow": ScrapingFlow(
                name="dashboard_ping_flow", nodes=[FlowNode(id="n1", plan_ref="dashboard_ping")]
            ),
        },
        templates={
            "dashboard_ping": TemplatePlan(
                name="dashboard_ping",
                objective_template="Ping the dashboard",
                url_template="http://acme-books.test/dashboard",
                steps_template=[{"action": "navigate", "url": "{{url}}"}],
            ),
        },
    )
    tk._opened = True
    tk._flow_executor = AsyncMock()
    tk._flow_executor.run = AsyncMock(return_value=FlowResult(flow_name="fake", success=True))
    return tk


@pytest.fixture
def scheduler():
    return InProcessScheduler()


@pytest.fixture
def fake_channel():
    channel = AsyncMock()
    channel.alerts = []

    async def _record(recipient, message):
        channel.alerts.append(message)

    channel.send_notification = AsyncMock(side_effect=_record)
    return channel


async def _invoke_registered_job(scheduler: InProcessScheduler, job_id: str):
    """Directly await the callback registered under *job_id* — simulates a
    single cron fire without waiting on real cron timing."""
    job = scheduler._jobs[job_id]
    return await job.func()


class TestSmokeCheckRegistration:
    def test_refuses_submit_operation(self, toolkit, scheduler):
        with pytest.raises(ValueError, match="READ"):
            register_smoke(
                scheduler, toolkit, SmokeCheck(operation="issue_invoice", cron="0 * * * *")
            )

    def test_refuses_unregistered_operation(self, toolkit, scheduler):
        with pytest.raises(ValueError, match="not a registered"):
            register_smoke(
                scheduler, toolkit, SmokeCheck(operation="does_not_exist", cron="0 * * * *")
            )

    def test_registration_does_not_schedule_a_refused_check(self, toolkit, scheduler):
        with pytest.raises(ValueError):
            register_smoke(
                scheduler, toolkit, SmokeCheck(operation="issue_invoice", cron="0 * * * *")
            )
        assert scheduler._scheduler.get_jobs() == []

    def test_accepts_read_operation(self, toolkit, scheduler):
        job_id = register_smoke(
            scheduler, toolkit, SmokeCheck(operation="dashboard_ping", cron="0 * * * *")
        )
        assert scheduler._scheduler.get_job(job_id) is not None
        assert "dashboard_ping" in job_id


class TestSmokeCheckExecution:
    async def test_pass_is_silent(self, toolkit, scheduler, fake_channel):
        job_id = register_smoke(
            scheduler,
            toolkit,
            SmokeCheck(operation="dashboard_ping", cron="0 * * * *"),
            channel=fake_channel,
        )
        record = await _invoke_registered_job(scheduler, job_id)
        assert record["status"] == "done"
        assert not fake_channel.alerts

    async def test_failure_alerts_with_operation_node_and_error(
        self, toolkit, scheduler, fake_channel
    ):
        toolkit._flow_executor.run = AsyncMock(
            return_value=FlowResult(
                flow_name="dashboard_ping_flow",
                success=False,
                error_message="dashboard selector not found",
                node_results={
                    "n1": {"success": False, "error_message": "dashboard selector not found"}
                },
            )
        )
        job_id = register_smoke(
            scheduler,
            toolkit,
            SmokeCheck(operation="dashboard_ping", cron="0 * * * *"),
            channel=fake_channel,
        )
        record = await _invoke_registered_job(scheduler, job_id)

        assert record["status"] == "failed"
        assert fake_channel.alerts, "a failing smoke check must alert"
        alert = fake_channel.alerts[0]
        assert "dashboard_ping" in alert
        assert "n1" in alert
        assert "dashboard selector not found" in alert

    async def test_run_smoke_check_directly(self, toolkit, fake_channel):
        check = SmokeCheck(operation="dashboard_ping", cron="0 * * * *")
        record = await run_smoke_check(toolkit, check, channel=fake_channel)
        assert record["status"] == "done"
        assert not fake_channel.alerts

    async def test_no_channel_does_not_raise_on_failure(self, toolkit):
        toolkit._flow_executor.run = AsyncMock(
            return_value=FlowResult(flow_name="x", success=False, error_message="boom")
        )
        check = SmokeCheck(operation="dashboard_ping", cron="0 * * * *")
        record = await run_smoke_check(toolkit, check, channel=None)
        assert record["status"] == "failed"

    async def test_registration_failure_before_run_alerts(self, toolkit, fake_channel):
        # Simulate run_operation itself returning an error (e.g. missing flow).
        toolkit._flows.clear()
        check = SmokeCheck(operation="dashboard_ping", cron="0 * * * *")
        record = await run_smoke_check(toolkit, check, channel=fake_channel)
        assert record["status"] == "error"
        assert fake_channel.alerts
        assert "registration" in fake_channel.alerts[0]
