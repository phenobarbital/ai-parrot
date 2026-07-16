---
type: Wiki Overview
title: 'TASK-1707: MSAgent Integration Config Dataclass'
id: doc:sdd-tasks-completed-task-1707-msagent-integration-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task creates the `MSAgentIntegrationConfig` dataclass that models the
  YAML configuration for `kind: msagent` entries in `integrations_bots.yaml`. This
  config extends the existing `MSAgentSDKConfig` pattern with credential broker fields,
  O365 OAuth fields, and A2A companion s'
relates_to:
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
---

# TASK-1707: MSAgent Integration Config Dataclass

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the `MSAgentIntegrationConfig` dataclass that models the YAML configuration for `kind: msagent` entries in `integrations_bots.yaml`. This config extends the existing `MSAgentSDKConfig` pattern with credential broker fields, O365 OAuth fields, and A2A companion settings.

Implements spec §3 Module 2.

---

## Scope

- Add `MSAgentIntegrationConfig` dataclass to `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` (same file as `MSAgentSDKConfig`).
- Implement `from_dict(name, data)` classmethod for YAML parsing.
- Implement `__post_init__()` for env var fallback.
- Implement `to_msagentsdk_config()` method that converts to the inner `MSAgentSDKConfig` used by `MSAgentSDKWrapper`.
- Support all fields: MS Agent SDK fields (forwarded), A2A companion fields (`url`, `tags`, `jwt_secret`), credential broker fields (`enable_credential_broker`, `credentials`), O365 fields (`o365_client_id`, `o365_client_secret`, `o365_tenant_id`, `redirect_uri`), and `debug`.

**NOT in scope**: Wiring into `IntegrationBotConfig.from_dict()` (TASK-1708), startup logic (TASK-1711).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` | MODIFY | Add `MSAgentIntegrationConfig` below existing `MSAgentSDKConfig` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field          # stdlib
from typing import Dict, List, Any, Optional      # stdlib
from navconfig import config                      # verified: already imported in models.py:7
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
@dataclass
class MSAgentSDKConfig:
    name: str                                # line 67
    chatbot_id: str                          # line 68
    client_id: Optional[str] = None          # line 69
    client_secret: Optional[str] = None      # line 70
    tenant_id: Optional[str] = None          # line 71
    anonymous_auth: bool = False             # line 72
    api_key: Optional[str] = None            # line 73
    api_key_header: str = "x-api-key"        # line 74
    app_type: str = "SingleTenant"           # line 75
    authority: Optional[str] = None          # line 76
    kind: str = "msagentsdk"                 # line 77
    welcome_message: Optional[str] = None    # line 78
    system_prompt_override: Optional[str] = None  # line 79
    endpoint: Optional[str] = None           # line 80
    oauth_connections: Dict[str, str] = field(default_factory=dict)  # line 81
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)  # line 82

    def __post_init__(self) -> None:         # line 84
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":  # line 132
```

### Does NOT Exist
- ~~`MSAgentIntegrationConfig`~~ — does not exist yet; this task creates it
- ~~`MSAgentSDKConfig.to_msagentsdk_config()`~~ — no such method on MSAgentSDKConfig
- ~~`MSAgentSDKConfig.credentials`~~ — MSAgentSDKConfig has no credentials field

---

## Implementation Notes

### Pattern to Follow
```python
@dataclass
class MSAgentIntegrationConfig:
    name: str
    chatbot_id: str
    kind: str = "msagent"

    # MS Agent SDK fields (forwarded to MSAgentSDKConfig via to_msagentsdk_config)
    microsoft_app_id: Optional[str] = None
    microsoft_app_password: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)

    # A2A companion
    url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    jwt_secret: Optional[str] = None

    # Credential broker
    enable_credential_broker: bool = False
    credentials: List[Dict[str, Any]] = field(default_factory=list)

    # O365 OAuth infra
    o365_client_id: Optional[str] = None
    o365_client_secret: Optional[str] = None
    o365_tenant_id: Optional[str] = None
    redirect_uri: Optional[str] = None

    debug: bool = False

    def __post_init__(self) -> None:
        # Env var fallback using same {NAME.upper()}_* pattern
        ...

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentIntegrationConfig":
        ...

    def to_msagentsdk_config(self) -> MSAgentSDKConfig:
        """Convert to the inner MSAgentSDKConfig for MSAgentSDKWrapper."""
        return MSAgentSDKConfig(
            name=self.name,
            chatbot_id=self.chatbot_id,
            client_id=self.microsoft_app_id,
            client_secret=self.microsoft_app_password,
            tenant_id=self.microsoft_tenant_id,
            anonymous_auth=self.anonymous_auth,
            api_key=self.api_key,
            api_key_header=self.api_key_header,
            app_type=self.app_type,
            authority=self.authority,
            welcome_message=self.welcome_message,
            system_prompt_override=self.system_prompt_override,
            endpoint=self.endpoint,
            oauth_connections=self.oauth_connections,
            obo_scopes=self.obo_scopes,
        )
```

