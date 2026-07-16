---
type: Wiki Entity
title: SharepointClient
id: class:parrot.interfaces.sharepoint.SharepointClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: SharePoint Client - Migrated to Microsoft Graph SDK
relates_to:
- concept: class:parrot.interfaces.o365.O365Client
  rel: extends
---

# SharepointClient

Defined in [`parrot.interfaces.sharepoint`](../summaries/mod:parrot.interfaces.sharepoint.md).

```python
class SharepointClient(O365Client)
```

SharePoint Client - Migrated to Microsoft Graph SDK

Uses Microsoft Graph SDK for all SharePoint operations.

## Methods

- `def get_context(self, url: str, *args)` — Backwards compatibility method.
- `def connection(self)` — Establish SharePoint connection using the migrated O365Client.
- `async def verify_sharepoint_access(self)` — Verify SharePoint-specific access and cache site/drive info.
- `async def upload_files(self, filenames: Optional[List[Union[Path, PurePath, str]]]=None, destination: Optional[str]=None, destination_filenames: Optional[List[str]]=None) -> List[Dict[str, Any]]` — Upload files to SharePoint using Microsoft Graph API.
- `async def test_permissions(self) -> Dict[str, Any]` — Test SharePoint permissions using Microsoft Graph API.
- `async def upload_folder(self, local_folder: PurePath, destination: str=None, destination_filenames: Optional[List[str]]=None)` — Upload an entire folder to SharePoint using Microsoft Graph API.
- `async def create_subscription(self, library_id: str, webhook_url: str, client_state: str='secret_string', expiration_days: int=1) -> dict` — Create webhook subscription using Graph API.
- `async def get_library_id(self, absolute_url: str) -> str` — Get library ID using Graph API.
- `async def close(self)` — Clean up resources.
- `async def download_found_files(self, found: List[Dict[str, Any]]) -> List[Dict[str, str]]` — Download all items in 'found' (from file_search) into local self.directory.
- `async def file_search(self) -> List[Dict[str, Any]]` — Search for files with Graph API (when safe) and recursive fallback starting at the target folder.
- `async def file_lookup(self, files: Optional[List[Dict[str, str]]]=None) -> List[Dict[str, Any]]` — Resolve exact files (no search) into 'destinations' items.
- `async def debug_root_structure(self)` — Quick debug to see what's actually at the root of this SharePoint site.
