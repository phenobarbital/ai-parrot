---
type: Wiki Entity
title: APIKeyStore
id: class:parrot.mcp.oauth_server.APIKeyStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory API key store with session logging.
---

# APIKeyStore

Defined in [`parrot.mcp.oauth_server`](../summaries/mod:parrot.mcp.oauth_server.md).

```python
class APIKeyStore
```

In-memory API key store with session logging.

Provides API key issuance, validation, and session tracking for
MCP server authentication.

## Methods

- `def issue_key(self, user_id: str, scopes: Optional[list[str]]=None, ttl: Optional[int]=None, description: str='') -> APIKeyRecord` — Issue a new API key for a user.
- `def add_key(self, key: str, user_id: str, scopes: Optional[list[str]]=None, description: str='') -> APIKeyRecord` — Register an existing API key.
- `def validate_key(self, key: str) -> Optional[APIKeyRecord]` — Validate an API key.
- `def revoke_key(self, key: str) -> bool` — Revoke an API key.
- `def log_session_start(self, key: str, user_id: str, timestamp: float) -> None` — Log the start of a session using an API key.
- `def get_sessions(self, user_id: Optional[str]=None, limit: int=100) -> list[Dict[str, Any]]` — Get session logs.
- `def list_keys(self, user_id: Optional[str]=None) -> list[APIKeyRecord]` — List all API keys.
