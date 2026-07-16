---
type: Wiki Overview
title: 'TASK-924: NetSuite Registry Entry & Factory Map'
id: doc:sdd-tasks-completed-task-924-netsuite-registry-entry-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After the NetSuite factory function exists (TASK-923), it needs to be registered
relates_to:
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
---

# TASK-924: NetSuite Registry Entry & Factory Map

**Feature**: FEAT-135 — NetSuite MCP Integration
**Spec**: `sdd/specs/netsuite-mcp-integration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-923
**Assigned-to**: unassigned

---

## Context

After the NetSuite factory function exists (TASK-923), it needs to be registered
in the MCP server catalog so it can be discovered and activated via the MCP helper
HTTP endpoint. This task adds a `MCPServerDescriptor` entry to `_REGISTRY` and
a `"netsuite"` entry to `get_factory_map()`.

Implements Spec §3 Module 3.

---

## Scope

- Add `MCPServerDescriptor` entry for NetSuite to `_REGISTRY` list in `registry.py`
- Add `"netsuite"` → `create_netsuite_mcp_server` mapping in `get_factory_map()`
- Params: `account_id` (STRING, required), `client_id` (SECRET, required), `user_id` (STRING, required)
- Category: `"erp"`
- Method name: `"add_netsuite_mcp_server"`

**NOT in scope**: Factory function (TASK-923), VaultTokenStore (TASK-922), tests (TASK-925)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/registry.py` | MODIFY | Add NetSuite descriptor to `_REGISTRY` and factory map entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.mcp.registry import MCPServerDescriptor, MCPServerParam, MCPParamType
    # verified: packages/ai-parrot/src/parrot/mcp/registry.py:62, :44, :37
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/mcp/registry.py:62
class MCPServerDescriptor(BaseModel):
    name: str           # Registry slug, e.g. "perplexity"
    display_name: str   # Human-friendly name
    description: str    # What this MCP server does
    method_name: str    # MCPEnabledMixin method to call
    params: List[MCPServerParam]
    category: str = "general"
    activatable: bool = True

# packages/ai-parrot/src/parrot/mcp/registry.py:44
class MCPServerParam(BaseModel):
    name: str
    type: MCPParamType  # STRING, INTEGER, BOOLEAN, SECRET
    required: bool = True
    default: Optional[Any] = None
    description: str = ""

# packages/ai-parrot/src/parrot/mcp/registry.py:37
class MCPParamType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    SECRET = "secret"

# packages/ai-parrot/src/parrot/mcp/registry.py:145
_REGISTRY: List[MCPServerDescriptor] = [
    MCPServerDescriptor(
        name="perplexity",
        display_name="Perplexity AI",
        description="Web search, conversational AI, deep research...",
        method_name="add_perplexity_mcp_server",
        category="search",
        params=[
            MCPServerParam(name="api_key", type=MCPParamType.SECRET, required=True, description="..."),
        ],
    ),
    # ... more entries ...
]

# packages/ai-parrot/src/parrot/mcp/registry.py:439
def get_factory_map() -> Dict[str, Any]:
    from parrot.mcp.integration import (
        create_alphavantage_mcp_server,
        create_chrome_devtools_mcp_server,
        create_fireflies_mcp_server,
        create_google_maps_mcp_server,
        create_perplexity_mcp_server,
        create_quic_mcp_server,
        create_websocket_mcp_server,
    )
    return {
        "perplexity": create_perplexity_mcp_server,
        "fireflies": create_fireflies_mcp_server,
        # ...
    }
```

### Does NOT Exist

- ~~`_REGISTRY` entry for `"netsuite"`~~ — does not exist yet; this task creates it
- ~~`get_factory_map()["netsuite"]`~~ — does not exist yet; this task adds it
- ~~`MCPParamType.OAUTH`~~ — no such type; use `SECRET` for `client_id`

---

## Implementation Notes

### Pattern to Follow

Add the descriptor entry to `_REGISTRY` following the existing pattern. Place it
at the end of the list, before the closing `]`:

```python
MCPServerDescriptor(
    name="netsuite",
    display_name="NetSuite (Oracle)",
    description=(
        "NetSuite ERP record CRUD, reports, saved searches, and SuiteQL "
        "queries via the NetSuite AI Connector Service (MCP). "
        "Requires OAuth2 Authorization Code + PKCE."
    ),
    method_name="add_netsuite_mcp_server",
    category="erp",
    params=[
        MCPServerParam(
            name="account_id",
            type=MCPParamType.STRING,
            required=True,
            description="NetSuite account ID (e.g. '4984231')",
        ),
        MCPServerParam(
            name="client_id",
            type=MCPParamType.SECRET,
            required=True,
            description="OAuth2 client ID from NetSuite integration record",
        ),
        MCPServerParam(
            name="user_id",
            type=MCPParamType.STRING,
            required=True,
            description="User identifier for token storage scoping",
        ),
    ],
),
```

For `get_factory_map()`, add the import and mapping:

```python
def get_factory_map() -> Dict[str, Any]:
    from parrot.mcp.integration import (
        create_alphavantage_mcp_server,
        create_chrome_devtools_mcp_server,
        create_fireflies_mcp_server,
        create_google_maps_mcp_server,
        create_netsuite_mcp_server,       # ← ADD
        create_perplexity_mcp_server,
        create_quic_mcp_server,
        create_websocket_mcp_server,
    )
    return {
        # ... existing entries ...
        "netsuite": create_netsuite_mcp_server,   # ← ADD
    }
```

### Key Constraints

- Keep imports alphabetically sorted in `get_factory_map()`
- `client_id` is `SECRET` type (it's an OAuth credential)
- `account_id` is `STRING` (it's a non-secret identifier)

---

## Acceptance Criteria

- [ ] NetSuite `MCPServerDescriptor` entry exists in `_REGISTRY`
- [ ] Registry entry has correct `name`, `display_name`, `method_name`, `category`, `params`
- [ ] `get_factory_map()` returns `create_netsuite_mcp_server` for key `"netsuite"`
- [ ] Import in `get_factory_map()` is alphabetically sorted
- [ ] `MCPServerRegistry().get_server("netsuite")` returns the descriptor

---

## Test Specification

```python
# tests/mcp/test_netsuite_mcp.py (partial — registry tests)
import pytest
from parrot.mcp.registry import MCPServerRegistry, get_factory_map


class TestNetsuiteRegistry:
    def test_netsuite_in_registry(self):
        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        assert desc is not None
        assert desc.name == "netsuite"
        assert desc.method_name == "add_netsuite_mcp_server"
        assert desc.category == "erp"

    def test_netsuite_params(self):
        registry = MCPServerRegistry()
        desc = registry.get_server("netsuite")
        param_names = [p.name for p in desc.params]
        assert "account_id" in param_names
        assert "client_id" in param_names
        assert "user_id" in param_names

    def test_netsuite_in_factory_map(self):
        fmap = get_factory_map()
        assert "netsuite" in fmap
        assert callable(fmap["netsuite"])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/netsuite-mcp-integration.spec.md` for full context
2. **Check dependencies** — verify TASK-923 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `_REGISTRY` list and `get_factory_map()` location
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the registry entry and factory map addition
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-924-netsuite-registry-entry.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-04-29
**Notes**: Added MCPServerDescriptor for netsuite to _REGISTRY with 3 params (account_id STRING, client_id SECRET, user_id STRING), category=erp, method_name=add_netsuite_mcp_server. Added create_netsuite_mcp_server to get_factory_map() with alphabetically sorted imports.

**Deviations from spec**: none
