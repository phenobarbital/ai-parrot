"""Unit tests for TASK-1669: Core tool-loop credential seam + ContextVar injection.

Tests:
- tool with credential_provider receives credential via current_credential()
- tool without credential_provider runs unchanged (no-op)
- secret never appears in tool args/schema
- missing identity + gated tool → fail closed
- CredentialRequired bubbles up from execute()
"""
import pytest

from parrot.tools.abstract import AbstractTool, ToolResult, current_credential
from parrot.auth.credentials import CredentialRequired
from parrot.auth.broker import CredentialBroker


# ---------------------------------------------------------------------------
# Fake tool implementations
# ---------------------------------------------------------------------------


class NoCredentialTool(AbstractTool):
    """A plain tool with no credential_provider — must run unaffected."""

    name = "no_credential_tool"
    description = "Plain tool, no credentials"

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="plain-result", metadata={})


class CredentialedTool(AbstractTool):
    """Tool that declares credential_provider and reads it via current_credential()."""

    name = "cred_tool"
    description = "Needs creds"
    credential_provider = "testprovider"

    async def _execute(self, **kwargs) -> ToolResult:
        cred = current_credential()
        return ToolResult(
            status="success",
            result=f"got-cred:{cred}",
            metadata={"credential_received": cred is not None},
        )


# ---------------------------------------------------------------------------
# Fake broker
# ---------------------------------------------------------------------------


def _make_broker(token=None, auth_url="https://example.com/auth"):
    """Build a broker whose only resolver returns *token* (or None for miss)."""
    broker = CredentialBroker()

    from parrot.auth.credentials import CredentialResolver

    class FakeResolver(CredentialResolver):
        async def resolve(self, channel, user_id):
            return token

        async def get_auth_url(self, channel, user_id):
            return auth_url

    broker.register("testprovider", FakeResolver())
    return broker


# ---------------------------------------------------------------------------
# Tests: no credential_provider tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_credential_tool_runs_unchanged():
    """A tool without credential_provider runs byte-for-byte unchanged."""
    tool = NoCredentialTool()
    result = await tool.execute()

    assert result.status == "success"
    assert result.result == "plain-result"
    # ContextVar must not be set
    assert current_credential() is None


@pytest.mark.asyncio
async def test_no_credential_tool_ignores_broker_kwargs():
    """Broker kwargs are popped and don't appear in tool's args/schema."""
    tool = NoCredentialTool()
    broker = _make_broker(token="secret")
    # Even when broker is passed, a no-credential tool ignores it
    result = await tool.execute(
        _broker=broker,
        _cred_channel="chat",
        _cred_user_id="user@example.com",
    )
    assert result.status == "success"


# ---------------------------------------------------------------------------
# Tests: credentialed tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credentialed_tool_receives_credential_via_contextvar():
    """A tool with credential_provider gets the credential via current_credential()."""
    broker = _make_broker(token="my-api-key")
    tool = CredentialedTool()

    result = await tool.execute(
        _broker=broker,
        _cred_channel="chat",
        _cred_user_id="alice@example.com",
    )

    assert result.status == "success"
    assert "got-cred:my-api-key" in result.result
    assert result.metadata.get("credential_received") is True


@pytest.mark.asyncio
async def test_credential_is_reset_after_execute():
    """ContextVar is reset to None after execute() completes (no leak)."""
    broker = _make_broker(token="temporary-secret")
    tool = CredentialedTool()

    await tool.execute(
        _broker=broker,
        _cred_channel="chat",
        _cred_user_id="user@example.com",
    )

    # After execute() the ContextVar must be reset
    assert current_credential() is None


@pytest.mark.asyncio
async def test_credential_required_raised_on_miss():
    """CredentialRequired is raised (not swallowed) when broker returns NeedsAuth."""
    broker = _make_broker(token=None, auth_url="https://app/auth")
    tool = CredentialedTool()

    with pytest.raises(CredentialRequired) as exc_info:
        await tool.execute(
            _broker=broker,
            _cred_channel="chat",
            _cred_user_id="user@example.com",
        )

    exc = exc_info.value
    assert exc.provider == "testprovider"
    assert exc.auth_url == "https://app/auth"
    assert exc.auth_kind in ("obo", "oauth2", "static_key", "mcp")


@pytest.mark.asyncio
async def test_fail_closed_no_identity():
    """Credentialed tool + no user identity → fail closed (tool does NOT execute).

    The broker raises ValueError which is caught by execute() and returned as
    ToolResult(status='error').  The tool's _execute() must never run.
    """
    executed = []

    class SentinelTool(AbstractTool):
        name = "sentinel"
        description = "Must not execute"
        credential_provider = "testprovider"

        async def _execute(self, **kwargs):
            executed.append(True)
            return ToolResult(status="success", result="oops-ran", metadata={})

    broker = _make_broker(token="some-token")
    tool = SentinelTool()

    result = await tool.execute(
        _broker=broker,
        _cred_channel="chat",
        _cred_user_id="",  # empty identity
    )

    # Tool must NOT have executed
    assert len(executed) == 0, "_execute() must NOT run when identity is empty"
    # Result should signal failure
    assert result.status == "error"


