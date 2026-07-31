---
type: Wiki Entity
title: O365Client
id: class:parrot.interfaces.o365.O365Client
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: O365Client - Migrated to Microsoft Graph SDK
---

# O365Client

Defined in [`parrot.interfaces.o365`](../summaries/mod:parrot.interfaces.o365.md).

```python
class O365Client(CredentialsInterface)
```

O365Client - Migrated to Microsoft Graph SDK

Overview

    The O365Client class is an abstract base class for managing connections to Office 365 services
    using the official Microsoft Graph SDK. It handles authentication, credential processing,
    and provides methods for obtaining the Graph client. It uses Azure Identity for authentication
    and Microsoft Graph SDK for context management.

Supported Authentication Methods:
    - Username/Password (UsernamePasswordCredential)
    - Client Credentials (ClientSecretCredential)
    - On-Behalf-Of (OnBehalfOfCredential)

.. table:: Properties
:widths: auto

    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | Name             | Required | Description                                                                                      |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | url              |   No     | The base URL for the Office 365 service.                                                         |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | tenant           |   Yes    | The tenant ID for the Office 365 service.                                                        |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | site             |   No     | The site URL for the Office 365 service.                                                         |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | credential       |   Yes    | The Azure Identity credential object.                                                            |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | graph_client     |   Yes    | The Microsoft Graph SDK client object.                                                           |
    +------------------+----------+--------------------------------------------------------------------------------------------------+
    | credentials      |   Yes    | A dictionary containing the credentials for authentication.                                      |
    +------------------+----------+--------------------------------------------------------------------------------------------------+

Return

    The methods in this class manage the authentication and connection setup for Office 365 services,
    providing an abstract base for subclasses to implement specific service interactions.

## Methods

- `def get_context(self, url: str, *args)` — Return the Graph client for the given URL.
- `async def run_in_executor(self, fn, *args, **kwargs)` — Calling any blocking process in an executor.
- `def processing_credentials(self)` — Process credentials using the inherited CredentialsInterface.
- `def graph_client(self) -> GraphServiceClient` — Get the Graph client, creating it if necessary.
- `def access_token(self) -> Optional[str]` — Get current access token for backwards compatibility.
- `def set_auth_mode(self, auth_mode: Optional[str]) -> None` — Persist the authentication mode used to acquire tokens.
- `def is_app_only(self) -> bool` — Return True when running with application (client credentials) permissions.
- `def get_user_context(self, user_id: Optional[str]=None)` — Return the appropriate user request builder for Graph operations.
- `def connection(self)` — Establish connection to Office 365 services using Microsoft Graph SDK.
- `def user_auth(self, username: str, password: str, scopes: Optional[List[str]]=None) -> Dict[str, Any]` — Authenticate using username and password with Microsoft Graph SDK.
- `def acquire_token(self, scopes: Optional[List[str]]=None) -> Dict[str, Any]` — Acquire token using client credentials with Microsoft Graph SDK.
- `def acquire_token_on_behalf_of(self, user_assertion: str, scopes: Optional[List[str]]=None) -> Dict[str, Any]` — Acquire token using On-Behalf-Of flow with Microsoft Graph SDK.
- `async def get_me(self)` — Get current user information.
- `async def get_organization(self)` — Get organization information.
- `async def get_sites(self)` — Get SharePoint sites.
- `async def get_drives(self)` — Get OneDrive/SharePoint drives.
- `async def close(self)` — Clean up resources.
- `async def interactive_login(self, scopes: Optional[List[str]]=None, redirect_uri: str='http://localhost', open_browser: bool=True, login_callback: Optional[Callable[[str], Optional[bool]]]=None, device_flow_callback: Optional[Callable[[Dict[str, Any]], None]]=None) -> Dict[str, Any]` — Perform interactive login supporting both public and confidential clients.
- `async def ensure_interactive_session(self, scopes: Optional[List[str]]=None)` — Ensure an interactive session (with cached refresh tokens) exists.