### Key Constraints
- Use `@dataclass`, NOT Pydantic.
- The MS fields use `microsoft_app_id` / `microsoft_app_password` / `microsoft_tenant_id` (YAML-friendly names), which map to `client_id` / `client_secret` / `tenant_id` in `MSAgentSDKConfig`.
- `to_msagentsdk_config()` must produce a valid `MSAgentSDKConfig` that `MSAgentSDKWrapper` accepts.
- `credentials` is `List[Dict[str, Any]]` — raw YAML dicts.

---

## Acceptance Criteria

- [ ] `MSAgentIntegrationConfig` dataclass created with all fields from spec §2
- [ ] `from_dict()` correctly parses a YAML-like dict
- [ ] `__post_init__()` falls back to env vars for MS credentials, O365 credentials, `jwt_secret`
- [ ] `to_msagentsdk_config()` returns a valid `MSAgentSDKConfig`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py`
- [ ] Import works: `from parrot.integrations.msagentsdk.models import MSAgentIntegrationConfig`

---

## Test Specification

```python
# tests/integrations/test_msagent_config.py
import pytest
from parrot.integrations.msagentsdk.models import MSAgentIntegrationConfig, MSAgentSDKConfig


class TestMSAgentIntegrationConfig:
    def test_from_dict_minimal(self):
        data = {"chatbot_id": "jirachi", "kind": "msagent"}
        cfg = MSAgentIntegrationConfig.from_dict("Jirachi", data)
        assert cfg.name == "Jirachi"
        assert cfg.chatbot_id == "jirachi"
        assert cfg.kind == "msagent"

    def test_from_dict_full(self):
        data = {
            "chatbot_id": "jirachi",
            "kind": "msagent",
            "microsoft_app_id": "app-id",
            "microsoft_app_password": "secret",
            "microsoft_tenant_id": "tenant",
            "url": "https://example.com",
            "enable_credential_broker": True,
            "credentials": [{"provider": "o365", "auth": "oauth2"}],
            "o365_client_id": "o365-id",
            "debug": True,
        }
        cfg = MSAgentIntegrationConfig.from_dict("Jirachi", data)
        assert cfg.microsoft_app_id == "app-id"
        assert cfg.debug is True
        assert len(cfg.credentials) == 1

    def test_to_msagentsdk_config(self):
        cfg = MSAgentIntegrationConfig(
            name="Test",
            chatbot_id="test",
            microsoft_app_id="app-id",
            microsoft_app_password="secret",
            microsoft_tenant_id="tenant",
        )
        sdk_cfg = cfg.to_msagentsdk_config()
        assert isinstance(sdk_cfg, MSAgentSDKConfig)
        assert sdk_cfg.client_id == "app-id"
        assert sdk_cfg.client_secret == "secret"
        assert sdk_cfg.tenant_id == "tenant"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `MSAgentSDKConfig` is still at `msagentsdk/models.py`
4. **Implement** `MSAgentIntegrationConfig` below the existing `MSAgentSDKConfig` in the same file
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1707-msagent-integration-config.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude)
**Date**: 2026-07-09
**Notes**: Added `MSAgentIntegrationConfig` dataclass to `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py`, directly below the existing `MSAgentSDKConfig`, exactly per the Codebase Contract's pattern to follow. Implemented `from_dict()`, `__post_init__()` (env var fallback for MS Azure AD, O365, and JWT secret fields, mirroring `MSAgentSDKConfig.__post_init__`), and `to_msagentsdk_config()` producing a valid `MSAgentSDKConfig`. Verified against the task's 3-case test scaffold (minimal parse, full parse, `to_msagentsdk_config()` conversion) — all pass. `ruff check` passes clean. No new files created; only the one file listed in scope was modified.

**Deviations from spec**: none
