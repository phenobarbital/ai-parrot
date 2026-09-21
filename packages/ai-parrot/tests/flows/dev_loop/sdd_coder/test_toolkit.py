"""Tests for SddCoderToolkit — MCP surface, arg validation, error mapping (TASK-3122)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure
from parrot.flows.dev_loop.sdd_coder.models import CoderResult, RosterConfig
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.mcp.adapter import MCPToolAdapter


def _toolkit(three_seat_roster):
    return SddCoderToolkit(roster=three_seat_roster)


EXPECTED_TOOLS = {
    "coder_plan",
    "coder_run_chunk",
    "coder_prepare_native",
    "coder_merge",
    "coder_wait",
    "coder_status",
    "coder_cleanup",
    "coder_record_feedback",
    "coder_record_review",
    "coder_feedback_report",
    # FEAT-559 M4: the three new execution lifecycle/suspension tools.
    "coder_begin_execution",
    "coder_end_execution",
    "coder_suspend_model",
    # FEAT-584 M2/R3: worker-reported native observation (no acceptance, no release).
    "coder_record_native_observation",
    # FEAT-584 M1b/R1b: purposeful, side-effect-free reads.
    "coder_task_context",
    "coder_delivery_report",
    # FEAT-584 M3/R2: recover a durable/paginated artifact a `compact`
    # response_mode referenced.
    "coder_read_artifact",
    # FEAT-584 M8/R8: deterministic background status + protected validation.
    "coder_bg_status",
    "coder_run_validation",
}


def test_toolkit_exposes_execution_lifecycle_tools(three_seat_roster):
    """Actual registered tool set contains the existing tools plus the new ones; no helper leaks into MCP."""
    toolkit = _toolkit(three_seat_roster)
    names = {t.name for t in toolkit.get_tools()}
    assert names == EXPECTED_TOOLS


def test_toolkit_accepts_roster_as_list_of_dicts():
    toolkit = SddCoderToolkit(roster=[{"label": "a", "backend": "nova"}])
    assert toolkit._engine.roster.seats[0].label == "a"


def test_toolkit_accepts_complexity_config_with_list_roster():
    """Both configuration paths deliver the same policy to the engine."""
    from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy

    complexity_config = {
        "version": "v1",
        "strong_models": [
            {"canonical_model": "gpt-5.6-terra", "backend": "codex", "model": "gpt-5.6-terra"},
            {"canonical_model": "sonnet-5", "backend": "claude", "model": "claude-sonnet-5"},
        ],
    }
    toolkit = SddCoderToolkit(
        roster=[{"label": "a", "backend": "nova"}],
        complexity=complexity_config,
    )
    assert toolkit._engine.roster.complexity.version == "v1"
    assert len(toolkit._engine.roster.complexity.strong_models) == 2


def test_toolkit_preserves_roster_config_complexity():
    """With RosterConfig and complexity omitted: preserve that object's policy."""
    from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy

    original_policy = ComplexityPolicy(
        version="v1",
        strong_models=[
            {"canonical_model": "gpt-5.6-terra", "backend": "codex", "model": "gpt-5.6-terra"},
        ],
    )
    roster_config = RosterConfig(
        seats=[{"label": "a", "backend": "nova"}],
        complexity=original_policy,
    )
    toolkit = SddCoderToolkit(roster=roster_config)
    assert toolkit._engine.roster.complexity.version == "v1"
    assert len(toolkit._engine.roster.complexity.strong_models) == 1


def test_toolkit_validates_complexity_override():
    """With both object and explicit complexity: validate a copied config with the explicit override."""
    from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy

    original_policy = ComplexityPolicy(
        version="v1",
        strong_models=[
            {"canonical_model": "gpt-5.6-terra", "backend": "codex", "model": "gpt-5.6-terra"},
        ],
    )
    roster_config = RosterConfig(
        seats=[{"label": "a", "backend": "nova"}],
        complexity=original_policy,
    )
    # Valid override
    complexity_config = {
        "version": "v1",
        "strong_models": [
            {"canonical_model": "sonnet-5", "backend": "claude", "model": "claude-sonnet-5"},
        ],
    }
    toolkit = SddCoderToolkit(roster=roster_config, complexity=complexity_config)
    assert toolkit._engine.roster.complexity.version == "v1"
    assert len(toolkit._engine.roster.complexity.strong_models) == 1
    # Original config should be unchanged
    assert len(original_policy.strong_models) == 1


