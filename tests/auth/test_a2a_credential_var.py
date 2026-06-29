"""Tests that A2AServer._try_invoke_with_gate() injects _CREDENTIAL_VAR.

Issue 1 fix (FEAT-264 code review): the resolved branch must set the
per-call ContextVar so tools can retrieve the credential via
current_credential() inside _execute().

No real HTTP server is started; _try_invoke_with_gate() is called directly.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal fakes that avoid importing the full SDK stack
# ---------------------------------------------------------------------------


class _FakeTask:
    """Minimal Task double that records complete/fail calls."""

    def __init__(self):
        self.result = None
        self.failed = False
        self.artifacts = []
        self.status = MagicMock()
        self.id = "task-1"
        self.context_id = "ctx-1"

    def complete(self, result):
        self.result = result

    def fail(self, reason):
        self.failed = True
        self.result = reason


class _CredentialCapturingTool:
    """A real (non-fake) tool whose _execute() calls current_credential().

    Returns the credential value so the test can assert it was injected.
    """

    name = "credential_capturing_tool"
    credential_provider = "test_provider"

    async def _execute(self, **kwargs):
        from parrot.tools.abstract import current_credential

        return current_credential()


class _ResolvedCredentialResolver:
    """Resolver that always returns a fixed secret."""

    def __init__(self, secret: str = "test-secret-token") -> None:
        self._secret = secret

    async def resolve(self, channel: str, user_id: str):
        return self._secret

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return "https://example.com/auth"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def broker_with_test_provider():
    """CredentialBroker pre-loaded with a resolver for 'test_provider'."""
    from parrot.auth.broker import CredentialBroker
    from parrot.security.audit_ledger import AuditLedger

    ledger = AuditLedger()
    broker = CredentialBroker(audit_ledger=ledger)
    broker.register(
        "test_provider", _ResolvedCredentialResolver(), auth_kind="static_key"
    )
    return broker


@pytest.fixture
def a2a_server(broker_with_test_provider):
    """A2AServer wrapping a minimal mock agent, configured with the broker."""
    from parrot.a2a.server import A2AServer

    mock_agent = MagicMock()
    mock_agent.name = "TestAgent"
    mock_agent.tool_manager = MagicMock()
    mock_agent.tool_manager.list_tools.return_value = []
    mock_agent.tool_manager.get_tool.return_value = None
    mock_agent.tools = None

    server = A2AServer(mock_agent, broker=broker_with_test_provider)
    return server


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA2ACredentialVarInjection:
    """_try_invoke_with_gate() must set _CREDENTIAL_VAR before calling _execute()."""

    @pytest.mark.asyncio
    async def test_resolved_credential_reaches_tool_via_contextvar(
        self, a2a_server
    ):
        """Tool._execute() sees the resolved secret via current_credential().

        The broker resolves a credential for 'test_provider'; the A2A gate
        must inject it into _CREDENTIAL_VAR before calling _execute() so
        the tool can retrieve it via current_credential().
        """
        tool = _CredentialCapturingTool()
        task = _FakeTask()

        # Monkey-patch _find_tool so the server returns our capturing tool.
        a2a_server._find_tool = lambda name: tool if name == tool.name else None

        suspended = await a2a_server._try_invoke_with_gate(
            tool_name=tool.name,
            params={},
            user_id="alice@example.com",
            channel="a2a:copilot",
            task=task,
        )

        assert not suspended, "task should complete, not suspend"
        assert not task.failed, f"task failed unexpectedly: {task.result}"
        assert task.result == "test-secret-token", (
            f"tool received {task.result!r} instead of the injected credential; "
            "check that _CREDENTIAL_VAR is set before _execute() is called"
        )

    @pytest.mark.asyncio
    async def test_credential_var_is_reset_after_execute(self, a2a_server):
        """_CREDENTIAL_VAR must be None after _try_invoke_with_gate() returns.

        Confirms the finally block resets the token so subsequent unrelated
        tool calls do not accidentally see a stale credential.
        """
        from parrot.tools.abstract import current_credential

        tool = _CredentialCapturingTool()
        task = _FakeTask()
        a2a_server._find_tool = lambda name: tool if name == tool.name else None

        await a2a_server._try_invoke_with_gate(
            tool_name=tool.name,
            params={},
            user_id="alice@example.com",
            channel="a2a:copilot",
            task=task,
        )

        assert current_credential() is None, (
            "_CREDENTIAL_VAR was not reset after _try_invoke_with_gate(); "
            "finally block in server.py is missing or broken"
        )

    @pytest.mark.asyncio
    async def test_missing_credential_suspends_task(self, broker_with_test_provider):
        """NeedsAuth → task suspended (INPUT_REQUIRED), not completed."""
        from parrot.a2a.server import A2AServer
        from parrot.auth.broker import CredentialBroker
        from parrot.auth.credentials import CredentialResolver

        class _NeverResolvesResolver(CredentialResolver):
            async def resolve(self, channel, user_id):
                return None

            async def get_auth_url(self, channel, user_id) -> str:
                return "https://example.com/auth"

        mock_agent = MagicMock()
        mock_agent.name = "TestAgent"
        mock_agent.tools = None
        mock_agent.tool_manager = MagicMock()
        mock_agent.tool_manager.list_tools.return_value = []
        mock_agent.tool_manager.get_tool.return_value = None

        broker = CredentialBroker()
        broker.register(
            "needs_auth_provider", _NeverResolvesResolver(), auth_kind="oauth2"
        )

        server = A2AServer(mock_agent, broker=broker)

        class _NeedsAuthTool:
            name = "needs_auth_tool"
            credential_provider = "needs_auth_provider"

            async def _execute(self, **kwargs):
                return "should not reach here"

        tool = _NeedsAuthTool()
        task = _FakeTask()
        server._find_tool = lambda name: tool if name == tool.name else None

        suspended = await server._try_invoke_with_gate(
            tool_name=tool.name,
            params={},
            user_id="alice@example.com",
            channel="a2a:copilot",
            task=task,
        )

        assert suspended is True, "task should be suspended when credential is missing"
        assert not task.failed, "task should not have failed — it should be suspended"
        assert task.result is None, "task.complete() should not have been called"
