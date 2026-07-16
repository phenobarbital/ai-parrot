---
type: Wiki Overview
title: 'TASK-1038: MCP HTTP handshake validator'
id: doc:sdd-tasks-completed-task-1038-mcp-handshake-validator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.mcp.config import MCPServerConfig # parrot/mcp/config.py:16'
relates_to:
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.config
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
---

# TASK-1038: MCP HTTP handshake validator

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> During ephemeral agent warm-up, each MCP HTTP server configured by the user must be
> validated: connect, list tools once, and confirm the server is reachable (spec §3 Module 8).
> If validation fails, the agent stays in `status=error` and cannot be promoted.

---

## Scope

- Implement `async def validate_mcp_http(config: MCPServerConfig) -> None` in `parrot/mcp/integration.py`.
  - Create an `MCPClient` instance from the config.
  - Call `await client.connect()`.
  - Call `await client.get_available_tools()` to confirm tool listing works.
  - Call `await client.disconnect()`.
  - On any error (connection refused, timeout, protocol error), raise a typed exception with a human-readable message.
- Define a `MCPValidationError(Exception)` in the same module for typed error handling.
- Write unit tests with a stub HTTP server.

**NOT in scope**: Warm-up orchestration (Module 3), stdio MCP support (explicitly out of scope per spec §7).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/mcp/integration.py` | MODIFY | Add `validate_mcp_http` function and `MCPValidationError` |
| `tests/unit/test_mcp_validator.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.config import MCPServerConfig                        # parrot/mcp/config.py:16
from parrot.mcp.integration import MCPClient                         # parrot/mcp/integration.py:309
```

### Existing Signatures to Use
```python
# parrot/mcp/integration.py:309
class MCPClient:
    async def connect(self): ...                                     # line 345
    async def get_available_tools(self) -> List[Dict[str, Any]]: ... # line 402
    async def disconnect(self): ...                                  # line 628

# parrot/mcp/config.py:16
class MCPServerConfig:
    # Contains server URL, auth, transport type, etc.
    ...
```

### Does NOT Exist
- ~~`validate_mcp_http`~~ — does not exist yet; this task creates it.
- ~~`MCPClient.validate()`~~ — no built-in validation method.
- ~~`MCPClient.ping()`~~ — no ping method; use `connect()` + `get_available_tools()`.

---

## Implementation Notes

### Pattern to Follow
```python
class MCPValidationError(Exception):
    """Raised when an MCP HTTP server fails handshake validation."""

async def validate_mcp_http(config: MCPServerConfig) -> None:
    client = MCPClient(config)
    try:
        await client.connect()
        tools = await client.get_available_tools()
        if not isinstance(tools, list):
            raise MCPValidationError(f"Unexpected tool listing response from {config.url}")
    except MCPValidationError:
        raise
    except Exception as exc:
        raise MCPValidationError(
            f"MCP handshake failed for {config.url}: {exc}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()
```

### Key Constraints
- Always disconnect in `finally` — even on error.
- Timeout: use whatever timeout `MCPClient.connect()` already supports. If no timeout exists, wrap with `asyncio.wait_for(..., timeout=30)`.
- HTTP-only for now — stdio MCP is explicitly out of scope per spec §7.

### References in Codebase
- `parrot/mcp/integration.py:309` — `MCPClient` class
- `parrot/mcp/integration.py:345` — `connect()` method
- `parrot/mcp/integration.py:402` — `get_available_tools()` method

---

## Acceptance Criteria

- [ ] `validate_mcp_http` succeeds (no exception) when the MCP server is reachable and lists tools.
- [ ] `validate_mcp_http` raises `MCPValidationError` with a human-readable message on connection failure.
- [ ] `validate_mcp_http` raises `MCPValidationError` on timeout.
- [ ] Client is always disconnected, even on error.
- [ ] All tests pass: `pytest tests/unit/test_mcp_validator.py -v`
- [ ] No linting errors: `ruff check parrot/mcp/integration.py`
- [ ] Import works: `from parrot.mcp.integration import validate_mcp_http, MCPValidationError`

---

## Test Specification

```python
# tests/unit/test_mcp_validator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.mcp.integration import validate_mcp_http, MCPValidationError
from parrot.mcp.config import MCPServerConfig


class TestValidateMCPHTTP:
    async def test_success_with_valid_server(self):
        config = MagicMock(spec=MCPServerConfig)
        with patch("parrot.mcp.integration.MCPClient") as MockClient:
            client = MockClient.return_value
            client.connect = AsyncMock()
            client.get_available_tools = AsyncMock(return_value=[{"name": "tool1"}])
            client.disconnect = AsyncMock()
            await validate_mcp_http(config)
            client.connect.assert_called_once()
            client.disconnect.assert_called_once()

    async def test_connection_refused(self):
        config = MagicMock(spec=MCPServerConfig)
        with patch("parrot.mcp.integration.MCPClient") as MockClient:
            client = MockClient.return_value
            client.connect = AsyncMock(side_effect=ConnectionRefusedError())
            client.disconnect = AsyncMock()
            with pytest.raises(MCPValidationError, match="handshake failed"):
                await validate_mcp_http(config)

    async def test_timeout(self):
        config = MagicMock(spec=MCPServerConfig)
        with patch("parrot.mcp.integration.MCPClient") as MockClient:
            client = MockClient.return_value
            client.connect = AsyncMock(side_effect=TimeoutError())
            client.disconnect = AsyncMock()
            with pytest.raises(MCPValidationError):
                await validate_mcp_http(config)

    async def test_disconnect_always_called(self):
        config = MagicMock(spec=MCPServerConfig)
        with patch("parrot.mcp.integration.MCPClient") as MockClient:
            client = MockClient.return_value
            client.connect = AsyncMock()
            client.get_available_tools = AsyncMock(side_effect=RuntimeError("boom"))
            client.disconnect = AsyncMock()
            with pytest.raises(MCPValidationError):
                await validate_mcp_http(config)
            client.disconnect.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 8.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** — read `parrot/mcp/integration.py` MCPClient class.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** `validate_mcp_http` and `MCPValidationError`.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `MCPValidationError` and `validate_mcp_http()` added to tail of `parrot/mcp/integration.py`. `contextlib` added to imports. The function uses the existing `MCPClient` class; disconnect is always called in `finally` via `contextlib.suppress`. 12 unit tests pass using `patch.object` on the live module to work around the worktree's lack of a real `parrot.mcp` package namespace.

**Deviations from spec**: none
