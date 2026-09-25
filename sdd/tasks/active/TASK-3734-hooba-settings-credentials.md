# TASK-3734: HoobaSettings.from_env, EnvCredentialResolver, broker registration and the login hook

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3733
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2**. The toolkit reads `HOOBA_*` configuration from the environment and
must obtain `HOOBA_USERNAME` / `HOOBA_PASSWORD` only through `CredentialBroker` provider
`hooba` (AC-8). The broker's built-in `static_key` path is vault-backed and knows nothing
of environment variables (design research S7), so this task adds an explicit
`EnvCredentialResolver` and a registration helper. It also builds the login hook
TASK-3737 hands to `OpenAPIToolkit(auth_type="cookie")`: `POST {base_url}/auth/login`
with JSON `{username, password}`, returning `{"sid": ...}` from the response cookies.

---

## Scope

- `settings.py`: `HoobaSettings` (fields per spec §2), `from_env(env=None)`, `default_headers()`.
- `credentials.py`: `EnvCredentialResolver`, `register_hooba_provider`, `HoobaAuthError`, `make_login_hook`.
- `tests/hooba/test_settings_credentials.py`.

**NOT in scope**: the OpenAPI toolkit (TASK-3737), browser login (TASK-3738).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/settings.py` | CREATE | HoobaSettings + from_env + default_headers |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/credentials.py` | CREATE | EnvCredentialResolver, register_hooba_provider, HoobaAuthError, make_login_hook |
| `packages/ai-parrot-tools/tests/hooba/test_settings_credentials.py` | CREATE | unit tests (no network) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.auth.broker import CredentialBroker                              # verified: packages/ai-parrot/src/parrot/auth/__init__.py:64
from parrot.auth.credentials import CredentialResolver, NeedsAuth, ResolvedCredential   # verified: credentials.py:162, 82, 65
from parrot.interfaces.http import HTTPService                               # verified: openapitoolkit.py:40 (relative form)
from pydantic import BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):                                                # line 162
    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]      # line 166 — None ⇒ broker returns NeedsAuth
    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str           # line 175
    async def is_connected(self, channel: str, user_id: str) -> bool          # line 179 (concrete)
class ResolvedCredential(BaseModel): provider: str; secret: Any; key_fingerprint: str   # lines 65-79

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker:                                                       # line 419
    def __init__(self, *, audit_ledger=None, identity_mapper=None)            # lines 455-466
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None   # lines 468-491
    async def resolve(self, provider: str, channel: str, user_id: str, **ctx) -> ResolvedCredential | NeedsAuth   # lines 543-639
    #   empty user_id → ValueError (lines 577-581); unregistered provider → KeyError (lines 583-585)

# packages/ai-parrot/src/parrot/interfaces/http.py
async def _request(self, url, method='get', cookies=None, params=None, data=None, headers=None, ...,
                   use_proxy=True, use_json=False, follow_redirects=True, raise_for_status=True,
                   full_response=False, ..., num_retries=2, **kwargs)        # lines 1610-1631
