---
type: Wiki Overview
title: 'TASK-1637: Package Scaffold + Config Model'
id: doc:sdd-tasks-completed-task-1637-msagentsdk-package-and-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational task for the MS Agent SDK integration. It creates
  the
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
---

# TASK-1637: Package Scaffold + Config Model

**Feature**: FEAT-259 — Microsoft Copilot Agent SDK Integration
**Spec**: `sdd/specs/microsoft-copilot-agent-sdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for the MS Agent SDK integration. It creates the
package directory structure, `__init__.py`, the `MSAgentSDKConfig` dataclass,
and adds the optional `msagentsdk` extras group to `pyproject.toml`.

Implements: Spec §3 Module 1 (Config Model) + Module 5 (Package Init + Dependencies).

---

## Scope

- Create the `msagentsdk/` package directory under `packages/ai-parrot-integrations/src/parrot/integrations/`.
- Create `__init__.py` with lazy exports for `MSAgentSDKConfig`.
- Create `models.py` with the `MSAgentSDKConfig` dataclass following the
  `WhatsAppAgentConfig` pattern (dataclass, `__post_init__` for env var fallback,
  `from_dict` classmethod).
- Add `msagentsdk` extras group to `packages/ai-parrot-integrations/pyproject.toml`:
  `microsoft-agents-hosting-aiohttp~=0.9.0`.

**NOT in scope**: Bridge agent, wrapper, manager registration, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py` | CREATE | Package init with lazy exports |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` | CREATE | `MSAgentSDKConfig` dataclass |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add `msagentsdk` extras group |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from navconfig import config  # verified: used in whatsapp/models.py:6, msteams/models.py:6
```

### Existing Signatures to Use

```python
# packages/ai-parrot-integrations/src/parrot/integrations/whatsapp/models.py:10
# REFERENCE PATTERN — follow this structure for MSAgentSDKConfig
@dataclass
class WhatsAppAgentConfig:
    name: str                              # line 31
    chatbot_id: str                        # line 32
    phone_id: Optional[str] = None         # line 33
    kind: str = "whatsapp"                 # line 38
    welcome_message: Optional[str] = None  # line 40
    system_prompt_override: Optional[str] = None  # line 41
    
    def __post_init__(self):  # line 47
        prefix = self.name.upper()
        if not self.phone_id:
            self.phone_id = config.get(f"{prefix}_WHATSAPP_PHONE_ID")

    @classmethod
    def from_dict(cls, name: str, data: dict) -> 'WhatsAppAgentConfig':
        # constructs from YAML dict
```

### Does NOT Exist

- ~~`parrot.integrations.base.AbstractIntegration`~~ — no base class for integrations
- ~~`parrot.integrations.base.BaseConfig`~~ — no base config class; each platform has its own dataclass
- ~~`from microsoft.agents import *`~~ — old namespace; SDK uses `microsoft_agents` (underscores)

---

## Implementation Notes

### Pattern to Follow

```python
# Follow WhatsAppAgentConfig exactly (whatsapp/models.py:10-60)
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from navconfig import config


@dataclass
class MSAgentSDKConfig:
    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None

    def __post_init__(self):
        prefix = self.name.upper()
        if not self.client_id:
            self.client_id = config.get(f"{prefix}_MICROSOFT_APP_ID")
        if not self.client_secret:
            self.client_secret = config.get(f"{prefix}_MICROSOFT_APP_PASSWORD")
        if not self.tenant_id:
            self.tenant_id = config.get(f"{prefix}_MICROSOFT_TENANT_ID")

    @classmethod
    def from_dict(cls, name: str, data: dict) -> 'MSAgentSDKConfig':
        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', ''),
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            tenant_id=data.get('tenant_id'),
            anonymous_auth=data.get('anonymous_auth', False),
            welcome_message=data.get('welcome_message'),
            system_prompt_override=data.get('system_prompt_override'),
        )
```

### Key Constraints

- Use `@dataclass` (not Pydantic) — all existing config models use `@dataclass`.
- Use `navconfig.config.get()` for env var fallback in `__post_init__`.
- Keep `kind` field as string literal `"msagentsdk"`.

### pyproject.toml extras pattern

```toml
# Add alongside existing extras (slack, telegram, etc.)
[project.optional-dependencies]
msagentsdk = [
    "microsoft-agents-hosting-aiohttp~=0.9.0",
]
```

---

## Acceptance Criteria

- [ ] `MSAgentSDKConfig` can be constructed from a dict via `from_dict()`
- [ ] `__post_init__` resolves credentials from env vars when not provided
- [ ] `kind` field defaults to `"msagentsdk"`
- [ ] Package `__init__.py` exports `MSAgentSDKConfig`
- [ ] `msagentsdk` extras group added to `pyproject.toml`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/`

---

## Test Specification

```python
# tests/integrations/test_msagentsdk/test_models.py
import pytest
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig


class TestMSAgentSDKConfig:
    def test_from_dict_basic(self):
        data = {
            "chatbot_id": "test_agent",
            "client_id": "app-id-123",
            "client_secret": "secret-456",
            "tenant_id": "tenant-789",
        }
        config = MSAgentSDKConfig.from_dict("TestBot", data)
        assert config.name == "TestBot"
        assert config.chatbot_id == "test_agent"
        assert config.client_id == "app-id-123"
        assert config.kind == "msagentsdk"

    def test_from_dict_anonymous_auth(self):
        data = {"chatbot_id": "test_agent", "anonymous_auth": True}
        config = MSAgentSDKConfig.from_dict("TestBot", data)
        assert config.anonymous_auth is True
        assert config.client_id is None

    def test_from_dict_defaults(self):
        data = {"chatbot_id": "test_agent"}
        config = MSAgentSDKConfig.from_dict("TestBot", data)
        assert config.anonymous_auth is False
        assert config.welcome_message is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/microsoft-copilot-agent-sdk.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `WhatsAppAgentConfig` pattern is still at the listed path/lines
4. **Implement** the config model and package structure
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-1637-msagentsdk-package-and-config.md`
7. **Update index** → `"done"`

---

## Completion Note

Implemented by sdd-worker on 2026-06-25.

Created:
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/__init__.py` — lazy exports using PEP 562 `__getattr__` pattern (matching WhatsApp/Slack init pattern)
- `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py` — `MSAgentSDKConfig` dataclass following `WhatsAppAgentConfig` pattern with `__post_init__` env var fallback and `from_dict()` classmethod

Modified:
- `packages/ai-parrot-integrations/pyproject.toml` — added `msagentsdk = ["microsoft-agents-hosting-aiohttp~=0.9.0"]` extras group

All acceptance criteria met. Lint passes (`ruff check`). No breaking changes to existing integrations.
