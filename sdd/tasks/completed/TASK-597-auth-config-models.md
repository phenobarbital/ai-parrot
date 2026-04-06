# TASK-597: AuthConfig Models

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-086. It introduces the `AuthConfig` discriminated union model that `SubmitAction` will use (TASK-598) and `SubmissionForwarder` will resolve (TASK-600). Without this, no other task can reference auth configuration.

Implements Spec Module 1.

---

## Scope

- Create `core/auth.py` with the following Pydantic models:
  - `NoAuth` — `type: Literal["none"]`, `resolve()` returns empty dict
  - `BearerAuth` — `type: Literal["bearer"]`, `token_env: str`, `resolve()` returns `{"Authorization": "Bearer <token>"}`
  - `ApiKeyAuth` — `type: Literal["api_key"]`, `key_env: str`, `header_name: str = "X-API-Key"`, `resolve()` returns `{header_name: <key>}`
  - `AuthConfig = NoAuth | BearerAuth | ApiKeyAuth` type alias
- Each auth model's `resolve()` method:
  1. Tries `from navconfig import config; config.get(env_var)`
  2. Falls back to `os.environ.get(env_var)` if navconfig not available
  3. Raises `ValueError` if the env var is not found
- Export from `core/__init__.py`

**NOT in scope**: Modifying `SubmitAction`, creating forwarder, creating tests (TASK-605)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/auth.py` | CREATE | AuthConfig models with resolve() |
| `packages/parrot-formdesigner/src/parrot/formdesigner/core/__init__.py` | MODIFY | Export new auth types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field  # used throughout core/
from typing import Literal, Any  # used throughout core/
import os  # stdlib fallback for env vars
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:19
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")  # line 43 — follow this pattern
```

### Does NOT Exist
- ~~`parrot.formdesigner.core.auth`~~ — module does not exist yet; this task creates it
- ~~`AuthConfig`~~ — does not exist yet; this task creates it
- ~~`BearerAuth`~~ — does not exist yet
- ~~`ApiKeyAuth`~~ — does not exist yet
- ~~`NoAuth`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same Pydantic model style as core/schema.py and core/constraints.py
class BearerAuth(BaseModel):
    """Bearer token authentication resolved from environment."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer"] = "bearer"
    token_env: str = Field(..., description="Environment variable name for the Bearer token")

    def resolve(self) -> dict[str, str]:
        """Resolve auth credentials to HTTP headers."""
        token = _get_env(self.token_env)
        return {"Authorization": f"Bearer {token}"}
```

### Key Constraints
- Use `ConfigDict(extra="forbid")` on all models (consistent with `FormField`)
- `resolve()` is a sync method (env lookup is not I/O)
- Handle `navconfig` ImportError gracefully — fall back to `os.environ.get()`
- Raise `ValueError` with a clear message when env var is missing
- Add module docstring explaining purpose

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` — Pydantic model pattern
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/constraints.py` — model with validation pattern
- `app.py:2` — `from navconfig import config` usage example

---

## Acceptance Criteria

- [ ] `core/auth.py` created with `NoAuth`, `BearerAuth`, `ApiKeyAuth`, `AuthConfig`
- [ ] Each model has a `resolve() -> dict[str, str]` method
- [ ] `navconfig` import failure falls back to `os.environ.get()`
- [ ] `ValueError` raised when env var is missing
- [ ] Models exported from `core/__init__.py`
- [ ] `from parrot.formdesigner.core.auth import AuthConfig, BearerAuth, ApiKeyAuth, NoAuth` works

---

## Test Specification

```python
# tests/test_auth_config.py
import os
import pytest
from parrot.formdesigner.core.auth import (
    AuthConfig, NoAuth, BearerAuth, ApiKeyAuth,
)


class TestNoAuth:
    def test_resolve_returns_empty(self):
        auth = NoAuth()
        assert auth.resolve() == {}

    def test_type_is_none(self):
        auth = NoAuth()
        assert auth.type == "none"


class TestBearerAuth:
    def test_resolve_with_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_TOKEN", "abc123")
        auth = BearerAuth(token_env="TEST_TOKEN")
        headers = auth.resolve()
        assert headers == {"Authorization": "Bearer abc123"}

    def test_resolve_missing_env_var(self):
        auth = BearerAuth(token_env="NONEXISTENT_VAR_12345")
        with pytest.raises(ValueError, match="NONEXISTENT_VAR_12345"):
            auth.resolve()


class TestApiKeyAuth:
    def test_resolve_with_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "key123")
        auth = ApiKeyAuth(key_env="TEST_API_KEY")
        headers = auth.resolve()
        assert headers == {"X-API-Key": "key123"}

    def test_custom_header_name(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "key123")
        auth = ApiKeyAuth(key_env="TEST_API_KEY", header_name="X-Custom")
        headers = auth.resolve()
        assert headers == {"X-Custom": "key123"}

    def test_resolve_missing_env_var(self):
        auth = ApiKeyAuth(key_env="NONEXISTENT_VAR_12345")
        with pytest.raises(ValueError):
            auth.resolve()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — read `core/__init__.py` to see current exports before modifying
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_auth_config.py -v`
7. **Move this file** to `tasks/completed/TASK-597-auth-config-models.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
