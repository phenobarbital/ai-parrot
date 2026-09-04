"""Unit tests for ``BedrockMantleClient`` (FEAT-407).

Covers endpoint resolution (region-aware base URL construction, explicit
overrides), API-key resolution order (kwarg -> BEDROCK_MANTLE_API_KEY ->
AWS_NOVA_API_KEY, surviving ``super().__init__``), the ``_fallback_model``
shadowing guard, ``get_client()``, ``LLMFactory`` registration (both the
``"bedrock-mantle"`` key and the ``"mantle"`` alias), and a mocked ``ask()``
round trip proving the inherited ``OpenAIBaseClient`` machinery (FEAT-438)
is untouched.

No live Bedrock/AWS calls are made by default — ``test_live_mantle_ask`` is
skip-gated behind ``RUN_MANTLE_LIVE_TEST``.

Conf-var testing gotcha: ``parrot.conf`` values are read at *import time*
into module-level constants inside ``parrot.clients.amazon.nova.mantle`` —
``monkeypatch.setenv`` after import does NOT change them. Tests patch the
constants directly on the ``mantle`` module instead.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from parrot.clients.factory import SUPPORTED_CLIENTS, LLMFactory
from parrot.clients.amazon.nova import BedrockMantleClient
from parrot.models import AIMessage


@pytest.fixture
def mantle_client(monkeypatch):
    """BedrockMantleClient isolated from the developer's real environment."""
    monkeypatch.setattr("parrot.clients.amazon.nova.mantle.AWS_NOVA_API_KEY", None, raising=False)
    monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_API_KEY", None, raising=False)
    monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_BASE_URL", None, raising=False)
    return BedrockMantleClient(api_key="ABSK-test-key", region="us-east-1")


def _make_mock_chat_completion_response(content: str = "ok"):
    """Build a MagicMock OpenAI chat-completion response, mirroring the
    shape used by test_nvidia_client.py's mocked round trips.
    """
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_choice.message.tool_calls = None
    mock_choice.message.role = "assistant"
    mock_choice.finish_reason = "stop"
    mock_choice.stop_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    mock_response.dict = MagicMock(return_value={})
    # AIMessageFactory.from_openai checks hasattr(response, "model_dump")
    # first (responses.py:492) — a bare MagicMock auto-vivifies that
    # attribute too, returning another MagicMock instead of a dict, which
    # fails AIMessage's raw_response validation. Pin it explicitly so this
    # mock exercises the same code path AIMessageFactory.from_openai
    # actually takes (pre-existing gap, predates FEAT-438 — confirmed via
    # the same failure on dev's gpt.py:1124 with this exact fixture).
    mock_response.model_dump = MagicMock(return_value={})
    return mock_response