def test_toolkit_rejects_malformed_complexity_config():
    """Malformed policy raises validation error."""
    from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy

    malformed_config = {
        "version": "v1",
        "strong_models": [
            {"canonical_model": "gpt-5.6-terra", "backend": "codex", "model": "gpt-5.6-terra"},
        ],
        "bands": {"cyclomatic_max": (-1, 10)},  # Negative band bound
    }
    with pytest.raises(ValidationError):
        SddCoderToolkit(
            roster=[{"label": "a", "backend": "nova"}],
            complexity=malformed_config,
        )


VALID_EXECUTION_ID = "11111111-1111-4111-8111-111111111111"


async def test_toolkit_pre_execute_rejects_bad_args(three_seat_roster):
    """A bad (non-execution_id) field, e.g. a relative worktree, is still `invalid_arguments`
    even with a valid execution_id present."""
    toolkit = _toolkit(three_seat_roster)
    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_run_chunk", feature="f", worktree="rel", task_ids=["TASK-1"], execution_id=VALID_EXECUTION_ID
        )
    assert excinfo.value.code == "invalid_arguments"


async def test_toolkit_pre_execute_ignores_permission_context(three_seat_roster):
    """`ToolkitTool._execute` always injects `_permission_context` (verified:
    toolkit.py:176-182) even for toolkits that don't use it — `_pre_execute`
    must not reject valid args just because that key is present."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_plan", feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID, _permission_context=None
    )  # must not raise


async def test_missing_execution_rejected(three_seat_roster):
    """A missing execution_id maps to `execution_required`, not the generic `invalid_arguments` --
    before any model work (probe/dispatch) could ever occur."""
    toolkit = _toolkit(three_seat_roster)
    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute("coder_plan", feature="f", worktree="/abs")
    assert excinfo.value.code == "execution_required"

    # An invalid (non-UUID) execution_id is still the generic invalid_arguments, not execution_required.
    with pytest.raises(CoderFailure) as excinfo2:
        await toolkit._pre_execute("coder_plan", feature="f", worktree="/abs", execution_id="not-a-uuid")
    assert excinfo2.value.code == "invalid_arguments"

    # coder_feedback_report never requires (or accepts) an execution_id at all.
    await toolkit._pre_execute("coder_feedback_report", feature="f", worktree="/abs")


def test_registered_schemas_require_execution_identity(three_seat_roster):
    """The seven scoped orchestration/review tool schemas mark execution_id required;
    coder_wait/coder_status/coder_feedback_report never do."""
    toolkit = _toolkit(three_seat_roster)
    scoped = {
        "coder_plan",
        "coder_run_chunk",
        "coder_prepare_native",
        "coder_merge",
        "coder_cleanup",
        "coder_record_feedback",
        "coder_record_review",
        "coder_record_native_observation",
        "coder_task_context",
        "coder_delivery_report",
        "coder_read_artifact",
        "coder_bg_status",
        "coder_run_validation",
    }
    unscoped = {"coder_wait", "coder_status", "coder_feedback_report"}
    for tool in toolkit.get_tools():
        parameters = tool.get_schema()["parameters"]
        required = set(parameters.get("required", []))
        if tool.name in scoped:
            assert "execution_id" in required, f"{tool.name} schema must require execution_id"
        elif tool.name in unscoped:
            assert "execution_id" not in parameters.get("properties", {}), f"{tool.name} must not expose execution_id"


VALID_OBSERVATION = {
    "event_id": "evt-toolkit-1",
    "task_id": "TASK-1",
    "attempt_uid": "abcd1234abcd1234abcd1234abcd1234",
    "agent_id": "agent-1",
    "observed_at": "2026-09-21T00:00:00+00:00",
    "kind": "finished",
    "evidence_ref": {
        "artifact_id": "e" * 64,
        "sha256": "e" * 64,
        "relative_path": "handback/agent-1.json",
        "size_bytes": 5,
        "media_type": "application/json",
    },
}


async def test_record_native_observation_pre_execute_validates_schema(three_seat_roster):
    """The nested `observation` schema is validated BEFORE the engine ever runs."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_record_native_observation",
        feature="f",
        worktree="/abs",
        execution_id=VALID_EXECUTION_ID,
        observation=VALID_OBSERVATION,
    )  # must not raise

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_record_native_observation",
            feature="f",
            worktree="/abs",
            execution_id=VALID_EXECUTION_ID,
            observation={**VALID_OBSERVATION, "kind": "not-a-kind"},
        )
    assert excinfo.value.code == "invalid_arguments"


