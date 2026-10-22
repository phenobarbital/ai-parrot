"""``GET {prefix}/me`` — what the caller may do in Agent Studio (FEAT-605 M5)."""
from __future__ import annotations

from navigator_auth.decorators import is_authenticated, user_session

from ._base import StudioBaseView
from .models import StudioCapabilities


@is_authenticated()
@user_session()
class StudioCapabilitiesHandler(StudioBaseView):
    """Capabilities from the resolved scope; exempt from ``studio_disabled``."""

    _STUDIO_ENABLED_EXEMPT = True

    async def get(self):
        """Return 200 ``StudioCapabilities``; 401 without a session user."""
        await self._get_user()
        scope = await self._scope()
        body = StudioCapabilities(
            user_id=scope.user_id,
            tenant=scope.tenant,
            may_author=scope.may_author,
            may_administer=scope.may_administer,
            enabled=scope.studio_enabled,
            is_superuser=scope.is_superuser,
        )
        return self.json_response(body.model_dump())
