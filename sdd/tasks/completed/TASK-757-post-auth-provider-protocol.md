# TASK-757: PostAuthProvider Protocol & Registry

**Feature**: FEAT-108 — Jira OAuth2 3LO Authentication from Telegram WebApp
**Spec**: `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-756
**Assigned-to**: unassigned

---

## Context

This task creates the generic framework for secondary authentication providers.
The `PostAuthProvider` protocol defines the interface that any provider (Jira,
Confluence, GitHub, etc.) must implement, and the `PostAuthRegistry` manages
provider instances keyed by name. The wrapper will use this registry to look up
and invoke the appropriate provider based on the `post_auth_actions` config.

Implements Spec Module 2.

---

## Scope

- Create a new module `parrot/integrations/telegram/post_auth.py`.
- Define `PostAuthProvider` as a `typing.Protocol` (or ABC) with:
  - `provider_name: str` class attribute
  - `async def build_auth_url(session, config, callback_base_url) -> str`
  - `async def handle_result(data, session, primary_auth_data) -> bool`
- Define `PostAuthRegistry` class with:
  - `register(provider: PostAuthProvider) -> None`
  - `get(name: str) -> Optional[PostAuthProvider]`
  - `providers` property returning registered names
- Write unit tests for the registry (register, get, unknown provider).

**NOT in scope**: Jira-specific provider implementation (TASK-758), wrapper
integration (TASK-763), or any actual auth flow logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/post_auth.py` | CREATE | Protocol + Registry |
| `packages/ai-parrot/tests/unit/test_post_auth_registry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.auth import TelegramUserSession  # auth.py:36
from parrot.integrations.telegram.models import TelegramAgentConfig  # models.py:13
from parrot.integrations.telegram.models import PostAuthAction  # created by TASK-756
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/integrations/telegram/auth.py
class TelegramUserSession:  # @dataclass, line 36
    telegram_id: int                  # line 39
    nav_user_id: Optional[str]        # line 44
    authenticated: bool               # line 48
    def set_authenticated(self, nav_user_id: str, session_token: str,
                          display_name: Optional[str] = None,
                          email: Optional[str] = None,
                          **extra_meta) -> None: ...  # line 84

# packages/ai-parrot/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:            # line 13
    post_auth_actions: List[PostAuthAction]  # CREATED BY TASK-756
```

### Does NOT Exist
- ~~`parrot.integrations.telegram.post_auth`~~ — module does not exist yet (this task creates it)
- ~~`PostAuthProvider`~~ — does not exist yet (this task creates it)
- ~~`PostAuthRegistry`~~ — does not exist yet (this task creates it)

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Protocol, runtime_checkable, Optional, Dict, Any

@runtime_checkable
class PostAuthProvider(Protocol):
    """Protocol for secondary auth providers chained after primary auth."""
    provider_name: str

    async def build_auth_url(
        self,
        session: TelegramUserSession,
        config: TelegramAgentConfig,
        callback_base_url: str,
    ) -> str: ...

    async def handle_result(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
        primary_auth_data: Dict[str, Any],
    ) -> bool: ...


class PostAuthRegistry:
    """Registry of secondary auth providers, keyed by provider name."""

    def __init__(self) -> None:
        self._providers: Dict[str, PostAuthProvider] = {}

    def register(self, provider: PostAuthProvider) -> None:
        self._providers[provider.provider_name] = provider

    def get(self, name: str) -> Optional[PostAuthProvider]:
        return self._providers.get(name)

    @property
    def providers(self) -> list[str]:
        return list(self._providers.keys())
```

### Key Constraints
- Use `typing.Protocol` with `@runtime_checkable` for duck typing
- The registry is a simple dict-based lookup — no framework magic
- Must be importable standalone without pulling in heavy deps

### References in Codebase
- `packages/ai-parrot/src/parrot/integrations/telegram/auth.py:177` — `AbstractAuthStrategy` as a pattern for abstract interfaces
- `packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py:232` — `CallbackRegistry` as a pattern for registries

---

## Acceptance Criteria

- [ ] `PostAuthProvider` protocol defined with `provider_name`, `build_auth_url`, `handle_result`
- [ ] `PostAuthRegistry` with `register()`, `get()`, `providers` property
- [ ] Module importable: `from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_post_auth_registry.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_post_auth_registry.py
import pytest
from parrot.integrations.telegram.post_auth import PostAuthProvider, PostAuthRegistry


class FakeProvider:
    provider_name = "fake"
    async def build_auth_url(self, session, config, callback_base_url):
        return "https://fake.example.com/auth"
    async def handle_result(self, data, session, primary_auth_data):
        return True


class TestPostAuthRegistry:
    def test_register_and_get(self):
        registry = PostAuthRegistry()
        provider = FakeProvider()
        registry.register(provider)
        assert registry.get("fake") is provider

    def test_get_unknown_returns_none(self):
        registry = PostAuthRegistry()
        assert registry.get("nonexistent") is None

    def test_providers_property(self):
        registry = PostAuthRegistry()
        registry.register(FakeProvider())
        assert "fake" in registry.providers

    def test_protocol_check(self):
        provider = FakeProvider()
        assert isinstance(provider, PostAuthProvider)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-108-jiratoolkit-auth-telegram.spec.md`
2. **Check dependencies** — verify TASK-756 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `TelegramUserSession` and `TelegramAgentConfig` still match
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** the protocol and registry
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-19
**Notes**:

- Created `packages/ai-parrot/src/parrot/integrations/telegram/post_auth.py`
  with `PostAuthProvider` (`@runtime_checkable` Protocol) and
  `PostAuthRegistry` classes.
- Added helpful extras beyond the bare spec: `__contains__`, `__len__`,
  overwrite warning on re-registration, and empty-name guard in `register()`.
- Created `packages/ai-parrot/tests/unit/test_post_auth_registry.py` with
  10 tests; all pass.
- Type-checking at runtime works because `PostAuthProvider` is declared with
  `@runtime_checkable` — `isinstance(provider, PostAuthProvider)` returns
  True for compliant classes.

**Deviations from spec**: none — added small ergonomic extras that do not
violate the interface contract.
