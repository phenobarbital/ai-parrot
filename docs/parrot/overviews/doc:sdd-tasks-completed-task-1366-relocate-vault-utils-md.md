---
type: Wiki Overview
title: 'TASK-1366: Relocate vault_utils and credentials_utils to parrot/security/'
id: doc:sdd-tasks-completed-task-1366-relocate-vault-utils-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 2. `vault_utils.py` and `credentials_utils.py` currently
  live in `parrot/handlers/` but are imported by core modules (`parrot/mcp/oauth.py`,
  `parrot/auth/oauth2_base.py`). Since handlers will move to the satellite, these
  shared utilities must be relocated to `pa
relates_to:
- concept: mod:parrot.handlers.credentials_utils
  rel: mentions
- concept: mod:parrot.handlers.vault_utils
  rel: mentions
- concept: mod:parrot.mcp.oauth
  rel: mentions
- concept: mod:parrot.security.credentials_utils
  rel: mentions
- concept: mod:parrot.security.vault_utils
  rel: mentions
---

# TASK-1366: Relocate vault_utils and credentials_utils to parrot/security/

**Feature**: FEAT-203 — ai-parrot-server
**Spec**: `sdd/specs/ai-parrot-server.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context
Implements Module 2. `vault_utils.py` and `credentials_utils.py` currently live in `parrot/handlers/` but are imported by core modules (`parrot/mcp/oauth.py`, `parrot/auth/oauth2_base.py`). Since handlers will move to the satellite, these shared utilities must be relocated to `parrot/security/` (which already exists) before the extraction.

## Scope
- Move `packages/ai-parrot/src/parrot/handlers/vault_utils.py` (175 lines) to `packages/ai-parrot/src/parrot/security/vault_utils.py`
- Move `packages/ai-parrot/src/parrot/handlers/credentials_utils.py` (81 lines) to `packages/ai-parrot/src/parrot/security/credentials_utils.py`
- Update `parrot/security/__init__.py` to export the new modules
- Replace original files with backward-compatible import redirects
- Update direct imports:
  - `parrot/mcp/oauth.py:14` — `from parrot.security.vault_utils import ...`
  - `parrot/auth/oauth2_base.py:166` — `from parrot.security.vault_utils import ...`

**NOT in scope**: Moving handlers to satellite (TASK-1371), modifying any other files.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/vault_utils.py` | CREATE | Relocated from handlers |
| `packages/ai-parrot/src/parrot/security/credentials_utils.py` | CREATE | Relocated from handlers |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | Add new exports |
| `packages/ai-parrot/src/parrot/handlers/vault_utils.py` | MODIFY | Replace with redirect |
| `packages/ai-parrot/src/parrot/handlers/credentials_utils.py` | MODIFY | Replace with redirect |
| `packages/ai-parrot/src/parrot/mcp/oauth.py` | MODIFY | Update import path |
| `packages/ai-parrot/src/parrot/auth/oauth2_base.py` | MODIFY | Update import path |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/security/__init__.py (existing exports — lines 4-14):
from .prompt_injection import PromptInjectionDetector, SecurityEventLogger, ThreatLevel, PromptInjectionException
from .query_validator import QueryLanguage, QueryValidator

# parrot/handlers/vault_utils.py:5 imports:
from parrot.handlers.credentials_utils import decrypt_credential, encrypt_credential

# parrot/mcp/oauth.py:14 imports:
from parrot.handlers.vault_utils import (
    store_vault_credential, retrieve_vault_credential,
    delete_vault_credential, load_vault_keys, oauth2_vault_name
)

# parrot/auth/oauth2_base.py:166 (local import inside method):
from parrot.handlers.vault_utils import (
    store_vault_credential, retrieve_vault_credential, oauth2_vault_name
)
```

### Existing Signatures to Use
```python
# parrot/handlers/vault_utils.py
def load_vault_keys(): ...  # line 44
async def store_vault_credential(): ...  # line 69
async def retrieve_vault_credential(): ...  # line 116
async def delete_vault_credential(): ...  # line 149
def oauth2_vault_name(): ...  # line 168

# parrot/handlers/credentials_utils.py
def encrypt_credential(): ...  # line 19
def decrypt_credential(): ...  # line 52
```

### Does NOT Exist
- ~~`parrot.security.vault_utils`~~ — does not exist yet; this task creates it
- ~~`parrot.security.credentials_utils`~~ — does not exist yet

## Acceptance Criteria
- [ ] `from parrot.security.vault_utils import store_vault_credential` works
- [ ] `from parrot.security.credentials_utils import encrypt_credential` works
- [ ] `from parrot.handlers.vault_utils import store_vault_credential` still works (redirect)
- [ ] `from parrot.mcp.oauth import VaultTokenStore` works (updated import)
- [ ] No circular imports introduced

## Test Specification
```python
def test_new_import_path():
    from parrot.security.vault_utils import store_vault_credential
    assert callable(store_vault_credential)

def test_backward_compat_redirect():
    from parrot.handlers.vault_utils import store_vault_credential
    assert callable(store_vault_credential)

def test_credentials_new_path():
    from parrot.security.credentials_utils import encrypt_credential
    assert callable(encrypt_credential)
```

## Agent Instructions
(standard — see template)

## Completion Note
*(Agent fills this in when done)*
