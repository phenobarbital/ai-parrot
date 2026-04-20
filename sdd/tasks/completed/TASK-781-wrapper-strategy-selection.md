# TASK-781: Wrapper Strategy Selection Refactor

**Feature**: FEAT-109 — Telegram Multi-Auth Negotiation
**Spec**: `sdd/specs/FEAT-109-telegram-multi-auth-negotiation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-779, TASK-780
**Assigned-to**: unassigned

---

## Context

Today strategy selection is an inline `if/elif` chain at
`wrapper.py:103-119`. With `auth_methods` now a list and a
`CompositeAuthStrategy` available, the selection logic fans out:
0 methods → no auth, 1 method → single strategy, 2+ methods →
Composite. Extract to a helper and route accordingly.

Implements **Module 5** of the spec.

---

## Scope

- Extract `wrapper.py:103-119` into
  `_build_auth_strategy(self, config) -> Optional[AbstractAuthStrategy]`.
- Logic:
  - `len(config.auth_methods) == 0` → return `None` (auth disabled).
  - `len(config.auth_methods) == 1`:
    - `"basic"` → `BasicAuthStrategy(config.auth_url, config.login_page_url)`
    - `"azure"` → `AzureAuthStrategy(auth_url, azure_auth_url,
      login_page_url)` — if TASK-778 chose Approach A, pass the
      `post_auth_registry` too.
    - `"oauth2"` → `OAuth2AuthStrategy(config)`.
  - `len(config.auth_methods) >= 2`:
    - Build each member strategy individually (reuse the
      single-method construction helpers).
    - Wrap in `CompositeAuthStrategy(strategies={…}, login_page_url=
      config.login_page_url)`.
- Post_auth registry injection: whatever wiring TASK-778 chose,
  follow it consistently. If Approach A, the registry is built
  BEFORE `_build_auth_strategy` runs (already happens — see
  `wrapper.py:339-401`).
- Keep all existing single-method behavior byte-for-byte identical
  (regression-critical).

**NOT in scope**:
- Capability-based post_auth gating — TASK-782.
- `login_multi.html` validation — TASK-784.
- `auth_methods` config field — TASK-780 already added it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Extract strategy selection to helper; route to Composite when >= 2 methods |
| `packages/ai-parrot/tests/integrations/telegram/test_wrapper_strategy_selection.py` | CREATE | Tests for all selection branches |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py — already imports:
from .auth import (
    AbstractAuthStrategy,
    AzureAuthStrategy,
    BasicAuthStrategy,
    OAuth2AuthStrategy,
    TelegramUserSession,
)
# MUST ADD: CompositeAuthStrategy (introduced by TASK-779).
from .auth import CompositeAuthStrategy
```

### Existing Signatures to Use

```python
# wrapper.py:103-119 (today — to be extracted):
self._auth_strategy = None
if config.auth_method == "azure" and config.azure_auth_url:
    self._auth_strategy = AzureAuthStrategy(
        auth_url=config.auth_url or config.azure_auth_url,
        azure_auth_url=config.azure_auth_url,
        login_page_url=config.login_page_url,
    )
elif config.auth_method == "oauth2" and config.oauth2_client_id:
    self._auth_strategy = OAuth2AuthStrategy(config)
elif config.auth_url:
    self._auth_strategy = BasicAuthStrategy(
        config.auth_url, config.login_page_url
    )
```

### Does NOT Exist

- ~~`_build_auth_strategy(config)` helper~~ — introduced here.
- ~~`config.auth_methods` — introduced by TASK-780.
- ~~Composite referenced in wrapper — introduced here.

---

## Implementation Notes

### Helper

```python
def _build_auth_strategy(self, config) -> Optional[AbstractAuthStrategy]:
    methods = getattr(config, "auth_methods", []) or []
    if not methods:
        return None
    if len(methods) == 1:
        return self._build_single_strategy(methods[0], config)
    strategies = {m: self._build_single_strategy(m, config) for m in methods}
    strategies = {k: v for k, v in strategies.items() if v is not None}
    if not strategies:
        return None
    return CompositeAuthStrategy(
        strategies=strategies,
        login_page_url=config.login_page_url,
    )


def _build_single_strategy(self, method, config) -> Optional[AbstractAuthStrategy]:
    if method == "basic" and config.auth_url:
        return BasicAuthStrategy(config.auth_url, config.login_page_url)
    if method == "azure" and config.azure_auth_url:
        return AzureAuthStrategy(
            auth_url=config.auth_url or config.azure_auth_url,
            azure_auth_url=config.azure_auth_url,
            login_page_url=config.login_page_url,
            # If TASK-778 Approach A: add post_auth_registry=self._post_auth_registry
        )
    if method == "oauth2" and config.oauth2_client_id:
        return OAuth2AuthStrategy(config)
    self.logger.warning(
        "Agent '%s': auth_method '%s' listed but required config missing; skipping.",
        getattr(config, "name", "?"), method,
    )
    return None
```

