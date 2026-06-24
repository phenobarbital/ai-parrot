"""Unit tests for the OpenAI-compatible LLM dev-loop dispatcher."""

from __future__ import annotations

import json
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    LLMCodeDispatchProfile,
    LLMCodeDispatcher,
    ResearchOutput,
)


class _Function:
    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(
        self,
        *,
        content: str = "",
        tool_calls: Sequence[_ToolCall] = (),
    ) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Response:
    def __init__(self, message: _Message) -> None:
        self.choices = [_Choice(message)]


class _FakeClient:
    model = "moonshotai/kimi-k2-instruct-0905"

    def __init__(self, responses: Sequence[_Message]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.client = object()

    async def _chat_completion(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake client exhausted")
        return _Response(self.responses.pop(0))


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


def _dispatcher(monkeypatch, client: _FakeClient) -> LLMCodeDispatcher:
    captured: dict[str, Any] = {}

    def _client_factory(*args: Any, **kwargs: Any) -> _FakeClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return client

    disp = LLMCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        client_factory=_client_factory,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    disp._captured_factory = captured  # type: ignore[attr-defined]
    return disp


def _published_events(dispatcher: LLMCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


@pytest.mark.asyncio
async def test_dispatch_runs_tool_loop_and_validates_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(
                content="I will inspect the file.",
                tool_calls=[_ToolCall("call_1", "read_file", {"path": "app.py"})],
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "call_2",
                        "final_output",
                        {
                            "files_changed": ["app.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "implemented the spec",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(
            llm="nvidia:moonshotai/kimi-k2-instruct-0905",
            max_turns=4,
        ),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.files_changed == ["app.py"]
    assert dispatcher._captured_factory["args"][0] == "nvidia:moonshotai/kimi-k2-instruct-0905"  # type: ignore[attr-defined]
    assert client.calls[0]["model"] == "moonshotai/kimi-k2-instruct-0905"
    assert client.calls[0]["use_tools"] is True
    assert any(tool["function"]["name"] == "final_output" for tool in client.calls[0]["tools"])

    kinds = [event["kind"] for event in _published_events(dispatcher)]
    assert "dispatch.queued" in kinds
    assert "dispatch.started" in kinds
    assert "dispatch.message" in kinds
    assert "dispatch.tool_use" in kinds
    assert "dispatch.tool_result" in kinds
    assert "dispatch.completed" in kinds


@pytest.mark.asyncio
async def test_text_json_final_output_is_supported(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeClient(
        [
            _Message(
                content=json.dumps(
                    {
                        "files_changed": ["app.py"],
                        "commit_shas": ["abc1234"],
                        "summary": "implemented the spec",
                    }
                )
            )
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "implemented the spec"


@pytest.mark.asyncio
async def test_invalid_final_tool_payload_raises_validation_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeClient([_Message(tool_calls=[_ToolCall("call_1", "final_output", {"files_changed": []})])])
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )


@pytest.mark.asyncio
async def test_cwd_outside_worktree_base_rejected(monkeypatch, brief):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(DispatchExecutionError):
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd="/etc",
        )


@pytest.mark.asyncio
async def test_run_command_rejects_non_allowlisted_command(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    result = await dispatcher._tool_run_command(
        str(tmp_path),
        {"argv": ["rm", "-rf", "."]},
        LLMCodeDispatchProfile(allowed_commands=["git"]),
    )

    assert result["ok"] is False
    assert "not allow-listed" in result["stderr"]


def test_patch_path_traversal_rejected(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))

    with pytest.raises(ValueError):
        dispatcher._validate_patch_paths(
            str(tmp_path),
            "diff --git a/../outside.txt b/../outside.txt\n" "--- a/../outside.txt\n" "+++ b/../outside.txt\n",
        )
