"""FEAT-776 M8 needs-auth collection and Telegram prompt tests."""

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.pending import record_auth_requirement
from parrot.integrations.core.auth.connections import ConnectOutcome
from parrot.integrations.telegram.auth import TelegramUserSession
from parrot.integrations.telegram.connection_commands import LOGIN_FIRST
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


class NeedsAuthTool(AbstractTool):
    """ToolManager-backed needs-auth producer for the end-to-end prompt test."""

    name = "needs_auth_tool"
    description = "Request Jira authorization for an end-to-end Telegram test."

    async def _execute(self, **kwargs: object) -> ToolResult:
        """Raise the canonical authorization requirement."""
        raise AuthorizationRequired(
            tool_name=self.name,
            message="Authorize Jira.",
            auth_url="https://stale-tool-state.example/jira",
            provider="jira",
            scopes=["read:jira"],
        )


class FakeConnectionCommands:
    """Record automatic connection requests and return a stable URL outcome."""

    def __init__(self) -> None:
        self.connect = AsyncMock(
            return_value=ConnectOutcome(
                kind="auth_url",
                provider_id="jira",
                display_name="Jira",
                auth_url="https://connect.example/state",
            )
        )


def make_wrapper() -> TelegramAgentWrapper:
    """Build the minimal wrapper state needed by the M8 helpers."""
    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.config = SimpleNamespace(tenant="tenant-a", singleton_agent=False, agent_timeout=1.0)
    wrapper._bot_id = "bot-7"
    wrapper._connection_commands = FakeConnectionCommands()
    wrapper._ensure_principal_link = AsyncMock(return_value=True)
    wrapper._connection_permission_context = MagicMock(return_value=SimpleNamespace())
    wrapper._build_permission_context = MagicMock(return_value=SimpleNamespace())
    wrapper._enrich_question = MagicMock(side_effect=lambda question, _session: question)
    wrapper.logger = MagicMock()
    return wrapper


def make_session(*, authenticated: bool = True) -> TelegramUserSession:
    """Return a Telegram session with an optional Navigator principal."""
    return TelegramUserSession(
        telegram_id=42,
        nav_user_id="nav-42" if authenticated else None,
        authenticated=authenticated,
    )


def make_message(*, chat_type: str = "private") -> Any:
    """Return a minimal aiogram Message double."""
    return SimpleNamespace(
        chat=SimpleNamespace(id=99, type=chat_type),
        answer=AsyncMock(),
    )


def auth_payload(
    provider: str = "jira",
    *,
    scopes: list[str] | None = None,
    auth_kind: str = "oauth2",
    user_code: str | None = None,
    verification_uri: str | None = None,
) -> AuthRequiredPayload:
    """Build a needs-auth payload with explicit rendering fields."""
    return AuthRequiredPayload(
        provider=provider,
        scopes=scopes or [],
        auth_kind=auth_kind,
        user_code=user_code,
        verification_uri=verification_uri,
    )


@pytest.mark.asyncio
async def test_invoke_agent_collects_and_prompts() -> None:
    """Both invocation and prompt rendering use the invocation-local payload list."""
    wrapper = make_wrapper()
    session = make_session()
    message = make_message()

    async def ask(*_args: Any, **_kwargs: Any) -> str:
        record_auth_requirement(auth_payload(scopes=["read:jira"]))
        return "agent reply"

    agent = SimpleNamespace(ask=ask)
    wrapper._resolve_agent_for_request = AsyncMock(return_value=(agent, None))

    response, pending = await wrapper._invoke_agent(session, "hello", memory=SimpleNamespace(), message=message)
    assert response == "agent reply"
    assert [payload.provider for payload in pending] == ["jira"]

    await wrapper._send_auth_prompts(message, session, pending)

    wrapper._connection_commands.connect.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url == "https://connect.example/state"


