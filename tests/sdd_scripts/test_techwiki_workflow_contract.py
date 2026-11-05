"""YAML-level contract for ``.github/workflows/techwiki.yml`` (FEAT-801 AC-12)."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/techwiki.yml"


class TestTechwikiWorkflow:
    """Assertions on the techwiki sync workflow's triggers, permissions and steps."""

    @pytest.fixture(autouse=True)
    def load_workflow(self) -> None:
        """Parse the workflow once per test."""
        assert WORKFLOW.exists(), "techwiki.yml not found"
        self.wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_trigger_release_published(self) -> None:
        """Publishing happens only on a published release."""
        assert self.wf["on"]["release"]["types"] == ["published"]

    def test_trigger_pull_request_present(self) -> None:
        """Pull requests run the validation path, scoped by paths."""
        assert "pull_request" in self.wf["on"]
        paths = self.wf["on"]["pull_request"]["paths"]
        assert "wiki/**" in paths
        assert ".github/workflows/techwiki.yml" in paths

    def test_trigger_workflow_dispatch_present(self) -> None:
        """Manual runs are allowed (preview artifact only)."""
        assert "workflow_dispatch" in self.wf["on"]

    def test_permissions_contents_write(self) -> None:
        """The token is read-only workflow-wide; only the publish job may write (it pushes to the wiki)."""
        assert self.wf["permissions"]["contents"] == "read"
        assert self.wf["jobs"]["publish"]["permissions"]["contents"] == "write"
        assert "permissions" not in self.wf["jobs"]["bundle"]

    def test_bundle_checkout_does_not_persist_credentials(self) -> None:
        """The PR-executed bundle job must not leave the token in the checkout's git config."""
        checkout = next(s for s in self.wf["jobs"]["bundle"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
        assert checkout["with"]["persist-credentials"] is False

    def test_concurrency_serialises_runs(self) -> None:
        """Runs are serialised per event/ref and never cancelled mid-push."""
        concurrency = self.wf["concurrency"]
        assert "github.event_name" in concurrency["group"]
        assert concurrency["cancel-in-progress"] is False

    def test_publish_only_on_release(self) -> None:
        """The publish job is gated on the release event."""
        publish = self.wf["jobs"]["publish"]
        assert publish["if"] == "github.event_name == 'release'"
        assert publish["needs"] == "bundle"

    def test_bundle_uses_strict(self) -> None:
        """The bundle installs the techwiki extra and runs in strict JSON mode."""
        bundle_job = self.wf["jobs"]["bundle"]
        steps_text = yaml.dump(bundle_job["steps"])
        assert "--strict" in steps_text
        assert "--extra techwiki" in steps_text
        assert "--json" in steps_text

    def test_pr_uses_dry_run(self) -> None:
        """Pull-request runs pass --dry-run to the bundle command."""
        bundle_job = self.wf["jobs"]["bundle"]
        steps_text = yaml.dump(bundle_job["steps"])
        assert "--dry-run" in steps_text
        build = next(s for s in bundle_job["steps"] if s.get("name") == "Build bundle")
        assert '"$EVENT_NAME" = "pull_request"' in build["run"]
        assert build["env"]["EVENT_NAME"] == "${{ github.event_name }}"

    def test_bundle_artifact_always_uploaded(self) -> None:
        """The bundle artifact is uploaded even when the bundle step fails."""
        steps = self.wf["jobs"]["bundle"]["steps"]
        upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        assert upload and upload[0]["if"] == "always()"
