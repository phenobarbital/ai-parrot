---
type: Wiki Overview
title: 'TASK-1552: Fireflies MCP env-var key fallback (FIREFLIES_API_KEY)'
id: doc:sdd-tasks-completed-task-1552-fireflies-env-key-fallback-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Fireflies.ai MCP server is already wired into the MCP Client definition
relates_to:
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
- concept: mod:parrot.mcp.registry
  rel: mentions
---

# TASK-1552: Fireflies MCP env-var key fallback (FIREFLIES_API_KEY)

**Feature**: FEAT-237 — Integrate FIREFLIES_API_KEY env-var support into the MCP Client definition
**Spec**: `sdd/specs/integrate-mcp-fireflies.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The Fireflies.ai MCP server is already wired into the MCP Client definition
(`parrot.mcp`), but — unlike the sibling AlphaVantage/Perplexity servers — its
helpers require an explicit `api_key` and have **no** fallback to an
environment variable. This task brings Fireflies to full parity with the
AlphaVantage pattern: resolve the credential from `FIREFLIES_API_KEY` (via
`navconfig.config`) when no key is passed, and relax the registry descriptor so
the catalog/activation endpoint treats `api_key` as optional.

Implements the entire spec (Modules 1 and 2 of §3, §4 Test Specification, §5
Acceptance Criteria). Single sequential task per the spec's Worktree Strategy.

---

## Scope

- **Modify `create_fireflies_mcp_server`** (`integration.py`): change
  `api_key: str` (required, keyword-only) → `api_key: Optional[str] = None`.
  Before building the config, resolve:
  `api_key = api_key or config.get('FIREFLIES_API_KEY')`, and if still empty
  raise `ValueError("FIREFLIES_API_KEY is required")`. Keep the keyword-only
  (`*`) form, the `api_base` default, the `npx mcp-remote` stdio transport, and
  the `Authorization: Bearer {api_key}` header unchanged. Update the docstring
  to document the env-var fallback.
- **Modify `add_fireflies_mcp_server`** (`integration.py`, inside
  `MCPEnabledMixin`): change `api_key: str` → `api_key: Optional[str] = None`;
  forward it unchanged to the factory (factory performs the fallback). Update
  the docstring/example.
- **Modify the `fireflies` `MCPServerDescriptor`** (`registry.py`): change the
  `api_key` `MCPServerParam` from `required=True` to `required=False`, add
  `default=None`, and reword the `description` to mention the
  `FIREFLIES_API_KEY` env-var fallback (mirror the `alphavantage` descriptor).
- **Add/extend tests** (`packages/ai-parrot/tests/unit/`): explicit-key wins,
  env-var fallback, missing-key raises, and `validate_params("fireflies", {})`
  no longer raises (fills `api_key=None`). Keep `test_get_server_fireflies`
  green.

**NOT in scope**:
- The `Authorization: Bearer` header construction, transport, or endpoint URL.
- Any other MCP server's helper or descriptor.
- The factory-map entry in `registry.py` (`"fireflies": create_fireflies_mcp_server`
  already exists — do NOT touch).
- Vault/per-user secret storage path for other params.
- Using raw `os.environ` — use `navconfig.config.get(...)`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | `create_fireflies_mcp_server` (line 1028) + `add_fireflies_mcp_server` (line 1348): optional `api_key` + env fallback |
| `packages/ai-parrot/src/parrot/mcp/registry.py` | MODIFY | `fireflies` descriptor (lines 164–181): `api_key` → `required=False`, `default=None`, updated description |
| `packages/ai-parrot/tests/unit/test_mcp_registry.py` | MODIFY | Add `test_validate_params_fireflies_optional_key`; keep `test_get_server_fireflies` green |
| `packages/ai-parrot/tests/unit/test_fireflies_env_key.py` | CREATE | Factory tests: explicit-key wins, env fallback, missing-key raises |

---

## Codebase Contract (Anti-Hallucination)

> All references verified by `read`/`grep` on branch `dev` on 2026-06-15.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/mcp/integration.py:9  (ALREADY PRESENT — do not re-add)
from navconfig import BASE_DIR, config

# Registry data models — packages/ai-parrot/src/parrot/mcp/registry.py
#   MCPServerDescriptor  (registry.py:62)
#   MCPServerParam       (registry.py:44)   fields: name, type, required(=True), default(=None), description
#   MCPParamType         (registry.py:30)   → MCPParamType.SECRET

# Tests import (see existing test_mcp_registry.py):
#   from parrot.mcp.registry import MCPServerRegistry
# Factory tests:
#   from parrot.mcp.integration import create_fireflies_mcp_server
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/integration.py:1028  — CURRENT (to change)
def create_fireflies_mcp_server(
    *,
    api_key: str,                                   # ← change to: api_key: Optional[str] = None
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs,
) -> MCPServerConfig:
    return MCPServerConfig(
        name="fireflies",
        command="npx",
        args=["mcp-remote", api_base, "--header", f"Authorization: Bearer {api_key}"],
        transport="stdio",
        **kwargs,
    )

# packages/ai-parrot/src/parrot/mcp/integration.py:1348  — CURRENT (to change), inside MCPEnabledMixin
async def add_fireflies_mcp_server(
    self,
    api_key: str,                                   # ← change to: api_key: Optional[str] = None
    **kwargs,
) -> List[str]:
    config = create_fireflies_mcp_server(api_key=api_key, **kwargs)
    return await self.add_mcp_server(config)

# REFERENCE PATTERN — packages/ai-parrot/src/parrot/mcp/integration.py:1232  (copy this shape)
def create_alphavantage_mcp_server(
    api_key: Optional[str] = None,
    name: str = "alphavantage",
    **kwargs,
) -> MCPServerConfig:
    api_key = api_key or config.get('ALPHAVANTAGE_API_KEY')
    if not api_key:
        raise ValueError("ALPHAVANTAGE_API_KEY is required")
    ...

# packages/ai-parrot/src/parrot/mcp/registry.py:164-181  — CURRENT fireflies descriptor (to change)
MCPServerDescriptor(
    name="fireflies",
    display_name="Fireflies.ai",
    description=(
        "Transcription, meeting notes, and conversation intelligence "
        "via the Fireflies.ai API."
    ),
    method_name="add_fireflies_mcp_server",
    category="productivity",
    params=[
        MCPServerParam(
            name="api_key",
            type=MCPParamType.SECRET,
            required=True,                          # ← change to: False
            # ← add: default=None,
            description="Fireflies API key from app.fireflies.ai/account",  # ← reword: mention FIREFLIES_API_KEY fallback
        ),
    ],
),

# REFERENCE — alphavantage descriptor (registry.py ~247-265): api_key required=False, default=None,
#   description="Alpha Vantage API key (optional; falls back to ALPHAVANTAGE_API_KEY env var)"

# validate_params (registry.py:418-463): absent + required → ValueError("Missing required parameter(s)...");
#   absent + not required → cleaned[name] = param.default. So required=False/default=None makes
#   validate_params("fireflies", {}) succeed with api_key=None.

# Existing registry test (packages/ai-parrot/tests/unit/test_mcp_registry.py:57-62) — MUST stay green:
#   asserts only desc.method_name == "add_fireflies_mcp_server" and desc.category == "productivity"
#   (does NOT assert required), so the descriptor change will not break it.
```

