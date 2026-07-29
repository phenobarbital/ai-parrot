---
type: Wiki Overview
title: 'TASK-1659: MCPOAuth2Config Model & Presets Registry'
id: doc:sdd-tasks-completed-task-1659-mcp-oauth2-config-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for FEAT-262. It defines the Pydantic data
  models
relates_to:
- concept: mod:parrot.mcp.oauth2_config
  rel: mentions
---

# TASK-1659: MCPOAuth2Config Model & Presets Registry

**Feature**: FEAT-262 — MCP Server OAuth2 Support
**Spec**: `sdd/specs/mcp-server-oauth2-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-262. It defines the Pydantic data models
(`MCPOAuth2Config`, `MCPOAuth2Preset`, `MCPOAuth2GrantType`) and the presets registry
that all other tasks depend on. Implements spec Module 1.

The presets registry follows the same in-code pattern as `MCPServerDescriptor`
(module-level list with lookup functions).

RFC 7591 dynamic client registration is supported: `client_id` is optional. When
omitted, the MCP SDK's `OAuthContext` handles dynamic registration automatically.

---

## Scope

- Create `parrot/mcp/oauth2_config.py` with:
  - `MCPOAuth2GrantType` enum (`authorization_code`, `client_credentials`)
  - `MCPOAuth2Config` Pydantic model with `client_id` (optional for RFC 7591),
    `client_secret`, `auth_url`, `token_url`, `scopes`, `grant_type`,
    `redirect_path`, `extra_token_params`
  - `MCPOAuth2Preset` Pydantic model with `name`, `display_name`, `auth_url`,
    `token_url`, `scopes`, `grant_type`, `url_template`, `required_params`
  - Module-level `_PRESETS: list[MCPOAuth2Preset]` with at least NetSuite entry
  - `get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None`
  - `list_mcp_oauth2_presets() -> list[MCPOAuth2Preset]`
- Write unit tests

**NOT in scope**: Integration with `MCPClientConfig` (TASK-1662), storage adapter
(TASK-1660), or transport layer (TASK-1663).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/oauth2_config.py` | CREATE | Models and presets registry |
| `tests/mcp/test_oauth2_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # standard pydantic
from typing import Optional, List
from enum import Enum
```

### Existing Signatures to Use
```python
# parrot/mcp/registry.py:62 — pattern to follow for presets (in-code registry)
class MCPServerDescriptor(BaseModel):
    name: str                          # line 63
    display_name: str                  # line 64
    description: str                   # line 65
    method_name: str                   # line 66
    params: List[MCPServerParam] = []  # line 67
    category: str = "general"          # line 85

# parrot/mcp/integration.py:788-799 — NetSuite URL templates to reuse
NETSUITE_MCP_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/..."
NETSUITE_AUTH_URL = "https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl"
NETSUITE_TOKEN_URL = "https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token"
NETSUITE_SCOPES = ["mcp"]
```

### Does NOT Exist
- ~~`parrot.mcp.oauth2_config`~~ — this is the module being created
- ~~`MCPOAuth2Config`~~ — does not exist yet
- ~~`MCPOAuth2Preset`~~ — does not exist yet
- ~~`MCPOAuth2GrantType`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow MCPServerDescriptor pattern from parrot/mcp/registry.py
_PRESETS: list[MCPOAuth2Preset] = [
    MCPOAuth2Preset(
        name="netsuite",
        display_name="NetSuite",
        auth_url="https://{account_id}.app.netsuite.com/app/login/oauth2/authorize.nl",
        token_url="https://{account_id}.suitetalk.api.netsuite.com/services/rest/auth/oauth2/v1/token",
        scopes=["mcp"],
        url_template="https://{account_id}.suitetalk.api.netsuite.com/services/mcp/v1/...",
        required_params=["account_id", "client_id"],
    ),
]

def get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None:
    return next((p for p in _PRESETS if p.name == name), None)
```

### Key Constraints
- `client_id` is `Optional[str]` — when `None`, RFC 7591 dynamic registration is used
- Use Pydantic `BaseModel` with `Field` for all models
- `grant_type` defaults to `authorization_code`
- `redirect_path` defaults to `"/api/auth/oauth2/mcp/callback"`

---

## Acceptance Criteria

- [ ] `MCPOAuth2Config` model validates correctly (client_id optional, grant_type enum)
- [ ] `MCPOAuth2Preset` model contains all required fields
- [ ] `get_mcp_oauth2_preset("netsuite")` returns correct preset
- [ ] `get_mcp_oauth2_preset("unknown")` returns `None`
- [ ] `list_mcp_oauth2_presets()` returns all presets
- [ ] All tests pass: `pytest tests/mcp/test_oauth2_config.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
- [ ] Import works: `from parrot.mcp.oauth2_config import MCPOAuth2Config, MCPOAuth2Preset`

---

## Test Specification

```python
# tests/mcp/test_oauth2_config.py
import pytest
from parrot.mcp.oauth2_config import (
    MCPOAuth2Config,
    MCPOAuth2Preset,
    MCPOAuth2GrantType,
    get_mcp_oauth2_preset,
    list_mcp_oauth2_presets,
)


class TestMCPOAuth2Config:
    def test_defaults(self):
        cfg = MCPOAuth2Config()
        assert cfg.client_id is None
        assert cfg.grant_type == MCPOAuth2GrantType.AUTHORIZATION_CODE
        assert cfg.redirect_path == "/api/auth/oauth2/mcp/callback"

    def test_with_client_id(self):
        cfg = MCPOAuth2Config(client_id="my-app", scopes=["read"])
        assert cfg.client_id == "my-app"

    def test_grant_type_enum(self):
        cfg = MCPOAuth2Config(grant_type="client_credentials")
        assert cfg.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS


class TestPresets:
    def test_netsuite_preset_exists(self):
        preset = get_mcp_oauth2_preset("netsuite")
        assert preset is not None
        assert preset.name == "netsuite"
        assert "mcp" in preset.scopes

    def test_unknown_preset(self):
        assert get_mcp_oauth2_preset("nonexistent") is None

    def test_list_presets(self):
        presets = list_mcp_oauth2_presets()
        assert len(presets) >= 1
        assert any(p.name == "netsuite" for p in presets)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `MCPServerDescriptor` pattern at `parrot/mcp/registry.py:62`
4. **Implement** the models and presets registry
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1659-mcp-oauth2-config-models.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-26
**Notes**: Created `packages/ai-parrot/src/parrot/mcp/oauth2_config.py` with
MCPOAuth2GrantType enum, MCPOAuth2Config Pydantic model, MCPOAuth2Preset Pydantic
model, module-level _PRESETS list with NetSuite and Fireflies entries, and lookup
functions. All 19 tests pass with --import-mode=importlib (required due to
namespace conflict between tests/mcp/__init__.py and the MCP SDK mcp package).

**Deviations from spec**: Tests require --import-mode=importlib due to pre-existing
namespace conflict with MCP SDK package. Fireflies preset added as noted in task context.
