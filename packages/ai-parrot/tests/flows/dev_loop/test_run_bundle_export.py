"""Run-bundle export/teardown tests (FEAT-378 TASK-1929).

Drives ``DevLoopRunner.run()`` end-to-end with a fake flow (mirroring
``test_runner_host.py``'s ``_FakeFlow`` pattern) so ``_close_host`` runs
for real, then asserts the two new artifacts
(``{run_id}.bundle.json``/``{run_id}.report.md``) land next to the
existing terminal snapshot under ``conf.OUTPUT_DIR/dev_loop_runs/`` (the
``_isolate_dev_loop_run_artifacts`` autouse fixture in ``conftest.py``
already redirects ``conf.OUTPUT_DIR`` to ``tmp_path``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

import parrot.flows.dev_loop.runner as _runner_module
from parrot import conf
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    RunBundle,
    ShellCriterion,
    build_run_bundle,
    render_markdown,
)


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


class _FakeFlow:
    """Minimal ``run_flow`` stub — no real node graph, no redis."""

    def __init__(
        self,
        *,
        status: FlowStatus = FlowStatus.COMPLETED,
        responses: Dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.responses = responses or {}
        self.calls: List[Any] = []

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.calls.append(ctx)
        return FlowResult(
            output=ctx.shared_data.get("run_id"),
            status=self.status,
            responses=dict(self.responses),
        )


def _bundle_paths(run_id: str) -> tuple[Path, Path]:
    out_dir = Path(conf.OUTPUT_DIR) / "dev_loop_runs"
    return out_dir / f"{run_id}.bundle.json", out_dir / f"{run_id}.report.md"


@pytest.mark.asyncio
async def test_close_host_writes_bundle_and_report(tmp_path, brief):
    flow = _FakeFlow(responses={"deployment_handoff": {"pr_url": "http://pr/1"}})
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-bundle-export1")
    assert result.status == FlowStatus.COMPLETED

    bundle_path, report_path = _bundle_paths("run-bundle-export1")
    assert bundle_path.exists()
    assert report_path.exists()

    # bundle.json is valid JSON that round-trips through RunBundle.
    raw = json.loads(bundle_path.read_text())
    bundle = RunBundle.model_validate(raw)
    assert bundle.run_id == "run-bundle-export1"
    assert bundle.outcome == "succeeded"

    # report.md is non-empty and contains the run id.
    report = report_path.read_text()
    assert report.strip()
    assert "run-bundle-export1" in report

    # The existing terminal snapshot is unaffected (sibling artifact).
    snapshot_path = Path(conf.OUTPUT_DIR) / "dev_loop_runs" / "run-bundle-export1.snapshot.json"
    assert snapshot_path.exists()


@pytest.mark.asyncio
async def test_failed_run_still_exports(tmp_path, brief):
    flow = _FakeFlow(status=FlowStatus.FAILED)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-bundle-export2")
    assert result.status == FlowStatus.FAILED

    bundle_path, report_path = _bundle_paths("run-bundle-export2")
    assert bundle_path.exists()
    assert report_path.exists()

    bundle = RunBundle.model_validate_json(bundle_path.read_text())
    assert bundle.outcome == "failed"


@pytest.mark.asyncio
async def test_bundle_export_failure_never_breaks_teardown(tmp_path, brief, monkeypatch):
    """A raising ``build_run_bundle`` must not break run teardown — the run
    still completes, the host is still discarded, and the (independent)
    terminal snapshot is still persisted."""

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    # Object-form setattr (not the dotted-string form): the string form's
    # import-path resolution is unreliable here because
    # test_lazy_import.py's tests aggressively delete/reimport/restore
    # every ``parrot.flows.dev_loop*`` entry in ``sys.modules`` — when this
    # test runs after one of those, the string-path resolver can land on a
    # transient module reference and the patched attribute doesn't stick.
    # Patching the already-imported module object directly sidesteps that.
    monkeypatch.setattr(_runner_module, "build_run_bundle", _raise)

    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-bundle-export3")
    assert result.status == FlowStatus.COMPLETED
    # Host lifecycle unaffected by the export failure.
    assert runner.get_host("run-bundle-export3") is None

    # No bundle/report were written...
    bundle_path, report_path = _bundle_paths("run-bundle-export3")
    assert not bundle_path.exists()
    assert not report_path.exists()
    # ...but the independent terminal snapshot still was (order-independence).
    snapshot_path = Path(conf.OUTPUT_DIR) / "dev_loop_runs" / "run-bundle-export3.snapshot.json"
    assert snapshot_path.exists()


@pytest.mark.parametrize(
    "case_id, node_id, response, expected_outcome",
    [
        # FAILED — nothing was delivered.
        ("blocked-deployment", "deployment_handoff",
         {"status": "blocked", "error": "push failed"}, "failed"),
        ("blocked-feature", "feature_handoff",
         {"status": "blocked", "error": "PR create failed"}, "failed"),
        ("blocked-revision", "revision_handoff",
         {"status": "blocked", "error": "push: boom", "branch": "b"}, "failed"),
        # FAILED — QA failed and the run escalated; the handoff node was
        # SKIPPED, so there is no handoff response at all.
        ("escalated", "failure_handler",
         {"status": "escalated", "issue_key": "OPS-1"}, "failed"),
        # SUCCEEDED — degraded but delivered: the revision WAS pushed, only
        # the courtesy PR comment failed.
        ("comment-failed", "revision_handoff",
         {"status": "comment_failed", "pr_number": 7, "branch": "b"}, "succeeded"),
    ],
)
@pytest.mark.asyncio
async def test_close_host_outcome_from_terminal_status(
    tmp_path, brief, case_id, node_id, response, expected_outcome,
):
    flow = _FakeFlow(responses={node_id: response})
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    run_id = f"run-terminal-{case_id}"

    result = await runner.run(brief, run_id=run_id)
    # The terminal node never raises, so the flow itself still reports
    # COMPLETED — that is deliberate (spec Non-Goals); only the RECORDED
    # outcome is corrected.
    assert result.status == FlowStatus.COMPLETED

    bundle_path, _ = _bundle_paths(run_id)
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == expected_outcome
    # No PR url in any of these canned payloads.
    assert bundle.developed.pr_url == ""


@pytest.mark.asyncio
async def test_close_host_ignores_blocked_status_on_non_terminal_node(tmp_path, brief):
    """A non-terminal node using the same status vocabulary must NOT flip
    the run outcome — the scan is an explicit node-id allowlist."""
    flow = _FakeFlow(responses={
        "development": {"status": "blocked", "error": "not a terminal node"},
        "deployment_handoff": {"status": "ready_to_deploy", "pr_url": "http://pr/9"},
    })
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    await runner.run(brief, run_id="run-terminal-allowlist")

    bundle_path, _ = _bundle_paths("run-terminal-allowlist")
    bundle = RunBundle.model_validate(json.loads(bundle_path.read_text()))
    assert bundle.outcome == "succeeded"
    assert bundle.developed.pr_url == "http://pr/9"


def test_package_exports():
    """`from parrot.flows.dev_loop import RunBundle, build_run_bundle,
    render_markdown` must work (TASK-1929 package-export requirement)."""
    assert RunBundle is not None
    assert callable(build_run_bundle)
    assert callable(render_markdown)
