---
type: Wiki Overview
title: 'TASK-983: OAuth2 Integration Models and Provider Registry'
id: doc:sdd-tasks-completed-task-983-oauth2-models-and-registry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for FEAT-144. It creates the new
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-983: OAuth2 Integration Models and Provider Registry

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-144. It creates the new
`parrot/integrations/oauth2/` package with all Pydantic wire models and the
`OAuth2ProviderRegistry` singleton. Every subsequent task in this feature
imports from the modules created here.

Implements spec Modules 1 and 2.

---

## Scope

- Create the `parrot/integrations/oauth2/` package with `__init__.py` and
  `models.py`.
- Implement all Pydantic models: `IntegrationDescriptor`, `ConnectInitRequest`,
  `ConnectInitResponse`, `EnableResponse`, `DisconnectResponse`,
  `AuthRequiredEnvelope`, `UsersIntegrationRow`, `UserAgentToolkitRow`.
- Define the `_WEB_CHANNEL = "web"` constant in `__init__.py`.
- Create `registry.py` with `OAuth2Provider` ABC, `OAuth2ProviderRegistry`
  (in-memory singleton), and `register_oauth2_provider()` helper.
- Write unit tests for all models (validation, defaults, serialisation) and
  registry operations (register, get, all, overwrite).

**NOT in scope**: JiraOAuth2Provider (TASK-984), persistence (TASK-984),
service layer (TASK-985), handlers (TASK-986).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/oauth2/__init__.py` | CREATE | Package init, `_WEB_CHANNEL` constant, public re-exports |
| `packages/ai-parrot/src/parrot/integrations/oauth2/models.py` | CREATE | All Pydantic models from spec §2 Data Models |
| `packages/ai-parrot/src/parrot/integrations/oauth2/registry.py` | CREATE | `OAuth2Provider` ABC + `OAuth2ProviderRegistry` singleton |
| `tests/unit/integrations/oauth2/__init__.py` | CREATE | Test package init |
| `tests/unit/integrations/oauth2/test_models.py` | CREATE | Model validation tests |
| `tests/unit/integrations/oauth2/test_registry.py` | CREATE | Registry operation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# pydantic v2 — already a core dep
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime
from abc import ABC, abstractmethod

# Channel constant mirrors:
# parrot/integrations/telegram/jira_commands.py:39
_TELEGRAM_CHANNEL = "telegram"   # existing, DO NOT modify
# New constant in this task:
_WEB_CHANNEL = "web"
```

### Existing Signatures to Use
```python
# parrot/auth/credentials.py:27
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...

# parrot/tools/__init__.py — AbstractToolkit is used as return type hint
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:630
class JiraToolkit(AbstractToolkit): ...
```

### Does NOT Exist
- ~~`parrot.integrations.oauth2`~~ — does not exist yet; this task creates it.
- ~~`AbstractOAuthIntegration`~~ — does not exist; `OAuth2Provider` is the new ABC.
- ~~`IntegrationModel` or `IntegrationBase`~~ — no such base class; use plain Pydantic `BaseModel`.
- ~~`parrot.integrations.base`~~ — no base module for integrations; create the package from scratch.

---

## Implementation Notes

### Pattern to Follow
```python
# OAuth2Provider ABC (registry.py)
class OAuth2Provider(ABC):
    provider_id: str                        # e.g. "jira"
    display_name: str                       # e.g. "Jira"
    icon: Optional[str]                     # e.g. "mdi:jira"
    default_scopes: List[str]
    pbac_action_namespace: str              # e.g. "integration"

    @property
    @abstractmethod
    def manager(self) -> Any:
        """Return the underlying OAuth manager (e.g. JiraOAuthManager)."""

    @abstractmethod
    def toolkit_factory(
        self, credential_resolver: "CredentialResolver"
    ) -> "AbstractToolkit":
        """Build a fresh toolkit instance bound to the resolver."""


# OAuth2ProviderRegistry — simple in-memory singleton
class OAuth2ProviderRegistry:
    _instance: ClassVar[Optional["OAuth2ProviderRegistry"]] = None
    _providers: Dict[str, OAuth2Provider]

    def __new__(cls) -> "OAuth2ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
        return cls._instance

    def register(self, provider: OAuth2Provider) -> None: ...
    def get(self, provider_id: str) -> Optional[OAuth2Provider]: ...
    def all(self) -> List[OAuth2Provider]: ...


def register_oauth2_provider(provider: OAuth2Provider) -> None:
    """Module-level convenience."""
    OAuth2ProviderRegistry().register(provider)
```