class TestBedrockMantleClient:
    def test_default_model(self, mantle_client):
        assert mantle_client.client_type == "bedrock-mantle"
        assert mantle_client.client_name == "bedrock-mantle"
        assert mantle_client._default_model == "openai.gpt-oss-120b"

    def test_region_kwarg_builds_base_url(self, mantle_client):
        assert mantle_client.base_url == "https://bedrock-mantle.us-east-1.api.aws/v1"

    def test_fallback_model_survives_init(self, mantle_client):
        """FEAT-438 G5: AbstractClient.__init__ only creates an instance
        _fallback_model attribute when fallback_model= is explicitly
        passed, so this class's class-level _fallback_model is visible
        without any per-subclass workaround (the former
        kwargs.setdefault("fallback_model", ...) guard was removed)."""
        assert mantle_client._fallback_model == "google.gemma-4-26b-a4b"

    def test_explicit_base_url_wins(self):
        c = BedrockMantleClient(api_key="k", base_url="https://custom.example/v1")
        assert c.base_url == "https://custom.example/v1"

    def test_default_base_url_from_region(self, monkeypatch):
        """No region/base_url kwargs and conf region unset -> constructed
        default URL for the us-east-1 fallback."""
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_AWS_REGION", None, raising=False)
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.AWS_REGION_NAME", None, raising=False)
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_BASE_URL", None, raising=False)
        c = BedrockMantleClient(api_key="k")
        assert c.base_url == "https://bedrock-mantle.us-east-1.api.aws/v1"

    def test_conf_base_url_wins_over_region_construction(self, monkeypatch):
        """BEDROCK_MANTLE_BASE_URL conf var beats region-constructed URL,
        but explicit base_url kwarg still wins over it."""
        monkeypatch.setattr(
            "parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_BASE_URL",
            "https://conf-configured.example/v1",
            raising=False,
        )
        c = BedrockMantleClient(api_key="k", region="eu-west-1")
        assert c.base_url == "https://conf-configured.example/v1"

        c2 = BedrockMantleClient(api_key="k", region="eu-west-1", base_url="https://kwarg-wins.example/v1")
        assert c2.base_url == "https://kwarg-wins.example/v1"

    def test_api_key_resolution_order(self, monkeypatch):
        # kwarg wins over conf vars
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_API_KEY", "mantle-key", raising=False)
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.AWS_NOVA_API_KEY", "nova-key", raising=False)
        c = BedrockMantleClient(api_key="explicit-key", region="us-east-1")
        assert c.api_key == "explicit-key"

        # BEDROCK_MANTLE_API_KEY wins over AWS_NOVA_API_KEY when no kwarg
        c2 = BedrockMantleClient(region="us-east-1")
        assert c2.api_key == "mantle-key"

        # AWS_NOVA_API_KEY used as final fallback
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_API_KEY", None, raising=False)
        c3 = BedrockMantleClient(region="us-east-1")
        assert c3.api_key == "nova-key"

        # A developer's real OPENAI_API_KEY must NOT be silently used
        # against Mantle when a Mantle/Nova key is already configured —
        # resolution happens before super().__init__, so OpenAIClient's
        # own OPENAI_API_KEY fallback (gpt.py:92) is never reached.
        monkeypatch.setattr(
            "parrot.clients.openai.client.config.get",
            lambda key, *a, **kw: "SHOULD-NOT-BE-USED" if key == "OPENAI_API_KEY" else None,
        )
        c4 = BedrockMantleClient(region="us-east-1")
        assert c4.api_key == "nova-key"
        assert c4.api_key != "SHOULD-NOT-BE-USED"

    def test_base_headers_not_leaked_when_no_key_resolves(self, monkeypatch):
        """Code-review regression test (FEAT-407): when no Mantle/Nova/
        explicit key resolves, OpenAIClient.__init__ falls back to
        config.get("OPENAI_API_KEY") for BOTH self.api_key and
        self.base_headers before the re-set guard runs. The guard fixes
        self.api_key, but base_headers must also be rebuilt — otherwise
        AbstractClient.__aenter__ (use_session=True) would send a real
        OPENAI_API_KEY as a bearer token to the Bedrock Mantle host."""
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.BEDROCK_MANTLE_API_KEY", None, raising=False)
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.AWS_NOVA_API_KEY", None, raising=False)
        monkeypatch.setattr(
            "parrot.clients.openai.client.config.get",
            lambda key, *a, **kw: "SHOULD-NOT-LEAK" if key == "OPENAI_API_KEY" else None,
        )
        c = BedrockMantleClient(region="us-east-1")
        assert c.api_key is None
        assert c.base_headers["Authorization"] == "Bearer None"
        assert "SHOULD-NOT-LEAK" not in c.base_headers["Authorization"]

    @pytest.mark.asyncio
    async def test_get_client_uses_base_url(self, mantle_client):
        from openai import AsyncOpenAI

        openai_client = await mantle_client.get_client()
        assert isinstance(openai_client, AsyncOpenAI)
        assert str(openai_client.base_url).rstrip("/") == mantle_client.base_url.rstrip("/")
        assert openai_client.api_key == mantle_client.api_key


class TestBedrockMantleFactory:
    def test_factory_creates_mantle_client(self, monkeypatch):
        monkeypatch.setattr("parrot.clients.amazon.nova.mantle.AWS_NOVA_API_KEY", "test-key", raising=False)
        assert "bedrock-mantle" in SUPPORTED_CLIENTS
        assert "mantle" in SUPPORTED_CLIENTS

        client = LLMFactory.create("bedrock-mantle:openai.gpt-oss-120b")
        assert isinstance(client, BedrockMantleClient)
        assert client.model == "openai.gpt-oss-120b"

        alias_client = LLMFactory.create("mantle:openai.gpt-oss-120b")
        assert isinstance(alias_client, BedrockMantleClient)
        assert alias_client.model == "openai.gpt-oss-120b"


class TestBedrockMantleAsk:
    @pytest.mark.asyncio
    async def test_ask_delegates_to_openai_machinery(self, mantle_client):
        """Mocked chat-completion round trip returns an AIMessage — proves
        the inherited OpenAIBaseClient.ask() path is untouched (no
        _chat_completion/ask override on BedrockMantleClient). FEAT-438
        rebased BedrockMantleClient onto OpenAIBaseClient (not
        OpenAIClient), so the funnel to patch is on the new base module."""
        mock_response = _make_mock_chat_completion_response("Hello from Mantle")

        async def fake_chat_completion(model, messages, use_tools=False, **kwargs):
            return mock_response

        with patch(
            "parrot.clients.openai_base.OpenAIBaseClient._chat_completion",
            side_effect=fake_chat_completion,
        ):
            result = await mantle_client.ask(
                "Explain quantum entanglement simply.",
                model="anthropic.claude-mythos-preview",
            )

        assert isinstance(result, AIMessage)
        assert result.output == "Hello from Mantle"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_mantle_ask():
    """Real integration test against the Bedrock Mantle endpoint (spec §4).

    Skipped by default — requires an explicit opt-in
    (``RUN_MANTLE_LIVE_TEST=1``) plus a real Bedrock API key configured via
    ``BEDROCK_MANTLE_API_KEY`` / ``AWS_NOVA_API_KEY``.
    """
    if not os.getenv("RUN_MANTLE_LIVE_TEST"):
        pytest.skip("RUN_MANTLE_LIVE_TEST not set — opt-in required for real Bedrock " "Mantle calls (see docstring).")

    client = BedrockMantleClient()
    try:
        result = await client.ask("Say 'hello' and nothing else.", model="openai.gpt-oss-120b")
    except Exception as exc:  # pragma: no cover — depends on account/region state
        pytest.skip(f"Bedrock Mantle not accessible in this account/region: {exc}")
    assert result.output
