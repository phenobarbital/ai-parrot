# TASK-769: MCP Server Registry — Declarative Catalog of Pre-Built Helpers

**Feature**: FEAT-110 — MCP Mixin Helper Handler
**Spec**: `sdd/specs/mcp-mixin-helper-handler.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-110. The MCP Server Registry is a declarative
catalog that describes every `add_*_mcp_server` helper method on `MCPEnabledMixin` —
its name, human-readable description, required/optional parameters (with types), and
category. All other tasks in this feature depend on this registry.

Implements spec Section 3, Module 1 and the data models from Section 2.

---

## Scope

- Create the Pydantic models: `MCPParamType`, `MCPServerParam`, `MCPServerDescriptor`,
  `UserMCPServerConfig`, `ActivateMCPServerRequest`.
- Implement `MCPServerRegistry` class with:
  - `list_servers() -> List[MCPServerDescriptor]`
  - `get_server(name: str) -> Optional[MCPServerDescriptor]`
  - `validate_params(name: str, params: Dict[str, Any]) -> Dict[str, Any]`
- Populate the registry with descriptors for ALL existing `add_*_mcp_server` helpers:
  - `perplexity` — requires `api_key` (SECRET)
  - `fireflies` — requires `api_key` (SECRET)
  - `chrome-devtools` — optional `browser_url` (STRING, default `http://127.0.0.1:9222`)
  - `google-maps` — no required params
  - `alphavantage` — optional `api_key` (SECRET)
  - `genmedia` — no required params (uses env PROJECT_ID)
  - `quic` — requires `name`, `host`, `port`; optional `cert_path`
  - `websocket` — requires `name`, `url`; optional `auth_type`, `auth_config`, `headers`
- Write unit tests.

**NOT in scope**: HTTP handler, persistence, Vault integration — those are separate tasks.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/mcp/registry.py` | CREATE | Registry class and data models |
| `tests/unit/test_mcp_registry.py` | CREATE | Unit tests for registry |
| `parrot/mcp/__init__.py` | MODIFY | Export `MCPServerRegistry` if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # standard pydantic
from typing import Optional, Dict, Any, List
from enum import Enum

# These are for reference — the registry does NOT import them at runtime,
# it only stores method_name strings that map to these methods.
from parrot.mcp.integration import MCPEnabledMixin  # verified: parrot/mcp/integration.py:1087
```

### Existing Signatures to Use
```python
# parrot/mcp/integration.py — MCPEnabledMixin helper methods (for building descriptors)
class MCPEnabledMixin:  # line 1087
    async def add_perplexity_mcp_server(self, api_key: str, name: str = "perplexity", **kwargs) -> List[str]:  # line 1161
    async def add_fireflies_mcp_server(self, api_key: str, **kwargs) -> List[str]:  # line 1171
    async def add_chrome_devtools_mcp_server(self, browser_url: str = "http://127.0.0.1:9222", name: str = "chrome-devtools", **kwargs) -> List[str]:  # line 1193
    async def add_google_maps_mcp_server(self, name: str = "google-maps", **kwargs) -> List[str]:  # line 1216
    async def add_quic_mcp_server(self, name: str, host: str, port: int, cert_path: Optional[str] = None, **kwargs) -> List[str]:  # line 1236
    async def add_websocket_mcp_server(self, name: str, url: str, auth_type: Optional[str] = None, auth_config: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, **kwargs) -> List[str]:  # line 1248
    async def add_alphavantage_mcp_server(self, api_key: Optional[str] = None, name: str = "alphavantage", **kwargs) -> List[str]:  # line 1351
    async def add_genmedia_mcp_servers(self, **kwargs) -> Dict[str, List[str]]:  # line 1370

# parrot/mcp/integration.py — Factory functions (these produce MCPClientConfig objects)
def create_perplexity_mcp_server(api_key: str, *, name: str = "perplexity", timeout_ms: int = 600000, **kwargs) -> MCPServerConfig:  # line 970
def create_fireflies_mcp_server(*, api_key: str, api_base: str = "https://api.fireflies.ai/mcp", **kwargs) -> MCPServerConfig:  # line 851
def create_chrome_devtools_mcp_server(browser_url: str = "http://127.0.0.1:9222", name: str = "chrome-devtools", **kwargs) -> MCPServerConfig:  # line 883
def create_google_maps_mcp_server(name: str = "google-maps", **kwargs) -> MCPServerConfig:  # line 942
def create_alphavantage_mcp_server(api_key: Optional[str] = None, name: str = "alphavantage", **kwargs) -> MCPServerConfig:  # line 1055
def create_quic_mcp_server(name: str, host: str, port: int, cert_path: Optional[str] = None, serialization: str = "msgpack", **kwargs) -> MCPServerConfig:  # line 1013
def create_websocket_mcp_server(name: str, url: str, auth_type: Optional[str] = None, auth_config: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, **kwargs) -> MCPServerConfig:  # line 775
```

