---
type: Wiki Overview
title: 'TASK-1368: Split mcp/oauth.py — server parts to satellite'
id: doc:sdd-tasks-completed-task-1368-split-mcp-oauth-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 4. `parrot/mcp/oauth.py` (1137 lines) mixes server-side
  OAuth infrastructure with consumer-side token management. The server parts must
  be extracted to `oauth_server.py` in the satellite.
relates_to:
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.mcp.oauth_server
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
---

# TASK-1368: Split mcp/oauth.py — server parts to satellite

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1366
**Assigned-to**: unassigned

## Context
Implements Module 4. `parrot/mcp/oauth.py` (1137 lines) mixes server-side OAuth infrastructure with consumer-side token management. The server parts must be extracted to `oauth_server.py` in the satellite.

## Scope
- Create `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py` containing:
  - `APIKeyRecord` (dataclass, lines 30-39)
  - `APIKeyStore` (lines 41-207)
  - `ExternalOAuthValidator` (lines 211-325)
  - `OAuthClient` + `ClientRegistry` (lines 329-372)
  - `OAuthAuthorizationServer` (lines 374-564)
  - `OAuthRoutesMixin` (lines 1003-1137)
- Trim `parrot/mcp/oauth.py` to keep only consumer-side:
  - Helper functions `_b64url`, `_now` (lines 19-27)
  - `TokenStore` abstract + `InMemoryTokenStore` + `RedisTokenStore` + `VaultTokenStore` (lines 566-707)
  - `NetSuiteM2MAuth` (lines 712-817)
  - `OAuthManager` (lines 819-1001)
- The satellite's `oauth_server.py` imports `TokenStore` etc. from `parrot.mcp.oauth` (core)
- Update `parrot/mcp/__init__.py` lazy exports to resolve server classes from satellite

**NOT in scope**: Moving other MCP files (TASK-1369).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py` | CREATE | Server-side OAuth classes |
| `packages/ai-parrot/src/parrot/mcp/oauth.py` | MODIFY | Remove server classes, keep consumer |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# oauth.py current imports (lines 1-18):
import os, sys, logging, typing, dataclasses, asyncio, time, base64, hashlib, secrets, json, urllib
from aiohttp import web, ClientSession
from parrot.security.vault_utils import (  # UPDATED path after TASK-1366
    store_vault_credential, retrieve_vault_credential,
    delete_vault_credential, load_vault_keys, oauth2_vault_name
)
```

### Existing Signatures to Use
```python
# Lines to MOVE to satellite:
class APIKeyRecord:  # line 30 — @dataclass
class APIKeyStore:  # line 41
class ExternalOAuthValidator:  # line 211
class OAuthClient:  # line 329 — @dataclass
class ClientRegistry:  # line 339
class OAuthAuthorizationServer:  # line 374
class OAuthRoutesMixin:  # line 1003

# Lines to KEEP in core:
class TokenStore:  # line 566 — abstract
class InMemoryTokenStore(TokenStore):  # line 572
class RedisTokenStore(TokenStore):  # line 586
class VaultTokenStore(TokenStore):  # line 607
class NetSuiteM2MAuth:  # line 712
class OAuthManager:  # line 819
```

### Does NOT Exist
- ~~`parrot.mcp.oauth_server`~~ — does not exist yet; this task creates it
- ~~`parrot.mcp.oauth.OAuthAuthorizationServer` (after this task)~~ — will have moved to satellite

## Acceptance Criteria
- [ ] `from parrot.mcp.oauth import TokenStore, OAuthManager, NetSuiteM2MAuth` works (core)
- [ ] `from parrot.mcp.oauth_server import OAuthAuthorizationServer, APIKeyStore` works (satellite)
- [ ] `OAuthRoutesMixin` in satellite can import `TokenStore` from core
- [ ] No import errors in existing code

## Test Specification
```python
def test_core_oauth_imports():
    """Consumer-side classes remain in core."""
    from parrot.mcp.oauth import TokenStore, OAuthManager, NetSuiteM2MAuth
    assert TokenStore is not None
    assert OAuthManager is not None

def test_satellite_oauth_server_imports():
    """Server-side classes live in satellite."""
    from parrot.mcp.oauth_server import (
        OAuthAuthorizationServer, APIKeyStore, ExternalOAuthValidator
    )
    assert OAuthAuthorizationServer is not None

def test_satellite_imports_core_tokenstore():
    """Server module can import from core."""
    from parrot.mcp.oauth_server import OAuthAuthorizationServer
    from parrot.mcp.oauth import TokenStore
    # OAuthAuthorizationServer internally uses TokenStore from core
    assert TokenStore is not None
```

## Agent Instructions
(standard — see template)

## Completion Note
*(Agent fills this in when done)*
