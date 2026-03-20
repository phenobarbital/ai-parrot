# Feature Specification: Odoo Interface (JSON-RPC 2.0)

**Feature ID**: FEAT-054
**Date**: 2026-03-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents need to interact with Odoo ERP (v16+) for reading/writing business data
(partners, invoices, products, inventory, etc.). Currently there is no Odoo integration in
the framework. Odoo exposes its data through a JSON-RPC 2.0 API (`/jsonrpc` endpoint),
which requires session-based authentication and uses the `execute_kw` dispatch pattern for
all model operations.

### Goals

- **OdooInterface**: A new async interface at `parrot/interfaces/odoointerface.py` that
  wraps Odoo's JSON-RPC 2.0 API with a clean, Pythonic API.
- **Authentication**: Support `authenticate` via JSON-RPC (database + username + password),
  with session UID caching.
- **CRUD Operations**: `search`, `search_read`, `read`, `create`, `write`, `unlink` on
  any Odoo model via `execute_kw`.
- **Domain Filters**: Pythonic domain filter builder compatible with Odoo's domain triplet
  syntax `[(field, operator, value)]`.
- **Async-First**: All network I/O through `aiohttp` — no blocking calls.
- **Configurable**: Connection parameters via environment variables or constructor kwargs.
- **Odoo v16+**: Target Odoo 16, 17, and 18 Community/Enterprise.

### Non-Goals (explicitly out of scope)

- ORM-like model abstraction (no mapped Python classes per Odoo model).
- Odoo XML-RPC support (JSON-RPC only).
- Odoo webhook/event handling (polling or real-time subscriptions).
- Admin operations (module install, database management).
- File/attachment upload (binary field handling) — follow-up feature.
- Building an OdooToolkit for agents — follow-up feature.

---

## 2. Architectural Design

### Overview

Single-class interface following the same patterns as `SOAPClient` and `DBInterface`:
an ABC-derived async client that manages authentication, session state, and provides
typed methods for Odoo model operations.

### Component Diagram

```
OdooInterface
  │
  ├── __init__(url, database, username, password, ...)
  │     └── Validates config, creates aiohttp.ClientSession
  │
  ├── authenticate() → uid: int
  │     └── POST /jsonrpc {"service": "common", "method": "login"}
  │
  ├── execute_kw(model, method, args, kwargs) → Any
  │     └── POST /jsonrpc {"service": "object", "method": "execute_kw"}
  │
  ├── search(model, domain, **kw) → list[int]
  ├── search_read(model, domain, fields, **kw) → list[dict]
  ├── read(model, ids, fields) → list[dict]
  ├── create(model, values) → int | list[int]
  ├── write(model, ids, values) → bool
  ├── unlink(model, ids) → bool
  ├── search_count(model, domain) → int
  ├── fields_get(model, attributes) → dict
  │
  └── close() / async context manager
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/conf.py` | Modified | Add `ODOO_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_PASSWORD` config variables |
| `parrot/interfaces/__init__.py` | Modified | Export `OdooInterface` |
| `aiohttp` | Consumed | Async HTTP client for JSON-RPC calls |
| `navconfig.logging` | Consumed | Standard logging |

### Data Models

**Pydantic models** (`parrot/interfaces/odoointerface.py`):

```python
class OdooConfig(BaseModel):
    """Configuration for Odoo JSON-RPC connection."""
    url: str = Field(..., description="Odoo instance URL (e.g. https://myodoo.com)")
    database: str = Field(..., description="Odoo database name")
    username: str = Field(..., description="Odoo login username")
    password: str = Field(..., description="Odoo login password or API key")
    timeout: int = Field(default=30, description="Request timeout in seconds")

class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request payload."""
    jsonrpc: str = "2.0"
    method: str = "call"
    id: int = 1
    params: dict[str, Any]

class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response payload."""
    jsonrpc: str
    id: int
    result: Any = None
    error: Optional[dict[str, Any]] = None
```

### API Design

