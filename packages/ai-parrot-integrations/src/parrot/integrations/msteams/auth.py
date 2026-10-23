"""MS Teams per-user session and its store."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from botbuilder.core import TurnContext

from parrot.integrations.core.state import InMemoryStateStore

if TYPE_CHECKING:  # pragma: no cover
    from parrot.bots.abstract import AbstractBot
    from parrot.tools import ToolManager

logger = logging.getLogger(__name__)

_KEY_PREFIX = "msteams:session"


def user_key(turn_context: TurnContext) -> str:
    """Return the Entra ``oid`` when present, else the Teams-scoped id.

    Same precedence as ``_get_user_id``.

    Args:
        turn_context: The current Bot Framework turn context.

    Returns:
        The stable key for the Teams user.
    """
    frm = turn_context.activity.from_property
    return getattr(frm, "aad_object_id", None) or frm.id


@dataclass
class MSTeamsUserSession:
    """Cached identity for one Teams user of one agent."""

    user_key: str
    teams_user_id: str
    aad_object_id: Optional[str] = None
    tenant_id: Optional[str] = None
    display_name: Optional[str] = None
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    external_expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tool_manager: Optional["ToolManager"] = field(default=None, repr=False, compare=False)
    user_agent: Optional["AbstractBot"] = field(default=None, repr=False, compare=False)
    post_login_ran: bool = field(default=False, repr=False, compare=False)

    @property
    def user_id(self) -> str:
        """Return Navigator id when authenticated, else a Teams-scoped fallback."""
        if self.authenticated and self.nav_user_id:
            return self.nav_user_id
        return f"msteams:{self.user_key}"

    def set_authenticated(
        self,
        nav_user_id: str,
        session_token: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        external_expires_at: Optional[datetime] = None,
        **extra_meta: Any,
    ) -> None:
        """Mark the session authenticated with Navigator credentials.

        Args:
            nav_user_id: Canonical Navigator user identifier.
            session_token: Navigator session token.
            display_name: Display name supplied by Navigator.
            email: Navigator email address.
            external_expires_at: Expiry of the exchanged external credential.
            **extra_meta: Additional serializable metadata for the session.
        """
        self.nav_user_id = nav_user_id
        self.nav_session_token = session_token
        if display_name is not None:
            self.display_name = display_name
        self.nav_email = email
        self.authenticated = True
        self.authenticated_at = datetime.now(timezone.utc)
        self.external_expires_at = external_expires_at
        if extra_meta:
            self.metadata.update(extra_meta)


class MSTeamsSessionStore:
    """Sessions for one agent's Teams users, over an injected state store."""

    def __init__(self, agent_name: str, store: Any = None, logger_: Any = None) -> None:
        """Initialize the session store.

        Args:
            agent_name: Agent namespace for stored session keys.
            store: Async state store implementing ``set``, ``get``, and ``delete``.
            logger_: Logger used for store diagnostics.
        """
        self.agent_name = agent_name
        self._store = store if store is not None else InMemoryStateStore()
        self._local: Dict[str, MSTeamsUserSession] = {}
        self.logger = logger_ or logger

    def _key(self, key: str) -> str:
        """Return the namespaced storage key for a user."""
        return f"{_KEY_PREFIX}:{self.agent_name}:{key}"

    @staticmethod
    def _ttl_for(session: MSTeamsUserSession) -> int:
        """Return seconds until the external token dies, or zero when unknown."""
        if session.external_expires_at is None:
            return 0
        remaining = (session.external_expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    def is_expired(self, session: MSTeamsUserSession) -> bool:
        """Return whether the session's external credential has expired."""
        return session.external_expires_at is not None and session.external_expires_at <= datetime.now(timezone.utc)

    async def get_or_create(self, turn_context: TurnContext) -> MSTeamsUserSession:
        """Return the live session, rehydrating from the store if needed.

        Args:
            turn_context: The current Bot Framework turn context.

        Returns:
            The cached or newly created session for the speaking user.
        """
        key = user_key(turn_context)
        if key in self._local:
            return self._local[key]

        payload = await self._store.get(self._key(key))
        if payload:
            session = self._from_payload(json.loads(payload))
            if self.is_expired(session):
                session.authenticated = False
            self._local[key] = session
            return session

        activity = turn_context.activity
        frm = activity.from_property
        channel_data = getattr(activity, "channel_data", None)
        tenant = getattr(channel_data, "tenant", None)
        session = MSTeamsUserSession(
            user_key=key,
            teams_user_id=frm.id,
            aad_object_id=getattr(frm, "aad_object_id", None),
            tenant_id=getattr(tenant, "id", None),
            display_name=getattr(frm, "name", None),
        )
        self._local[key] = session
        return session

    async def save(self, session: MSTeamsUserSession) -> None:
        """Persist serializable session fields with a token-derived TTL.

        Args:
            session: Session to persist.
        """
        self._local[session.user_key] = session
        await self._store.set(
            self._key(session.user_key),
            json.dumps(self._to_payload(session)),
            expire=self._ttl_for(session),
        )

    async def clear(self, key: str) -> None:
        """Drop a local and stored session without failing for a missing key.

        Args:
            key: The Teams user key to clear.
        """
        self._local.pop(key, None)
        try:
            await self._store.delete(self._key(key))
        except KeyError:
            return

    @staticmethod
    def _to_payload(session: MSTeamsUserSession) -> Dict[str, Any]:
        """Return only fields which can safely be persisted.

        Args:
            session: Session to serialize.

        Returns:
            JSON-compatible session data.
        """
        return {
            "user_key": session.user_key,
            "teams_user_id": session.teams_user_id,
            "aad_object_id": session.aad_object_id,
            "tenant_id": session.tenant_id,
            "display_name": session.display_name,
            "nav_user_id": session.nav_user_id,
            "nav_session_token": session.nav_session_token,
            "nav_email": session.nav_email,
            "authenticated": session.authenticated,
            "authenticated_at": session.authenticated_at.isoformat() if session.authenticated_at else None,
            "external_expires_at": session.external_expires_at.isoformat() if session.external_expires_at else None,
            "metadata": session.metadata,
        }

    @classmethod
    def _from_payload(cls, payload: Dict[str, Any]) -> MSTeamsUserSession:
        """Recreate a session from an older-compatible persisted payload.

        Args:
            payload: JSON-decoded persisted session data.

        Returns:
            A session with live isolation slots left at their defaults.
        """

        def parse_datetime(value: Any) -> Optional[datetime]:
            if not isinstance(value, str):
                return None
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed

        user_key_value = payload.get("user_key", "")
        return MSTeamsUserSession(
            user_key=user_key_value,
            teams_user_id=payload.get("teams_user_id", user_key_value),
            aad_object_id=payload.get("aad_object_id"),
            tenant_id=payload.get("tenant_id"),
            display_name=payload.get("display_name"),
            nav_user_id=payload.get("nav_user_id"),
            nav_session_token=payload.get("nav_session_token"),
            nav_email=payload.get("nav_email"),
            authenticated=payload.get("authenticated", False),
            authenticated_at=parse_datetime(payload.get("authenticated_at")),
            external_expires_at=parse_datetime(payload.get("external_expires_at")),
            metadata=payload.get("metadata", {}),
        )
