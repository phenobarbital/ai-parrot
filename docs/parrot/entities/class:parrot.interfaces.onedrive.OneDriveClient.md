---
type: Wiki Entity
title: OneDriveClient
id: class:parrot.interfaces.onedrive.OneDriveClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OneDrive Client - Migrated to Microsoft Graph SDK
relates_to:
- concept: class:parrot.interfaces.o365.O365Client
  rel: extends
---

# OneDriveClient

Defined in [`parrot.interfaces.onedrive`](../summaries/mod:parrot.interfaces.onedrive.md).

```python
class OneDriveClient(O365Client)
```

OneDrive Client - Migrated to Microsoft Graph SDK

Uses Microsoft Graph SDK for all OneDrive operations.

Interface for Managing connections to OneDrive resources.

Methods:
    file_list: Lists files in a specified OneDrive folder.
    file_search: Searches for files matching a query.
    file_download: Downloads a single file by its item ID.
    download_files: Downloads multiple files provided as a list of dictionaries containing file info.
    folder_download: Downloads a folder and its contents recursively.
    file_delete: Deletes a file or folder by its item ID.
    upload_files: Uploads multiple files to a specified OneDrive folder.
    upload_file: Uploads a single file to OneDrive.
    upload_folder: Uploads a local folder and its contents to OneDrive recursively.
    download_excel_file: Downloads Excel files and optionally converts to pandas DataFrame.
    upload_dataframe_as_excel: Uploads pandas DataFrame as Excel file to OneDrive.

## Methods

- `def connection(self)` — Establish OneDrive connection using the migrated O365Client.
- `async def verify_onedrive_access(self)` — Verify OneDrive access and cache drive info.
- `async def file_list(self, folder_path: str=None) -> List[dict]` — List files in a given OneDrive folder using Microsoft Graph API.
- `async def file_search(self, search_query: str) -> List[dict]` — Search for files in OneDrive matching the search query using Microsoft Graph API.
- `async def file_download(self, item_id: str, destination: Path) -> str` — Download a file from OneDrive by item ID using Microsoft Graph API.
- `async def download_files(self, items: List[dict], destination_folder: Path) -> List[str]` — Download multiple files from OneDrive using Microsoft Graph API.
- `async def folder_download(self, folder_id: str, destination_folder: Path) -> bool` — Download a folder and its contents from OneDrive using Microsoft Graph API.
- `async def file_delete(self, item_id: str) -> bool` — Delete a file or folder in OneDrive by item ID using Microsoft Graph API.
- `async def upload_file(self, file_path: Path, destination_folder: str=None) -> dict` — Upload a single file to OneDrive using Microsoft Graph API.
- `async def upload_files(self, files: List[Path], destination_folder: str=None) -> List[dict]` — Upload multiple files to OneDrive using Microsoft Graph API.
- `async def upload_folder(self, local_folder: Path, destination_folder: str=None) -> List[dict]` — Upload a local folder and its contents to OneDrive using Microsoft Graph API.
- `async def download_excel_file(self, item_id: str, destination: Path=None, as_pandas: bool=False)` — Download an Excel file from OneDrive by item ID using Microsoft Graph API.
- `async def upload_dataframe_as_excel(self, df: pd.DataFrame, file_name: str, destination_folder: str=None) -> dict` — Upload a pandas DataFrame as an Excel file to OneDrive using Microsoft Graph API.
- `async def test_permissions(self) -> Dict[str, Any]` — Test OneDrive permissions using Microsoft Graph API.
- `async def close(self)` — Clean up resources.
