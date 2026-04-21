# TASK-804: Secret/Public Splitter Helper

**Feature**: FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp
**Spec**: `sdd/specs/mcp-command-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-803
**Assigned-to**: unassigned

---

## Context

This task adds the `_split_secret_and_public` private helper inside the existing
`mcp_commands.py` module. It splits an `/add_mcp` JSON payload into:

- `TelegramMCPPublicParams` — non-secret fields safe to persist in DocumentDB.
- `dict[str, Any]` (`secret_params`) — secret fields (`token`, `api_key`,
  `username`, `password`) that go into the Vault.

This helper is the "seam" that allows `add_mcp_handler` (TASK-805) to delegate
persistence cleanly without mixing secret and public data. Implements **Module 2**
of the spec (§3).

---

## Scope

- Modify `mcp_commands.py` to import `TelegramMCPPublicParams` from the new
  `mcp_persistence` module.
- Add the `_split_secret_and_public(payload: dict) -> tuple[TelegramMCPPublicParams, dict[str, Any]]` function.
- The function must:
  - Validate the same conditions as `_build_config` (name, url, auth_scheme),
    raising `ValueError` with the same messages so handlers can echo `_USAGE`.
  - Extract secret fields according to `auth_scheme`:
    - `bearer` → `secret_params = {"token": payload["token"]}`.
    - `api_key` → `secret_params = {"api_key": payload["api_key"]}`.
    - `basic` → `secret_params = {"username": payload["username"], "password": payload["password"]}`.
    - `none` → `secret_params = {}`.
  - Build and return `TelegramMCPPublicParams` from the non-secret fields.
  - The returned `TelegramMCPPublicParams` must NOT contain any secret field values.
- Do **NOT** yet rewrite any handlers (that is TASK-805).
- Do **NOT** delete the Redis helpers yet (that is TASK-805).

**NOT in scope**: Handler rewrites, removing Redis helpers, wrapper changes, tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py` | MODIFY | Add import of `TelegramMCPPublicParams`; add `_split_secret_and_public` function |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in mcp_commands.py:41 — keep unchanged:
from ...mcp.client import AuthCredential, AuthScheme, MCPClientConfig

# Add this new import (after verifying TASK-803 is done):
from .mcp_persistence import TelegramMCPPublicParams
```

### Existing Signatures to Use

```python
# mcp_commands.py:63-69 — _ALLOWED_SCHEMES (use this for validation in the splitter)
_ALLOWED_SCHEMES = {
    "none": AuthScheme.NONE,
    "bearer": AuthScheme.BEARER,
    "api_key": AuthScheme.API_KEY,
    "apikey": AuthScheme.API_KEY,
    "basic": AuthScheme.BASIC,
}

# mcp_commands.py:90 — existing _build_config (do NOT modify; keep it)
def _build_config(payload: Dict[str, Any]) -> MCPClientConfig: ...

