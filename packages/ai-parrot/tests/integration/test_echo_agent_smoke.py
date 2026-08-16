"""Smoke-test: real (no-mock) round-trip through the bot pipeline.

Verifies that a real LLM call with tool-calling, guardrails, and the
full ``bot.ask()`` pipeline still works end-to-end after any codebase
change.  This is NOT for CI — it hits a real LLM (gemini-3.1-flash-lite)
and requires valid Google API credentials in the environment.

Run locally with::

    source .venv/bin/activate
    pytest packages/ai-parrot/tests/integration/test_echo_agent_smoke.py -v -s

Two layers:
    1. **Direct bot.ask()** — instantiates ``EchoAgent``, calls ``ask()``
       with ``user_id=35`` (int), verifies response + tool invocation.
    2. **AgentTalk HTTP** — mounts a test-subclass of ``AgentTalk`` on an
       aiohttp test client, POSTs a chat request, verifies HTTP 200 +
       valid response body.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
from aiohttp import web

from parrot.bots import Agent
from parrot.models.responses import AIMessage
from parrot.tools.echo_tools import get_current_datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TODAY_STR = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _make_echo_agent() -> Agent:
    """Create a fresh EchoAgent for testing (no registry side-effects)."""
    agent = Agent(
        name="echo_agent_test",
        model="gemini-3.1-flash-lite",
        system_prompt=(
            "You are a concise test agent.  When the user asks about the "
            "current date or time, you MUST call the get_current_datetime "
            "tool and include the result in your answer.  Keep answers "
            "short — one sentence maximum."
        ),
    )
    agent.register_tool(get_current_datetime)
    return agent


# ===================================================================
# Layer 1 — Direct bot.ask() (pipeline-level smoke test)
# ===================================================================


class TestDirectBotAsk:
    """Invoke ``bot.ask()`` directly — exercises the full internal pipeline:
    guardrails (``GuardrailContext`` with ``user_id=int``), tool-calling,
    LLM completion, and response construction.
    """

    @pytest.fixture
    async def echo_agent(self) -> Agent:
        agent = _make_echo_agent()
        await agent.configure()
        return agent

    async def test_ask_returns_non_empty_response(self, echo_agent: Agent):
        """Basic round-trip: LLM answers with non-empty content."""
        response: AIMessage = await echo_agent.ask(
            question="What is the current date and time?",
            user_id=35,  # int — was crashing before the GuardrailContext fix
            session_id="smoke-test-session",
            use_conversation_history=False,
            use_vector_context=False,
        )
        assert response is not None, "ask() returned None"
        assert isinstance(response, AIMessage), f"Expected AIMessage, got {type(response)}"
        content = response.content or ""
        assert len(content) > 0, "Response content is empty"
        logger.info("LLM response: %s", content)

    async def test_tool_calling_works(self, echo_agent: Agent):
        """The LLM should invoke get_current_datetime and include today's date."""
        response: AIMessage = await echo_agent.ask(
            question="Tell me today's date using your tool.",
            user_id=35,
            session_id="smoke-test-tool",
            use_conversation_history=False,
            use_vector_context=False,
        )
        content = (response.content or "").strip()
        assert len(content) > 0, "Response content is empty"
        # The response should contain today's date in some form
        # (YYYY-MM-DD or spelled out)
        year_str = datetime.now(timezone.utc).strftime("%Y")
        assert year_str in content, (
            f"Expected the current year ({year_str}) in the response. "
            f"Got: {content!r}"
        )
        logger.info("Tool-calling response: %s", content)

    async def test_int_user_id_does_not_crash(self, echo_agent: Agent):
        """Regression: ``GuardrailContext(user_id=<int>)`` must not raise."""
        # If guardrails are not configured this still exercises the code
        # path that constructs GuardrailContext in _run_input_pipeline.
        response: AIMessage = await echo_agent.ask(
            question="Hello",
            user_id=35,
            session_id="smoke-test-int-uid",
            use_conversation_history=False,
            use_vector_context=False,
        )
        assert response is not None
        assert isinstance(response.content, str)


# ===================================================================
# Layer 2 — AgentTalk HTTP endpoint
# ===================================================================

# Auth decorators must be replaced with no-ops BEFORE the handler module
# is imported — they are applied at class-definition time, so a late
# patch has no effect.  This mirrors the pattern in
# packages/ai-parrot/tests/handlers/conftest.py.
def _noop_auth_factory(*_args, **_kwargs):
    """Return a passthrough decorator — replaces @is_authenticated / @user_session."""
    def _passthrough(handler):
        return handler
    return _passthrough


