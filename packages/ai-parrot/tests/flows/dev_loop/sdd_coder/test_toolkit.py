"""Tests for SddCoderToolkit — MCP surface, arg validation, error mapping (TASK-3122)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure
from parrot.flows.dev_loop.sdd_coder.models import CoderResult
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.mcp.adapter import MCPToolAdapter


def _toolkit(three_seat_roster):
    return SddCoderToolkit(roster=three_seat_roster)


def test_toolkit_exposes_seven_tools(three_seat_roster):
    toolkit = _toolkit(three_seat_roster)
    names = {t.name for t in toolkit.get_tools()}
    assert names == {
        "coder_plan",
        "coder_run_chunk",
        "coder_prepare_native",
        "coder_merge",
        "coder_wait",
        "coder_status",
        "coder_cleanup",
    }


def test_toolkit_accepts_roster_as_list_of_dicts():
    toolkit = SddCoderToolkit(roster=[{"label": "a", "backend": "nova"}])
    assert toolkit._engine.roster.seats[0].label == "a"


async def test_toolkit_pre_execute_rejects_bad_args(three_seat_roster):
    toolkit = _toolkit(three_seat_roster)
    with pytest.raises(CoderFailure) as excinfo:
        await toolkit._pre_execute("coder_run_chunk", feature="f", worktree="rel", task_ids=["TASK-1"])
    assert excinfo.value.code == "invalid_arguments"


async def test_toolkit_pre_execute_ignores_permission_context(three_seat_roster):
    """`ToolkitTool._execute` always injects `_permission_context` (verified:
    toolkit.py:176-182) even for toolkits that don't use it — `_pre_execute`
    must not reject valid args just because that key is present."""
    toolkit = _toolkit(three_seat_roster)
    await toolkit._pre_execute("coder_plan", feature="f", worktree="/abs", _permission_context=None)  # must not raise


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
    result = await toolkit.coder_plan(feature="nope", worktree="/abs")
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
    raw = await tool._execute(feature="f", worktree="/abs")
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
    assert names == {
        "coder_plan",
        "coder_run_chunk",
        "coder_prepare_native",
        "coder_merge",
        "coder_wait",
        "coder_status",
        "coder_cleanup",
    }


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
    monkeypatch.setattr(toolkit._engine, "status", lambda job_id: job)

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
