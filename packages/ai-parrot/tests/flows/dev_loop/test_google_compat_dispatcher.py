import json
from types import SimpleNamespace

from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile, LLMCodeDispatcher
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.models import DevAgentSpec


def _disp(cls=GoogleCompatCodeDispatcher):
    return cls(max_concurrent=1, redis_url="redis://localhost:1/0", stream_ttl_seconds=60)


def _call(extra=None):
    fn = SimpleNamespace(name="read_file", arguments='{"path": "README.md"}')
    return SimpleNamespace(id="c1", type="function", function=fn, extra_content=extra)


def test_compat_profile_defaults():
    p = GoogleCompatCodeDispatchProfile()
    assert p.llm == "google-compat:gemini-3.5-flash" and p.reasoning_effort == "none" and p.enable_thinking is False
    assert GoogleCompatCodeDispatchProfile(model="gemini-3.8-flash").llm == "google-compat:gemini-3.8-flash"


def test_compat_dispatcher_completion_args():
    args = _disp()._completion_args(GoogleCompatCodeDispatchProfile(enable_thinking=True), tools=[{"type": "function"}])
    assert args["reasoning_effort"] == "none" and "extra_body" not in args
    assert {"tools", "tool_choice", "parallel_tool_calls", "max_tokens"} <= set(args)


def test_compat_dispatcher_carries_extra_content():
    sig = {"google": {"thought_signature": "abc=="}}
    assert _disp()._tool_call_to_openai_dict(_call(sig))["extra_content"] == sig
    assert "extra_content" not in _disp()._tool_call_to_openai_dict(_call(None))
    assert "extra_content" not in _disp(LLMCodeDispatcher)._tool_call_to_openai_dict(_call(sig))


def test_compat_dispatcher_multiturn_wire_format():
    sig = {"google": {"thought_signature": "abc=="}}
    dispatcher = _disp()
    rendered = dispatcher._tool_call_to_openai_dict(_call(sig))
    assistant_turn = {"role": "assistant", "content": "", "tool_calls": [rendered]}
    tool_result = {"role": "tool", "tool_call_id": rendered["id"], "content": "README contents"}
    messages = [assistant_turn, tool_result]

    assert messages[0]["tool_calls"][0]["extra_content"] == sig
    assert isinstance(messages[0]["tool_calls"][0]["function"]["arguments"], str)
    parsed = json.loads(messages[0]["tool_calls"][0]["function"]["arguments"])
    assert parsed == {"path": "README.md"}
    assert messages[1]["tool_call_id"] == rendered["id"]

    # The base dispatcher never carries extra_content, regression-guarding S9.
    base_rendered = _disp(LLMCodeDispatcher)._tool_call_to_openai_dict(_call(sig))
    assert "extra_content" not in base_rendered


def test_build_dispatcher_google_compat():
    def getter(k, fb=None):
        return {"DEV_LOOP_GOOGLE_COMPAT_MODEL": "gemini-3.6-flash"}.get(k, fb)

    d, p = build_dispatcher(
        DevAgentSpec(agent="google-compat"),
        redis_url="redis://x",
        max_concurrent=1,
        stream_ttl_seconds=60,
        config_getter=getter,
    )
    assert isinstance(d, GoogleCompatCodeDispatcher) and p.model == "gemini-3.6-flash"
    _, p2 = build_dispatcher(
        DevAgentSpec(agent="google-compat", model="gemini-3.5-flash"),
        redis_url="redis://x",
        max_concurrent=1,
        stream_ttl_seconds=60,
        config_getter=getter,
    )
    assert p2.llm == "google-compat:gemini-3.5-flash"
