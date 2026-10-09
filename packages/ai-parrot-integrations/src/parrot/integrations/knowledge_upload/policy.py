"""Authorization policy: username OR group allow-list, deny by default."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from parrot.auth.userinfo import EmployeeProfile, UserInfoService

from .models import UploaderIdentity

logger = logging.getLogger(__name__)


class UploadPolicy:
    """Username-or-group allow-list; deny by default."""

    def __init__(self, allowed_usernames: Iterable[str], allowed_groups: Iterable[str]) -> None:
        self._usernames = {
            username.strip().casefold() for username in allowed_usernames if username and username.strip()
        }
        self._groups = {group.strip().casefold() for group in allowed_groups if group and group.strip()}

    def is_allowed(self, profile: EmployeeProfile | None) -> bool:
        """Return whether the profile matches either configured allow-list."""
        if profile is None or not (self._usernames or self._groups):
            return False
        if profile.username and profile.username.strip().casefold() in self._usernames:
            return True
        return bool(
            self._groups.intersection(group.strip().casefold() for group in profile.groups if group and group.strip())
        )


async def resolve_profile(identity: UploaderIdentity, userinfo: UserInfoService) -> EmployeeProfile | None:
    """Resolve a navigator id first, then fall back to an email address."""
    try:
        profile = None
        if identity.nav_user_id:
            profile = await userinfo.get_profile(identity.nav_user_id)
        if profile is None and identity.email:
            profile = await userinfo.get_profile_by_email(identity.email)
        return profile
    except Exception:
        logger.warning("Knowledge upload identity lookup failed", exc_info=True)
        return None
