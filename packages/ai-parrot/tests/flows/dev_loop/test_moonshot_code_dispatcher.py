"""Unit tests for the Moonshot dev-loop dispatcher (MoonshotCodeDispatcher)."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock

from parrot.clients import moonshot as moonshot_mod
from parrot.flows.dev_loop import (
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    MoonshotCodeDispatchProfile,
    MoonshotCodeDispatcher,
    ResearchOutput,
)
from parrot.models.moonshot import K_SERIES_MODELS, MoonshotModel


# ---------------------------------------------------------------------------
# Module 1 — registry / model constants
# ---------------------------------------------------------------------------


def test_kimi_k3_in_enum_and_k_series():
    assert MoonshotModel.KIMI_K3.value == "kimi-k3"
    assert MoonshotModel.KIMI_K3.value in K_SERIES_MODELS


# ---------------------------------------------------------------------------
# Module 2 — MoonshotCodeDispatchProfile
# ---------------------------------------------------------------------------


def test_moonshot_profile_defaults():
    profile = MoonshotCodeDispatchProfile()
    assert profile.model == "kimi-k3"
    assert profile.llm == "moonshot:kimi-k3"
    assert profile.enable_thinking is True
    assert profile.reasoning_effort == "max"
    assert profile.max_tokens == 8192


def test_moonshot_profile_model_syncs_llm():
    profile = MoonshotCodeDispatchProfile(model="kimi-k2.6")
    assert profile.llm == "moonshot:kimi-k2.6"


def test_moonshot_profile_explicit_llm_wins():
    profile = MoonshotCodeDispatchProfile(model="kimi-k3", llm="kimi:kimi-k3")
    assert profile.llm == "kimi:kimi-k3"


def test_moonshot_profile_max_tokens_bounds():
    MoonshotCodeDispatchProfile(max_tokens=131072)
    with pytest.raises(ValidationError):
        MoonshotCodeDispatchProfile(max_tokens=131073)
    with pytest.raises(ValidationError):
        MoonshotCodeDispatchProfile(max_tokens=255)


# ---------------------------------------------------------------------------
# Module 3 — MoonshotCodeDispatcher._completion_args / client factory
# ---------------------------------------------------------------------------


def _make_dispatcher() -> MoonshotCodeDispatcher:
    return MoonshotCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=60,
    )


def test_moonshot_completion_args_k_series_omits_temperature():
    disp = _make_dispatcher()
    args = disp._completion_args(MoonshotCodeDispatchProfile(), tools=[])
    assert "temperature" not in args
    assert args["thinking"] is True
    assert args["reasoning_effort"] == "max"
    assert args["max_tokens"] == 8192
    assert "extra_body" not in args


def test_moonshot_completion_args_legacy_model_keeps_temperature():
    disp = _make_dispatcher()
    profile = MoonshotCodeDispatchProfile(model="moonshot-v1-128k")
    args = disp._completion_args(profile, tools=[])
    assert args["temperature"] == 0.0


def test_moonshot_thinking_warns_always_thinking_model(caplog):
    disp = _make_dispatcher()
    profile = MoonshotCodeDispatchProfile(
        model="kimi-k2.7-code", enable_thinking=False
    )
    with caplog.at_level(logging.WARNING):
        args = disp._completion_args(profile, tools=[])
    assert args["thinking"] is False
    assert any("enable_thinking" in record.message for record in caplog.records)


def test_moonshot_client_factory_forwards_model_args():
    disp = _make_dispatcher()
    try:
        disp._client_factory(
            "moonshot:kimi-k3",
            model_args={"temperature": 0.0, "max_tokens": 100},
        )
    except TypeError as exc:  # pragma: no cover - failure path
        raise AssertionError(
            f"default Moonshot client factory raised TypeError: {exc}"
        ) from exc
    except Exception:
        # Building a real MoonshotClient without MOONSHOT_API_KEY may raise —
        # this test only asserts the lambda signature accepts model_args=.
        pass


# ---------------------------------------------------------------------------
# Dispatch-loop harness (mirrors test_zai_code_dispatcher.py)
# ---------------------------------------------------------------------------


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


class _FakeMoonshotClient:
    """Fake ``MoonshotClient`` exposing ``_chat_completion()`` per the contract.

    ``MoonshotCodeDispatcher._chat_completion`` sets the client module's
    thinking context variable and delegates to the client's own
    ``_chat_completion`` (which, on the real client, sanitizes K-series
    params and injects the thinking-mode ``extra_body``). The fake records
    the context value observed during each call so tests can assert the
    dispatcher propagated the profile's thinking flags.
    """

    def __init__(self, responses: Sequence[_Message]) -> None:
        self.client = object()  # marks the SDK client as already initialised
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.thinking_ctxs: list[dict[str, Any]] = []

    async def _chat_completion(
        self,
        *,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs: Any,
    ) -> _Response:
        self.thinking_ctxs.append(moonshot_mod._thinking_ctx.get())
        self.calls.append(
            {"model": model, "messages": messages, "use_tools": use_tools, **kwargs}
        )
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
        spec_path="sdd/specs/moonshot-client-llm.spec.md",
        feat_id="FEAT-311",
        branch_name="feat-311-moonshot-code-dispatcher",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


def _dispatcher(
    monkeypatch, moonshot_client: _FakeMoonshotClient
) -> MoonshotCodeDispatcher:
    captured: dict[str, Any] = {}

    def _client_factory(*args: Any, **kwargs: Any) -> _FakeMoonshotClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["model"] = args[0]
        return moonshot_client

    disp = MoonshotCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    monkeypatch.setattr(disp, "_client_factory", _client_factory)

    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    disp._captured_factory = captured  # type: ignore[attr-defined]
    return disp


def _published_events(dispatcher: MoonshotCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


@pytest.mark.asyncio
async def test_moonshot_dispatch_runs_tool_loop_and_validates_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeMoonshotClient(
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
        profile=MoonshotCodeDispatchProfile(max_turns=4),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.files_changed == ["app.py"]
    assert dispatcher._captured_factory["model"] == "moonshot:kimi-k3"  # type: ignore[attr-defined]
    first_call = client.calls[0]
    assert first_call["model"] == "kimi-k3"
    assert first_call["use_tools"] is True
    # The thinking markers are popped from the args and forwarded through
    # the client's context variable — never sent as raw create() kwargs.
    assert "thinking" not in first_call
    assert "reasoning_effort" not in first_call
    assert "temperature" not in first_call
    assert "extra_body" not in first_call
    assert client.thinking_ctxs[0] == {"thinking": True, "reasoning_effort": "max"}
    assert any(
        tool["function"]["name"] == "final_output" for tool in first_call["tools"]
    )

    kinds = [event["kind"] for event in _published_events(dispatcher)]
    assert "dispatch.queued" in kinds
    assert "dispatch.started" in kinds
    assert "dispatch.message" in kinds
    assert "dispatch.tool_use" in kinds
    assert "dispatch.tool_result" in kinds
    assert "dispatch.completed" in kinds


@pytest.mark.asyncio
async def test_moonshot_text_json_final_output_is_supported(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeMoonshotClient(
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
        profile=MoonshotCodeDispatchProfile(),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "implemented the spec"


@pytest.mark.asyncio
async def test_moonshot_invalid_final_tool_payload_raises_validation_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeMoonshotClient(
        [_Message(tool_calls=[_ToolCall("call_1", "final_output", {"files_changed": []})])]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=MoonshotCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )


@pytest.mark.asyncio
async def test_moonshot_cwd_outside_worktree_base_rejected(monkeypatch, brief):
    dispatcher = _dispatcher(monkeypatch, _FakeMoonshotClient([]))

    with pytest.raises(DispatchExecutionError):
        await dispatcher.dispatch(
            brief=brief,
            profile=MoonshotCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd="/etc",
        )
