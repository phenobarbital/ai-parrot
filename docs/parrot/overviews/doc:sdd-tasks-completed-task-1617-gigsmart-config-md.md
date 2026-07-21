---
type: Wiki Overview
title: 'TASK-1617: GigSmart Configuration'
id: doc:sdd-tasks-completed-task-1617-gigsmart-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration module for the GigSmart client. Loads OAuth credentials and
  API
relates_to:
- concept: mod:parrot_tools.interfaces.gigsmart.config
  rel: mentions
- concept: mod:parrot_tools.interfaces.gigsmart.exceptions
  rel: mentions
---

# TASK-1617: GigSmart Configuration

**Feature**: FEAT-253 — GigSmart Interface Toolkit
**Spec**: `sdd/specs/gigsmart-interface-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1616
**Assigned-to**: unassigned

---

## Context

Configuration module for the GigSmart client. Loads OAuth credentials and API
settings from environment variables. Implements Spec Module 2.

---

## Scope

- Implement `GigSmartConfig` dataclass/model for client configuration
- Load credentials from env vars (`GIGSMART_CLIENT_ID`, `GIGSMART_CLIENT_SECRET`, etc.)
- Support production and sandbox environments
- Write unit tests

**NOT in scope**: OAuth token exchange (TASK-1618), HTTP client setup (TASK-1621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/gigsmart/config.py` | CREATE | Configuration model |
| `tests/tools/gigsmart/test_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartError  # from TASK-1616
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
# REFERENCE PATTERN — WorkdayConfig uses similar env-based loading
# Uses os.getenv() pattern, NOT pydantic BaseSettings
```

### Does NOT Exist
- ~~`pydantic.BaseSettings`~~ — not used in this codebase for tool configs; use `os.getenv()` + dataclass or BaseModel
- ~~`SecretStr`~~ — not used anywhere in parrot_tools; use plain strings loaded from env
- ~~`GigSmartCredentials`~~ — from brainstorm SPEC; the correct class name is `GigSmartConfig`

---

## Implementation Notes

### Config Fields
```python
@dataclass
class GigSmartConfig:
    client_id: str                   # GIGSMART_CLIENT_ID
    client_secret: str               # GIGSMART_CLIENT_SECRET
    environment: str = "production"  # GIGSMART_ENV — "production" or "sandbox"
    endpoint_url: str = "https://api.gigsmart.com/graphql"
    token_url: str = "https://api.gigsmart.com/oauth/token"
    authorize_url: str = "https://api.gigsmart.com/oauth/authorize"
    request_timeout: float = 30.0
    max_concurrent_requests: int = 8
    log_pii: bool = False            # GIGSMART_LOG_PII

    @classmethod
    def from_env(cls) -> "GigSmartConfig": ...
```

- Sandbox endpoint likely at a different URL — make configurable
- `GIGSMART_ENDPOINT_URL` overrides the default if set
- Raise `GigSmartError` if `client_id` or `client_secret` is missing

---

## Acceptance Criteria

- [ ] `GigSmartConfig.from_env()` loads from environment variables
- [ ] Missing required credentials raises `GigSmartError`
- [ ] Default endpoint is `https://api.gigsmart.com/graphql`
- [ ] `environment` defaults to `"production"`
- [ ] Tests pass: `pytest tests/tools/gigsmart/test_config.py -v`

---

## Test Specification

```python
import os
import pytest
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig

class TestGigSmartConfig:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "test-id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "test-secret")
        config = GigSmartConfig.from_env()
        assert config.client_id == "test-id"
        assert config.client_secret == "test-secret"
        assert config.environment == "production"

    def test_missing_client_id_raises(self, monkeypatch):
        monkeypatch.delenv("GIGSMART_CLIENT_ID", raising=False)
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        with pytest.raises(Exception):
            GigSmartConfig.from_env()

    def test_sandbox_environment(self, monkeypatch):
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GIGSMART_ENV", "sandbox")
        config = GigSmartConfig.from_env()
        assert config.environment == "sandbox"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1616 is in `tasks/completed/`
3. **Verify the Codebase Contract**
4. **Implement** following scope and notes
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
