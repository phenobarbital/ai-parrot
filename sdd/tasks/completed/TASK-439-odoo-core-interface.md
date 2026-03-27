# TASK-439 — Odoo Core Interface (Auth + execute_kw + Context Manager)

**Feature**: FEAT-054 — odoo-interface
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-373

---

## Objective

Implement the core `OdooInterface` class in `parrot/interfaces/odoointerface.py` with JSON-RPC 2.0 authentication, the generic `execute_kw` dispatcher, Pydantic data models, custom exceptions, and async context manager support.

## File(s) to Create

- `parrot/interfaces/odoointerface.py`

## Implementation Details

### 1. Pydantic Models

```python
class OdooConfig(BaseModel):
    url: str
    database: str
    username: str
    password: str
    timeout: int = 30
    verify_ssl: bool = True

class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str = "call"
    id: int = 1
    params: dict[str, Any]
```

### 2. Exception Hierarchy

```python
class OdooError(Exception): ...
class OdooAuthenticationError(OdooError): ...
class OdooRPCError(OdooError): ...
class OdooConnectionError(OdooError): ...
```

### 3. OdooInterface Class

- **Constructor**: Accept `url`, `database`, `username`, `password`, `timeout`, `verify_ssl` as kwargs. Fall back to `parrot.conf` values when not provided. Validate via `OdooConfig`. Do NOT create `aiohttp.ClientSession` in `__init__` (defer to `__aenter__` or first call).
- **`_get_session()`**: Lazily create and return `aiohttp.ClientSession` with proper timeout and SSL settings.
- **`_jsonrpc_call(service, method, args)`**: Internal method that builds the JSON-RPC 2.0 payload, posts to `{url}/jsonrpc`, parses the response. Raise `OdooConnectionError` on network errors, `OdooRPCError` if `error` key present in response.
- **`authenticate()`**: Call `_jsonrpc_call("common", "login", [database, username, password])`. Cache the returned `uid`. Raise `OdooAuthenticationError` if uid is `False`/`None`.
- **`execute_kw(model, method, args=None, kwargs=None)`**: Call `_jsonrpc_call("object", "execute_kw", [database, uid, password, model, method, args or [], kwargs or {}])`. Auto-authenticate if uid is not set.
- **`__aenter__` / `__aexit__`**: Create and close `aiohttp.ClientSession`.
- **`close()`**: Close the session explicitly.

### 4. Logging

- Use `navconfig.logging` logger named `"OdooInterface"`.
- Log authentication success/failure, RPC calls (model + method, NOT password).
- Never log the password field.

### 5. Security

- Validate model name: must match `^[a-z_][a-z0-9_.]*$` to prevent injection.
- SSL verification enabled by default.

## Acceptance Criteria

- [ ] `OdooInterface` can be instantiated with explicit params or from env vars.
- [ ] `authenticate()` returns uid on success, raises `OdooAuthenticationError` on failure.
- [ ] `execute_kw()` sends correct JSON-RPC 2.0 payload and returns parsed result.
- [ ] Auto-authentication works when `execute_kw` is called without prior `authenticate()`.
- [ ] `OdooRPCError` raised on Odoo-side errors with details.
- [ ] `OdooConnectionError` raised on network failures.
- [ ] Async context manager properly creates/closes aiohttp session.
- [ ] Password never appears in log output.
- [ ] Model name validation rejects invalid names.

## Tests

- `test_authenticate_success` — mock successful login, verify uid cached.
- `test_authenticate_failure` — mock failed login, verify OdooAuthenticationError.
- `test_execute_kw_payload` — verify correct JSON-RPC 2.0 payload structure.
- `test_execute_kw_auto_auth` — verify auto-authentication on first call.
- `test_rpc_error_handling` — mock error response, verify OdooRPCError.
- `test_connection_error` — mock network failure, verify OdooConnectionError.
- `test_context_manager` — verify session lifecycle.
- `test_model_name_validation` — invalid model names rejected.