async def test_record_native_observation_routes_through_run(three_seat_roster, monkeypatch):
    """`coder_record_native_observation` maps engine success/failure through `_run` like every other tool."""
    from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef

    toolkit = _toolkit(three_seat_roster)
    seen = {}

    async def _record(feature, worktree, execution_id, observation):
        seen["args"] = (feature, worktree, execution_id, observation)
        return EvidenceRef(
            artifact_id="evt-toolkit-1",
            sha256="e" * 64,
            relative_path="executions/x/events.jsonl",
            size_bytes=10,
            media_type="application/x-ndjson",
        )

    monkeypatch.setattr(toolkit._engine, "record_native_observation", _record)
    result = await toolkit.coder_record_native_observation(
        feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID, observation=VALID_OBSERVATION
    )
    assert result.status == "ok"
    assert result.data["artifact_id"] == "evt-toolkit-1"
    assert seen["args"][3] == VALID_OBSERVATION

    async def _raise(*args, **kwargs):
        raise CoderFailure("attempt_not_found", "x")

    monkeypatch.setattr(toolkit._engine, "record_native_observation", _raise)
    result = await toolkit.coder_record_native_observation(
        feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID, observation=VALID_OBSERVATION
    )
    assert result.status == "error"
    assert result.error.code == "attempt_not_found"


async def test_task_context_pre_execute_validates_schema(three_seat_roster):
    """`coder_task_context` shares `CoderPrepareNativeArgs`' shape: task_id/execution_id/absolute worktree."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_task_context", feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )  # must not raise

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_task_context", feature="f", worktree="/abs", task_id="not-a-task-id", execution_id=VALID_EXECUTION_ID
        )
    assert excinfo.value.code == "invalid_arguments"

    with pytest.raises(CoderFailure) as excinfo2:
        await toolkit._pre_execute("coder_task_context", feature="f", worktree="/abs", task_id="TASK-1")
    assert excinfo2.value.code == "execution_required"


async def test_delivery_report_pre_execute_validates_schema(three_seat_roster):
    """`coder_delivery_report` shares the same strict argument shape."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_delivery_report", feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )  # must not raise

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_delivery_report", feature="f", worktree="rel", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
        )
    assert excinfo.value.code == "invalid_arguments"


async def test_task_context_routes_through_run(three_seat_roster, monkeypatch):
    """`coder_task_context` maps a plain dict engine result through `_run` like every other tool."""
    toolkit = _toolkit(three_seat_roster)
    seen = {}

    async def _task_context(feature, worktree, task_id, execution_id):
        seen["args"] = (feature, worktree, task_id, execution_id)
        return {"task_id": task_id, "ready": True, "blockers": []}

    monkeypatch.setattr(toolkit._engine, "task_context", _task_context)
    result = await toolkit.coder_task_context(
        feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )
    assert result.status == "ok"
    assert result.data == {"task_id": "TASK-1", "ready": True, "blockers": []}
    assert seen["args"] == ("f", "/abs", "TASK-1", VALID_EXECUTION_ID)

    async def _raise(*args, **kwargs):
        raise CoderFailure("task_not_in_plan", "x")

    monkeypatch.setattr(toolkit._engine, "task_context", _raise)
    result = await toolkit.coder_task_context(
        feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )
    assert result.status == "error"
    assert result.error.code == "task_not_in_plan"


