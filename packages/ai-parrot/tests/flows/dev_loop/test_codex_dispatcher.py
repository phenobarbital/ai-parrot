"""Unit tests for the Codex-backed dev-loop dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    CodexCodeDispatchProfile,
    CodexCodeDispatcher,
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


class _FakeCodexProcess:
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
        "parrot.flows.dev_loop.dispatchers.codex.conf.WORKTREE_BASE_PATH",
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
    disp = CodexCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    return disp


def _development_payload() -> str:
    return json.dumps(
        {
            "files_changed": ["app.py"],
            "commit_shas": ["abc1234"],
            "summary": "implemented the spec",
        }
    )


def _write_output(command: Sequence[str], payload: str) -> None:
    output_path = Path(command[command.index("-o") + 1])
    output_path.write_text(payload, encoding="utf-8")


def _published_events(dispatcher: CodexCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


class TestCodexCommandAndEvents:
    @pytest.mark.asyncio
    async def test_dispatch_builds_command_and_maps_jsonl_events(
        self, dispatcher, brief, _patch_worktree_base, monkeypatch
    ):
        captured: dict[str, Sequence[str]] = {}

        async def _fake_create(command: Sequence[str]):
            captured["command"] = list(command)
            _write_output(command, _development_payload())
            return _FakeCodexProcess(
                stdout_lines=[
                    ('{"type":"item.started","item":' '{"type":"command_execution","command":"pytest"}}\n'),
                    ('{"type":"item.completed","item":' '{"type":"command_execution","status":"completed"}}\n'),
                    '{"type":"turn.completed"}\n',
                ]
            )

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        result = await dispatcher.dispatch(
            brief=brief,
            profile=CodexCodeDispatchProfile(model="gpt-5.5"),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )

        assert result.files_changed == ["app.py"]
        command = captured["command"]
        assert command[:2] == ["codex", "exec"]
        assert "--json" in command
        assert command[command.index("--cd") + 1] == str(_patch_worktree_base)
        assert command[command.index("--model") + 1] == "gpt-5.5"
        assert command[command.index("--sandbox") + 1] == "workspace-write"
        assert command[command.index("--ask-for-approval") + 1] == "never"
        assert "--output-schema" in command
        assert "-o" in command
        assert "--ignore-user-config" in command

        kinds = [event["kind"] for event in _published_events(dispatcher)]
        assert "dispatch.queued" in kinds
        assert "dispatch.started" in kinds
        assert "dispatch.tool_use" in kinds
        assert "dispatch.tool_result" in kinds
        assert "dispatch.completed" in kinds


class TestCodexFailures:
    @pytest.mark.asyncio
    async def test_missing_cli_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _missing(_command: Sequence[str]):
            raise FileNotFoundError("codex")

        monkeypatch.setattr(dispatcher, "_create_process", _missing)

        with pytest.raises(DispatchExecutionError, match="Codex CLI"):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str]):
            _write_output(command, _development_payload())
            return _FakeCodexProcess(stderr="permission denied", return_code=2)

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchExecutionError, match="exit code 2"):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_invalid_output_raises_validation_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str]):
            _write_output(command, '{"files_changed": []}')
            return _FakeCodexProcess()

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchOutputValidationError):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_cwd_outside_worktree_base_rejected(self, dispatcher, brief):
        with pytest.raises(DispatchExecutionError):
            await dispatcher.dispatch(
                brief=brief,
                profile=CodexCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd="/etc",
            )


def _cmd_started(cmd="pytest -q"):
    return {"type": "item.started", "item": {"type": "command_execution", "command": cmd}}


def _cmd_completed(cmd="pytest -q", exit_code=0):
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": cmd,
            "exit_code": exit_code,
            "status": "completed",
        },
    }


class TestCodexEventExtraction:
    """FEAT-496 TASK-2725 — display extraction from codex_event."""

    def test_command_started_yields_tool_name_and_input(self):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        out = d._extract_codex_display(_cmd_started())
        assert out["tool_name"]
        assert "pytest" in out["tool_input"]

    def test_command_completed_carries_exit_detail(self):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        out = d._extract_codex_display(_cmd_completed(exit_code=1))
        assert out.get("exit_code") == 1

    @pytest.mark.asyncio
    async def test_raw_event_is_preserved(self, dispatcher):
        """AC9: the expanded JSON view still shows the provider event."""
        await dispatcher._publish_codex_event(
            "flow:r1:dispatch:development", _cmd_started(), "r1", "development"
        )
        events = _published_events(dispatcher)
        assert events[-1]["payload"]["codex_event"] == _cmd_started()

    @pytest.mark.parametrize(
        "bad", [{}, {"type": "x"}, {"item": None}, {"item": {"type": "unknown"}}]
    )
    def test_malformed_event_never_raises(self, bad):
        d = CodexCodeDispatcher(max_concurrent=1, redis_url="redis://localhost", stream_ttl_seconds=300)
        assert isinstance(d._extract_codex_display(bad), dict)

    @pytest.mark.asyncio
    async def test_every_payload_has_a_summary(self, dispatcher):
        for event in (_cmd_started(), _cmd_completed()):
            await dispatcher._publish_codex_event(
                "flow:r1:dispatch:development", event, "r1", "development"
            )
        for evt in _published_events(dispatcher):
            assert evt["payload"]["summary"]

    @pytest.mark.asyncio
    async def test_dispatch_accepts_labels(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        from parrot.flows.dev_loop.models import DispatchLabels

        async def _fake_create(command: Sequence[str]):
            _write_output(command, _development_payload())
            return _FakeCodexProcess(stdout_lines=[])

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        await dispatcher.dispatch(
            brief=brief,
            profile=CodexCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
            labels=DispatchLabels(task_id="TASK-1", seat="development.w1"),
        )
        events = _published_events(dispatcher)
        queued = next(e for e in events if e["kind"] == "dispatch.queued")
        assert queued["payload"]["task_id"] == "TASK-1"
