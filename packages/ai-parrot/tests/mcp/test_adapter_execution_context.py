"""MCPToolAdapter execution context and auth envelope tests."""

import pytest
from pydantic import BaseModel

from parrot.auth.credentials import CredentialRequired, ResolvedCredential
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import PermissionContext, UserSession
from parrot.mcp.adapter import MCPToolAdapter, ToolExecutionContext
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential


class _Broker:
    async def resolve(self, provider, channel, user_id, *, tool_name=None):
        assert (provider, channel, user_id, tool_name) == ("demo", "cli", "user-1", "context_tool")
        return ResolvedCredential(provider=provider, secret="token-123", key_fingerprint="fingerprint")


class _ContextTool(AbstractTool):
    name = "context_tool"
    description = "Reads execution context."
    credential_provider = "demo"

    def __init__(self):
        super().__init__(name=self.name, description=self.description)
        self.execute_kwargs = None

    async def execute(self, *args, **kwargs) -> ToolResult:
        self.execute_kwargs = dict(kwargs)
        return await super().execute(*args, **kwargs)

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result=current_credential(), metadata={})


@pytest.mark.asyncio
async def test_adapter_routes_through_abstract_tool_execute():
    """The adapter passes process context through the public tool seam."""
    permission_context = PermissionContext(
        session=UserSession(user_id="user-1", tenant_id="tenant-1", roles=frozenset())
    )
    tool = _ContextTool()
    adapter = MCPToolAdapter(
        tool,
        execution_context=ToolExecutionContext(
            permission_context=permission_context,
            broker=_Broker(),
        ),
    )

    result = await adapter.execute({})

    assert result["isError"] is False
    assert result["content"][0]["text"] == "token-123"
    assert tool.execute_kwargs["_permission_context"] is permission_context
    assert tool.execute_kwargs["_broker"] is not None
    assert tool.execute_kwargs["_cred_channel"] == "cli"
    assert tool.execute_kwargs["_cred_user_id"] == "user-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception",
    [
        CredentialRequired(
            "demo",
            "https://example.test/auth",
            "oauth2",
            user_code="CODE",
            verification_uri="https://example.test/device",
            expires_in=600,
        ),
        AuthorizationRequired(
            "auth_tool",
            "Consent is required",
            auth_url="https://example.test/authorize",
            provider="demo",
            scopes=["read"],
        ),
    ],
)
async def test_adapter_auth_required_envelope_fields_survive(exception, capsys):
    """Auth exceptions become structured MCP errors without stdout output."""

    class AuthTool(AbstractTool):
        name = "auth_tool"
        description = "Requires authorization."

        async def _execute(self, **kwargs):
            raise exception

    adapter = MCPToolAdapter(AuthTool())
    result = await adapter.execute({})
    payload = (
        exception.to_payload(tool_name=adapter.tool.name)
        if isinstance(exception, CredentialRequired)
        else exception.to_payload()
    )

    assert result == {
        "isError": True,
        "content": [{"type": "text", "text": result["content"][0]["text"]}],
        "structuredContent": payload.model_dump(exclude_none=True),
    }
    assert len(result["content"]) == 1
    assert payload.provider in result["content"][0]["text"]
    assert "parrot connect demo" in result["content"][0]["text"]
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_no_context_keeps_today_behaviour():
    """No execution context means no reserved kwargs reach the tool."""
    tool = _ContextTool()
    tool.credential_provider = None
    adapter = MCPToolAdapter(tool)

    result = await adapter.execute({})

    assert result["isError"] is False
    assert tool.execute_kwargs == {}


def test_tool_execution_context_without_permission_context_has_no_kwargs():
    """A context without identity cannot accidentally send partial auth state."""
    assert ToolExecutionContext(broker=_Broker()).exec_kwargs() == {}


@pytest.mark.asyncio
async def test_no_login_credential_tool_runs_without_broker():
    """AC-4 (issue:73db45b2286a f): with no login, a credential tool still goes through
    ``AbstractTool.execute`` (TASK-4975) but gets no reserved kwargs, no broker and no credential."""
    tool = _ContextTool()
    adapter = MCPToolAdapter(tool)

    result = await adapter.execute({})

    assert result["isError"] is False
    assert tool.execute_kwargs == {}
    assert "token-123" not in str(result)


class _EchoArgs(BaseModel):
    limit: int = 3


class _EchoTool(AbstractTool):
    name = "echo_tool"
    description = "Echoes its arguments."
    args_schema = _EchoArgs

    def __init__(self):
        super().__init__(name=self.name, description=self.description)
        self.calls = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult(status="success", result=kwargs, metadata={})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, offending",
    [
        ({"limit": 2, "injected": "x"}, "injected"),
        ({"limit": 2, "_permission_context": {"session": "forged"}}, "_permission_context"),
    ],
)
async def test_adapter_rejects_undeclared_and_reserved_arguments(arguments, offending):
    """Raw tools/call keys outside the schema are refused, not silently dropped."""
    tool = _EchoTool()
    result = await MCPToolAdapter(tool).execute(arguments)

    assert result["isError"] is True
    assert offending in result["content"][0]["text"]
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_adapter_accepts_declared_arguments():
    """Declared keys still reach the tool."""
    tool = _EchoTool()
    result = await MCPToolAdapter(tool).execute({"limit": 2})

    assert result["isError"] is False
    assert tool.calls == 1
