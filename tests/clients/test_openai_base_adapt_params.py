"""Unit tests for ``OpenAIBaseClient._adapt_completion_params()``.

Hotfix ``openai-max-completion-tokens`` (no Jira ticket, FEAT-466) — see
``sdd/specs/openai-max-completion-tokens.spec.md`` §3 Module 1.
"""
from types import SimpleNamespace
from typing import Any

import pytest
from parrot.clients.openai_base import OpenAIBaseClient

from tests.clients.test_openai_compatible_defaults import WIRE_SUBCLASSES


class _Stub(OpenAIBaseClient):
    """Concrete stand-in (mirrors tests/clients/test_openai_base.py::_Stub)."""

    async def get_client(self):  # pragma: no cover - not exercised here
        return None

    async def ask(self, *a, **k):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def ask_stream(self, *a, **k):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def resume(self, *a, **k):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def invoke(self, *a, **k):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _OptedIn(_Stub):
    _uses_max_completion_tokens = True
    _fixed_temperature_models = ("gpt-5",)


@pytest.fixture
def captured_payload():
    """Capture the kwargs handed to the SDK without a network call."""
    seen: dict[str, Any] = {}

    async def _fake_create(*, model, messages, **kwargs):
        seen.update(kwargs)
        seen["model"] = model
        return SimpleNamespace(choices=[], usage=None)

    return seen, _fake_create


def test_max_tokens_renamed_when_opted_in():
    c = _OptedIn.__new__(_OptedIn)
    out = c._adapt_completion_params("gpt-4.1", {"max_tokens": 512})
    assert out == {"max_completion_tokens": 512}


def test_max_tokens_untouched_by_default():
    c = _Stub.__new__(_Stub)
    assert c._adapt_completion_params("any", {"max_tokens": 512}) == {"max_tokens": 512}


def test_no_token_key_added_when_absent():
    c = _OptedIn.__new__(_OptedIn)
    out = c._adapt_completion_params("gpt-5-mini", {"messages_extra": 1})
    assert "max_tokens" not in out and "max_completion_tokens" not in out


def test_temperature_dropped_for_fixed_temperature_model():
    c = _OptedIn.__new__(_OptedIn)
    assert "temperature" not in c._adapt_completion_params("gpt-5-mini", {"temperature": 0.0})


def test_temperature_kept_for_normal_model():
    c = _OptedIn.__new__(_OptedIn)
    assert c._adapt_completion_params("gpt-4.1", {"temperature": 0.0})["temperature"] == 0.0


@pytest.mark.parametrize("model", ["GPT-5-Mini", "gpt-5.6-sol", "openai/gpt-5"])
def test_fixed_temperature_match_is_substring_and_case_insensitive(model):
    c = _OptedIn.__new__(_OptedIn)
    assert "temperature" not in c._adapt_completion_params(model, {"temperature": 0.2})


def test_adapt_does_not_mutate_caller_kwargs():
    c = _OptedIn.__new__(_OptedIn)
    src = {"max_tokens": 5, "temperature": 0.0}
    c._adapt_completion_params("gpt-5-mini", src)
    assert src == {"max_tokens": 5, "temperature": 0.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_chat_completion_routes_through_hook(captured_payload, stream, bind_sdk_client):
    """The funnel applies the hook on both the plain and the streaming path."""
    seen, fake = captured_payload
    c = _OptedIn.__new__(_OptedIn)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake)))
    bind_sdk_client(c, sdk)
    await c._chat_completion(
        "gpt-5-mini", [], use_tools=True, stream=stream, max_tokens=64, temperature=0.0
    )
    assert seen["max_completion_tokens"] == 64
    assert "max_tokens" not in seen and "temperature" not in seen


# NOTE: `OpenAIClient` is not a member of WIRE_SUBCLASSES (it never was —
# see test_openai_compatible_defaults.py). `MoonshotClient` is excluded here
# by HOTFIX-openai-max-completion-tokens-3: it opts in
# (`_uses_max_completion_tokens = True`) as part of folding its bespoke
# translation into this shared hook; see
# tests/clients/test_moonshot_client.py::TestMoonshotPayloadUnchanged for its
# own payload-parity coverage.
_DEFAULTS_SWEEP_ROSTER = [cls for cls in WIRE_SUBCLASSES if cls.__name__ != "MoonshotClient"]


@pytest.mark.parametrize("cls", _DEFAULTS_SWEEP_ROSTER, ids=lambda c: c.__name__)
def test_wire_subclasses_keep_defaults(cls):
    """Guards the byte-identical-payload criterion for non-opted-in clients."""
    assert cls._uses_max_completion_tokens is False
    assert cls._fixed_temperature_models == ()
