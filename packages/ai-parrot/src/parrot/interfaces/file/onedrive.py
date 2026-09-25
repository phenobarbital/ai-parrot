"""OneDrive FileManager (FEAT-603)."""
from __future__ import annotations

from typing import Any

from parrot.interfaces.onedrive import OneDriveClient

from .graph import GraphDriveFileManager, GraphFileManagerError


class OneDriveFileManager(GraphDriveFileManager):
    """FileManagerInterface over a user's OneDrive.

    ``user="me"`` requires delegated / cached / on_behalf_of auth; under app-only (direct) auth ``user`` must be a UPN or
    object id and the app needs the ``Files.ReadWrite.All`` application permission. Credentials default to
    O365_CLIENT_ID / O365_CLIENT_SECRET / O365_TENANT_ID.
    """

    manager_name: str = "onedrivefile"
    client_class: type = OneDriveClient

    def __init__(self, user: str = "me", **kwargs: Any) -> None:
        """Initialize the OneDrive file manager.

        Args:
            user: UPN, Entra object id, or ``"me"``.
            **kwargs: Forwarded to :class:`GraphDriveFileManager` (prefix, credentials, auth_mode, ...).
        """
        super().__init__(**kwargs)
        if not user or not str(user).strip():
            raise ValueError("OneDriveFileManager requires a user (UPN, object id, or 'me')")
        self.user = str(user).strip()

    def _build_client(self) -> OneDriveClient:
        """Return a not-yet-authenticated OneDrive client."""
        return OneDriveClient(credentials=dict(self.credentials or {}))

    async def _resolve_drive_id(self) -> str:
        """Resolve the configured user's drive through the client cache."""
        if self.user.strip().lower() == "me" and self.client.is_app_only:
            raise RuntimeError("OneDrive user 'me' requires delegated, cached or on_behalf_of authentication")
        drive = await self.client._resolve_user_drive(self.user)
        drive_id = getattr(drive, "id", None)
        if not drive_id:
            raise GraphFileManagerError(f"OneDrive user '{self.user}' has no drive id")
        return drive_id
