---
id: F008
query_id: Q011
type: read
intent: SharePointFileManager / OneDriveFileManager thin subclasses — the two-hook pattern to mirror
executed_at: 2026-09-25T22:53:40Z
duration_ms: 500
parent_id: null
depth: 0
---

# F008 — Each concrete Graph manager is ~50 lines: `manager_name`, `client_class`, `__init__`, `_build_client`, `_resolve_drive_id`

## Summary

`sharepoint.py` (`SharePointFileManager(site, library="Documents", *,
tenant=None, **kwargs)`) and `onedrive.py` (`OneDriveFileManager(user="me",
**kwargs)`) only validate their locator argument, build the right
not-yet-authenticated client, and resolve a drive id (guarding `user="me"`
against app-only auth). `manager_name` values follow S3's `"<x>file"`
convention (`"sharepointfile"`, `"onedrivefile"`). The Drive analogue is a
locator of `folder_id` / `drive_id` (shared drive) / `"root"` plus the same
auth kwargs.

## Citations

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py`
  lines: 12-37
  symbol: `SharePointFileManager.__init__`
  excerpt: |
    class SharePointFileManager(GraphDriveFileManager):
        manager_name: str = "sharepointfile"
        client_class: type = SharepointClient
        def __init__(self, site: str, library: str = "Documents", *, tenant: Optional[str] = None, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            if not site or not str(site).strip("/"): raise ValueError("SharePointFileManager requires a site")

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py`
  lines: 39-57
  symbol: `_build_client / _resolve_drive_id`
  excerpt: |
    def _build_client(self) -> SharepointClient:
        credentials = {**self.credentials, "site": self.site, ...}
        client = SharepointClient(credentials=credentials)
    async def _resolve_drive_id(self) -> str:
        await self.client.verify_sharepoint_access(); drive = await self.client._resolve_drive(self.library)

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/onedrive.py`
  lines: 12-47
  symbol: `OneDriveFileManager`
  excerpt: |
    manager_name: str = "onedrivefile"
    client_class: type = OneDriveClient
    def __init__(self, user: str = "me", **kwargs: Any) -> None: ...
    async def _resolve_drive_id(self) -> str:
        if self.user.strip().lower() == "me" and self.client.is_app_only:
            raise RuntimeError("OneDrive user 'me' requires delegated, cached or on_behalf_of authentication")
