"""SharePoint document-library FileManager (FEAT-603)."""

from __future__ import annotations

from typing import Any, Optional

from parrot.interfaces.sharepoint import SharepointClient

from .graph import GraphDriveFileManager, GraphFileManagerError


class SharePointFileManager(GraphDriveFileManager):
    """FileManagerInterface over one SharePoint document library.

    ``site`` is the site path under ``/sites/`` — ``"TeamSite"`` or, for a sub-site, ``"parent/sub"`` given
    explicitly (``_resolve_site`` builds ``…sharepoint.com:/sites/{site}``). The client's sub-site auto-detection only
    acts on its hidden ``_srcfiles`` list, which this manager never populates (S2). ``library`` defaults to
    ``"Documents"`` and accepts the ``"Shared Documents"`` alias. Credentials default to SHAREPOINT_APP_ID /
    SHAREPOINT_APP_SECRET / SHAREPOINT_TENANT_ID / SHAREPOINT_TENANT_NAME.
    """

    manager_name: str = "sharepointfile"
    client_class: type = SharepointClient

    def __init__(self, site: str, library: str = "Documents", *, tenant: Optional[str] = None, **kwargs: Any) -> None:
        """Args:
        site: Site path under ``/sites/`` (``"parent/sub"`` for a sub-site).
        library: Document library name.
        tenant: ``<tenant>.sharepoint.com`` host name; falls back to credentials / SHAREPOINT_TENANT_NAME.
        **kwargs: Forwarded to :class:`GraphDriveFileManager` (prefix, credentials, auth_mode, ...).
        """
        super().__init__(**kwargs)
        if not site or not str(site).strip("/"):
            raise ValueError("SharePointFileManager requires a site")
        self.site = str(site).strip("/")
        self.library = library or "Documents"
        self.tenant = tenant or (self.credentials or {}).get("tenant")

    def _build_client(self) -> SharepointClient:
        """A not-yet-authenticated SharepointClient targeting ``site`` (and ``tenant`` when known)."""
        credentials = {**self.credentials, "site": self.site, **({"tenant": self.tenant} if self.tenant else {})}
        client = SharepointClient(credentials=credentials)
        if client._srcfiles != []:
            # AC23 invariant: a freshly built SharepointClient must never carry pre-populated
            # `_srcfiles` state — that would silently leak files between managers. A bare
            # `assert` is stripped under `python -O`; this must never be skippable.
            raise RuntimeError("SharepointClient._srcfiles must be empty on a freshly built client")
        return client

    async def _resolve_drive_id(self) -> str:
        """verify_sharepoint_access() then _resolve_drive(library) on the client; return the drive id."""
        await self.client.verify_sharepoint_access()
        drive = await self.client._resolve_drive(self.library)
        drive_id = getattr(drive, "id", None)
        if not drive_id:
            raise GraphFileManagerError(f"SharePoint library '{self.library}' has no drive id")
        return drive_id
