"""Unit tests for the agy (Google Antigravity CLI) dev-loop dispatcher."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Sequence
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop import (
    GoogleCodingDispatchProfile,
    GoogleCodingDispatcher,
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
)
from parrot.flows.dev_loop.dispatchers.google_coding import AgyToolStep, parse_agy_tool_step


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
async def test_dispatch_invalid_output_publishes_corrective_event(dispatcher, brief, monkeypatch):
    """FEAT-496 (code-review finding): a mid-stream "result" event already
    published dispatch.completed before final validation runs. Unlike
    claude.py/codex.py/gemini.py, this dispatcher had no corrective
    dispatch.output_invalid event on a later validation failure, silently
    leaving session state stuck reporting "completed" for the failed
    dispatch. Now fixed to mirror the other three backends.
    """
    stream_lines = [
        json.dumps({"type": "result", "result": "{not valid json}"}) + "\n",
    ]
    fake_proc = _FakeAgyProcess(stdout_lines=stream_lines)

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    profile = GoogleCodingDispatchProfile(model="auto")
    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=profile,
            output_model=DevelopmentOutput,
            run_id="run-agy-corrective",
            node_id="development",
            cwd=brief.worktree_path,
        )

    kinds = []
    for call in dispatcher._fake_redis.xadd.await_args_list:
        fields = call.args[1]
        kinds.append(json.loads(fields["event"])["kind"])
    assert "dispatch.output_invalid" in kinds
    assert kinds[-1] == "dispatch.output_invalid", (
        "the corrective event must be the LAST one published, after any "
        f"premature dispatch.completed from a mid-stream result event: {kinds}"
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
        out = GoogleCodingDispatcher._extract_agy_display({"type": "step_update", "step_update": {"text_delta": "hi"}})
        assert out["text"] == "hi"

    def test_result_as_json_string_does_not_raise(self):
        out = GoogleCodingDispatcher._extract_agy_display({"type": "result", "result": '{"turns": 3}'})
        assert isinstance(out, dict)

    @pytest.mark.asyncio
    async def test_raw_event_preserved(self, dispatcher):
        """AC9."""
        event = _tool_call_step_update()
        await dispatcher._publish_agy_event("flow:r1:dispatch:development", event, "r1", "development")
        args, _kwargs = dispatcher._fake_redis.xadd.call_args
        fields = args[1]
        decoded = json.loads(fields["event"])
        assert decoded["payload"]["agy_event"] == event

    @pytest.mark.asyncio
    async def test_every_payload_has_a_summary(self, dispatcher):
        for event in (_tool_call_step_update(), {"type": "init", "model": "gemini-3.6"}):
            await dispatcher._publish_agy_event("flow:r1:dispatch:development", event, "r1", "development")
        for call in dispatcher._fake_redis.xadd.call_args_list:
            fields = call.args[1]
            decoded = json.loads(fields["event"])
            assert decoded["payload"]["summary"]


# ---------------------------------------------------------------------------
# FEAT-888 — agy 1.5.8 emits ``step_type: "tool"`` (ACTIVE, then DONE) instead
# of tool_call / tool_response. Fixtures are sanitized live 1.5.8 captures.
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def _agy_fixture(name: str) -> list[Dict[str, Any]]:
    lines = (_FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _agy_tool_events(name: str) -> list[Dict[str, Any]]:
    return [
        event
        for event in _agy_fixture(name)
        if event.get("event") == "step_update" and event["step_update"].get("step_type") == "tool"
    ]


def _tool_event(name: str, tool: str, state: str, needle: str = "") -> Dict[str, Any]:
    for event in _agy_tool_events(name):
        su = event["step_update"]
        params = json.dumps(su["tool_info"].get("parameters", {}))
        if su["tool_info"]["name"] == tool and su["state"] == state and needle in params:
            return event
    raise AssertionError(f"no {tool}/{state}/{needle!r} step in {name}")


_STEPS = "agy_1_5_8_tool_steps.jsonl"
_DENIED = "agy_1_5_8_denied_command.jsonl"


class TestAgyToolStepParser:
    def test_done_run_command_success(self):
        step = parse_agy_tool_step(_tool_event(_STEPS, "run_command", "DONE", "echo")["step_update"])
        assert isinstance(step, AgyToolStep)
        assert step.done is True
        assert step.name == "run_command"
        assert step.command == "echo hello"
        assert step.step_index == 2
        assert step.exit_code == 0
        assert step.is_error is False
        assert step.command_output == "hello"

    def test_done_run_command_failure(self):
        step = parse_agy_tool_step(_tool_event(_STEPS, "run_command", "DONE", "nonexistent")["step_update"])
        assert step is not None
        assert step.exit_code == 2
        assert step.is_error is True
        assert "/nonexistent_dir_xyz" in step.command_output
        assert "Created At" not in step.command_output

    def test_active_step_has_no_output(self):
        step = parse_agy_tool_step(_tool_event(_STEPS, "run_command", "ACTIVE", "echo")["step_update"])
        assert step is not None
        assert step.done is False
        assert step.command == "echo hello"
        assert step.output is None
        assert step.exit_code is None
        assert step.is_error is None

    def test_read_file_has_no_exit_code(self):
        step = parse_agy_tool_step(_tool_event(_STEPS, "read_file", "DONE")["step_update"])
        assert step is not None
        assert step.parameters["Path"] == "/work/agyprobe/note.txt"
        assert step.command is None
        assert step.output == "1 lines, 11 bytes"
        assert step.exit_code is None
        assert step.is_error is None
        assert step.command_output is None

    def test_denied_command_done_without_output(self):
        step = parse_agy_tool_step(_tool_event(_DENIED, "run_command", "DONE")["step_update"])
        assert step is not None
        assert step.done is True
        assert step.command.startswith("for i in")
        assert step.output is None
        assert step.is_error is None

    def test_non_tool_and_malformed_return_none(self):
        assert parse_agy_tool_step({"step_type": "agent_response", "text_delta": "hi"}) is None
        assert parse_agy_tool_step({"step_type": "user_input", "state": "DONE"}) is None
        assert parse_agy_tool_step("not a dict") is None
        assert parse_agy_tool_step(None) is None

        bare = parse_agy_tool_step({"step_type": "tool", "tool_name": "run_command", "tool_info": "bogus"})
        assert bare is not None
        assert bare.name == "run_command"
        assert bare.parameters == {}

        odd = parse_agy_tool_step({"step_type": "tool", "tool_info": {"parameters": "oops", "output": 123}})
        assert odd is not None
        assert odd.parameters == {}
        assert odd.output == "123"
        assert odd.exit_code is None


class TestAgyToolStepEvents:
    async def _replay(self, dispatcher, events) -> list[str]:
        for event in events:
            await dispatcher._publish_agy_event("flow:r1:dispatch:development", event, "r1", "development")
        return [json.loads(call.args[1]["event"])["kind"] for call in dispatcher._fake_redis.xadd.call_args_list]

    @pytest.mark.asyncio
    async def test_fixture_publishes_tool_use_and_result_pairs(self, dispatcher):
        kinds = await self._replay(dispatcher, _agy_fixture(_STEPS))
        assert kinds.count("dispatch.tool_use") == 3
        assert kinds.count("dispatch.tool_result") == 3
        assert kinds[0] == "dispatch.started"
        assert kinds[-1] == "dispatch.completed"

    @pytest.mark.asyncio
    async def test_fixture_folds_tool_use_count(self, dispatcher):
        from parrot.flows.dev_loop.dispatchers._shared import _SESSION_HOST_CTX
        from parrot.flows.dev_loop.session_state import SessionHost

        host = SessionHost("r1")
        token = _SESSION_HOST_CTX.set(host)
        try:
            await self._replay(dispatcher, _agy_fixture(_STEPS))
        finally:
            _SESSION_HOST_CTX.reset(token)
        assert host.state.nodes["development"].dispatch.tool_use_count == 3

    @pytest.mark.asyncio
    async def test_denied_command_still_pairs(self, dispatcher):
        kinds = await self._replay(dispatcher, _agy_fixture(_DENIED))
        assert kinds.count("dispatch.tool_use") == 1
        assert kinds.count("dispatch.tool_result") == 1

    def test_display_keys_for_done_failure(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_event(_STEPS, "run_command", "DONE", "nonexistent"))
        assert out["tool_name"] == "run_command"
        assert out["tool_input"] == "ls /nonexistent_dir_xyz"
        assert out["exit_code"] == 2
        assert out["is_error"] is True
        assert "nonexistent_dir_xyz" in out["result_snippet"]
        assert "Created At" not in out["result_snippet"]

    def test_display_keys_for_done_success(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_event(_STEPS, "run_command", "DONE", "echo"))
        assert out["exit_code"] == 0
        assert out["is_error"] is False
        assert out["result_snippet"] == "hello"

    def test_display_keys_for_active_step(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_event(_STEPS, "run_command", "ACTIVE", "echo"))
        assert out == {"tool_name": "run_command", "tool_input": "echo hello"}

    def test_display_keys_for_read_file(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_event(_STEPS, "read_file", "DONE"))
        assert out["tool_name"] == "read_file"
        assert out["tool_input"].endswith("note.txt")
        assert out["result_snippet"] == "1 lines, 11 bytes"
        assert "is_error" not in out
        assert "exit_code" not in out

    def test_display_keys_for_denied_command(self):
        out = GoogleCodingDispatcher._extract_agy_display(_tool_event(_DENIED, "run_command", "DONE"))
        assert out["tool_name"] == "run_command"
        assert out["tool_input"].startswith("for i in")
        assert "is_error" not in out
        assert "result_snippet" not in out

    @pytest.mark.asyncio
    async def test_unknown_tool_state_is_message(self, dispatcher):
        event = {
            "event": "step_update",
            "step_update": {"step_type": "tool", "state": "PENDING", "tool_info": {"name": "run_command"}},
        }
        kinds = await self._replay(dispatcher, [event])
        assert kinds == ["dispatch.message"]


# ---------------------------------------------------------------------------
# FEAT-606: the --json-schema file must be readable by ``agy --sandbox``,
# which can only see its workspace (the dispatch cwd).
# ---------------------------------------------------------------------------


def _schema_arg(cmd: Sequence[str]) -> str:
    return cmd[list(cmd).index("--json-schema") + 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("return_code", [0, 1])
async def test_schema_file_is_inside_cwd_and_cleaned_up(dispatcher, brief, monkeypatch, return_code):
    stream_lines = [json.dumps({"type": "result", "result": _development_payload()}) + "\n"]
    seen: Dict[str, Any] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        schema_path = _schema_arg(cmd)
        seen["path"] = schema_path
        seen["schema"] = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        seen["gitignore"] = (Path(schema_path).parent / ".gitignore").read_text(encoding="utf-8")
        return _FakeAgyProcess(stdout_lines=stream_lines, stderr="boom", return_code=return_code)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    cwd = Path(brief.worktree_path)
    coro = dispatcher.dispatch(
        brief=brief,
        profile=GoogleCodingDispatchProfile(model="auto", sandbox=True),
        output_model=DevelopmentOutput,
        run_id="run-agy-schema",
        node_id="development",
        cwd=str(cwd),
    )
    if return_code:
        with pytest.raises(DispatchExecutionError):
            await coro
    else:
        await coro

    schema_path = Path(seen["path"])
    assert schema_path.is_relative_to(cwd.resolve())
    assert seen["schema"] == DevelopmentOutput.model_json_schema()
    assert seen["gitignore"].strip() == "*"
    assert not schema_path.exists()
    assert not schema_path.parent.exists()


def test_schema_dir_is_git_ignored(dispatcher, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = dispatcher._materialize_json_schema(DevelopmentOutput, str(tmp_path))
    try:
        status = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert Path(path).exists()
        assert status == ""
    finally:
        dispatcher._cleanup_json_schema(path)
    assert not Path(path).parent.exists()


def test_concurrent_schemas_use_distinct_dirs(dispatcher, tmp_path):
    first = dispatcher._materialize_json_schema(DevelopmentOutput, str(tmp_path))
    second = dispatcher._materialize_json_schema(DevelopmentOutput, str(tmp_path))
    assert Path(first).parent != Path(second).parent
    dispatcher._cleanup_json_schema(first)
    assert Path(second).exists()
    dispatcher._cleanup_json_schema(second)
    assert list(tmp_path.iterdir()) == []


# -- stdin isolation (issue:995ad869e502) ---------------------------------------


@pytest.mark.asyncio
async def test_create_process_isolates_stdin(dispatcher, monkeypatch, tmp_path):
    """fd 0 of an MCP-served process is its JSON-RPC channel; a child inheriting
    it can EOF the server's own read and kill it silently."""
    captured: Dict[str, Any] = {}

    async def _fake_exec(*args: Any, **kwargs: Any):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeAgyProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    await dispatcher._create_process(["agy", "--version"], str(tmp_path))

    assert captured["args"] == ("agy", "--version")
    assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] is asyncio.subprocess.PIPE
    assert captured["kwargs"]["stderr"] is asyncio.subprocess.PIPE


@pytest.mark.parametrize("mode", ["accept-edits", "auto", "plan"])
@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_google_coding_profile_auto_and_xhigh(mode: str, effort: str | None) -> None:
    profile = GoogleCodingDispatchProfile(mode=mode, effort=effort)
    assert (profile.mode, profile.effort) == (mode, effort)


def test_google_coding_profile_defaults_unchanged() -> None:
    profile = GoogleCodingDispatchProfile()
    assert profile.mode == "accept-edits" and profile.effort is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("mode", "yolo"), ("effort", "ultra"), ("effort", "minimal")],
)
def test_google_coding_profile_rejects_unknown_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        GoogleCodingDispatchProfile(**{field: value})


def test_build_command_passes_through_auto_mode_and_xhigh_effort(dispatcher) -> None:
    command = dispatcher._build_command(
        profile=GoogleCodingDispatchProfile(mode="auto", effort="xhigh"),
        schema_path="s.json",
        prompt="p",
    )

    mode_index = command.index("--mode")
    effort_index = command.index("--effort")
    assert command[mode_index : mode_index + 2] == ["--mode", "auto"]
    assert command[effort_index : effort_index + 2] == ["--effort", "xhigh"]