@pytest.mark.asyncio
async def test_auth_prompt_device_code_and_no_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A complete device challenge is preferred, while no principal emits one login line."""
    wrapper = make_wrapper()
    session = make_session()
    message = make_message()
    pending = [
        auth_payload("o365", auth_kind="device_code", user_code="incomplete"),
        auth_payload(
            "o365",
            auth_kind="device_code",
            user_code="ABCD-EFGH",
            verification_uri="https://microsoft.com/devicelogin",
        ),
    ]

    await wrapper._send_auth_prompts(message, session, pending)

    sent_text = message.answer.await_args.args[0]
    assert "ABCD-EFGH" in sent_text
    assert "https://microsoft.com/devicelogin" in sent_text
    wrapper._connection_commands.connect.assert_not_awaited()

    no_principal_message = make_message()
    monkeypatch.setattr(
        "parrot.integrations.telegram.wrapper.principal_for_session",
        AsyncMock(return_value=None),
    )
    await wrapper._send_auth_prompts(
        no_principal_message,
        make_session(authenticated=False),
        [auth_payload("jira"), auth_payload("o365")],
    )

    no_principal_message.answer.assert_awaited_once_with(LOGIN_FIRST, parse_mode=None)


@pytest.mark.asyncio
async def test_e2e_needs_auth_button() -> None:
    """A recorded tool requirement produces a fresh button only after the reply is sent."""
    wrapper = make_wrapper()
    session = make_session()
    message = make_message()
    events: list[str] = []
    manager = ToolManager(include_search_tool=False)
    manager.add_tool(NeedsAuthTool())

    async def ask() -> str:
        result = await manager.execute_tool("needs_auth_tool", {})
        assert result.status == "authorization_required"
        return "Connect Jira to continue."

    response, pending = await wrapper._ask_with_auth_requirements(ask)
    events.append("reply")
    await message.answer(response, parse_mode=None)
    await wrapper._send_auth_prompts(message, session, pending)
    events.append("prompt")

    assert events == ["reply", "prompt"]
    assert message.answer.await_count == 2
    assert wrapper._connection_commands.connect.await_args.kwargs["extra_state"] == {
        "chat_id": 99,
        "bot_id": "bot-7",
    }
    assert wrapper._connection_commands.connect.await_args.kwargs["scopes"] == ["read:jira"]
    assert "stale-tool-state.example" not in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_all_telegram_ask_paths_collect() -> None:
    """All six ask sites use the helper, and concurrent/cancelled turns remain isolated."""
    source = inspect.getsource(TelegramAgentWrapper)
    assert source.count("lambda: asyncio.wait_for(") == 2
    assert source.count("lambda: self.agent.ask(") == 4

    wrapper = make_wrapper()
    release = asyncio.Event()

    async def ask(provider: str) -> str:
        record_auth_requirement(auth_payload(provider))
        await release.wait()
        return provider

    jira_task = asyncio.create_task(wrapper._ask_with_auth_requirements(lambda: ask("jira")))
    o365_task = asyncio.create_task(wrapper._ask_with_auth_requirements(lambda: ask("o365")))
    await asyncio.sleep(0)
    release.set()
    jira_result, o365_result = await asyncio.gather(jira_task, o365_task)
    assert [payload.provider for payload in jira_result[1]] == ["jira"]
    assert [payload.provider for payload in o365_result[1]] == ["o365"]

    started = asyncio.Event()

    async def cancelled_ask() -> None:
        record_auth_requirement(auth_payload("cancelled"))
        started.set()
        await asyncio.Event().wait()

    cancelled_task = asyncio.create_task(wrapper._ask_with_auth_requirements(cancelled_ask))
    await started.wait()
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task

    response, pending = await wrapper._ask_with_auth_requirements(lambda: asyncio.sleep(0, result="clean"))
    assert response == "clean"
    assert pending == []


@pytest.mark.asyncio
async def test_telegram_scope_union_upgrade() -> None:
    """Repeated provider requirements mint one state with a sorted scope union."""
    wrapper = make_wrapper()
    session = make_session()
    message = make_message()

    await wrapper._send_auth_prompts(
        message,
        session,
        [
            auth_payload(scopes=["write:jira", "read:jira"]),
            auth_payload(scopes=["read:jira", "admin:jira"]),
        ],
    )

    wrapper._connection_commands.connect.assert_awaited_once()
    assert wrapper._connection_commands.connect.await_args.kwargs["scopes"] == [
        "admin:jira",
        "read:jira",
        "write:jira",
    ]