# mcp_persistence.py (TASK-803) — TelegramMCPPublicParams fields:
class TelegramMCPPublicParams(BaseModel):
    name: str
    url: str
    transport: str = "http"
    description: Optional[str] = None
    auth_scheme: str = "none"
    api_key_header: Optional[str] = None
    use_bearer_prefix: Optional[bool] = None
    headers: Dict[str, str]
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None
```

### Does NOT Exist

- ~~`TelegramMCPPublicParams.token`~~ — secrets are never stored on this model.
- ~~`TelegramMCPPublicParams.api_key`~~ — same; only in `secret_params` dict.
- ~~`TelegramMCPPublicParams.password`~~ — same.
- ~~`_split_secret_and_public` returning a dataclass~~ — returns a plain `dict` for secret_params.
- ~~`parrot.integrations.telegram.mcp_commands.VaultClient`~~ — does not exist.

---

## Implementation Notes

### Splitter Implementation

```python
def _split_secret_and_public(
    payload: Dict[str, Any],
) -> tuple[TelegramMCPPublicParams, Dict[str, Any]]:
    """Split an /add_mcp payload into public config and secret params.

    Args:
        payload: Raw JSON dict from the Telegram command.

    Returns:
        Tuple of (TelegramMCPPublicParams, secret_params dict).
        secret_params is empty when auth_scheme is "none".

    Raises:
        ValueError: Same validation errors as _build_config.
    """
    name = payload.get("name")
    url = payload.get("url")
    if not name or not isinstance(name, str):
        raise ValueError("'name' is required and must be a string.")
    if not url or not isinstance(url, str):
        raise ValueError("'url' is required and must be a string.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("'url' must be an http:// or https:// URL.")

    scheme_name = str(payload.get("auth_scheme", "none")).lower()
    if scheme_name not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Unsupported auth_scheme {scheme_name!r}. "
            f"Allowed: {sorted(_ALLOWED_SCHEMES)}."
        )

    secret_params: Dict[str, Any] = {}
    if scheme_name == "bearer":
        token = payload.get("token")
        if not token:
            raise ValueError("bearer auth requires a 'token' field.")
        secret_params = {"token": token}
    elif scheme_name in ("api_key", "apikey"):
        api_key = payload.get("api_key") or payload.get("token")
        if not api_key:
            raise ValueError("api_key auth requires an 'api_key' field.")
        secret_params = {"api_key": api_key}
    elif scheme_name == "basic":
        username = payload.get("username")
        password = payload.get("password")
        if not username or not password:
            raise ValueError("basic auth requires 'username' and 'password'.")
        secret_params = {"username": username, "password": password}

    headers = payload.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("'headers' must be a JSON object if provided.")
    allowed = payload.get("allowed_tools")
    if allowed is not None and not isinstance(allowed, list):
        raise ValueError("'allowed_tools' must be a list if provided.")
    blocked = payload.get("blocked_tools")
    if blocked is not None and not isinstance(blocked, list):
        raise ValueError("'blocked_tools' must be a list if provided.")

    public_params = TelegramMCPPublicParams(
        name=name,
        url=url,
        transport=str(payload.get("transport", "http")),
        description=payload.get("description"),
        auth_scheme=scheme_name,
        api_key_header=payload.get("api_key_header"),
        use_bearer_prefix=payload.get("use_bearer_prefix"),
        headers={str(k): str(v) for k, v in headers.items()},
        allowed_tools=list(allowed) if allowed else None,
        blocked_tools=list(blocked) if blocked else None,
    )
    return public_params, secret_params
```

### Key Constraints

- The function must raise `ValueError` with the same messages as `_build_config`
  so the handler can forward them verbatim.
- `api_key` scheme: store `api_key_header` and `use_bearer_prefix` in public params
  (they are not secrets; they configure how the key is sent).
- `_build_config` must be kept intact and unchanged — it is still called from
  `add_mcp_handler` to build the live `MCPClientConfig` for the session.

---

## Acceptance Criteria

- [ ] `_split_secret_and_public` is importable from `mcp_commands` (private, so tested indirectly).
- [ ] `bearer` scheme: `secret_params = {"token": ...}`, `TelegramMCPPublicParams.auth_scheme == "bearer"`, no `token` in public params.
- [ ] `api_key` scheme: `secret_params = {"api_key": ...}`, `api_key_header` in public params.
- [ ] `basic` scheme: `secret_params = {"username": ..., "password": ...}`, neither in public params.
- [ ] `none` scheme: `secret_params == {}`.
- [ ] Missing `token` for bearer → raises `ValueError("bearer auth requires a 'token' field.")`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`

---

## Test Specification

Full tests in TASK-807. Quick validation:

```python
from parrot.integrations.telegram.mcp_commands import _split_secret_and_public

def test_split_bearer():
    payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "bearer", "token": "sk-123"}
    public, secret = _split_secret_and_public(payload)
    assert secret == {"token": "sk-123"}
    assert not hasattr(public, "token")
    assert public.auth_scheme == "bearer"

def test_split_none():
    payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "none"}
    public, secret = _split_secret_and_public(payload)
    assert secret == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-803 is completed** — `mcp_persistence.py` must exist.
2. **Read** `mcp_commands.py` fully to understand the existing structure.
3. **Verify the Codebase Contract** — confirm `TelegramMCPPublicParams` is importable from `.mcp_persistence`.
4. Add the import and the `_split_secret_and_public` function.
5. Run `ruff check` and fix issues.
6. **Commit**: `git add packages/ai-parrot/src/parrot/integrations/telegram/mcp_commands.py`
7. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
