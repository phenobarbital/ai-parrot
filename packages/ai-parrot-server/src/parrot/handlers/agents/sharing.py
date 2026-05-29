"""Agent sharing scaffold — deferred to a follow-up FEAT.

Design decision (FEAT-149 §8 Open Questions):
    Sharing will be implemented as a per-user permission list stored in the
    ``permissions`` JSONB column of ``navigator.users_bots``.  The exact
    scheme (read-only share links, per-user ACL, org-level visibility) is
    still being finalised and is intentionally out of scope for FEAT-149.

Intended interface (subject to change)::

    POST /api/v1/user_agents/{chatbot_id}/share
        {
          "target_user_id": 42,
          "permission": "read"  # or "write" | "none"
        }

    GET /api/v1/user_agents/{chatbot_id}/share
        → list of {user_id, permission, granted_at}

    DELETE /api/v1/user_agents/{chatbot_id}/share/{target_user_id}

References:
    - FEAT-149 spec §3 Module 9
    - FEAT-149 spec §8 Open Questions (sharing / multi-user)

TODO(FEAT-XXX): Implement agent sharing when the design is finalised.
"""
from __future__ import annotations

from aiohttp import web


class AgentSharingHandler:
    """Stub handler for ephemeral agent sharing.

    All methods raise :class:`NotImplementedError` until the follow-up
    feature implements the sharing scheme.
    """

    # TODO(FEAT-XXX): implement agent sharing
    async def post(self, request: web.Request) -> web.Response:
        """Share an agent with another user (not yet implemented).

        Args:
            request: The aiohttp request object.

        Raises:
            NotImplementedError: Always, until sharing is implemented.
        """
        raise NotImplementedError(
            "Agent sharing is not yet implemented. See FEAT-149 §8 and TODO(FEAT-XXX)."
        )

    async def get(self, request: web.Request) -> web.Response:
        """List users with access to an agent (not yet implemented).

        Args:
            request: The aiohttp request object.

        Raises:
            NotImplementedError: Always, until sharing is implemented.
        """
        raise NotImplementedError(
            "Agent sharing is not yet implemented. See FEAT-149 §8 and TODO(FEAT-XXX)."
        )

    async def delete(self, request: web.Request) -> web.Response:
        """Revoke access to an agent (not yet implemented).

        Args:
            request: The aiohttp request object.

        Raises:
            NotImplementedError: Always, until sharing is implemented.
        """
        raise NotImplementedError(
            "Agent sharing is not yet implemented. See FEAT-149 §8 and TODO(FEAT-XXX)."
        )
