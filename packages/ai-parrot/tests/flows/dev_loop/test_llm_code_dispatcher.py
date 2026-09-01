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
    model = "minimaxai/minimax-m3"

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
        "parrot.flows.dev_loop.dispatchers.llm.conf.WORKTREE_BASE_PATH",
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
            llm="nvidia:minimaxai/minimax-m3",
            max_turns=4,
        ),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.files_changed == ["app.py"]
    assert dispatcher._captured_factory["args"][0] == "nvidia:minimaxai/minimax-m3"  # type: ignore[attr-defined]
    assert client.calls[0]["model"] == "minimaxai/minimax-m3"
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
async def test_exhausted_turns_are_salvaged_by_forcing_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A model that did the work but never closed must not lose the task.

    The observed failure: every seat of an 8-task run burned its turn budget
    exploring, and each dispatch was discarded whole even though it had
    patched and committed.
    """
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeClient(
        [
            # Two turns of real work, never calling final_output...
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(tool_calls=[_ToolCall("c2", "read_file", {"path": "app.py"})]),
            # ...then the forced salvage round closes the books.
            _Message(
                tool_calls=[
                    _ToolCall(
                        "c3",
                        "final_output",
                        {
                            "files_changed": ["app.py"],
                            "commit_shas": ["abc1234"],
                            "summary": "patched and committed before running out of turns",
                        },
                    )
                ]
            ),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=2),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    assert result.commit_shas == ["abc1234"]
    # The salvage round forces the tool choice; the loop rounds do not.
    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[-1]["tool_choice"] == {
        "type": "function",
        "function": {"name": "final_output"},
    }
    # The nudge is appended without mutating the loop's own history.
    assert client.calls[-1]["messages"][-1]["role"] == "user"
    assert "turn budget is exhausted" in client.calls[-1]["messages"][-1]["content"].lower()

    events = _published_events(dispatcher)
    completed = next(e for e in events if e["kind"] == "dispatch.completed")
    assert completed["payload"]["salvaged"] is True
    assert completed["payload"]["max_turns"] == 2


@pytest.mark.asyncio
async def test_salvage_nudge_offers_the_raw_json_fallback(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """Forcing `tool_choice` is a request, not a guarantee.

    A Bedrock Mantle seat answered a forced `final_output` with prose and
    the salvage died on "Could not locate a JSON object in the assistant
    output" — the model had the answer and no accepted way to give it. The
    nudge must name the raw-JSON escape and the exact field names.
    """
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content=json.dumps({"files_changed": [], "commit_shas": [], "summary": "done"})),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=1),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    nudge = client.calls[-1]["messages"][-1]["content"]
    assert "cannot call a tool" in nudge
    assert "ONLY a raw JSON object" in nudge
    assert "DevelopmentOutput" in nudge
    # The exact field names, not a hand-written list that can drift.
    for field in ("files_changed", "commit_shas", "summary", "incomplete_tasks"):
        assert field in nudge
    # ...and it still tells the model to be honest about partial work.
    assert "do not claim work you did" in nudge


@pytest.mark.asyncio
async def test_salvage_accepts_plain_text_answer(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """Some backends answer a forced tool choice with text instead."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content=json.dumps({"files_changed": ["app.py"], "commit_shas": [], "summary": "done"})),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(max_turns=1),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "done"


@pytest.mark.asyncio
async def test_failed_salvage_still_reports_max_turns(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A salvage that recovers nothing must not mask the real failure."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")
    client = _FakeClient(
        [
            _Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})]),
            _Message(content="I still need to check a few more files."),
        ]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchExecutionError) as excinfo:
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(max_turns=1),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
        )

    message = str(excinfo.value)
    assert "exceeded max_turns=1" in message
    assert "final_output" in message
    # The reason travels on the ordinary failure event, not a new kind.
    failed = next(e for e in _published_events(dispatcher) if e["kind"] == "dispatch.failed")
    assert "final_output" in failed["payload"]["error_message"]


@pytest.mark.asyncio
async def test_provider_rejecting_forced_tool_choice_is_not_a_new_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    """A backend without forced tool choice degrades to the max_turns error."""
    (_patch_worktree_base / "app.py").write_text("x\n", encoding="utf-8")

    class _RejectsForcedChoice(_FakeClient):
        async def _chat_completion(self, **kwargs: Any) -> _Response:
            if kwargs.get("tool_choice") != "auto":
                raise RuntimeError("tool_choice not supported by this endpoint")
            return await super()._chat_completion(**kwargs)

    client = _RejectsForcedChoice([_Message(tool_calls=[_ToolCall("c1", "read_file", {"path": "app.py"})])])
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchExecutionError) as excinfo:
        await dispatcher.dispatch(
            brief=brief,
            profile=LLMCodeDispatchProfile(max_turns=1),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development.w1",
            cwd=str(_patch_worktree_base),
        )

    assert "exceeded max_turns=1" in str(excinfo.value)
    assert "tool_choice not supported" in str(excinfo.value)


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
