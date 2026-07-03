"""Unit tests for the Z.ai dev-loop dispatcher (ZaiCodeDispatcher) — FEAT-269."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from parrot.clients.zai import ZaiClient
from parrot.flows.dev_loop import (
    DevelopmentOutput,
    DispatchExecutionError,
    DispatchOutputValidationError,
    ResearchOutput,
    ZaiCodeDispatchProfile,
    ZaiCodeDispatcher,
)
from parrot.models.zai import THINKING_CAPABLE_ZAI_MODELS, ZaiModel


# ---------------------------------------------------------------------------
# Module 1 — registry / client defaults
# ---------------------------------------------------------------------------


def test_glm_5_2_in_enum_and_thinking_capable():
    assert ZaiModel.GLM_5_2.value == "glm-5.2"
    assert ZaiModel.GLM_5_2.value in THINKING_CAPABLE_ZAI_MODELS


def test_zai_client_default_model_is_glm_5_2():
    assert ZaiClient.model == ZaiClient._default_model == "glm-5.2"


# ---------------------------------------------------------------------------
# Module 2 — ZaiCodeDispatchProfile
# ---------------------------------------------------------------------------


def test_zai_profile_defaults():
    profile = ZaiCodeDispatchProfile()
    assert profile.model == "glm-5.2"
    assert profile.llm == "zai:glm-5.2"
    assert profile.enable_thinking is True
    assert profile.reasoning_effort == "max"
    assert profile.max_tokens == 8192


def test_zai_profile_model_syncs_llm():
    profile = ZaiCodeDispatchProfile(model="glm-5.1")
    assert profile.llm == "zai:glm-5.1"


def test_zai_profile_max_tokens_bounds():
    ZaiCodeDispatchProfile(max_tokens=131072)
    with pytest.raises(ValidationError):
        ZaiCodeDispatchProfile(max_tokens=131073)
    with pytest.raises(ValidationError):
        ZaiCodeDispatchProfile(max_tokens=255)


# ---------------------------------------------------------------------------
# Module 3 — ZaiCodeDispatcher._completion_args / client factory
# ---------------------------------------------------------------------------


def _make_dispatcher() -> ZaiCodeDispatcher:
    return ZaiCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=60,
    )


def test_zai_completion_args_native_thinking():
    disp = _make_dispatcher()
    args = disp._completion_args(ZaiCodeDispatchProfile(), tools=[])
    assert args["thinking"] == {"type": "enabled"}
    assert args["reasoning_effort"] == "max"
    assert args["max_tokens"] == 8192
    assert "extra_body" not in args


def test_zai_completion_args_thinking_disabled():
    disp = _make_dispatcher()
    profile = ZaiCodeDispatchProfile(enable_thinking=False)
    args = disp._completion_args(profile, tools=[])
    assert args["thinking"] == {"type": "disabled"}
    assert "extra_body" not in args


def test_zai_thinking_warns_non_capable_model(caplog):
    disp = _make_dispatcher()
    profile = ZaiCodeDispatchProfile(model="glm-9000")
    with caplog.at_level(logging.WARNING):
        args = disp._completion_args(profile, tools=[])
    assert args["thinking"] == {"type": "enabled"}
    assert any("thinking" in record.message.lower() for record in caplog.records)


def test_zai_client_factory_forwards_model_args():
    disp = _make_dispatcher()
    try:
        disp._client_factory("zai:glm-5.2", model_args={"temperature": 0.0, "max_tokens": 100})
    except TypeError as exc:  # pragma: no cover - failure path
        raise AssertionError(f"default Zai client factory raised TypeError: {exc}") from exc
    except Exception:
        # Building a real ZaiClient without ZAI_API_KEY raises ValueError —
        # this test only asserts the lambda signature accepts model_args=.
        pass


# ---------------------------------------------------------------------------
# Dispatch-loop harness (mirrors test_grok_code_dispatcher.py)
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


class _FakeCompletions:
    """Synchronous ``chat.completions`` stand-in for the sync zai-sdk.

    ``ZaiCodeDispatcher._chat_completion`` wraps this call in
    ``asyncio.to_thread``, so ``create`` must be a plain (non-async)
    callable — unlike the Grok fixture, whose fake client is async.
    """

    def __init__(self, responses: Sequence[_Message]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake client exhausted")
        return _Response(self.responses.pop(0))


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeSDKClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


class _FakeZaiClient:
    """Fake ``ZaiClient`` exposing ``_ensure_client()`` per the contract.

    Unlike Grok's fake (which exposes a ``.client`` attribute consumed
    directly), the Zai dispatcher calls
    ``sdk = await client._ensure_client()`` and uses the return value.
    """

    def __init__(self, responses: Sequence[_Message]) -> None:
        self._completions = _FakeCompletions(responses)
        self._sdk = _FakeSDKClient(self._completions)
        self._ensure_client = AsyncMock(return_value=self._sdk)


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
        spec_path="sdd/specs/zai-client-code.spec.md",
        feat_id="FEAT-269",
        branch_name="feat-269-zai-client-code",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


def _dispatcher(monkeypatch, zai_client: _FakeZaiClient) -> ZaiCodeDispatcher:
    captured: dict[str, Any] = {}

    def _client_factory(*args: Any, **kwargs: Any) -> _FakeZaiClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["model"] = args[0]
        return zai_client

    disp = ZaiCodeDispatcher(
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


def _published_events(dispatcher: ZaiCodeDispatcher) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in dispatcher._fake_redis.xadd.await_args_list:  # type: ignore[attr-defined]
        fields = call.args[1]
        events.append(json.loads(fields["event"]))
    return events


@pytest.mark.asyncio
async def test_zai_dispatch_runs_tool_loop_and_validates_final_output(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    (_patch_worktree_base / "app.py").write_text("print('hello')\n", encoding="utf-8")
    client = _FakeZaiClient(
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
        profile=ZaiCodeDispatchProfile(max_turns=4),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.files_changed == ["app.py"]
    assert dispatcher._captured_factory["model"] == "zai:glm-5.2"  # type: ignore[attr-defined]
    completions = client._completions
    assert completions.calls[0]["model"] == "glm-5.2"
    assert completions.calls[0]["thinking"] == {"type": "enabled"}
    assert completions.calls[0]["reasoning_effort"] == "max"
    assert "extra_body" not in completions.calls[0]
    assert any(tool["function"]["name"] == "final_output" for tool in completions.calls[0]["tools"])

    kinds = [event["kind"] for event in _published_events(dispatcher)]
    assert "dispatch.queued" in kinds
    assert "dispatch.started" in kinds
    assert "dispatch.message" in kinds
    assert "dispatch.tool_use" in kinds
    assert "dispatch.tool_result" in kinds
    assert "dispatch.completed" in kinds


@pytest.mark.asyncio
async def test_zai_text_json_final_output_is_supported(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeZaiClient(
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
        profile=ZaiCodeDispatchProfile(),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    assert result.summary == "implemented the spec"


@pytest.mark.asyncio
async def test_zai_invalid_final_tool_payload_raises_validation_error(
    monkeypatch,
    brief,
    _patch_worktree_base,
):
    client = _FakeZaiClient(
        [_Message(tool_calls=[_ToolCall("call_1", "final_output", {"files_changed": []})])]
    )
    dispatcher = _dispatcher(monkeypatch, client)

    with pytest.raises(DispatchOutputValidationError):
        await dispatcher.dispatch(
            brief=brief,
            profile=ZaiCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd=str(_patch_worktree_base),
        )


@pytest.mark.asyncio
async def test_zai_cwd_outside_worktree_base_rejected(monkeypatch, brief):
    dispatcher = _dispatcher(monkeypatch, _FakeZaiClient([]))

    with pytest.raises(DispatchExecutionError):
        await dispatcher.dispatch(
            brief=brief,
            profile=ZaiCodeDispatchProfile(),
            output_model=DevelopmentOutput,
            run_id="r1",
            node_id="development",
            cwd="/etc",
        )
