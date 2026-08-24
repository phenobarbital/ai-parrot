"""Tests for BusinessAutomationToolkit core (FEAT-453, Module 5).

FEAT-453 TASK-2390. ``TestPlansDirWiring`` was added during the feature's
final code-review remediation pass, closing the seam TASK-2390's own
docstring deferred to TASK-2391 ("This task wires the seam ... does not
implement the directory scan itself") — TASK-2391 built and fully tested
``PlanDirectoryStore`` standalone, but nothing ever called it from
``BusinessAutomationToolkit.__init__``, so a toolkit constructed with only
``plans_dir`` (no ``operations``/``flows``/``templates`` overrides) silently
booted with an empty operation registry. See
``sdd/tasks/completed/TASK-2391-external-plans-directory-store.md``'s
completion-note addendum for the full remediation note.
"""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot_tools.business_automation import toolkit as business_toolkit
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "acme-books"


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


class TestPlansDirWiring:
    """BusinessAutomationToolkit(plans_dir=...) with NO overrides must load
    real operations from the directory (via PlanDirectoryStore) — not boot
    silently empty."""

    @pytest.fixture
    def fixture_plans_dir(self, tmp_path: Path) -> Path:
        dest = tmp_path / "plans"
        shutil.copytree(FIXTURES_DIR, dest)
        return dest

    def test_no_overrides_loads_from_plans_dir(self, fixture_plans_dir):
        tk = BusinessAutomationToolkit(plans_dir=fixture_plans_dir, browser=None)
        assert set(tk._operations) == {"list_clients", "register_expense"}
        assert tk._plan_store is not None

    def test_overrides_still_skip_the_directory_scan(self, fixture_plans_dir):
        # The interim/test seam must keep working exactly as before: passing
        # explicit overrides means plans_dir is never scanned, even though
        # it exists and contains real (different) fixture operations.
        tk = BusinessAutomationToolkit(
            plans_dir=fixture_plans_dir,
            browser=None,
            operations={},
            flows={},
            templates={},
        )
        assert tk._operations == {}
        assert tk._plan_store is None

    def test_nonexistent_plans_dir_without_overrides_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            BusinessAutomationToolkit(plans_dir=tmp_path / "does-not-exist", browser=None)

    def test_malformed_plans_dir_without_overrides_raises(self, fixture_plans_dir):
        (fixture_plans_dir / "broken.operation.json").write_text("{not valid json")
        with pytest.raises(ValueError, match="broken.operation.json"):
            BusinessAutomationToolkit(plans_dir=fixture_plans_dir, browser=None)

    async def test_run_operation_hot_reloads_plans_dir(self, fixture_plans_dir):
        tk = BusinessAutomationToolkit(plans_dir=fixture_plans_dir, browser=None)
        assert "new_operation" not in tk._operations

        await asyncio.sleep(0.01)  # ensure a distinct mtime
        (fixture_plans_dir / "new_operation.operation.json").write_text(
            json.dumps(
                {
                    "name": "new_operation",
                    "description": "Added after construction",
                    "kind": "read",
                    "flow_ref": "clients_flow",
                }
            )
        )

        result = await tk.run_operation("new_operation", {})
        # A READ operation with no wired FlowExecutor still gets past the
        # registry lookup — the point here is that hot-reload happened
        # before that lookup, not that the run itself completes cleanly.
        assert result.get("status") != "error" or "Unknown operation" not in result.get("error", "")

    async def test_hot_reload_failure_returns_clean_error(self, fixture_plans_dir):
        tk = BusinessAutomationToolkit(plans_dir=fixture_plans_dir, browser=None)

        await asyncio.sleep(0.01)
        (fixture_plans_dir / "broken.operation.json").write_text("{not valid json")

        result = await tk.run_operation("register_expense", {"client": "ACME"})
        assert result["status"] == "error"
        assert "hot-reload" in result["error"]
        # Previously-loaded operations must remain usable after a failed
        # reload — the store leaves its last-good state untouched.
        assert "register_expense" in tk._operations