### Does NOT Exist
- ~~Any `FIREFLIES_API_KEY` read in the codebase today~~ — this task adds the first one.
- ~~`os.environ.get('FIREFLIES_API_KEY')` in `create_fireflies_mcp_server`~~ — use `config.get(...)` (navconfig) instead, matching AlphaVantage.
- ~~A separate Fireflies config/settings module~~ — the key flows through `navconfig.config`.
- ~~`parrot/integrations/mcp/`~~ — wrong path; the MCP client lives at `packages/ai-parrot/src/parrot/mcp/`.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror create_alphavantage_mcp_server (integration.py:1232) exactly:
def create_fireflies_mcp_server(
    *,
    api_key: Optional[str] = None,
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs,
) -> MCPServerConfig:
    api_key = api_key or config.get('FIREFLIES_API_KEY')
    if not api_key:
        raise ValueError("FIREFLIES_API_KEY is required")
    return MCPServerConfig(
        name="fireflies",
        command="npx",
        args=["mcp-remote", api_base, "--header", f"Authorization: Bearer {api_key}"],
        transport="stdio",
        **kwargs,
    )
```

### Key Constraints
- Use `navconfig.config.get('FIREFLIES_API_KEY')`, NOT raw `os.environ`.
- Resolution precedence: explicit argument → env var → `ValueError`.
- Keep `create_fireflies_mcp_server` keyword-only (`*`). Backward compatible —
  existing `api_key="..."` call sites must keep working.
- Do not log `args` at INFO (the resolved key is embedded in the header).
  Note `logging.getLogger("MCPClient")` is set to INFO in `integration.py`.
- `navconfig.config` may snapshot the env at import time; in tests, patch
  `parrot.mcp.integration.config.get` (e.g. `monkeypatch.setattr`) rather than
  relying solely on `monkeypatch.setenv`.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/integration.py:1232` — `create_alphavantage_mcp_server` (exact pattern).