### Usage site

Replace lines 103-119 with:
```python
self._auth_strategy = self._build_auth_strategy(config)
```

### Back-compat check

For YAML with only `auth_method: azure` and no `auth_methods`:
TASK-780's `__post_init__` normalizes to `auth_methods = ["azure"]`,
so `_build_auth_strategy` picks up the single-method branch and the
resulting strategy is byte-for-byte identical to today.

---

## Acceptance Criteria

- [ ] Selection logic fully extracted from `__init__`; `__init__`
      just calls `_build_auth_strategy(config)`.
- [ ] `auth_methods: ["basic"]` → `BasicAuthStrategy`.
- [ ] `auth_methods: ["azure"]` → `AzureAuthStrategy`.
- [ ] `auth_methods: ["oauth2"]` → `OAuth2AuthStrategy`.
- [ ] `auth_methods: ["basic", "azure"]` →
      `CompositeAuthStrategy` with both members.
- [ ] Legacy YAML (`auth_method: basic`, no `auth_methods`) still
      builds BasicAuthStrategy identically.
- [ ] Missing required config for a listed method skips it with a
      logged warning — does NOT raise.
- [ ] All existing Telegram wrapper tests pass.

---

## Test Specification (sketch)

```python
# tests/integrations/telegram/test_wrapper_strategy_selection.py
import pytest
from unittest.mock import MagicMock
from parrot.integrations.telegram.auth import (
    BasicAuthStrategy, AzureAuthStrategy, OAuth2AuthStrategy,
    CompositeAuthStrategy,
)

# Build a wrapper via __new__ + fixture attribute injection to bypass
# heavy __init__; or use a minimal real fixture. Agent decides.


def test_build_single_basic(wrapper_factory):
    wrapper = wrapper_factory(auth_methods=["basic"],
                              auth_url="https://h/api/v1/login")
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)


def test_build_single_azure(wrapper_factory):
    wrapper = wrapper_factory(auth_methods=["azure"],
                              azure_auth_url="https://h/api/v1/auth/azure/")
    assert isinstance(wrapper._auth_strategy, AzureAuthStrategy)


def test_build_composite(wrapper_factory):
    wrapper = wrapper_factory(
        auth_methods=["basic", "azure"],
        auth_url="https://h/api/v1/login",
        azure_auth_url="https://h/api/v1/auth/azure/",
    )
    assert isinstance(wrapper._auth_strategy, CompositeAuthStrategy)
    assert set(wrapper._auth_strategy.strategies.keys()) == {"basic", "azure"}


def test_empty_methods_yields_none(wrapper_factory):
    wrapper = wrapper_factory(auth_methods=[])
    assert wrapper._auth_strategy is None


def test_missing_config_for_listed_method_is_skipped(wrapper_factory, caplog):
    wrapper = wrapper_factory(
        auth_methods=["basic", "azure"],
        auth_url="https://h/api/v1/login",
        # no azure_auth_url configured
    )
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)  # azure skipped
    assert "azure" in caplog.text.lower()


def test_legacy_auth_method_basic_still_works(wrapper_factory):
    # Config normalization (TASK-780) promotes auth_method="basic" →
    # auth_methods=["basic"], so this is the same as test_build_single_basic,
    # but exercised through the full path.
    wrapper = wrapper_factory(auth_method="basic",
                              auth_url="https://h/api/v1/login")
    assert isinstance(wrapper._auth_strategy, BasicAuthStrategy)
```

---

## Agent Instructions

1. Read the spec + TASK-779 completion (Composite constructor
   signature).
2. Grep `wrapper.py:103` to confirm line numbers (they may shift).
3. Implement the extraction + Composite routing.
4. Run all telegram tests — regressions here are high-blast-radius.
5. Commit.

---

## Completion Note

*(Agent fills this in when done)*
