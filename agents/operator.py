"""OperatorAgent — per-user assistant with Office365 access.

End-to-end demo target for the generic OAuth2 toolkit infrastructure:

- Registered with ``at_startup=False`` so each user gets a fresh
  instance via ``BotManager.get_bot(new=True, session_id=...)``.
- Resolves Office365 credentials at tool-call time through the
  per-app :class:`parrot.auth.o365_oauth.O365OAuthManager` and
  :class:`parrot.auth.credentials.OAuthCredentialResolver`.
- Raises :class:`parrot.auth.exceptions.AuthorizationRequired` when the
  user has not authorized yet, which AgentTalk surfaces back to the chat
  as a clickable consent URL.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.bots import Agent
from parrot.registry import register_agent


_BACKSTORY = """
You are Operator, a personal productivity assistant that can act on the
user's behalf inside Microsoft 365: read inbox, search messages, send
mail, list OneDrive files, search SharePoint, and check calendar events.

Operating principles:
- ALWAYS confirm with the user before sending email on their behalf.
- When summarising mail, redact obvious personal data (phone numbers,
  passport numbers) before quoting.
- If a tool returns ``AuthorizationRequired``, surface the auth URL
  verbatim and ask the user to click it before retrying.
"""


@register_agent(name="operator", at_startup=False)
class OperatorAgent(Agent):
    """Per-user Office365 assistant.

    The OAuth2 manager is expected to live at
    ``app["oauth2_manager_o365"]`` (mounted by ``O365OAuthManager.setup``).
    The toolkit registers itself during :meth:`configure` and consults
    the resolver every time a tool fires.
    """

    agent_id: str = "operator"
    model: str = "claude-sonnet-4-6"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(
            *args,
            name=kwargs.pop("name", "operator"),
            backstory=_BACKSTORY,
            **kwargs,
        )
        self.logger = logging.getLogger(__name__)
        self.office365_toolkit: Optional[Any] = None

    async def configure(self, app: Any = None) -> None:
        """Register the Office365 toolkit from the per-app OAuth2 manager."""
        await super().configure(app)

        target_app = app or self.app
        manager = None
        if target_app is not None:
            try:
                manager = target_app.get("oauth2_manager_o365")
            except Exception:  # pragma: no cover - defensive
                manager = None

        if manager is None:
            self.logger.warning(
                "OperatorAgent: app['oauth2_manager_o365'] is not set; "
                "Office365 tools will NOT be registered. Ensure "
                "O365OAuthManager.setup() was called during app startup."
            )
            return

        try:
            from parrot.auth.credentials import OAuthCredentialResolver
            from parrot_tools.o365.oauth_toolkit import Office365Toolkit
        except ImportError as exc:  # pragma: no cover - missing deps
            self.logger.error(
                "OperatorAgent: Office365 toolkit imports failed: %s", exc,
            )
            return

        resolver = OAuthCredentialResolver(manager)
        self.office365_toolkit = Office365Toolkit(
            credential_resolver=resolver,
            tenant_id=getattr(manager, "tenant_id", "common"),
        )

        try:
            tools = self.tool_manager.register_toolkit(self.office365_toolkit)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "OperatorAgent: failed to register Office365 toolkit: %s",
                exc, exc_info=True,
            )
            return

        if not tools:
            return

        if not hasattr(self, "tools") or self.tools is None:
            self.tools = []
        self.tools.extend(tools)

        # Re-sync LLM tool schemas if a client is bound.
        if getattr(self, "_llm", None) is not None and hasattr(self._llm, "tool_manager"):
            try:
                self.sync_tools(self._llm)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "OperatorAgent: failed to sync tools to LLM: %s", exc,
                )

        self.logger.info(
            "OperatorAgent: registered %d Office365 tools (tenant=%s)",
            len(tools), getattr(manager, "tenant_id", "common"),
        )