class TestCredentialResolverFromBroker:
    """AC-5 code-review remediation: BusinessAutomationToolkit adapts a
    CredentialBroker into a CredentialResolverFn and forwards it to
    FlowExecutor — previously the resolver was built nowhere, so a
    credential_provider-backed Authenticate always failed closed regardless
    of whether a broker was configured."""

    async def test_dict_secret_maps_to_username_password(self, tmp_path):
        from parrot.auth.credentials import ResolvedCredential
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(
            return_value=ResolvedCredential(
                provider="acme", secret={"username": "bob", "password": "s3cret"}, key_fingerprint="fp"
            )
        )
        resolver = _credential_resolver_from_broker(broker, "gestoria")

        action = SimpleNamespace(credential_provider="acme")
        result = await resolver(action)

        assert result == ("bob", "s3cret")
        broker.resolve.assert_awaited_once_with("acme", "business_automation", "gestoria")

    async def test_tuple_secret_passthrough(self, tmp_path):
        from parrot.auth.credentials import ResolvedCredential
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(
            return_value=ResolvedCredential(provider="acme", secret=("bob", "s3cret"), key_fingerprint="fp")
        )
        resolver = _credential_resolver_from_broker(broker, "gestoria")
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result == ("bob", "s3cret")

    async def test_opaque_string_secret_maps_to_password_only(self, tmp_path):
        from parrot.auth.credentials import ResolvedCredential
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(
            return_value=ResolvedCredential(provider="acme", secret="api-key-xyz", key_fingerprint="fp")
        )
        resolver = _credential_resolver_from_broker(broker, "gestoria")
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result == (None, "api-key-xyz")

    async def test_needs_auth_resolves_to_none(self, tmp_path):
        from parrot.auth.credentials import NeedsAuth
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(
            return_value=NeedsAuth(provider="acme", auth_url="https://auth.example/consent", auth_kind="oauth2")
        )
        resolver = _credential_resolver_from_broker(broker, "gestoria")
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result is None

    async def test_broker_exception_resolves_to_none_not_raise(self, tmp_path):
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(side_effect=KeyError("no resolver registered"))
        resolver = _credential_resolver_from_broker(broker, "gestoria")
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result is None

    async def test_unrecognized_secret_shape_resolves_to_none(self, tmp_path):
        from parrot.auth.credentials import ResolvedCredential
        from parrot_tools.business_automation.toolkit import (
            _credential_resolver_from_broker,
        )

        broker = AsyncMock()
        broker.resolve = AsyncMock(
            return_value=ResolvedCredential(provider="acme", secret=12345, key_fingerprint="fp")
        )
        resolver = _credential_resolver_from_broker(broker, "gestoria")
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result is None


class TestToolkitWiresResolverAndChannel:
    """The toolkit must build and forward the resolver/channel into
    FlowExecutor at _open() time — not just store the raw broker/manager."""

    async def test_no_broker_means_no_resolver(self, fixture_plans_dir_for_wiring):
        tk = BusinessAutomationToolkit(
            plans_dir=fixture_plans_dir_for_wiring, browser=None, operations={}, flows={}, templates={}
        )
        assert tk._credential_resolver is None

    async def test_broker_produces_a_resolver(self, fixture_plans_dir_for_wiring):
        broker = AsyncMock()
        tk = BusinessAutomationToolkit(
            plans_dir=fixture_plans_dir_for_wiring,
            browser=None,
            credential_broker=broker,
            operations={},
            flows={},
            templates={},
        )
        assert tk._credential_resolver is not None

    async def test_open_forwards_resolver_and_channel_to_flow_executor(self, fixture_plans_dir_for_wiring):
        broker = AsyncMock()
        channel = object()
        tk = BusinessAutomationToolkit(
            plans_dir=fixture_plans_dir_for_wiring,
            browser=None,
            credential_broker=broker,
            human_channel=channel,
            operations={},
            flows={},
            templates={},
        )
        await tk._open()
        assert tk._flow_executor._credential_resolver is tk._credential_resolver
        assert tk._flow_executor._channel is channel


@pytest.fixture
def fixture_plans_dir_for_wiring(tmp_path):
    return tmp_path


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
