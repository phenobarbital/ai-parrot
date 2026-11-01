"""Jira preset for the generic Telegram connection post-auth provider."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

from parrot.integrations.telegram.post_auth_connection import ConnectionPostAuthProvider

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.integrations.telegram.connection_notifier import SessionHook


class JiraPostAuthProvider(ConnectionPostAuthProvider):
    """Jira preset of :class:`ConnectionPostAuthProvider` (YAML ``provider: jira``)."""

    provider_name = "jira"

    def __init__(
        self,
        *,
        service: "IntegrationsService",
        app: Mapping[str, Any],
        session_hook: Optional["SessionHook"] = None,
    ) -> None:
        super().__init__("jira", service=service, app=app, session_hook=session_hook)
