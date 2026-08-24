"""Tests for BusinessAutomationToolkit core (FEAT-453, Module 5).

FEAT-453 TASK-2390.
"""

from pathlib import Path

from parrot_tools.business_automation import toolkit as business_toolkit


class TestListAndDescribeOperations:
    async def test_list_operations(self, toolkit):
        result = await toolkit.list_operations()
        names = {op["name"] for op in result["operations"]}
        assert names == {"issue_invoice", "draft_invoice"}

    async def test_describe_known_operation(self, toolkit):
        result = await toolkit.describe_operation("issue_invoice")
        assert result["kind"] == "submit"
        assert result["name"] == "issue_invoice"

    async def test_describe_unknown_operation(self, toolkit):
        result = await toolkit.describe_operation("does_not_exist")
        assert result["status"] == "error"


class TestRunOperation:
    async def test_submit_requires_confirmation(self, toolkit, spy_guard):
        result = await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert spy_guard.confirm_calls, "SUBMIT ran without a confirmation ask"
        assert result["status"] == "started"
        assert "run_id" in result

    async def test_draft_runs_unattended(self, toolkit, spy_guard):
        result = await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        assert not spy_guard.confirm_calls
        assert result["status"] == "started"

    async def test_run_id_returned_immediately(self, toolkit):
        result = await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        assert result["status"] == "started"
        assert result["run_id"].startswith("run_")
        # The background task exists and is tracked (not awaited to completion
        # inline — that is the point of returning run_id immediately).
        assert result["run_id"] in toolkit._run_tasks

    async def test_unknown_operation_returns_error(self, toolkit):
        result = await toolkit.run_operation("does_not_exist", {})
        assert result["status"] == "error"

    async def test_confirmation_denied_returns_cancelled_without_running(self, toolkit, spy_guard):
        spy_guard._allow = False
        spy_guard._status = "cancelled"
        result = await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert result["status"] == "cancelled"
        toolkit._flow_executor.run.assert_not_awaited()

    async def test_missing_flow_ref_is_a_clean_error(self, toolkit):
        toolkit._flows.pop("draft_invoice_flow")
        result = await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        assert result["status"] == "error"

    async def test_invalid_params_fail_before_driver(self, toolkit):
        # Missing the required 'client' param -> template.bind() raises
        # inside _validate_flow(), which must run BEFORE _ensure_open()/the
        # flow executor is ever invoked.
        result = await toolkit.run_operation("draft_invoice", {})
        assert result["status"] == "error"
        toolkit._flow_executor.run.assert_not_awaited()


class TestResumeOperation:
    async def test_resume_unknown_run_id(self, toolkit):
        result = await toolkit.resume_operation("run_doesnotexist")
        assert result["status"] == "error"

    async def test_resume_known_run(self, toolkit):
        started = await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        run_id = started["run_id"]
        result = await toolkit.resume_operation(run_id)
        assert result["status"] == "started"
        assert result["resumed"] is True


class TestNoSiteIdentifiers:
    def test_package_has_no_site_identifiers(self):
        """AC: `grep -ci hooba` over the package returns 0 — the engine is
        domain-neutral. Scans every .py source file directly (no vendor
        name, e.g. the one used in the spec's motivating example, ever
        appears) — not just the one specific banned word."""
        pkg_dir = Path(business_toolkit.__file__).parent
        banned = ("hooba",)
        for py_file in pkg_dir.glob("*.py"):
            source = py_file.read_text().lower()
            for word in banned:
                assert word not in source, f"{py_file} contains banned identifier {word!r}"