#   full_response=True → (httpx.Response, None): .status_code, .cookies (httpx.Cookies, .get(name)), .history
```

### Does NOT Exist
- ~~An environment-variable resolver in `parrot.auth`~~ — none; `CredentialResolverFactory._build_static_key` is vault-backed.
- ~~`CredentialBroker.resolve` returning `NeedsAuth` for an unknown provider~~ — it raises `KeyError`.
- ~~`HTTPService.post_json` / `login`~~ — use `_request(..., method="post", data=..., use_json=True)`.
- ~~`parrot.tools.openapitoolkit.LoginHook`~~ as an import here — TASK-3732 defines it, but this task must not depend on it; type the hook locally as `Callable[[HTTPService], Awaitable[Dict[str, str]]]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/settings.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/credentials.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_settings_credentials.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/broker.py#CredentialBroker",
    "sym:packages/ai-parrot/src/parrot/auth/broker.py#CredentialBroker.register",
    "sym:packages/ai-parrot/src/parrot/auth/broker.py#CredentialBroker.resolve",
    "sym:packages/ai-parrot/src/parrot/auth/credentials.py#CredentialResolver",
    "sym:packages/ai-parrot/src/parrot/interfaces/http.py#HTTPService._request"
  ]
}
```

---

## Implementation Notes

- Env names: `HOOBA_BASE_URL`, `HOOBA_ACCOUNT_ID` (required, int), `HOOBA_MEMBER_ID`, `HOOBA_USER_ID`, `HOOBA_SUBSCRIPTION_ID`,
  `HOOBA_LANGUAGE`, `HOOBA_ORIGIN`, `HOOBA_CATALOG_DIR`, `HOOBA_SPEC_PATH`, `HOOBA_INCLUDE_TAGS` (comma list).
- `make_login_hook` fails closed BEFORE any network call (S7): unregistered provider (`KeyError`), empty identity
  (`ValueError`), `NeedsAuth`, or a secret that is neither a `{"username","password"}` dict nor a 2-tuple/list →
  `HoobaAuthError` with a message that never contains the secret.
- Read `sid` from `response.cookies` first, then from each `response.history[*].cookies` (the login may redirect, spec §7).
- `num_retries=0` on the login POST — never replay credentials at transport level.

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `settings.py` — *why*: one typed source for every `HOOBA_*` variable.
2. Write `credentials.py` — *why*: AC-8, credentials only via the broker; S7, explicit env bootstrap.
3. Tests with a fake `HTTPService` whose `_request` returns scripted responses — *why*: no network.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/settings.py` (CREATE)
```python
"""Hooba configuration from the environment (FEAT-602 M2)."""
from __future__ import annotations

import os
from typing import Dict, Mapping, Optional

from pydantic import BaseModel


class HoobaSettings(BaseModel):
    """Connection and account settings for api.hooba.com."""

    base_url: str = "https://api.hooba.com"
    account_id: int
    member_id: Optional[int] = None
    user_id: Optional[int] = None
    subscription_id: Optional[int] = None
    language: str = "es"
    origin: str = "https://app.hooba.com"
    catalog_dir: Optional[str] = None
    spec_path: Optional[str] = None
    include_tags: Optional[list[str]] = None
    credential_provider: str = "hooba"
    credential_user_id: str = "hooba"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "HoobaSettings":
        """Build settings from ``HOOBA_*`` variables (default ``os.environ``).

        Raises:
            ValueError: ``HOOBA_ACCOUNT_ID`` is missing or not an integer (message names the variable).
        """
        env = os.environ if env is None else env
        # FILL IN: map every HOOBA_* variable listed in Implementation Notes; ints via int(); HOOBA_INCLUDE_TAGS
        #          split on "," and stripped (empty → None) — bounded by spec §3 M2
        raise NotImplementedError

    def default_headers(self) -> Dict[str, str]:
        """Headers every Hooba API call carries (captured from the web app)."""
        return {
            "origin": self.origin,
            "x-hooba-language": self.language,
            "ngsw-bypass": "true",
            "accept": "application/json, text/plain, */*",
        }
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/credentials.py` (CREATE)
```python
"""Broker-backed Hooba credentials and the cookie-session login hook (FEAT-602 M2)."""
from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver, NeedsAuth
from parrot.interfaces.http import HTTPService

from .settings import HoobaSettings

logger = logging.getLogger(__name__)

HoobaLoginHook = Callable[[HTTPService], Awaitable[Dict[str, str]]]
_BROKER_CHANNEL = "hooba"


class HoobaAuthError(RuntimeError):
    """Login rejected, credentials unavailable, or no ``sid`` cookie in the login response."""


class EnvCredentialResolver(CredentialResolver):
    """Resolve a ``{"username", "password"}`` pair from environment variables."""

    def __init__(self, username_var: str = "HOOBA_USERNAME", password_var: str = "HOOBA_PASSWORD",
                 env: Optional[Mapping[str, str]] = None) -> None:
        self._username_var = username_var
        self._password_var = password_var
        self._env = env

    async def resolve(self, channel: str, user_id: str) -> Optional[Dict[str, str]]:
        """Return the pair when both variables are set, else ``None`` (the broker turns it into ``NeedsAuth``)."""
        env = os.environ if self._env is None else self._env
        # FILL IN: read both vars; both non-empty → dict; else None — bounded by AC-8
        raise NotImplementedError

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """No out-of-band flow: the operator sets the variables."""
        return ""


def register_hooba_provider(broker: CredentialBroker, provider: str = "hooba",
                            resolver: Optional[CredentialResolver] = None) -> None:
    """Register ``provider`` on ``broker`` with an env-backed resolver by default."""
    broker.register(provider, resolver or EnvCredentialResolver(), auth_kind="static_key")


def make_login_hook(settings: HoobaSettings, broker: CredentialBroker,
                    user_id: Optional[str] = None) -> HoobaLoginHook:
    """Return the async hook ``OpenAPIToolkit(auth_type="cookie")`` calls to obtain ``{"sid": ...}``."""

    async def _login(http_service: HTTPService) -> Dict[str, str]:
        # FILL IN: resolve credentials via broker.resolve(settings.credential_provider, _BROKER_CHANNEL,
        #          user_id or settings.credential_user_id); map KeyError/ValueError/NeedsAuth/bad secret shape to
        #          HoobaAuthError BEFORE any request; POST f"{settings.base_url}/auth/login" with
        #          data={"username": ..., "password": ...}, use_json=True, headers=settings.default_headers(),
        #          full_response=True, raise_for_status=False, use_proxy=False, num_retries=0;
        #          status != 200 → HoobaAuthError(f"login failed: HTTP {status}"); sid from response.cookies then
        #          response.history; missing → HoobaAuthError — bounded by AC-8, S7; never log the secret
        raise NotImplementedError

    return _login
```
**Why this shape**: the hook type is declared locally so this task does not wait on TASK-3732; it is
structurally identical to `LoginHook`. Credential errors are raised before the POST so a misconfigured
agent never sends a half-filled login.