### Does NOT Exist
- ~~`parrot.mcp.registry`~~ — does not exist yet; this task creates it
- ~~`MCPEnabledMixin.get_available_helpers()`~~ — no introspection method exists
- ~~`MCPServerRegistry`~~ — does not exist; this task creates it
- ~~`MCPServerDescriptor`~~ — does not exist; this task creates it
- ~~`MCPParamType`~~ — does not exist; this task creates it

---

## Implementation Notes

### Pattern to Follow
Use a module-level `_REGISTRY` list of `MCPServerDescriptor` instances, and the
`MCPServerRegistry` class wraps it with lookup/validation methods. This is declarative,
not reflection-based — each entry explicitly maps a slug to a method name and params.

```python
_REGISTRY: List[MCPServerDescriptor] = [
    MCPServerDescriptor(
        name="perplexity",
        display_name="Perplexity AI",
        description="Web search, conversational AI, deep research, and reasoning",
        method_name="add_perplexity_mcp_server",
        category="search",
        params=[
            MCPServerParam(name="api_key", type=MCPParamType.SECRET, required=True,
                           description="Perplexity API key from perplexity.ai/account/api"),
        ],
    ),
    # ... one entry per helper
]
```

### Key Constraints
- Models must use Pydantic `BaseModel` with type hints
- `validate_params` must raise `ValueError` with descriptive message for missing required params
- `MCPParamType.SECRET` signals that a param must be stored in Vault (other tasks handle this)
- The `method_name` field stores the string name of the `MCPEnabledMixin` method
- The corresponding `create_*` factory function name follows the pattern: replace `add_` with `create_` in the method name

### References in Codebase
- `parrot/mcp/integration.py:1087-1399` — all `add_*_mcp_server` methods
- `parrot/mcp/integration.py:651-1080` — all `create_*_mcp_server` factory functions
- `parrot/handlers/models/credentials.py` — example of handler-level Pydantic models

---

## Acceptance Criteria

- [ ] `MCPServerRegistry().list_servers()` returns descriptors for all 8 existing helpers
- [ ] `MCPServerRegistry().get_server("perplexity")` returns the correct descriptor
- [ ] `MCPServerRegistry().get_server("nonexistent")` returns `None`
- [ ] `validate_params("perplexity", {"api_key": "x"})` succeeds
- [ ] `validate_params("perplexity", {})` raises `ValueError` (missing required `api_key`)
- [ ] Each descriptor has correct `params` list matching the actual method signature
- [ ] All tests pass: `pytest tests/unit/test_mcp_registry.py -v`
- [ ] Import works: `from parrot.mcp.registry import MCPServerRegistry, MCPServerDescriptor`

---

## Test Specification

```python
# tests/unit/test_mcp_registry.py
import pytest
from parrot.mcp.registry import (
    MCPServerRegistry,
    MCPServerDescriptor,
    MCPServerParam,
    MCPParamType,
)


@pytest.fixture
def registry():
    return MCPServerRegistry()


class TestMCPServerRegistry:
    def test_list_servers_returns_all(self, registry):
        servers = registry.list_servers()
        assert len(servers) >= 8
        names = [s.name for s in servers]
        assert "perplexity" in names
        assert "fireflies" in names
        assert "chrome-devtools" in names
        assert "google-maps" in names

    def test_get_server_found(self, registry):
        desc = registry.get_server("perplexity")
        assert desc is not None
        assert desc.name == "perplexity"
        assert desc.method_name == "add_perplexity_mcp_server"

    def test_get_server_not_found(self, registry):
        assert registry.get_server("nonexistent") is None

    def test_validate_params_ok(self, registry):
        result = registry.validate_params("perplexity", {"api_key": "test-key"})
        assert "api_key" in result

    def test_validate_params_missing_required(self, registry):
        with pytest.raises(ValueError, match="api_key"):
            registry.validate_params("perplexity", {})

    def test_validate_params_unknown_server(self, registry):
        with pytest.raises(ValueError, match="not found"):
            registry.validate_params("nonexistent", {})

    def test_secret_params_flagged(self, registry):
        desc = registry.get_server("perplexity")
        secret_params = [p for p in desc.params if p.type == MCPParamType.SECRET]
        assert len(secret_params) > 0
        assert secret_params[0].name == "api_key"

    def test_optional_params_have_defaults(self, registry):
        desc = registry.get_server("chrome-devtools")
        browser_url_param = next(p for p in desc.params if p.name == "browser_url")
        assert browser_url_param.required is False
        assert browser_url_param.default is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none; proceed immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm the `add_*_mcp_server` methods in "Existing Signatures" still have the listed parameters
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-769-mcp-server-registry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-19
**Notes**: Implemented all Pydantic models (MCPParamType, MCPServerParam, MCPServerDescriptor, UserMCPServerConfig, ActivateMCPServerRequest) and MCPServerRegistry class with list_servers(), get_server(), and validate_params() methods. Declarative registry includes all 8 MCP server helpers. All 28 unit tests pass. Updated mcp/__init__.py to export new symbols.

**Deviations from spec**: none