### Key Constraints
- All models use Pydantic v2 (`BaseModel`).
- `AuthorizationRequired.provider` defaults to `"unknown"` (exceptions.py:39) — the `AuthRequiredEnvelope.provider` field has no default (required).
- `AuthRequiredEnvelope.type` is `Literal["auth_required"]` with default `"auth_required"`.
- `UsersIntegrationRow.status` is `Literal["active", "revoked"]` with default `"active"`.
- Registry singleton must be resettable in tests (add a `_reset()` classmethod or similar).
- `__init__.py` should re-export: `OAuth2Provider`, `OAuth2ProviderRegistry`, `register_oauth2_provider`, `_WEB_CHANNEL`, and all model classes.

---

## Acceptance Criteria

- [ ] All Pydantic models instantiate with valid data and reject invalid data.
- [ ] `AuthRequiredEnvelope(provider="jira", message="Need auth").model_dump()` produces `{"type": "auth_required", "provider": "jira", ...}`.
- [ ] `OAuth2ProviderRegistry` is a singleton — two calls to `OAuth2ProviderRegistry()` return the same object.
- [ ] `register()` adds a provider; `get("jira")` retrieves it; `all()` returns all.
- [ ] Duplicate `register()` with same `provider_id` overwrites the previous entry.
- [ ] `get("nonexistent")` returns `None`.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/ -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/integrations/oauth2/`
- [ ] Imports work: `from parrot.integrations.oauth2 import OAuth2ProviderRegistry, AuthRequiredEnvelope`

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_models.py
import pytest
from parrot.integrations.oauth2.models import (
    IntegrationDescriptor,
    ConnectInitRequest,
    ConnectInitResponse,
    AuthRequiredEnvelope,
    UsersIntegrationRow,
    UserAgentToolkitRow,
)


class TestAuthRequiredEnvelope:
    def test_type_field_default(self):
        env = AuthRequiredEnvelope(provider="jira", message="Need auth")
        assert env.type == "auth_required"

    def test_serialization(self):
        env = AuthRequiredEnvelope(
            provider="jira", auth_url="https://auth.atlassian.com/...",
            scopes=["read:jira-work"], message="Connect Jira",
        )
        data = env.model_dump()
        assert data["type"] == "auth_required"
        assert data["provider"] == "jira"

    def test_optional_fields(self):
        env = AuthRequiredEnvelope(provider="jira", message="msg")
        assert env.tool_name is None
        assert env.auth_url is None
        assert env.scopes == []


class TestIntegrationDescriptor:
    def test_defaults(self):
        d = IntegrationDescriptor(provider="jira", display_name="Jira")
        assert d.connected is False
        assert d.enabled_on_agent is False


class TestUsersIntegrationRow:
    def test_status_default(self):
        from datetime import datetime
        row = UsersIntegrationRow(
            user_id="u1", provider="jira", account_id="a1",
            display_name="Test", scopes=["read:jira-work"],
            connected_at=datetime.now(),
        )
        assert row.status == "active"
        assert row.channel == "web"


# tests/unit/integrations/oauth2/test_registry.py
import pytest
from parrot.integrations.oauth2.registry import (
    OAuth2Provider, OAuth2ProviderRegistry,
)


class FakeProvider(OAuth2Provider):
    provider_id = "fake"
    display_name = "Fake"
    icon = None
    default_scopes = []
    pbac_action_namespace = "integration"

    @property
    def manager(self):
        return None

    def toolkit_factory(self, credential_resolver):
        return None


class TestOAuth2ProviderRegistry:
    @pytest.fixture(autouse=True)
    def reset_registry(self):
        OAuth2ProviderRegistry._reset()
        yield
        OAuth2ProviderRegistry._reset()

    def test_singleton(self):
        r1 = OAuth2ProviderRegistry()
        r2 = OAuth2ProviderRegistry()
        assert r1 is r2

    def test_register_and_get(self):
        reg = OAuth2ProviderRegistry()
        provider = FakeProvider()
        reg.register(provider)
        assert reg.get("fake") is provider

    def test_get_nonexistent_returns_none(self):
        reg = OAuth2ProviderRegistry()
        assert reg.get("nonexistent") is None

    def test_duplicate_register_overwrites(self):
        reg = OAuth2ProviderRegistry()
        p1 = FakeProvider()
        p2 = FakeProvider()
        reg.register(p1)
        reg.register(p2)
        assert reg.get("fake") is p2

    def test_all_returns_all_providers(self):
        reg = OAuth2ProviderRegistry()
        reg.register(FakeProvider())
        assert len(reg.all()) == 1
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md` §2-3 (Data Models, Modules 1-2)
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm imports and "Does NOT Exist" items
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the models, registry, and tests
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-983-oauth2-models-and-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Implemented parrot/integrations/oauth2/__init__.py (with _WEB_CHANNEL constant and re-exports), models.py (8 Pydantic v2 models), and registry.py (OAuth2Provider ABC + OAuth2ProviderRegistry singleton with _reset() for tests). All 26 unit tests pass.

**Deviations from spec**: none
