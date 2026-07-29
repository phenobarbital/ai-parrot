---
type: Wiki Entity
title: GoogleClient
id: class:parrot.interfaces.google.GoogleClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Google Services Client for AI-Parrot.
---

# GoogleClient

Defined in [`parrot.interfaces.google`](../summaries/mod:parrot.interfaces.google.md).

```python
class GoogleClient(CredentialsInterface, ABC)
```

Google Services Client for AI-Parrot.

Async-only implementation using aiogoogle for:
- Google Drive (file management)
- Google Sheets (spreadsheets)
- Google Docs (documents)
- Google Calendar (events)
- Google Cloud Storage (buckets)
- Gmail (email)
- Google Custom Search

Features:
- Service account and user credentials support
- Environment variable replacement in credentials
- Full async/await support via aiogoogle
- OAuth2 interactive login support (framework ready)
- Credential caching

Authentication Methods:
1. Service Account (recommended for server apps):
   - Use JSON key file
   - Use JSON string
   - Use dictionary

2. User Credentials (OAuth2):
   - Interactive browser login (TODO: implement)
   - Cached credentials

Example:
    # Service account from file
    client = GoogleClient(credentials="path/to/key.json")
    await client.initialize()

    # Service account from dict with env vars
    client = GoogleClient(credentials={
        "type": "service_account",
        "project_id": "${GCP_PROJECT_ID}",
        "private_key": "${GCP_PRIVATE_KEY}",
        ...
    })
    await client.initialize()

    # Context manager (recommended)
    async with GoogleClient(credentials="key.json", scopes="drive") as client:
        result = await client.execute_api_call(...)

## Methods

- `def load_cached_user_credentials(self) -> bool` — Public helper for loading cached user credentials.
- `def set_credentials(self, credentials: Optional[Union[str, dict, Path]]) -> None` — Public helper to update credentials after initialization.
- `def active_credentials(self) -> Optional[Union[ServiceAccountCreds, UserCreds]]` — Return whichever credential set is currently active.
- `def credentials_source(self) -> Optional[str]` — Return the source the client used to obtain credentials.
- `def is_authenticated(self) -> bool` — Expose authentication status for callers.
- `def using_service_account(self) -> bool` — Return True if the client is configured for service-account credentials.
- `def using_user_credentials(self) -> bool` — Return True if the client is configured for end-user OAuth credentials.
- `async def initialize(self) -> GoogleClient` — Initialize the client and authenticate.
- `async def execute_api_call(self, service_name: str, api_name: str, method_chain: str, version: str=None, **kwargs) -> Any` — Execute a Google API call.
- `async def get_drive_client(self, version: str='v3') -> Dict[str, Any]` — Get Google Drive client config.
- `async def get_sheets_client(self, version: str='v4') -> Dict[str, Any]` — Get Google Sheets client config.
- `async def get_docs_client(self, version: str='v1') -> Dict[str, Any]` — Get Google Docs client config.
- `async def get_calendar_client(self, version: str='v3') -> Dict[str, Any]` — Get Google Calendar client config.
- `async def get_storage_client(self, version: str='v1') -> Dict[str, Any]` — Get Google Cloud Storage client config.
- `async def get_gmail_client(self, version: str='v1') -> Dict[str, Any]` — Get Gmail client config.
- `async def search(self, query: str, cse_id: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Perform a Google Custom Search.
- `async def interactive_login(self, scopes: Optional[Union[List[str], str]]=None, port: int=5050, redirect_uri: Optional[str]=None, open_browser: bool=True, browser: str='system', login_callback: Optional[Callable[[str], Optional[bool]]]=None, timeout: int=300) -> Dict[str, Any]` — Perform interactive OAuth2 login for user credentials.
- `async def close(self) -> None` — Clean up resources.
- `async def ensure_interactive_session(self, scopes: Optional[Union[List[str], str]]=None) -> None` — Ensure we have usable user creds in memory; load from Redis/file cache if possible.
