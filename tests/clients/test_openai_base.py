"""Unit tests for the OpenAIBaseClient skeleton (FEAT-438 Module 1).

Verifies the base carries no OpenAI-provider defaults (no model-id values,
identity normalization, fail-fast on unresolved model) and that the module
source itself never leaks an OpenAI-only model literal.
"""
import pathlib

import parrot.clients.openai_base as _openai_base_module
import pytest
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.tools.manager import ToolFormat


class _Stub(OpenAIBaseClient):
    """Minimal concrete subclass for instantiation (abstract methods stubbed)."""

    client_type = "stub"

    async def get_client(self):  # pragma: no cover - not exercised here
        return None

    async def ask(self, *args, **kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def ask_stream(self, *args, **kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def resume(self, *args, **kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError

    async def invoke(self, *args, **kwargs):  # pragma: no cover - not exercised here
        raise NotImplementedError


def test_no_model_defaults():
    s = _Stub(api_key="k", base_url="http://x/v1")
    assert s._lightweight_model is None
    assert getattr(s, "_default_model", None) is None
    assert getattr(s, "_fallback_model", None) is None


def test_normalize_model_identity():
    s = _Stub(api_key="k", base_url="http://x/v1")
    assert s._normalize_model("whatever-model") == "whatever-model"


def test_resolve_model_fails_fast_without_model():
    s = _Stub(api_key="k", base_url="http://x/v1")
    with pytest.raises(ValueError, match="no model configured"):
        s._resolve_model(None)


def test_resolve_model_uses_configured_model():
    s = _Stub(api_key="k", base_url="http://x/v1", model="my-model")
    assert s._resolve_model(None) == "my-model"


def test_resolve_model_explicit_wins_over_configured():
    s = _Stub(api_key="k", base_url="http://x/v1", model="my-model")
    assert s._resolve_model("other-model") == "other-model"


def test_is_responses_model_always_false():
    s = _Stub(api_key="k", base_url="http://x/v1")
    assert s._is_responses_model("anything") is False


def test_with_extra_body_merges():
    payload = {"model": "x", "extra_body": {"a": 1}}
    merged = OpenAIBaseClient._with_extra_body(payload, {"b": 2})
    assert merged["extra_body"] == {"a": 1, "b": 2}


def test_tool_format_is_openai():
    assert OpenAIBaseClient.tool_format is ToolFormat.OPENAI


def test_module_has_no_gpt_literal():
    # Resolve via the imported module's own __file__ rather than a
    # cwd-relative literal: importing `parrot.*` triggers navconfig's
    # settings bootstrap, which os.chdir()s to the MAIN repo checkout —
    # a known cross-worktree gotcha (see
    # packages/ai-parrot/tests/unit/bots/test_finance_reporter_descriptors.py) —
    # so a cwd-relative path would silently resolve against the wrong tree.
    src = pathlib.Path(_openai_base_module.__file__).read_text()
    assert "gpt-" not in src
