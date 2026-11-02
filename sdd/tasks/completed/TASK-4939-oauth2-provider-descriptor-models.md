# TASK-4939: OAuth2 provider descriptor models, hook registry and loader

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Providers", §3 Module 3 (G3, S10). New providers become data: a typed Pydantic
`OAuth2ProviderDescriptor` with endpoints, scopes, PKCE and a `RefreshPolicy`. Provider-specific post-exchange
logic stays code, registered by **name** in a typed `PostExchangeHookRegistry` — YAML never carries import paths.
This task creates the data layer only; the generic manager that consumes it is TASK-4943.

---

## Scope

- Create `parrot/auth/oauth2/descriptor.py` with `RefreshPolicy`, `IdentityProbe`, `OAuth2ProviderDescriptor`
  (fields exactly as spec §2), `PostExchangeHook` type alias, `PostExchangeHookRegistry` (register/get; unknown
  name → `KeyError`; module-level default instance `post_exchange_hooks`), and `load_provider_descriptors(source)`
  accepting a YAML path (str/Path) or a sequence of mappings; validation errors raise `ValueError` naming the provider.
- Descriptors never carry `client_id`/`client_secret`/`redirect_uri` (forbid extra keys for those names).
- Unit tests `test_descriptor_validation_and_secrets_from_conf` (validation half) and `test_post_exchange_hook_registry_is_typed`.

**NOT in scope**: `StandardOAuth2Manager`, `DescriptorOAuth2Provider`, `register_descriptor_providers` (TASK-4943); conf keys (TASK-4941).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` | CREATE | descriptor models, hook registry, loader |
| `packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from pydantic import BaseModel, Field, ValidationError, model_validator   # pydantic v2
import yaml                                                                # PyYAML (existing dep, spec §7)
```

### Existing Signatures to Use
```python
# Spec §2 Data Models (normative) — RefreshPolicy, IdentityProbe, OAuth2ProviderDescriptor field lists.
# packages/ai-parrot/src/parrot/auth/oauth2_base.py:61
class AbstractOAuth2TokenSet(BaseModel): access_token, refresh_token, expires_at, scopes, granted_at,
    last_refreshed_at, account_id, display_name, email   # referenced only in the PostExchangeHook type alias
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.descriptor`~~ — created by this task.
- ~~descriptor `post_exchange` as an import path / `importlib` loading~~ — forbidden (S10); names only.
- ~~`OAuth2ProviderDescriptor.client_id` / `.client_secret` / `.redirect_uri`~~ — secrets come from navconfig only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2_base.py#AbstractOAuth2TokenSet"
  ]
}
```

---

## Implementation Notes

- Use `Field(default_factory=...)` for list/dict/model defaults (avoid shared mutable defaults).
- `load_provider_descriptors` reads YAML with `yaml.safe_load`; the file shape is either a list of mappings or
  `{"providers": [...]}` — accept both.
- Reject duplicate `provider_id`s in one load with `ValueError`.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write `descriptor.py` from the block — *why*: the field set is fixed by spec §2.
2. Fill the loader and the secret-key rejection — *why*: S10 + "secrets from navconfig only".
3. Write tests — *why*: spec §4 M3 rows.

