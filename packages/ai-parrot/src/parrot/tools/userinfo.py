"""UserinfoTool — exposes the session user's EmployeeProfile to the LLM (FEAT-406).

A standard `AbstractTool` returning the current session user's curated
`EmployeeProfile` (see `parrot.auth.userinfo.UserInfoService`) as JSON.
Identity always comes from the session/`PermissionContext` propagated by
`AbstractTool.execute()` — never from an LLM-supplied argument (security
invariant). See `sdd/specs/pbac-guardrails.spec.md` §3 Module 5.
"""
import logging
from typing import Any

from ..auth.userinfo import UserInfoService
from .abstract import AbstractTool

logger = logging.getLogger(__name__)


class UserinfoTool(AbstractTool):
    """Get the current user's profile information.

    Returns the session user's structured profile as JSON — name, email,
    job code, department, groups, programs, worker type, and manager info.
    Identity is always resolved from the caller's session/permission
    context; this tool takes no arguments and ignores any identity the LLM
    might otherwise attempt to supply.
    """
    name = "userinfo"

    def __init__(self, service: UserInfoService, **kwargs: Any) -> None:
        """Initialize the tool with a `UserInfoService`.

        Args:
            service: The shared `UserInfoService` used to load profiles.
            **kwargs: Forwarded to `AbstractTool.__init__`.
        """
        super().__init__(**kwargs)
        self._service = service
        self.logger = logging.getLogger(__name__)

    async def _execute(self, **kwargs: Any) -> dict:
        """Return the session user's `EmployeeProfile` as a JSON-safe dict.

        Identity comes exclusively from `self._current_pctx` (set by
        `AbstractTool.execute()` from the caller's `_permission_context`,
        never from `kwargs` — the default `args_schema` strips any
        LLM-supplied arguments before this method is even called).

        Args:
            **kwargs: Ignored (no LLM-facing parameters; see class docstring).

        Returns:
            The `EmployeeProfile` as a JSON-safe dict on success, or a
            structured ``{"status": "unavailable", "message": ...}`` dict
            when there is no session user or no matching profile row.
            Never raises.
        """
        pctx = self._current_pctx
        user_id = getattr(pctx, "user_id", None) if pctx is not None else None
        if not user_id:
            return {"status": "unavailable", "message": "No session user identified"}

        profile = await self._service.get_profile(user_id)
        if profile is None:
            return {"status": "unavailable", "message": "Profile not found"}

        return profile.model_dump(mode="json")