@pytest.mark.asyncio
async def test_secret_not_in_tool_args():
    """Secret credential never appears in resolved_kwargs sent to _execute."""
    captured_kwargs = {}

    class SpyTool(AbstractTool):
        name = "spy_tool"
        description = "Spy"
        credential_provider = "testprovider"

        async def _execute(self, **kwargs):
            captured_kwargs.update(kwargs)
            return ToolResult(status="success", result="ok", metadata={})

    broker = _make_broker(token="super-secret-token")
    tool = SpyTool()

    await tool.execute(
        _broker=broker,
        _cred_channel="chat",
        _cred_user_id="user@example.com",
    )

    # The secret must not appear in the kwargs passed to _execute
    for v in captured_kwargs.values():
        assert v != "super-secret-token", (
            f"Secret leaked into tool kwargs: {captured_kwargs}"
        )
    # Also must not have broker/channel/user_id fields
    assert "_broker" not in captured_kwargs
    assert "_cred_channel" not in captured_kwargs
    assert "_cred_user_id" not in captured_kwargs


# ---------------------------------------------------------------------------
# Tests: ToolManager broker propagation
# ---------------------------------------------------------------------------


def test_tool_manager_set_broker():
    """ToolManager.set_broker() stores the broker and broker property returns it."""
    from parrot.tools.manager import ToolManager

    tm = ToolManager()
    broker = _make_broker(token="tok")
    tm.set_broker(broker)

    assert tm.broker is broker


def test_tool_manager_clone_carries_broker():
    """clone() propagates the broker to the new ToolManager."""
    from parrot.tools.manager import ToolManager

    tm = ToolManager()
    broker = _make_broker(token="tok")
    tm.set_broker(broker)

    cloned = tm.clone()
    assert cloned.broker is broker


# ---------------------------------------------------------------------------
# Tests: AbstractToolkit credential_provider propagation (FEAT-264)
# ---------------------------------------------------------------------------


def _make_credentialed_toolkit_cls():
    from parrot.tools.toolkit import AbstractToolkit

    class GatedToolkit(AbstractToolkit):
        """Toolkit whose tools are gated through the broker seam."""

        credential_provider = "testprovider"

        async def do_thing(self, item: str = "x") -> str:
            """Do a thing that needs a per-user credential."""
            return f"did:{item}:cred={current_credential()}"

    return GatedToolkit


def test_toolkit_propagates_credential_provider_to_tools():
    """Every generated ToolkitTool inherits the toolkit's credential_provider."""
    toolkit = _make_credentialed_toolkit_cls()()
    tools = toolkit.get_tools()

    assert tools, "toolkit generated no tools"
    assert all(t.credential_provider == "testprovider" for t in tools)


def test_toolkit_credential_provider_constructor_override():
    """The credential_provider kwarg overrides the class attribute per instance."""
    toolkit = _make_credentialed_toolkit_cls()(credential_provider="other")
    tools = toolkit.get_tools()

    assert all(t.credential_provider == "other" for t in tools)


def test_toolkit_without_credential_provider_leaves_tools_ungated():
    """Default (None) keeps generated tools out of the broker seam."""
    from parrot.tools.toolkit import AbstractToolkit

    class PlainToolkit(AbstractToolkit):
        async def do_plain(self, item: str = "x") -> str:
            """A plain tool."""
            return f"plain:{item}"

    tools = PlainToolkit().get_tools()
    assert all(not t.credential_provider for t in tools)


@pytest.mark.asyncio
async def test_toolkit_tool_miss_raises_credential_required_before_body():
    """Broker miss on a toolkit tool raises CredentialRequired; body never runs."""
    toolkit = _make_credentialed_toolkit_cls()()
    tool = toolkit.get_tools()[0]
    broker = _make_broker(token=None, auth_url="https://login/consent")

    with pytest.raises(CredentialRequired) as exc_info:
        await tool.execute(
            _broker=broker,
            _cred_channel="msteams",
            _cred_user_id="alice@example.com",
            item="x",
        )

    assert exc_info.value.provider == "testprovider"
    assert exc_info.value.auth_url == "https://login/consent"


@pytest.mark.asyncio
async def test_toolkit_tool_hit_executes_with_credential():
    """Broker hit lets the toolkit tool run with the credential in context."""
    toolkit = _make_credentialed_toolkit_cls()()
    tool = toolkit.get_tools()[0]
    broker = _make_broker(token="user-token")

    result = await tool.execute(
        _broker=broker,
        _cred_channel="msteams",
        _cred_user_id="alice@example.com",
        item="x",
    )

    payload = result.result if isinstance(result, ToolResult) else result
    assert "cred=user-token" in str(payload)