### `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (CREATE)
```python
"""Typed OAuth2 provider descriptors (FEAT-773 M3, S10).

Descriptors are data; provider-specific post-exchange behaviour is a Python callable registered by name.
Client credentials never live in a descriptor — they come from navconfig ``OAUTH2_<PROVIDER>_*``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Union

from pydantic import BaseModel, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from parrot.auth.oauth2_base import AbstractOAuth2TokenSet

logger = logging.getLogger(__name__)

_FORBIDDEN_KEYS = frozenset({"client_id", "client_secret", "redirect_uri"})


class RefreshPolicy(BaseModel):
    """Informational refresh facts (R6). A returned refresh_token ALWAYS replaces the stored one."""

    rotating: bool = False
    sliding: bool = False
    refresh_lifetime_s: Optional[int] = None
    access_lifetime_s: Optional[int] = None


class IdentityProbe(BaseModel):
    url: str
    account_id_path: str
    display_name_path: Optional[str] = None
    email_path: Optional[str] = None


class OAuth2ProviderDescriptor(BaseModel):
    provider_id: str
    display_name: str
    icon: str = ""
    authorization_url: str
    token_url: str
    revoke_url: Optional[str] = None
    default_scopes: List[str]
    client_type: Literal["confidential", "public"] = "confidential"
    pkce: Literal["required", "optional", "none"] = "required"
    refresh_policy: RefreshPolicy = Field(default_factory=RefreshPolicy)
    identity_probe: Optional[IdentityProbe] = None
    extra_authorize_params: Dict[str, str] = Field(default_factory=dict)
    post_exchange: Optional[str] = None
    pbac_action_namespace: str = "integration"

    @model_validator(mode="before")
    @classmethod
    def _reject_secrets(cls, data: Any) -> Any:
        """Descriptors must never carry client credentials."""
        # FILL IN: if data is a Mapping and any key in _FORBIDDEN_KEYS → raise ValueError naming the key
        #          (no secret value in the message) — bounded by spec §2 comment "never from the descriptor"
        return data


PostExchangeHook = Callable[[Any, Dict[str, Any], "AbstractOAuth2TokenSet"], Awaitable["AbstractOAuth2TokenSet"]]


class PostExchangeHookRegistry:
    """Typed in-code registry of post-exchange hooks (S10). Never imports by path."""

    def __init__(self) -> None:
        self._hooks: Dict[str, PostExchangeHook] = {}

    def register(self, name: str, fn: PostExchangeHook) -> None:
        # FILL IN: reject non-callables (TypeError) and empty names (ValueError); store — bounded by S10
        raise NotImplementedError

    def get(self, name: str) -> PostExchangeHook:
        """Return the hook; raise ``KeyError`` naming it when unknown."""
        # FILL IN: KeyError(f"unknown post_exchange hook {name!r}") on miss
        raise NotImplementedError


post_exchange_hooks = PostExchangeHookRegistry()


def load_provider_descriptors(
    source: Union[str, Path, Sequence[Mapping[str, Any]]],
) -> List[OAuth2ProviderDescriptor]:
    """Load descriptors from a YAML file (``OAUTH2_PROVIDERS_FILE``) or mappings.

    Raises:
        ValueError: invalid entry (message names the provider_id) or duplicate provider_id.
    """
    # FILL IN: str/Path → yaml.safe_load (accept a list or {"providers": [...]}); validate each entry with
    #          OAuth2ProviderDescriptor.model_validate, re-raising ValidationError as ValueError naming
    #          entry.get("provider_id", f"#{i}"); reject duplicates — bounded by spec §3 M3 loader docstring
    raise NotImplementedError
```
**Why this shape**: the three models are the §2 contract verbatim (only mutable defaults moved to
`default_factory`). The forbidden-keys validator enforces "client id/secret never read from the descriptor"
(§4 test row). The module-level `post_exchange_hooks` instance is what TASK-4943 and TASK-4954 register against.

### FILL IN checklist
- [ ] `descriptor.py::OAuth2ProviderDescriptor._reject_secrets` — reject secret keys; bounded by §2
- [ ] `descriptor.py::PostExchangeHookRegistry.register/get` — typed registry; bounded by S10
- [ ] `descriptor.py::load_provider_descriptors` — YAML/dict loader + errors; bounded by §3 M3
- [ ] `test_oauth2_descriptor.py` — test bodies

---

## Acceptance Criteria

- [ ] Descriptor field set equals spec §2; `client_id`/`client_secret`/`redirect_uri` keys are rejected
- [ ] Invalid descriptor raises `ValueError` naming the provider; duplicate ids rejected
- [ ] `PostExchangeHookRegistry.get('missing')` raises `KeyError`; nothing is imported by path

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py
import pytest
from parrot.auth.oauth2.descriptor import (OAuth2ProviderDescriptor, PostExchangeHookRegistry,
                                           load_provider_descriptors)

BASE = {"provider_id": "dummy", "display_name": "Dummy", "authorization_url": "https://idp/authorize",
        "token_url": "https://idp/token", "default_scopes": ["read"]}


def test_descriptor_validation_and_secrets_from_conf():
    assert load_provider_descriptors([BASE])[0].provider_id == "dummy"
    with pytest.raises(ValueError, match="dummy"):
        load_provider_descriptors([{**BASE, "pkce": "sometimes"}])
    with pytest.raises(ValueError):
        load_provider_descriptors([{**BASE, "client_secret": "s3cr3t"}])
    with pytest.raises(ValueError):
        load_provider_descriptors([BASE, BASE])


def test_post_exchange_hook_registry_is_typed():
    reg = PostExchangeHookRegistry()
    with pytest.raises(KeyError):
        reg.get("parrot.auth.jira_oauth:hook")     # an import path is just an unknown name
    async def hook(manager, payload, token_set):
        return token_set
    reg.register("noop", hook)
    assert reg.get("noop") is hook
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-luna (codex)
**Date**: 2026-10-30
**Notes**: Implemented per task; merged, engine lint clean. Merge-tier validation: only red is pre-existing test_oauth_callback_routes::test_invalid_state_returns_400 (fails on dev too; ledger issue:e7b7e5906b6e).