```python
class OdooInterface:
    """Async interface for Odoo ERP via JSON-RPC 2.0.

    Supports Odoo v16+ (Community and Enterprise).

    Usage:
        async with OdooInterface(url=..., database=..., username=..., password=...) as odoo:
            await odoo.authenticate()
            partners = await odoo.search_read(
                "res.partner",
                domain=[("is_company", "=", True)],
                fields=["name", "email", "phone"],
                limit=10,
            )
    """

    async def authenticate(self) -> int:
        """Authenticate with Odoo and return the user ID (uid)."""

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Execute any Odoo model method via execute_kw."""

    async def search(
        self,
        model: str,
        domain: list | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        """Search for record IDs matching the domain."""

    async def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search and read records in a single call."""

    async def read(
        self,
        model: str,
        ids: list[int],
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read specific records by ID."""

    async def create(
        self,
        model: str,
        values: dict[str, Any] | list[dict[str, Any]],
    ) -> int | list[int]:
        """Create one or more records. Returns ID(s)."""

    async def write(
        self,
        model: str,
        ids: list[int],
        values: dict[str, Any],
    ) -> bool:
        """Update existing records."""

    async def unlink(
        self,
        model: str,
        ids: list[int],
    ) -> bool:
        """Delete records by ID."""

    async def search_count(
        self,
        model: str,
        domain: list | None = None,
    ) -> int:
        """Return the count of records matching the domain."""

    async def fields_get(
        self,
        model: str,
        attributes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get field definitions for a model."""
```

### Error Handling

```python
class OdooError(Exception):
    """Base exception for Odoo JSON-RPC errors."""

class OdooAuthenticationError(OdooError):
    """Raised when authentication fails."""

class OdooRPCError(OdooError):
    """Raised when Odoo returns a JSON-RPC error response."""

class OdooConnectionError(OdooError):
    """Raised on network/connection failures."""
```

### JSON-RPC 2.0 Protocol Details

**Authentication:**
```json
{
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "service": "common",
        "method": "login",
        "args": ["database_name", "username", "password"]
    }
}
```

**Model operations (execute_kw):**
```json
{
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "service": "object",
        "method": "execute_kw",
        "args": ["database_name", uid, "password", "res.partner", "search_read",
                 [[["is_company", "=", true]]],
                 {"fields": ["name", "email"], "limit": 5}]
    }
}
```

---

## 3. Implementation Tasks (high-level)

1. **Config variables**: Add `ODOO_*` environment variables to `parrot/conf.py`.
2. **Core OdooInterface class**: Implement authentication, session management, `execute_kw`,
   and async context manager in `parrot/interfaces/odoointerface.py`.
3. **CRUD convenience methods**: `search`, `search_read`, `read`, `create`, `write`,
   `unlink`, `search_count`, `fields_get` — all delegating to `execute_kw`.
4. **Error handling**: Custom exception hierarchy (`OdooError`, `OdooAuthenticationError`,
   `OdooRPCError`, `OdooConnectionError`).
5. **Export and registration**: Update `parrot/interfaces/__init__.py`.
6. **Unit tests**: Test JSON-RPC payload construction, error handling, and response parsing
   (mock `aiohttp` calls, no live Odoo needed).

---

## 4. Acceptance Criteria

- [ ] `OdooInterface` connects and authenticates to an Odoo v16+ instance via JSON-RPC 2.0.
- [ ] All CRUD operations (`search`, `search_read`, `read`, `create`, `write`, `unlink`)
      work correctly against any Odoo model.
- [ ] `search_count` and `fields_get` return correct results.
- [ ] `execute_kw` supports arbitrary model methods beyond the convenience wrappers.
- [ ] Authentication errors raise `OdooAuthenticationError`.
- [ ] JSON-RPC errors raise `OdooRPCError` with error details from the response.
- [ ] Network errors raise `OdooConnectionError`.
- [ ] Session is reusable across multiple calls (uid cached after auth).
- [ ] Async context manager properly creates and closes `aiohttp.ClientSession`.
- [ ] All I/O is async (no blocking calls).
- [ ] Config variables are available via `parrot/conf.py` and environment variables.
- [ ] Unit tests pass with mocked HTTP responses.

---

## 5. Security Considerations

- Passwords/API keys must come from environment variables, never hardcoded.
- JSON-RPC payloads must not log sensitive fields (password, API key).
- SSL verification enabled by default; configurable for development.
- Input validation on model names to prevent injection in JSON-RPC params.

---

## 6. Performance Considerations

- Reuse `aiohttp.ClientSession` across calls (connection pooling).
- UID caching avoids re-authentication on every call.
- Support `limit` and `offset` in search operations to control response size.
- Optional `timeout` configuration per-request.

---

## 7. Dependencies

- `aiohttp` (already in project)
- `pydantic` (already in project)
- No new external dependencies required.

---

## 8. Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks).
- All tasks run in a single worktree — no parallelization needed.
- **Cross-feature dependencies**: None. This is a standalone interface.

---

## 9. Future Work

- **OdooToolkit**: An `AbstractToolkit` subclass exposing Odoo operations as agent tools.
- **Attachment handling**: Binary field read/write for file uploads.
- **Multi-company support**: Switching between Odoo companies within a session.
- **Report generation**: Calling Odoo report actions and retrieving PDF output.
- **Odoo XML-RPC fallback**: For older Odoo versions (< v16).
