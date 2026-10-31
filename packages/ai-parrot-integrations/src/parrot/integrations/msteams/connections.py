"""Teams connections (FEAT-775): principal source, permission context, notifier and cards.

TASK-5066 owns the principal/context part; TASK-5067 appends the notifier, TASK-5068 the card builders.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel

from parrot.auth.permission import PermissionContext, build_principal_context
from parrot.auth.principal import Principal

from .auth import MSTeamsSessionStore, MSTeamsUserSession

if TYPE_CHECKING:  # pragma: no cover
    from botbuilder.core import TurnContext

logger = logging.getLogger(__name__)

MSTEAMS_CHANNEL = "msteams"


class TeamsConnectState(BaseModel):
    """What the Teams channel puts in ``IntegrationsService.start_connect(extra_state=...)``."""

    conversation_reference: Dict[str, Any]
    bot_app_id: str


class MSTeamsPrincipalSource:
    """Principal for the speaking Teams user, from the cached FEAT-729 session; never runs an exchange."""

    def __init__(self, store: Optional[MSTeamsSessionStore]) -> None:
        self._store = store

    async def session_for_turn(self, turn_context: "TurnContext") -> Optional[MSTeamsUserSession]:
        """Return the live authenticated session, or ``None``.

        Requires ``authenticated``, ``nav_user_id``, ``aad_object_id`` and an unexpired credential.
        """
        if self._store is None:
            return None
        session = await self._store.get_or_create(turn_context)
        if (
            session.authenticated
            and session.nav_user_id
            and session.aad_object_id
            and not self._store.is_expired(session)
        ):
            return session
        return None

    async def principal_for_turn(self, turn_context: "TurnContext") -> Optional[Principal]:
        """Return the FEAT-773 principal for an authenticated turn, else ``None``."""
        session = await self.session_for_turn(turn_context)
        if session is None:
            return None
        return Principal(
            user_id=str(session.nav_user_id),
            canonical_identity=session.aad_object_id,
            tenant_id=session.tenant_id,
            channel=MSTEAMS_CHANNEL,
            channel_user_id=str(session.aad_object_id),
        )


def build_msteams_permission_context(session: MSTeamsUserSession) -> PermissionContext:
    """Build the Navigator PBAC context for a validated Teams session.

    ``session.user_id`` is the Navigator id (PBAC subject); ``channel_user_id`` is the AAD oid used only for
    OAuth credential lookup. Roles stay empty: Teams sessions carry no verified role claims.
    """
    context = build_principal_context(
        str(session.nav_user_id),
        channel=MSTEAMS_CHANNEL,
        tenant_id=session.tenant_id,
        roles=frozenset(),
    )
    context.channel_user_id = session.aad_object_id
    return context
