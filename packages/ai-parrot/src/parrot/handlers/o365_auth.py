"""HTTP handlers for remote Office 365 interactive authentication."""
from typing import Any, Dict

from navigator_auth.decorators import is_authenticated, user_session
from navigator.views import BaseView

from ..services.o365_remote_auth import RemoteAuthManager


def _get_manager(app) -> RemoteAuthManager:
    manager = app.get("o365_auth_manager")
    if manager is None:
        manager = RemoteAuthManager()
        app["o365_auth_manager"] = manager
    return manager


@is_authenticated()
@user_session()
class O365InteractiveAuthSessions(BaseView):
    """Create remote Office 365 interactive login sessions."""

    async def post(self):
        manager = _get_manager(self.request.app)
        try:
            payload: Dict[str, Any] = await self.request.json()
        except Exception:
            payload = {}

        scopes = payload.get("scopes")
        if scopes is not None and not isinstance(scopes, list):
            return self.error(
                response={"message": "'scopes' must be a list of strings"},
                status=400,
            )

        redirect_uri = payload.get("redirect_uri")
        credentials = payload.get("credentials")
        if credentials is not None and not isinstance(credentials, dict):
            return self.error(
                response={"message": "'credentials' must be an object"},
                status=400,
            )

        try:
            session = await manager.start_session(
                credentials=credentials,
                scopes=scopes,
                redirect_uri=redirect_uri,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self.error(
                response={"message": f"Failed to start interactive login: {exc}"},
                status=500,
            )

        return self.json_response(session, status=201)


@is_authenticated()
@user_session()
class O365InteractiveAuthSessionDetail(BaseView):
    """Manage a specific Office 365 interactive login session."""

    async def get(self):
        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "Missing session_id"},
                status=400,
            )

        manager = _get_manager(self.request.app)
        session = await manager.get_session(session_id)
        if not session:
            return self.error(
                response={"message": "Session not found"},
                status=404,
            )

        return self.json_response(session)

    async def delete(self):
        session_id = self.request.match_info.get("session_id")
        if not session_id:
            return self.error(
                response={"message": "Missing session_id"},
                status=400,
            )

        manager = _get_manager(self.request.app)
        cancelled = await manager.cancel_session(session_id)
        if not cancelled:
            return self.error(
                response={"message": "Session not found"},
                status=404,
            )

        return self.json_response({"session_id": session_id, "status": "cancelled"})


__all__ = [
    "O365InteractiveAuthSessions",
    "O365InteractiveAuthSessionDetail",
]