- `packages/ai-parrot/src/parrot/mcp/registry.py` (~247-265) — `alphavantage` descriptor (exact descriptor parity).
- `packages/ai-parrot/tests/unit/test_mcp_registry.py:71-93` — existing `validate_params` test style (`test_validate_params_applies_defaults` for `chrome-devtools`).

---

## Acceptance Criteria

- [ ] `create_fireflies_mcp_server()` (no arg) resolves the key from `config.get('FIREFLIES_API_KEY')`.
- [ ] Explicit `api_key="X"` takes precedence over the env var; header is `Authorization: Bearer X`.
- [ ] No arg and no env var → `ValueError("FIREFLIES_API_KEY is required")`.
- [ ] `add_fireflies_mcp_server(api_key=None)` works (delegates fallback to the factory).
- [ ] `fireflies` descriptor `api_key` param is `required=False`, `default=None`, description mentions `FIREFLIES_API_KEY`.
- [ ] `registry.validate_params("fireflies", {})` no longer raises (returns `api_key=None`).
- [ ] Existing Bearer/stdio behaviour unchanged; existing `api_key="..."` callers unaffected.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_mcp_registry.py packages/ai-parrot/tests/unit/test_fireflies_env_key.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/integration.py packages/ai-parrot/src/parrot/mcp/registry.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_fireflies_env_key.py
import pytest
from parrot.mcp import integration
from parrot.mcp.integration import create_fireflies_mcp_server


def _header(cfg) -> str:
    # args = ["mcp-remote", api_base, "--header", "Authorization: Bearer <key>"]
    return cfg.args[-1]


def test_create_fireflies_uses_explicit_key(monkeypatch):
    """Explicit api_key wins over any env var."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: "env-key")
    cfg = create_fireflies_mcp_server(api_key="explicit-key")
    assert "Bearer explicit-key" in _header(cfg)


def test_create_fireflies_falls_back_to_env(monkeypatch):
    """With no api_key, resolve from FIREFLIES_API_KEY via navconfig.config."""
    monkeypatch.setattr(
        integration.config, "get",
        lambda key, *a, **k: "env-key-123" if key == "FIREFLIES_API_KEY" else None,
    )
    cfg = create_fireflies_mcp_server()
    assert "Bearer env-key-123" in _header(cfg)


def test_create_fireflies_missing_key_raises(monkeypatch):
    """No arg and no env var → ValueError mentioning FIREFLIES_API_KEY."""
    monkeypatch.setattr(integration.config, "get", lambda *a, **k: None)
    with pytest.raises(ValueError, match="FIREFLIES_API_KEY"):
        create_fireflies_mcp_server()


# packages/ai-parrot/tests/unit/test_mcp_registry.py (ADD to existing TestMCPServerRegistry)
def test_validate_params_fireflies_optional_key(self, registry):
    """api_key is optional for fireflies (env-var fallback); defaults to None."""
    result = registry.validate_params("fireflies", {})
    assert result["api_key"] is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/integrate-mcp-fireflies.spec.md` for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm `create_fireflies_mcp_server`
   (integration.py:1028), `add_fireflies_mcp_server` (integration.py:1348), and
   the `fireflies` descriptor (registry.py:164-181) still match before editing;
   re-grep if line numbers drifted.
4. **Update status** in `sdd/tasks/index/integrate-mcp-fireflies.json` → `"in-progress"`.
5. **Implement** following the scope and pattern above (mirror AlphaVantage).
6. **Run** the tests + ruff per Acceptance Criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-1552-fireflies-env-key-fallback.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented exactly as specified. Three changes made:
  1. `create_fireflies_mcp_server` in `integration.py`: `api_key: str` changed to
     `api_key: Optional[str] = None`; added `api_key = api_key or config.get('FIREFLIES_API_KEY')`
     and `if not api_key: raise ValueError("FIREFLIES_API_KEY is required")`. Docstring updated.
  2. `add_fireflies_mcp_server` in `integration.py` (MCPEnabledMixin): `api_key: str` changed
     to `api_key: Optional[str] = None`. Docstring updated with env-var fallback example.
  3. `fireflies` MCPServerDescriptor in `registry.py`: `api_key` param changed to
     `required=False`, `default=None`, description updated to mention `FIREFLIES_API_KEY` fallback.
  Created `test_fireflies_env_key.py` (7 tests) and added 2 tests to `test_mcp_registry.py`.
  All 37 tests pass. Pre-existing ruff issues in `integration.py` (F401 x3, F402 x1) are
  unchanged from before this feature — not introduced by this task.

**Deviations from spec**: none
