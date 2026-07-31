---
type: Wiki Entity
title: Office365Toolkit
id: class:parrot_tools.o365.oauth_toolkit.Office365Toolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Microsoft Graph toolkit with delegated per-user OAuth tokens.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# Office365Toolkit

Defined in [`parrot_tools.o365.oauth_toolkit`](../summaries/mod:parrot_tools.o365.oauth_toolkit.md).

```python
class Office365Toolkit(AbstractToolkit)
```

Microsoft Graph toolkit with delegated per-user OAuth tokens.

Tools generated automatically from public async methods:

- :meth:`read_inbox` — list recent messages.
- :meth:`search_messages` — full-text search the user's mailbox.
- :meth:`send_email` — send a plain-text message as the user.
- :meth:`list_onedrive_files` — list files under a OneDrive path.
- :meth:`list_sharepoint_sites` — search SharePoint sites the user can see.
- :meth:`list_upcoming_events` — read upcoming calendar events.

Credential UX (FEAT-264): the toolkit declares
``credential_provider = "o365"``, so when a CredentialBroker is attached
to the ToolManager (and the ``o365`` provider is registered on it, e.g.
``ProviderCredentialConfig(provider="o365", auth="oauth2")`` with an
``oauth_managers={"o365": manager}`` dep) a credential miss raises
:class:`~parrot.auth.credentials.CredentialRequired` before the tool
body — surfaces render their native consent UX (OAuthCard on MSAgentSDK).
Without a broker, the legacy ``_pre_execute`` path below applies and a
miss surfaces as an ``authorization_required`` ToolResult instead.

Args:
    credential_resolver: Resolver bound to a
        :class:`parrot.auth.o365_oauth.O365OAuthManager` (typically via
        :class:`parrot.auth.credentials.OAuthCredentialResolver`).
    tenant_id: Microsoft tenant identifier (``"common"``, ``"organizations"``,
        or a GUID). Recorded on each token set; used only for diagnostics.
    cache_size: Maximum number of (channel, user_id) → session entries.

## Methods

- `async def read_inbox(self, top: int=10) -> List[Dict[str, Any]]` — Read the user's most recent inbox messages.
- `async def search_messages(self, query: str, top: int=10) -> List[Dict[str, Any]]` — Search the user's mailbox using the Graph ``$search`` operator.
- `async def send_email(self, to: List[str], subject: str, body: str, cc: Optional[List[str]]=None) -> Dict[str, Any]` — Send an email from the user's mailbox.
- `async def list_onedrive_files(self, path: str='/', top: int=25) -> List[Dict[str, Any]]` — List files in the user's OneDrive under *path*.
- `async def list_sharepoint_sites(self, query: str='', top: int=10) -> List[Dict[str, Any]]` — Search SharePoint sites the user has access to.
- `async def list_upcoming_events(self, top: int=10) -> List[Dict[str, Any]]` — List the user's upcoming calendar events ordered by start time.
