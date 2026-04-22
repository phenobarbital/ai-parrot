"""Integration-agnostic per-user context.

Carried across integrations (Telegram, MS Teams, Slack, HTTP) so bots and
tools can react to a specific end user without coupling to a channel-
specific session model.

Wrappers are responsible for building a ``UserContext`` from their own
session object and passing it to ``AbstractBot.post_login`` and
``AbstractBot.clone_for_user``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class UserContext:
    """Channel-agnostic identity snapshot for a single end user.

    Built by the integration wrapper at authentication time (or lazily on
    first authenticated message) and passed to the agent so per-user
    initialization (credentials, tool bindings, caches) can happen without
    leaking integration types into bot code.

    Attributes:
        channel: Short identifier of the source channel (``"telegram"``,
            ``"msteams"``, ``"slack"``, ``"http"``).
        user_id: Stable per-channel user identifier used to look up
            credentials (e.g. ``"tg:123456"`` or a Navigator user id).
        display_name: Human-readable name. Optional.
        email: Primary email address. Optional.
        session_id: Stable session id for conversation memory keying.
            Optional — the bot falls back to its own conventions when
            absent.
        metadata: Free-form extras an integration wants to pass through
            (e.g. ``{"jira_account_id": ..., "telegram_username": ...}``).
            Frozen-dataclass mutability is intentionally restricted; pass
            a fresh ``UserContext`` when the state changes.
    """

    channel: str
    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
