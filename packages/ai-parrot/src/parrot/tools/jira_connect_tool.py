"""Placeholder tool and session helpers for Jira OAuth 2.0 (3LO) in AgenTalk.

When a user opens an AgenTalk session without prior Jira tokens, we cannot
register the full :class:`JiraToolkit` (it has no credentials to operate
with).  Instead we register a lightweight :class:`JiraConnectTool` that,
when invoked by the LLM, returns the OAuth authorization URL so the user
can connect their account.

Once tokens land in Redis (via the OAuth callback), the placeholder is
hot-swapped for the full toolkit using :func:`hotswap_to_full_toolkit`,
keeping the conversation alive.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional

from pydantic import BaseModel, Field

from .abstract import AbstractTool, ToolResult

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from ..auth.credentials import CredentialResolver
    from .manager import ToolManager


logger = logging.getLogger(__name__)


class _JiraConnectArgs(BaseModel):
    """No arguments — the tool simply returns the auth URL."""

    reason: Optional[str] = Field(
        default=None,
        description=(
            "Optional human-readable reason for why the user is being asked "
            "to connect Jira (propagated into the response message)."
        ),
    )


class JiraConnectTool(AbstractTool):
    """Placeholder tool returning the Jira OAuth authorization URL.

    The LLM sees this tool exactly like any regular tool.  When it calls
    ``connect_jira``, the response carries the URL the user should open to
    authorize their Jira account.
    """

    name = "connect_jira"
    description = (
        "Connect your Jira account to enable Jira tools. Returns an "
        "authorization link that the user must open in their browser."
    )
    args_schema = _JiraConnectArgs

    def __init__(
        self,
        credential_resolver: "CredentialResolver",
        channel: str,
        user_id: str,
    ) -> None:
        super().__init__(name=self.name, description=self.description)
        # args_schema is a class attribute on AbstractTool; explicitly set it
        # on the instance so schema generation picks up ``_JiraConnectArgs``.
        self.args_schema = _JiraConnectArgs
        self._resolver = credential_resolver
        self._channel = channel
        self._user_id = user_id

    async def _execute(self, **kwargs) -> ToolResult:  # noqa: D401
        reason = kwargs.get("reason")
        auth_url = await self._resolver.get_auth_url(
            self._channel, self._user_id,
        )
        prefix = (
            f"{reason.rstrip('.')}. " if reason else ""
        )
        return ToolResult(
            success=True,
            status="authorization_required",
            result=(
                f"{prefix}Please authorize your Jira account by opening this "
                f"link: {auth_url}"
            ),
            metadata={
                "auth_url": auth_url,
                "provider": "jira",
                "channel": self._channel,
                "user_id": self._user_id,
            },
        )


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


async def setup_jira_oauth_session(
    tool_manager: "ToolManager",
    credential_resolver: "CredentialResolver",
    channel: str,
    user_id: str,
    *,
    build_full_toolkit: Optional[Callable[[], Awaitable[Any]]] = None,
) -> None:
    """Register either :class:`JiraConnectTool` or the full Jira toolkit.

    On session start, check whether tokens exist via the resolver.  If yes,
    invoke ``build_full_toolkit`` (typically a factory that instantiates
    ``JiraToolkit(auth_type='oauth2_3lo', credential_resolver=resolver)``)
    and register the resulting toolkit.  If no, register the placeholder
    :class:`JiraConnectTool`.

    Args:
        tool_manager: The session's :class:`ToolManager`.
        credential_resolver: Resolver used to check the token store and
            generate auth URLs.
        channel: Originating channel (e.g., ``"agentalk"``).
        user_id: User identifier scoped to the channel.
        build_full_toolkit: Optional async factory building the full
            :class:`JiraToolkit` — call sites that only need the
            placeholder (e.g., early in the bootstrap) can omit it.
    """
    if await credential_resolver.is_connected(channel, user_id):
        if build_full_toolkit is not None:
            toolkit = await build_full_toolkit()
            if toolkit is not None:
                tool_manager.register_toolkit(toolkit)
                logger.info(
                    "Jira OAuth session: registered full toolkit for %s:%s",
                    channel, user_id,
                )
                return
    placeholder = JiraConnectTool(
        credential_resolver=credential_resolver,
        channel=channel,
        user_id=user_id,
    )
    tool_manager.add_tool(placeholder)
    logger.info(
        "Jira OAuth session: registered JiraConnectTool placeholder for %s:%s",
        channel, user_id,
    )


async def hotswap_to_full_toolkit(
    tool_manager: "ToolManager",
    build_full_toolkit: Callable[[], Awaitable[Any]],
    *,
    bot: Any = None,
) -> List[Any]:
    """Replace :class:`JiraConnectTool` in-place with the full toolkit.

    Called after the OAuth callback persists the user's tokens.  Safe to
    call multiple times — if the placeholder is already gone, the
    registered toolkit is still returned.

    Args:
        tool_manager: The session's :class:`ToolManager`.
        build_full_toolkit: Async factory returning a fresh toolkit.
        bot: Optional bot/agent instance.  If it exposes
            ``_sync_tools_to_llm``, it is invoked to update the live LLM
            tool list; otherwise the swap takes effect on the next turn.

    Returns:
        The list of AbstractTool instances registered from the toolkit.
    """
    # Remove the placeholder if present.  ToolManager stores registered
    # tools on ``_tools``; we pop directly to avoid depending on any
    # particular removal API.
    tools_map = getattr(tool_manager, "_tools", None)
    if isinstance(tools_map, dict):
        tools_map.pop("connect_jira", None)

    toolkit = await build_full_toolkit()
    tools = tool_manager.register_toolkit(toolkit) if toolkit is not None else []

    if bot is not None and hasattr(bot, "_sync_tools_to_llm"):
        try:
            result = bot._sync_tools_to_llm()
            if hasattr(result, "__await__"):
                await result  # support async implementations
        except Exception:  # noqa: BLE001 - best-effort; swap still succeeded
            logger.exception("_sync_tools_to_llm failed during hot-swap")

    return tools