def _import_agenttalk():
    """Import AgentTalk with auth decorators disabled."""
    import importlib
    import sys

    try:
        import navigator_auth.decorators as _auth_dec
    except ImportError:
        return None

    _orig_is_auth = _auth_dec.is_authenticated
    _orig_user_session = _auth_dec.user_session

    # Temporarily replace with no-ops
    _auth_dec.is_authenticated = _noop_auth_factory
    _auth_dec.user_session = _noop_auth_factory

    # Force re-import if already cached with real decorators
    mod_name = "parrot.handlers.agent"
    sys.modules.pop(mod_name, None)

    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, "AgentTalk", None)
    except ImportError:
        return None
    finally:
        _auth_dec.is_authenticated = _orig_is_auth
        _auth_dec.user_session = _orig_user_session


AgentTalk = _import_agenttalk()
_AGENTTALK_AVAILABLE = AgentTalk is not None


@pytest.mark.skipif(
    not _AGENTTALK_AVAILABLE,
    reason="AgentTalk handler not importable (ai-parrot-server not installed)",
)
class TestAgentTalkHTTP:
    """POST to a real AgentTalk endpoint backed by a real EchoAgent.

    Auth and PBAC are bypassed via a thin subclass; the bot pipeline
    (guardrails → tool-calling → LLM) runs completely unmodified.
    """

    @pytest.fixture
    async def echo_agent(self) -> Agent:
        agent = _make_echo_agent()
        await agent.configure()
        return agent

    @pytest.fixture
    async def client(self, echo_agent, aiohttp_client):
        """Boot a minimal aiohttp app with a test-only AgentTalk subclass."""
        # Capture the agent in closure for _resolve_bot
        _agent = echo_agent

        class _SmokeAgentTalk(AgentTalk):
            """AgentTalk subclass that bypasses auth/PBAC but uses a real bot."""

            async def _check_pbac_agent_access(
                self, agent_id: str, action: str = "agent:chat"
            ):
                return None  # always allow

            async def _get_user_session(self, data: dict):
                # Return user_id as int — exercises the GuardrailContext fix
                user_id = data.pop("user_id", 35)
                session_id = data.pop("session_id", None) or uuid.uuid4().hex
                return user_id, session_id

            async def _resolve_bot(self, data):
                return _agent, False

        app = web.Application()
        app.router.add_view(
            "/api/v1/agents/chat/{agent_id}",
            _SmokeAgentTalk,
        )
        return await aiohttp_client(app)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    async def _post_chat(client, query: str, **extra):
        """POST to the smoke agent and return (status, body_dict)."""
        payload = {"query": query, "user_id": 35, "output_format": "json", **extra}
        resp = await client.post(
            "/api/v1/agents/chat/echo_agent_test",
            json=payload,
        )
        body = await resp.json() if resp.content_type == "application/json" else {}
        return resp.status, body

    @staticmethod
    def _assert_valid_envelope(body: dict):
        """Assert the response envelope is a successful AgentTalk response,
        NOT a JSON-wrapped error string."""
        # Must NOT contain an error key
        assert "error" not in body, (
            f"Response contains an error: {body['error']}"
        )
        # Must contain the standard output fields
        assert "response" in body or "output" in body, (
            f"Missing 'response'/'output' in envelope. Keys: {list(body.keys())}"
        )
        content = body.get("response") or body.get("output") or ""
        assert len(content) > 0, f"Empty response content: {body}"
        # Metadata must be present and well-formed
        meta = body.get("metadata")
        assert isinstance(meta, dict), (
            f"Expected metadata dict, got {type(meta)}: {body}"
        )
        assert meta.get("model"), "metadata.model is missing"
        assert meta.get("provider"), "metadata.provider is missing"
        return content, meta

    # -- tests ---------------------------------------------------------------

    async def test_post_returns_valid_envelope(self, client):
        """POST returns HTTP 200 with a well-formed JSON envelope (not an error)."""
        status, body = await self._post_chat(client, "What is the current date?")
        assert status == 200, f"Expected 200, got {status}. Body: {body}"
        content, meta = self._assert_valid_envelope(body)
        logger.info("Envelope OK — content: %s", content[:120])

    async def test_response_includes_tool_result(self, client):
        """The LLM calls get_current_datetime and the date appears in the response."""
        status, body = await self._post_chat(
            client, "Tell me the current date and time using your tool.",
        )
        assert status == 200
        content, meta = self._assert_valid_envelope(body)
        # The response must contain today's date (ISO prefix)
        assert TODAY_STR in content, (
            f"Expected today's date ({TODAY_STR}) in response. Got: {content!r}"
        )
        logger.info("Tool result present — content: %s", content[:200])

    async def test_int_user_id_through_http(self, client):
        """Regression: int user_id=35 flows through GuardrailContext without crash."""
        status, body = await self._post_chat(client, "Hello")
        assert status == 200, (
            f"int user_id crashed the pipeline: {status} — {body}"
        )
        content, meta = self._assert_valid_envelope(body)
        # Verify user_id was coerced to str in metadata
        assert meta.get("user_id") == "35", (
            f"Expected user_id='35' in metadata, got {meta.get('user_id')!r}"
        )
