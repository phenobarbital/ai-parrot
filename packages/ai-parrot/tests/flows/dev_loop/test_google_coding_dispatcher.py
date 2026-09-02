"""Unit tests for the agy (Google Antigravity CLI) dev-loop dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    GoogleCodingDispatchProfile,
    GoogleCodingDispatcher,
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
)


class _AsyncBytesStream:
    def __init__(self, chunks: Sequence[str]) -> None:
        self._chunks = [chunk.encode("utf-8") for chunk in chunks]

    async def readline(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    async def read(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


class _FakeAgyProcess:
    def __init__(
        self,
        *,
        stdout_lines: Sequence[str] = (),
        stderr: str = "",
        return_code: int = 0,
    ) -> None:
        self.stdout = _AsyncBytesStream(stdout_lines)
        self.stderr = _AsyncBytesStream([stderr])
        self._return_code = return_code
        self.killed = False

    async def wait(self) -> int:
        return self._return_code

    def kill(self) -> None:
        self.killed = True


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.google_coding.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def brief(_patch_worktree_base) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


@pytest.fixture
def dispatcher(monkeypatch):
    disp = GoogleCodingDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        agy_bin="agy",
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _get_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_get_redis", _get_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    return disp


def _development_payload() -> Dict[str, Any]:
    return {
        "files_changed": ["src/main.py"],
        "commit_shas": ["abc1234"],
        "summary": "Fixed bug in main.py using agy",
    }


@pytest.mark.asyncio
async def test_dispatch_success(dispatcher, brief, monkeypatch):
    payload = _development_payload()
    stream_lines = [
        json.dumps({"type": "thought", "text": "Analyzing repo"}) + "\n",
        json.dumps({"type": "result", "result": payload}) + "\n",
    ]
    fake_proc = _FakeAgyProcess(stdout_lines=stream_lines)

    spawn_calls = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        spawn_calls.append((cmd, kwargs))
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="auto")
    result = await dispatcher.dispatch(
        brief=brief,
        profile=profile,
        output_model=DevelopmentOutput,
        run_id="run-agy-1",
        node_id="development",
        cwd=brief.worktree_path,
    )

    assert isinstance(result, DevelopmentOutput)
    assert result.files_changed == ["src/main.py"]
    assert result.commit_shas == ["abc1234"]
    assert result.summary == "Fixed bug in main.py using agy"

    assert len(spawn_calls) == 1
    cmd, kwargs = spawn_calls[0]
    assert cmd[0].endswith("agy")
    assert "--print" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd
    assert "--json-schema" in cmd
    assert kwargs["cwd"] == brief.worktree_path


@pytest.mark.asyncio
async def test_dispatch_non_zero_exit(dispatcher, brief, monkeypatch):
    fake_proc = _FakeAgyProcess(stderr="agy process crashed", return_code=1)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="gemini-3.6-flash")
    with pytest.raises(DispatchExecutionError, match="exit code 1"):
        await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id="run-agy-fail",
            node_id="development",
            cwd=brief.worktree_path,
        )


@pytest.mark.asyncio
async def test_dispatch_invalid_json_output(dispatcher, brief, monkeypatch):
    stream_lines = [
        json.dumps({"type": "result", "result": "{not valid json}"}) + "\n",
    ]
    fake_proc = _FakeAgyProcess(stdout_lines=stream_lines)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_proc

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    profile = GoogleCodingDispatchProfile(model="auto")
    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id="run-agy-bad-json",
            node_id="development",
            cwd=brief.worktree_path,
        )


@pytest.mark.asyncio
async def test_dispatch_profile_mismatch(dispatcher, brief):
    wrong_profile = "invalid_profile_object"
    with pytest.raises(ValueError, match="Expected GoogleCodingDispatchProfile"):
        await dispatcher.dispatch(
            brief=brief,
            profile=wrong_profile,
            output_model=DevelopmentOutput,
            run_id="run-mismatch",
            node_id="development",
            cwd=brief.worktree_path,
        )


# ---------------------------------------------------------------------------
# FEAT-496 TASK-2727 — wire-format fix (root cause 7) + display extraction
# ---------------------------------------------------------------------------


def _tool_call_step_update():
    return {
        "type": "step_update",
        "step_update": {
            "step_type": "tool_call",
            "tool_call": {"name": "read_file", "args": {"path": "src/a.py"}},
        },
    }


class TestAgyWireFormat:
    @pytest.mark.asyncio
    async def test_xadd_writes_a_single_event_field(self, dispatcher):
        """Defect (b): the flat-field layout the multiplexer cannot read."""
        await dispatcher._publish_event(
            "flow:r1:dispatch:development",
            kind="dispatch.tool_use",
            run_id="r1",
            node_id="development",
            payload={"agy_event": {}},
        )
        args, _kwargs = dispatcher._fake_redis.xadd.call_args
        fields = args[1]
        assert set(fields) == {"event"}
        assert json.loads(fields["event"])["kind"] == "dispatch.tool_use"

    @pytest.mark.asyncio
    async def test_multiplexer_reads_the_real_event_kind(self, dispatcher):
        """AC9b — the end-to-end symptom: flow.unknown in the console."""
        from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

        await dispatcher._publish_event(
            "flow:r1:dispatch:development.w1",
            kind="dispatch.tool_use",
            run_id="r1",
            node_id="development.w1",
            payload={"agy_event": {}},
        )
        args, _kwargs = dispatcher._fake_redis.xadd.call_args
        fields = args[1]

        mux = FlowStreamMultiplexer(dispatcher._fake_redis, run_id="r1")
        env = mux._fields_to_envelope("flow:r1:dispatch:development.w1", fields, ts=1.0)
        assert env["event_kind"] == "dispatch.tool_use"
        assert env["event_kind"] != "flow.unknown"

    @pytest.mark.asyncio
    async def test_session_host_is_folded(self, dispatcher):
        """Defect (b), second half: agy contributed nothing to session state."""
        from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX
        from parrot.flows.dev_loop.session_state import SessionHost

        host = SessionHost("run-agy-fold")
        token = _SESSION_HOST_CTX.set(host)
        try:
            await dispatcher._publish_event(
                "flow:run-agy-fold:dispatch:development",
                kind="dispatch.tool_use",
                run_id="run-agy-fold",
                node_id="development",
                payload={"agy_event": {}, "tool_name": "read_file"},
            )
        finally:
            _SESSION_HOST_CTX.reset(token)
        assert host.state.nodes["development"].dispatch.tool_use_count == 1

    @pytest.mark.asyncio
    async def test_redis_failure_still_folds_session_host(self, dispatcher, monkeypatch):
        from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX
        from parrot.flows.dev_loop.session_state import SessionHost

        async def _broken_redis():
            raise ConnectionError("redis down")

        monkeypatch.setattr(dispatcher, "_get_redis", _broken_redis)

        host = SessionHost("run-agy-broken")
        token = _SESSION_HOST_CTX.set(host)
        try:
            await dispatcher._publish_event(
                "flow:run-agy-broken:dispatch:development",
                kind="dispatch.tool_use",
                run_id="run-agy-broken",
                node_id="development",
                payload={"agy_event": {}, "tool_name": "read_file"},
            )
        finally:
            _SESSION_HOST_CTX.reset(token)
        assert host.state.nodes["development"].dispatch.tool_use_count == 1


class TestAgyEventExtraction:
    def test_tool_call_yields_name_and_input(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_call_step_update())
        assert out["tool_name"] == "read_file"
        assert "a.py" in out["tool_input"]

    def test_text_delta_yields_text(self):
        out = GoogleCodingDispatcher._extract_agy_display(
            {"type": "step_update", "step_update": {"text_delta": "hi"}}
        )
        assert out["text"] == "hi"

    def test_result_as_json_string_does_not_raise(self):
        out = GoogleCodingDispatcher._extract_agy_display(
            {"type": "result", "result": '{"turns": 3}'}
        )
        assert isinstance(out, dict)

    @pytest.mark.asyncio
    async def test_raw_event_preserved(self, dispatcher):
        """AC9."""
        event = _tool_call_step_update()
        await dispatcher._publish_agy_event(
            "flow:r1:dispatch:development", event, "r1", "development"
        )
        args, _kwargs = dispatcher._fake_redis.xadd.call_args
        fields = args[1]
        decoded = json.loads(fields["event"])
        assert decoded["payload"]["agy_event"] == event

    @pytest.mark.asyncio
    async def test_every_payload_has_a_summary(self, dispatcher):
        for event in (_tool_call_step_update(), {"type": "init", "model": "gemini-3.6"}):
            await dispatcher._publish_agy_event(
                "flow:r1:dispatch:development", event, "r1", "development"
            )
        for call in dispatcher._fake_redis.xadd.call_args_list:
            fields = call.args[1]
            decoded = json.loads(fields["event"])
            assert decoded["payload"]["summary"]