async def test_delivery_report_routes_through_run(three_seat_roster, monkeypatch):
    """`coder_delivery_report` maps a plain dict engine result through `_run` like every other tool."""
    toolkit = _toolkit(three_seat_roster)

    async def _delivery_report(feature, worktree, task_id, execution_id):
        return {"task_id": task_id, "branch": "b", "lint_evidence": "unknown"}

    monkeypatch.setattr(toolkit._engine, "delivery_report", _delivery_report)
    result = await toolkit.coder_delivery_report(
        feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )
    assert result.status == "ok"
    assert result.data["branch"] == "b"
    assert result.data["lint_evidence"] == "unknown"

    async def _raise(*args, **kwargs):
        raise CoderFailure("branch_not_found", "x")

    monkeypatch.setattr(toolkit._engine, "delivery_report", _raise)
    result = await toolkit.coder_delivery_report(
        feature="f", worktree="/abs", task_id="TASK-1", execution_id=VALID_EXECUTION_ID
    )
    assert result.status == "error"
    assert result.error.code == "branch_not_found"


async def test_bg_status_pre_execute_validates_schema(three_seat_roster):
    """`coder_bg_status` bounds execution_id/handle/since_revision/tail_bytes before the engine runs."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_bg_status", execution_id=VALID_EXECUTION_ID, handle="h-1", since_revision=None, tail_bytes=2048
    )  # must not raise

    async def _bad(**kwargs):
        with pytest.raises(CoderFailure) as excinfo:
            await toolkit._pre_execute("coder_bg_status", **kwargs)
        assert excinfo.value.code == "invalid_arguments"

    await _bad(execution_id="not-a-uuid", handle="h-1")
    await _bad(execution_id=VALID_EXECUTION_ID, handle="")
    await _bad(execution_id=VALID_EXECUTION_ID, handle="h-1", since_revision=-1)
    await _bad(execution_id=VALID_EXECUTION_ID, handle="h-1", tail_bytes=-1)
    await _bad(execution_id=VALID_EXECUTION_ID, handle="h-1", tail_bytes=4097)

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute("coder_bg_status", handle="h-1")
    assert excinfo.value.code == "execution_required"


async def test_bg_status_routes_through_run(three_seat_roster, monkeypatch):
    """`coder_bg_status` maps a `BackgroundStatus` engine result through `_run` like every other tool."""
    from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundStatus

    toolkit = _toolkit(three_seat_roster)
    seen = {}

    async def _bg_status(execution_id, handle, since_revision=None, tail_bytes=2048):
        seen["args"] = (execution_id, handle, since_revision, tail_bytes)
        return BackgroundStatus(
            state="finished",
            outcome="completed",
            exit_code=0,
            source="background-registry:validation",
            authority="supervisor",
            verified_at=None,
            stale=False,
            revision=1,
            changed=True,
            elapsed_ms=5,
            next_poll_after_ms=5000,
        )

    monkeypatch.setattr(toolkit._engine, "bg_status", _bg_status)
    result = await toolkit.coder_bg_status(execution_id=VALID_EXECUTION_ID, handle="h-1")
    assert result.status == "ok"
    assert result.data["state"] == "finished"
    assert seen["args"] == (VALID_EXECUTION_ID, "h-1", None, 2048)

    async def _raise(*args, **kwargs):
        raise CoderFailure("background_not_found", "x")

    monkeypatch.setattr(toolkit._engine, "bg_status", _raise)
    result = await toolkit.coder_bg_status(execution_id=VALID_EXECUTION_ID, handle="h-1")
    assert result.status == "error"
    assert result.error.code == "background_not_found"


async def test_run_validation_pre_execute_validates_schema(three_seat_roster):
    """`coder_run_validation` bounds task_ids/tier/timeout_seconds/request_id before the engine runs."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_run_validation",
        feature="f",
        worktree="/abs",
        execution_id=VALID_EXECUTION_ID,
        task_ids=["TASK-1"],
        tier="merge",
        timeout_seconds=60,
        request_id="req-1",
    )  # must not raise

    async def _bad(**kwargs):
        base = dict(
            feature="f",
            worktree="/abs",
            execution_id=VALID_EXECUTION_ID,
            task_ids=["TASK-1"],
            tier="merge",
            timeout_seconds=60,
            request_id="req-1",
        )
        base.update(kwargs)
        with pytest.raises(CoderFailure) as excinfo:
            await toolkit._pre_execute("coder_run_validation", **base)
        assert excinfo.value.code == "invalid_arguments"

    await _bad(worktree="rel")
    await _bad(task_ids=[])
    await _bad(task_ids=["not-a-task-id"])
    await _bad(tier="unknown")
    await _bad(timeout_seconds=0)
    await _bad(timeout_seconds=7201)
    await _bad(request_id="")

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_run_validation",
            feature="f",
            worktree="/abs",
            task_ids=["TASK-1"],
            tier="merge",
            timeout_seconds=60,
            request_id="req-1",
        )
    assert excinfo.value.code == "execution_required"


