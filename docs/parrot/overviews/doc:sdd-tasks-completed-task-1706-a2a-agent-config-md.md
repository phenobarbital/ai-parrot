---
type: Wiki Overview
title: 'TASK-1706: A2A Agent Config Dataclass'
id: doc:sdd-tasks-completed-task-1706-a2a-agent-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task creates the `A2AAgentConfig` dataclass that models the YAML configuration
  for `kind: a2a` entries in `integrations_bots.yaml`. This is the foundation for
  the A2A integration — all subsequent A2A tasks depend on this config model.'
relates_to:
- concept: mod:parrot.integrations.a2a
  rel: mentions
- concept: mod:parrot.integrations.a2a.models
  rel: mentions
---

# TASK-1706: A2A Agent Config Dataclass

**Feature**: FEAT-271 — MSAgent & A2A YAML Integrations
**Spec**: `sdd/specs/msagent-a2a-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the `A2AAgentConfig` dataclass that models the YAML configuration for `kind: a2a` entries in `integrations_bots.yaml`. This is the foundation for the A2A integration — all subsequent A2A tasks depend on this config model.

Implements spec §3 Module 1 and the `A2AAgentConfig` data model from §2.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/a2a/__init__.py` (package init).
- Create `packages/ai-parrot-integrations/src/parrot/integrations/a2a/models.py` with `A2AAgentConfig` dataclass.
- Implement `from_dict(name, data)` classmethod for YAML parsing.
- Implement `__post_init__()` for environment variable fallback (same pattern as `MSAgentSDKConfig.__post_init__`).
- Support all fields: `name`, `chatbot_id`, `kind`, `url`, `base_path`, `port`, `tags`, `welcome_message`, `system_prompt_override`, `jwt_secret`, `api_key`, `api_key_header`, `mtls_ca_cert`, `hmac_secret`, `basic_credentials`, `security_policy`, `enable_credential_broker`, `credentials`.

**NOT in scope**: Wiring into `IntegrationBotConfig.from_dict()` (TASK-1708), startup logic (TASK-1710).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/a2a/__init__.py` | CREATE | Package init with lazy exports |
| `packages/ai-parrot-integrations/src/parrot/integrations/a2a/models.py` | CREATE | `A2AAgentConfig` dataclass |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field          # stdlib
from typing import Dict, List, Any, Optional      # stdlib
from navconfig import config                      # verified: used by MSAgentSDKConfig for env var fallback
```

### Existing Signatures to Use
```python
# Pattern to follow: packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/models.py:11
@dataclass
class MSAgentSDKConfig:
    name: str                                # line 67
    chatbot_id: str                          # line 68
    kind: str = "msagentsdk"                 # line 77
    # ... (other fields)

    def __post_init__(self) -> None:         # line 84
        prefix = self.name.upper()
        if not self.client_id:
            self.client_id = config.get(f"{prefix}_MICROSOFT_APP_ID")
        # ... env var fallback pattern

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":  # line 132
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            # ... extract all fields from data dict
        )
```

### Does NOT Exist
- ~~`parrot.integrations.a2a`~~ — package does not exist yet; this task creates it
- ~~`A2AAgentConfig`~~ — does not exist yet; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the MSAgentSDKConfig pattern exactly:
@dataclass
class A2AAgentConfig:
    name: str
    chatbot_id: str
    kind: str = "a2a"
    # ... all fields with defaults

    def __post_init__(self) -> None:
        prefix = self.name.upper()
        if not self.jwt_secret:
            self.jwt_secret = config.get(f"{prefix}_JWT_SECRET")
        if not self.api_key:
            self.api_key = config.get(f"{prefix}_API_KEY")
        # ... other env var fallbacks

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "A2AAgentConfig":
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            url=data.get("url"),
            # ... extract from data dict
        )
```

### Key Constraints
- Use `@dataclass`, NOT Pydantic (matching existing config pattern).
- Use `field(default_factory=list)` for list/dict defaults.
- Use `navconfig.config.get()` for env var fallback in `__post_init__`.
- The `credentials` field is `List[Dict[str, Any]]` — raw dicts from YAML, not `ProviderCredentialConfig` (conversion happens at startup time).

---

## Acceptance Criteria

- [ ] `A2AAgentConfig` dataclass created with all fields from spec §2
- [ ] `from_dict()` correctly parses a YAML-like dict
- [ ] `__post_init__()` falls back to env vars for `jwt_secret`, `api_key`, `hmac_secret`
- [ ] `credentials` field accepts a list of raw dicts
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/a2a/`
- [ ] Import works: `from parrot.integrations.a2a.models import A2AAgentConfig`

---

## Test Specification

```python
# tests/integrations/test_a2a_config.py
import pytest
from parrot.integrations.a2a.models import A2AAgentConfig


class TestA2AAgentConfig:
    def test_from_dict_minimal(self):
        data = {"chatbot_id": "test_agent", "kind": "a2a"}
        cfg = A2AAgentConfig.from_dict("TestAgent", data)
        assert cfg.name == "TestAgent"
        assert cfg.chatbot_id == "test_agent"
        assert cfg.kind == "a2a"
        assert cfg.base_path == "/a2a"
        assert cfg.port is None

    def test_from_dict_full(self):
        data = {
            "chatbot_id": "jirachi",
            "kind": "a2a",
            "url": "https://example.com",
            "port": 8181,
            "tags": ["general"],
            "jwt_secret": "secret",
            "enable_credential_broker": True,
            "credentials": [{"provider": "fireflies", "auth": "static_key"}],
        }
        cfg = A2AAgentConfig.from_dict("Jirachi", data)
        assert cfg.port == 8181
        assert cfg.jwt_secret == "secret"
        assert len(cfg.credentials) == 1

    def test_defaults(self):
        cfg = A2AAgentConfig(name="Test", chatbot_id="test")
        assert cfg.kind == "a2a"
        assert cfg.base_path == "/a2a"
        assert cfg.enable_credential_broker is False
        assert cfg.credentials == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `MSAgentSDKConfig` pattern is still at the listed location
4. **Create the `a2a/` package** under `packages/ai-parrot-integrations/src/parrot/integrations/`
5. **Implement** following the scope and pattern above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1706-a2a-agent-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude)
**Date**: 2026-07-09
**Notes**: Created `packages/ai-parrot-integrations/src/parrot/integrations/a2a/__init__.py` and `models.py` with `A2AAgentConfig` dataclass, following the `MSAgentSDKConfig` pattern exactly (dataclass, `from_dict()`, `__post_init__()` env var fallback). The `__init__.py` uses the same lazy PEP-562 re-export pattern as `msagentsdk/__init__.py` since future A2A submodules (server wiring, added in TASK-1709) will depend on the optional `ai-parrot-server` package — importing `parrot.integrations.a2a.models` directly never touches that dependency. Verified import, `from_dict()`, and defaults against the task's test scaffold (all 3 cases pass) using `PYTHONPATH` pointing at the worktree's package `src/` dirs (the shared venv's editable install still points at the main repo's absolute paths, so this was necessary purely for ad-hoc verification in the worktree — no test files were created here since `tests/integrations/test_a2a_config.py` is explicitly scoped to TASK-1711). `ruff check` passes clean.

**Deviations from spec**: none
