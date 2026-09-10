"""Opt-in live round-trip guarding the Gemini 3 `thought_signature` fix (FEAT-549 AC-4, spec §6 variant C).

Never runs by default: `pytest -m live` opts in, and the test is additionally
skipped when no Gemini/Google API key is configured. NOT part of the default
`pytest packages/ai-parrot/tests/flows/dev_loop` run.
"""
from __future__ import annotations

import json

import pytest
from navconfig import config

from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile
from parrot.flows.dev_loop.models import DevelopmentOutput

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not (config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")),
    reason="needs GEMINI_API_KEY or GOOGLE_API_KEY (opt-in live test)",
)
async def test_gemini_compat_live_roundtrip():
    dispatcher = GoogleCompatCodeDispatcher(max_concurrent=1, redis_url="redis://127.0.0.1:1/0", stream_ttl_seconds=60)
    profile = GoogleCompatCodeDispatchProfile()
    client = dispatcher._create_compat_client(profile.llm, model_args={"temperature": 0.0, "max_tokens": 256})
    # Code-review fix (FEAT-549): the real `dispatch()` loop always calls this before its first
    # `_chat_completion` (dispatchers/llm.py:273) — it lazily opens the client's underlying SDK
    # session. Without it, `_chat_completion` raises `AttributeError: 'NoneType' object has no
    # attribute 'chat'` before ever reaching the network, so this test never actually exercised
    # the `thought_signature` fix it exists to guard.
    await dispatcher._ensure_client_ready(client)
    tools = dispatcher._tool_schemas(DevelopmentOutput)
    args = dispatcher._completion_args(profile, tools)
    messages = [
        {"role": "system", "content": "You are a coding agent. Use tools."},
        {"role": "user", "content": "Read README.md now."},
    ]
    r1 = await dispatcher._chat_completion(client=client, model=profile.model, messages=messages, args=args)
    calls = dispatcher._message_tool_calls(dispatcher._response_message(r1))
    assert calls, "expected a tool call"

    messages.append(
        {"role": "assistant", "content": "", "tool_calls": [dispatcher._tool_call_to_openai_dict(c) for c in calls]}
    )
    messages += [
        {"role": "tool", "tool_call_id": dispatcher._tool_call_id(c), "content": json.dumps({"content": "# README"})}
        for c in calls
    ]
    # Would be HTTP 400 "Function call is missing a thought_signature" without
    # the extra_content carry-over in `_tool_call_to_openai_dict`.
    r2 = await dispatcher._chat_completion(client=client, model=profile.model, messages=messages, args=args)
    assert dispatcher._finish_reason(r2) in ("stop", "tool_calls")
