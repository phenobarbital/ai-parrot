"""Unit tests for the Gemini-backed dev-loop dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    ClaudeCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    GeminiCodeDispatcher,
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


class _FakeGeminiProcess:
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
        "parrot.flows.dev_loop.dispatcher.conf.WORKTREE_BASE_PATH",
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
    disp = GeminiCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        gemini_bin="gemini",
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


def _published_events(dispatcher: GeminiCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


class TestGeminiCommandAndEvents:
    @pytest.mark.asyncio
    async def test_dispatch_builds_command_and_maps_jsonl_events(
        self, dispatcher, brief, _patch_worktree_base, monkeypatch
    ):
        captured: dict[str, Sequence[str]] = {}

        async def _fake_create(command: Sequence[str], cwd: str):
            captured["command"] = list(command)
            payload_str = _development_payload()
            assistant_event = {
                "type": "message",
                "role": "assistant",
                "content": f"```json\n{payload_str}\n```",
                "delta": True,
            }
            return _FakeGeminiProcess(
                stdout_lines=[
                    '{"type":"init","timestamp":"2026-06-23T12:00:00Z"}\n',
                    '{"type":"tool_call","timestamp":"2026-06-23T12:00:01Z"}\n',
                    '{"type":"tool_response","timestamp":"2026-06-23T12:00:02Z"}\n',
                    json.dumps(assistant_event) + "\n",
                ]
            )

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        result = await dispatcher.dispatch(
            brief=brief,
            profile=GeminiCodeDispatchProfile(model="gemini-2.5-pro"),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )

        assert result.files_changed == ["app.py"]
        command = captured["command"]
        assert "gemini" in command[0]
        assert "--skip-trust" in command
        assert "--output-format" in command
        assert "stream-json" in command
        assert "--approval-mode" in command
        assert "auto_edit" in command
        assert "--model" in command
        assert "gemini-2.5-pro" in command
        assert "--sandbox" in command
        assert "--prompt" in command

        kinds = [event["kind"] for event in _published_events(dispatcher)]
        assert "dispatch.queued" in kinds
        assert "dispatch.started" in kinds
        assert "dispatch.tool_use" in kinds
        assert "dispatch.tool_result" in kinds
        assert "dispatch.completed" in kinds

    @pytest.mark.asyncio
    async def test_dispatch_transparent_profile_conversion(
        self, dispatcher, brief, _patch_worktree_base, monkeypatch
    ):
        captured: dict[str, Sequence[str]] = {}

        async def _fake_create(command: Sequence[str], cwd: str):
            captured["command"] = list(command)
            payload_str = _development_payload()
            assistant_event = {
                "type": "message",
                "role": "assistant",
                "content": payload_str,
                "delta": True,
            }
            return _FakeGeminiProcess(
                stdout_lines=[
                    json.dumps(assistant_event) + "\n",
                ]
            )

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        # Pass a ClaudeCodeDispatchProfile explicitly
        result = await dispatcher.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(
                subagent="sdd-worker",
                permission_mode="acceptEdits",
            ),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )

        assert result.files_changed == ["app.py"]
        command = captured["command"]
        assert "--approval-mode" in command
        assert "auto_edit" in command


class TestGeminiFailures:
    @pytest.mark.asyncio
    async def test_missing_cli_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _missing(_command: Sequence[str], cwd: str):
            raise FileNotFoundError("gemini")

        monkeypatch.setattr(dispatcher, "_create_process", _missing)

        with pytest.raises(DispatchExecutionError, match="Gemini CLI executable"):
            await dispatcher.dispatch(
                brief=brief,
                profile=GeminiCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_execution_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str], cwd: str):
            return _FakeGeminiProcess(stderr="some error occurred", return_code=1)

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchExecutionError, match="exit code 1"):
            await dispatcher.dispatch(
                brief=brief,
                profile=GeminiCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd=str(_patch_worktree_base),
            )

    @pytest.mark.asyncio
    async def test_invalid_output_raises_validation_error(self, dispatcher, brief, _patch_worktree_base, monkeypatch):
        async def _fake_create(command: Sequence[str], cwd: str):
            assistant_event = {
                "type": "message",
                "role": "assistant",
                "content": '{"files_changed": []}',
                "delta": True,
            }
            return _FakeGeminiProcess(
                stdout_lines=[
                    json.dumps(assistant_event) + "\n"
                ]
            )

        monkeypatch.setattr(dispatcher, "_create_process", _fake_create)

        with pytest.raises(DispatchOutputValidationError):
            await dispatcher.dispatch(
                brief=brief,
                profile=GeminiCodeDispatchProfile(),
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
                profile=GeminiCodeDispatchProfile(),
                output_model=DevelopmentOutput,
                run_id="r1",
                node_id="development",
                cwd="/etc",
            )