async def test_run_validation_routes_through_run(three_seat_roster, monkeypatch):
    """`coder_run_validation` maps a `BackgroundRegistration` engine result through `_run`."""
    from datetime import datetime, timezone

    from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration

    toolkit = _toolkit(three_seat_roster)
    seen = {}

    async def _run_validation(feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id):
        seen["args"] = (feature, worktree, execution_id, task_ids, tier, timeout_seconds, request_id)
        return BackgroundRegistration(
            handle="req-1",
            execution_id=execution_id,
            launch_id="launch-1",
            owner_instance_id="owner-1",
            kind="validation",
            authority="supervisor",
            worktree=worktree,
            backend="pytest-subprocess",
            started_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(toolkit._engine, "run_validation", _run_validation)
    result = await toolkit.coder_run_validation(
        feature="f",
        worktree="/abs",
        execution_id=VALID_EXECUTION_ID,
        task_ids=["TASK-1"],
        tier="merge",
        timeout_seconds=60,
        request_id="req-1",
    )
    assert result.status == "ok"
    assert result.data["handle"] == "req-1"
    assert seen["args"] == ("f", "/abs", VALID_EXECUTION_ID, ["TASK-1"], "merge", 60, "req-1")

    async def _raise(*args, **kwargs):
        raise CoderFailure("validation_request_conflict", "x")

    monkeypatch.setattr(toolkit._engine, "run_validation", _raise)
    result = await toolkit.coder_run_validation(
        feature="f",
        worktree="/abs",
        execution_id=VALID_EXECUTION_ID,
        task_ids=["TASK-1"],
        tier="merge",
        timeout_seconds=60,
        request_id="req-1",
    )
    assert result.status == "error"
    assert result.error.code == "validation_request_conflict"


async def test_toolkit_pre_execute_via_full_execute_path_never_reaches_engine(three_seat_roster, monkeypatch):
    """Bad args are rejected in `_pre_execute`, BEFORE the bound tool method
    (and therefore the engine) ever runs — the full `ToolkitTool._execute()`
    path raises (verified: toolkit.py:145-202 has no try/except between
    `_pre_execute` and the bound method), which the MCP adapter converts to
    an `isError` response (adapter.py:59-95) rather than a `CoderResult` —
    `_pre_execute`'s own raised `CoderFailure` is what AC-23 actually gates on."""
    toolkit = _toolkit(three_seat_roster)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("engine.plan must not be called for invalid arguments")

    monkeypatch.setattr(toolkit._engine, "plan", _fail_if_called)
    tool = next(t for t in toolkit.get_tools() if t.name == "coder_plan")
    adapter = MCPToolAdapter(tool)

    response = await adapter.execute({"feature": "f", "worktree": "not-absolute"})
    assert response["isError"] is True


async def test_toolkit_maps_failure_to_error_result(three_seat_roster, monkeypatch):
    toolkit = _toolkit(three_seat_roster)

    async def _raise(*args, **kwargs):
        raise CoderFailure("feature_not_found", "x")

    monkeypatch.setattr(toolkit._engine, "plan", _raise)
    result = await toolkit.coder_plan(feature="nope", worktree="/abs", execution_id=VALID_EXECUTION_ID)
    assert result.status == "error"
    assert result.error.code == "feature_not_found"


async def test_toolkit_wait_caps_timeout(three_seat_roster, monkeypatch):
    toolkit = _toolkit(three_seat_roster)
    seen = {}

    async def _wait(job_id, timeout_seconds):
        seen["timeout_seconds"] = timeout_seconds
        from parrot.flows.dev_loop.sdd_coder.models import CoderJob

        return CoderJob(job_id=job_id, feature_id="F", chunk_task_ids=[], state="running", started_at="now")

    monkeypatch.setattr(toolkit._engine, "wait", _wait)
    with pytest.raises(ValidationError):
        from parrot.flows.dev_loop.sdd_coder.models import CoderWaitArgs

        CoderWaitArgs(job_id="j", timeout_seconds=900)

    result = await toolkit.coder_wait(job_id="j", timeout_seconds=300)
    assert result.status == "ok"
    assert seen["timeout_seconds"] == 300


async def test_toolkit_result_is_json_serialisable_via_post_execute(three_seat_roster, monkeypatch):
    toolkit = _toolkit(three_seat_roster)

    async def _raise(*args, **kwargs):
        raise CoderFailure("feature_not_found", "x")

    monkeypatch.setattr(toolkit._engine, "plan", _raise)
    tool = next(t for t in toolkit.get_tools() if t.name == "coder_plan")
    raw = await tool._execute(feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID)
    assert isinstance(raw, str)  # _post_execute serialises CoderResult -> JSON string
    parsed = CoderResult.model_validate_json(raw)
    assert parsed.status == "error" and parsed.error.code == "feature_not_found"


def test_mcp_local_serves_sdd_coder(monkeypatch, tmp_path):
    from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe
    from parrot.mcp.toolkit_server import create_toolkit_mcp_server

    async def _noop_probe(self, roster):
        from parrot.flows.dev_loop.sdd_coder.models import SeatProbeResult

        return [SeatProbeResult(label=s.label, kind=s.kind, backend=s.backend, available=True) for s in roster.seats]

    monkeypatch.setattr(RosterProbe, "probe", _noop_probe)

    repo_root = Path(__file__).resolve().parents[6]
    config_path = repo_root / "examples" / "sdd-coder-mcp.yaml"
    assert config_path.is_file(), config_path
    server = create_toolkit_mcp_server("sdd-coder", root=tmp_path, config_path=str(config_path))
    names = set(server.tools)
    assert names == EXPECTED_TOOLS


async def test_toolkit_status_and_wait_carry_the_per_seat_rollup(three_seat_roster, monkeypatch):
    """`coder_status` / `coder_wait` return `seats` so sdd-worker prints the table instead of computing it."""
    from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord, CoderJob, TaskResult

    toolkit = _toolkit(three_seat_roster)
    job = CoderJob(
        job_id="j",
        feature_id="F",
        chunk_task_ids=["TASK-1"],
        state="done",
        started_at="now",
        tasks=[
            TaskResult(
                task_id="TASK-1",
                outcome="merged",
                attempts=[
                    AttemptRecord(
                        attempt=1,
                        seat_label="a",
                        backend="nova",
                        model="m",
                        started_at="now",
                        duration_s=4.0,
                        usage={"input_tokens": 10, "output_tokens": 2},
                    )
                ],
            )
        ],
    )

    async def _status(job_id):
        return job

    monkeypatch.setattr(toolkit._engine, "status", _status)

    async def _wait(job_id, timeout_seconds):
        return job

    monkeypatch.setattr(toolkit._engine, "wait", _wait)

    for result in (await toolkit.coder_status(job_id="j"), await toolkit.coder_wait(job_id="j")):
        assert result.status == "ok"
        assert result.data["job_id"] == "j" and result.data["tasks"][0]["task_id"] == "TASK-1"
        (seat,) = result.data["seats"]
        assert seat["seat"] == "a" and seat["backend"] == "nova"
        assert seat["tasks_handled"] == ["TASK-1"] and seat["tasks_merged"] == 1
        assert seat["input_tokens"] == 10 and seat["usage_known"] is True


# -- FEAT-584 M3/R2: response_mode schema split + coder_read_artifact -------


def test_response_mode_schema_split_from_lifecycle_and_review_tools(three_seat_roster):
    """`coder_plan`/`coder_wait`/`coder_status` expose `response_mode`; the tools that
    reuse/inherit `CoderPlanArgs`' OLD shape (begin_execution, feedback, review,
    native observation) must never silently accept it too."""
    toolkit = _toolkit(three_seat_roster)
    schemas = {t.name: t.get_schema()["parameters"]["properties"] for t in toolkit.get_tools()}

    for name in ("coder_plan", "coder_wait", "coder_status"):
        assert "response_mode" in schemas[name], f"{name} must expose response_mode"

    for name in (
        "coder_begin_execution",
        "coder_record_feedback",
        "coder_record_review",
        "coder_record_native_observation",
        "coder_feedback_report",
    ):
        assert "response_mode" not in schemas[name], f"{name} must NOT inherit response_mode"


async def test_pre_execute_rejects_bad_response_mode(three_seat_roster):
    """Only the literal 'full'/'compact' values are accepted; the default is 'full'."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute(
        "coder_plan", feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID
    )  # default -- must not raise
    await toolkit._pre_execute(
        "coder_plan", feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID, response_mode="compact"
    )  # must not raise

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute(
            "coder_plan", feature="f", worktree="/abs", execution_id=VALID_EXECUTION_ID, response_mode="summary"
        )
    assert excinfo.value.code == "invalid_arguments"

    with pytest.raises(CoderFailure) as excinfo2:
        await toolkit._pre_execute("coder_wait", job_id="j", response_mode="nope")
    assert excinfo2.value.code == "invalid_arguments"


async def test_read_artifact_pre_execute_validates_schema(three_seat_roster):
    toolkit = _toolkit(three_seat_roster)

    await toolkit._pre_execute(
        "coder_read_artifact", execution_id=VALID_EXECUTION_ID, artifact_id="a" * 64, offset=0, limit=8192
    )  # must not raise

    async def _bad(**kwargs):
        with pytest.raises(CoderFailure) as excinfo:
            await toolkit._pre_execute("coder_read_artifact", **kwargs)
        assert excinfo.value.code == "invalid_arguments"

    await _bad(execution_id="not-a-uuid", artifact_id="a" * 64)
    await _bad(execution_id=VALID_EXECUTION_ID, artifact_id="a" * 64, offset=-1)
    await _bad(execution_id=VALID_EXECUTION_ID, artifact_id="a" * 64, limit=0)
    await _bad(execution_id=VALID_EXECUTION_ID, artifact_id="a" * 64, limit=16385)
    await _bad(execution_id=VALID_EXECUTION_ID, artifact_id="")

    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute("coder_read_artifact", artifact_id="a" * 64)
    assert excinfo.value.code == "execution_required"


async def test_read_artifact_no_store_configured_is_evidence_persistence_failed(three_seat_roster):
    """No `telemetry_dir`/`DEV_LOOP_CODER_TELEMETRY` was configured for this toolkit -- no store exists."""
    toolkit = _toolkit(three_seat_roster)
    assert toolkit._engine._evidence_store is None  # noqa: SLF001 -- asserting the fixture's own precondition

    result = await toolkit.coder_read_artifact(execution_id=VALID_EXECUTION_ID, artifact_id="a" * 64)
    assert result.status == "error"
    assert result.error.code == "evidence_persistence_failed"


async def test_read_artifact_routes_through_run(three_seat_roster, tmp_path):
    """A published artifact round-trips; a foreign execution/unknown id is `artifact_not_found`."""
    from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
    from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef

    toolkit = _toolkit(three_seat_roster)
    store = ExecutionEvidenceStore(tmp_path)
    toolkit._engine._evidence_store = store  # noqa: SLF001 -- same pattern as test_native_observations.py

    class _Payload(BaseModel):
        text: str

    ref: EvidenceRef = await store.put_artifact(VALID_EXECUTION_ID, _Payload(text="hello world"))

    result = await toolkit.coder_read_artifact(execution_id=VALID_EXECUTION_ID, artifact_id=ref.artifact_id)
    assert result.status == "ok"
    assert result.data["eof"] is True
    assert "hello world" in result.data["content"]

    # Cross-execution access to the SAME artifact_id fails: never found under a foreign scope.
    foreign_execution_id = "22222222-2222-4222-8222-222222222222"
    result = await toolkit.coder_read_artifact(execution_id=foreign_execution_id, artifact_id=ref.artifact_id)
    assert result.status == "error"
    assert result.error.code == "artifact_not_found"
