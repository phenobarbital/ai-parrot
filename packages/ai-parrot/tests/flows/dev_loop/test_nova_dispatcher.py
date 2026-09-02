"""Unit tests for NovaCodeDispatcher (FEAT-405, TASK-2086)."""

import pytest
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import NovaCodeDispatchProfile
from pydantic import BaseModel


class _Out(BaseModel):
    summary: str


@pytest.fixture
def dispatcher():
    return NovaCodeDispatcher(
        max_concurrent=1,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=60,
    )


class TestNovaCodeDispatcher:
    def test_subclasses_llm_dispatcher(self, dispatcher):
        assert isinstance(dispatcher, LLMCodeDispatcher)

    def test_completion_args_have_no_nvidia_extra_body(self, dispatcher):
        args = dispatcher._completion_args(NovaCodeDispatchProfile(), tools=[])
        assert "extra_body" not in args

    def test_completion_args_clamp_minimax(self, dispatcher):
        profile = NovaCodeDispatchProfile(model="minimax.minimax-m2.5", max_tokens=32_768)
        args = dispatcher._completion_args(profile, tools=[])
        assert args["max_tokens"] == 8_192

    def test_completion_args_no_clamp_under_ceiling(self, dispatcher):
        profile = NovaCodeDispatchProfile(model="minimax.minimax-m2.5", max_tokens=4_096)
        args = dispatcher._completion_args(profile, tools=[])
        assert args["max_tokens"] == 4_096

    def test_completion_args_include_tool_shape(self, dispatcher):
        tools = [{"type": "function", "function": {"name": "final_output"}}]
        args = dispatcher._completion_args(NovaCodeDispatchProfile(), tools=tools)
        assert args["tools"] == tools
        assert args["tool_choice"] == "auto"
        # Multi-call turns are ON by default: one tool per turn was
        # spending the `max_turns` budget on file reads.
        assert args["parallel_tool_calls"] is True

    def test_completion_args_honour_profile_parallel_tool_calls(self, dispatcher):
        profile = NovaCodeDispatchProfile(parallel_tool_calls=False)
        args = dispatcher._completion_args(profile, tools=[])
        assert args["parallel_tool_calls"] is False

    @pytest.mark.asyncio
    async def test_chat_completion_rejects_client_without_hook(self, dispatcher):
        class NoHook:
            pass

        with pytest.raises(DispatchExecutionError, match="chat completion"):
            await dispatcher._chat_completion(
                client=NoHook(), model="m", messages=[], args={}
            )

    @pytest.mark.asyncio
    async def test_chat_completion_delegates_to_client_hook(self, dispatcher):
        calls = {}

        class FakeClient:
            async def _chat_completion(self, *, model, messages, use_tools, **kwargs):
                calls["model"] = model
                calls["messages"] = messages
                calls["use_tools"] = use_tools
                calls["kwargs"] = kwargs
                return "ok"

        result = await dispatcher._chat_completion(
            client=FakeClient(),
            model="minimax.minimax-m2.5",
            messages=[{"role": "user", "content": "hi"}],
            args={"max_tokens": 100},
        )
        assert result == "ok"
        assert calls["model"] == "minimax.minimax-m2.5"
        assert calls["use_tools"] is True
        assert calls["kwargs"] == {"max_tokens": 100}


class TestMantleClientFactory:
    def test_missing_api_key_raises(self, dispatcher, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", None)
        with pytest.raises(DispatchExecutionError, match="AWS_NOVA_API_KEY"):
            dispatcher._create_mantle_client("nova:minimax.minimax-m2.5")

    def test_base_url_derived_from_region(self, dispatcher, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", "ABSK-test-key")
        monkeypatch.setattr(conf, "DEV_LOOP_NOVA_MANTLE_BASE_URL", "")
        monkeypatch.setattr(conf, "DEV_LOOP_NOVA_MANTLE_REGION", "us-east-1")
        client = dispatcher._create_mantle_client("nova:minimax.minimax-m2.5")
        assert client.base_url == "https://bedrock-mantle.us-east-1.api.aws/v1"
        assert client.model == "minimax.minimax-m2.5"

    def test_explicit_base_url_wins(self, dispatcher, monkeypatch):
        from parrot import conf

        monkeypatch.setattr(conf, "AWS_NOVA_API_KEY", "ABSK-test-key")
        monkeypatch.setattr(
            conf, "DEV_LOOP_NOVA_MANTLE_BASE_URL", "https://custom.example/v1"
        )
        client = dispatcher._create_mantle_client("nova:minimax.minimax-m2.5")
        assert client.base_url == "https://custom.example/v1"