### `packages/ai-parrot-tools/tests/hooba/test_settings_credentials.py` (CREATE)
```python
"""FEAT-602 TASK-3734 — settings, env resolver, broker registration, login hook."""
import logging
from types import SimpleNamespace

import pytest
from parrot.auth.broker import CredentialBroker
from parrot_tools.hooba.credentials import (
    EnvCredentialResolver, HoobaAuthError, make_login_hook, register_hooba_provider,
)
from parrot_tools.hooba.settings import HoobaSettings

ENV = {"HOOBA_ACCOUNT_ID": "23549", "HOOBA_USERNAME": "user@example.test", "HOOBA_PASSWORD": "s3cret"}


class FakeHTTP:
    """Records _request kwargs; returns a scripted httpx-like response."""
    # FILL IN: SimpleNamespace(status_code=..., cookies={"sid": "abc"}, history=[])


def test_settings_from_env_and_headers():
    # FILL IN: include_tags split; default_headers keys


def test_settings_missing_account_id_raises():
    # FILL IN


async def test_env_resolver_and_broker_registration():
    # FILL IN: dict when set; broker.resolve → ResolvedCredential; unset → NeedsAuth


async def test_login_hook_extracts_sid(caplog):
    # FILL IN: {"sid": "abc"}; also from response.history; "s3cret" not in caplog.text


async def test_login_hook_non_200_raises():
    # FILL IN: 401 → HoobaAuthError


async def test_login_hook_fails_closed_before_network():
    # FILL IN: unregistered provider, empty user id, bad secret shape → HoobaAuthError; FakeHTTP saw 0 calls (S7)
```

### FILL IN checklist
- [ ] `HoobaSettings.from_env`
- [ ] `EnvCredentialResolver.resolve`
- [ ] `make_login_hook._login` — fail-closed ordering, cookie extraction incl. redirect history
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-8 (spec, credential half): credentials flow only through `CredentialBroker` provider `hooba`; no password in logs (caplog test).
- [ ] `HoobaSettings.from_env` maps every `HOOBA_*` variable; missing `HOOBA_ACCOUNT_ID` → `ValueError` naming it.
- [ ] `make_login_hook` returns `{'sid': ...}` on 200, raises `HoobaAuthError` on non-200, missing cookie, or any credential failure — the last before any request.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_settings_credentials.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_settings_from_env_and_headers` | env mapping, header set |
| `test_settings_missing_account_id_raises` | required var |
| `test_env_resolver_and_broker_registration` | resolver + broker contract |
| `test_login_hook_extracts_sid` | cookie + redirect history, no secret in logs |
| `test_login_hook_non_200_raises` | `HoobaAuthError` |
| `test_login_hook_fails_closed_before_network` | S7 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
