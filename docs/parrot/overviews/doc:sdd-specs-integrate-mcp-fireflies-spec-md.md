---
type: Wiki Overview
title: 'Feature Specification: Integrate FIREFLIES_API_KEY env-var support into the
  MCP Client definition'
id: doc:sdd-specs-integrate-mcp-fireflies-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The Fireflies.ai MCP server is already wired into the MCP Client definition
relates_to:
- concept: mod:parrot.mcp
  rel: mentions
- concept: mod:parrot.mcp.integration
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Integrate FIREFLIES_API_KEY env-var support into the MCP Client definition

**Feature ID**: FEAT-237
**Date**: 2026-06-15
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement
The Fireflies.ai MCP server is already wired into the MCP Client definition
(`parrot.mcp`): there is a `create_fireflies_mcp_server` factory, an
`add_fireflies_mcp_server` mixin method, a registry descriptor, and a
factory-map entry. However — unlike the sibling AlphaVantage and Perplexity
servers — the Fireflies helpers require the caller to pass `api_key`
**explicitly** and have **no fallback to an environment variable**.

This is inconsistent with the rest of the catalog and forces every call site
(examples, agent code, the activation endpoint) to hard-code or hand-wire the
key. The goal is to let the credential be supplied via the
`FIREFLIES_API_KEY` environment variable (through `navconfig.config`), exactly
the way `create_alphavantage_mcp_server` already resolves
`ALPHAVANTAGE_API_KEY`.

### Goals
- `create_fireflies_mcp_server` reads `FIREFLIES_API_KEY` from
  `navconfig.config` as a fallback when `api_key` is not passed explicitly.
- An explicit `api_key` argument always wins over the env var.
- When neither is supplied, a clear `ValueError("FIREFLIES_API_KEY is
  required")` is raised (parity with AlphaVantage).
- `add_fireflies_mcp_server` accepts an optional `api_key` (env fallback).
- The registry descriptor for `fireflies` marks `api_key` as
  `required=False` (with `default=None`), so the catalog and the activation
  endpoint treat it as optional and rely on the env var — full parity with the
  `alphavantage` descriptor.
- Existing behaviour (Bearer-prefixed `Authorization` header, `npx mcp-remote`
  stdio transport) is unchanged.

### Non-Goals (explicitly out of scope)
- No change to the Fireflies transport (`stdio` via `npx mcp-remote`),
  endpoint URL, or the `Authorization: Bearer <key>` header construction.
- No change to the Vault/per-user secret-storage path for *other* secret
  params; this spec only relaxes the Fireflies descriptor to allow an env-var
  fallback.
- No new MCP servers and no changes to other servers' helpers.
- No CLI/wizard UI work.

---

## 2. Architectural Design

### Overview
Apply the AlphaVantage env-var-fallback pattern to Fireflies across the three
layers of the MCP Client definition:

1. **Factory** (`parrot/mcp/integration.py::create_fireflies_mcp_server`) —
   change the signature from a required keyword-only `api_key: str` to
   `api_key: Optional[str] = None`, then resolve
   `api_key = api_key or config.get('FIREFLIES_API_KEY')` and raise
   `ValueError` if still empty. `config` is already imported at the top of the
   module (`from navconfig import BASE_DIR, config`).

2. **Mixin method** (`parrot/mcp/integration.py::MCPEnabledMixin.add_fireflies_mcp_server`)
   — relax `api_key: str` to `api_key: Optional[str] = None` and forward it
   unchanged to the factory (which now performs the env fallback).

3. **Registry descriptor** (`parrot/mcp/registry.py`, the `fireflies`
   `MCPServerDescriptor`) — flip the `api_key` `MCPServerParam` from
   `required=True` to `required=False`, add `default=None`, and update its
   `description` to mention the `FIREFLIES_API_KEY` fallback (mirroring the
   `alphavantage` descriptor wording).

The resolution precedence is: **explicit argument → `FIREFLIES_API_KEY` env
var → error**.

### Component Diagram
```
caller / activation endpoint
        │  api_key (optional)
        ▼
add_fireflies_mcp_server (mixin)
        │
        ▼
create_fireflies_mcp_server ──→ config.get('FIREFLIES_API_KEY')  [fallback]
        │                              (navconfig)
        ▼
MCPServerConfig(stdio, npx mcp-remote, "Authorization: Bearer <key>")

MCPServerRegistry.fireflies descriptor: api_key required=False, default=None
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `navconfig.config` | uses | `config.get('FIREFLIES_API_KEY')` fallback; already imported in `integration.py` |
| `create_alphavantage_mcp_server` | mirrors | reference implementation of the exact pattern |
| `MCPServerRegistry` / `validate_params` | uses | `required=False` lets validation pass without `api_key`; default `None` is filled in |
| `MCPEnabledMixin.add_mcp_server` | uses | unchanged downstream call |

### Data Models
No new data models. Only an attribute change on the existing `fireflies`
`MCPServerDescriptor` entry (`required`, `default`, `description` of the
`api_key` `MCPServerParam`).

### New Public Interfaces
No new public interfaces. Signature relaxations only (backward compatible —
existing positional/keyword `api_key="..."` calls keep working):

```python
# parrot/mcp/integration.py
def create_fireflies_mcp_server(
    *,
    api_key: Optional[str] = None,
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs,
) -> MCPServerConfig: ...

class MCPEnabledMixin:
    async def add_fireflies_mcp_server(
        self,
        api_key: Optional[str] = None,
        **kwargs,
    ) -> List[str]: ...
```

---

## 3. Module Breakdown

> Single-module change across two existing files. One sequential task.

### Module 1: Fireflies factory + mixin env fallback
- **Path**: `packages/ai-parrot/src/parrot/mcp/integration.py`
- **Responsibility**:
  - `create_fireflies_mcp_server`: `api_key` → `Optional[str] = None`;
    `api_key = api_key or config.get('FIREFLIES_API_KEY')`; raise
    `ValueError("FIREFLIES_API_KEY is required")` when empty. Update the
    docstring to note the env-var fallback.
  - `add_fireflies_mcp_server`: `api_key` → `Optional[str] = None`; update the
    docstring/example.
- **Depends on**: existing `config` import (already present, line 9).

### Module 2: Registry descriptor relaxation
- **Path**: `packages/ai-parrot/src/parrot/mcp/registry.py`
- **Responsibility**: in the `fireflies` `MCPServerDescriptor` (lines
  164–181), change the `api_key` `MCPServerParam` to `required=False`,
  `default=None`, and a description that mentions the `FIREFLIES_API_KEY`
  fallback (mirror the `alphavantage` descriptor at lines ~247–265).
- **Depends on**: Module 1 conceptually (same feature), but the files are
  independent edits.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_create_fireflies_uses_explicit_key` | Module 1 | Explicit `api_key="X"` wins; the resulting `MCPServerConfig.args` contain `Authorization: Bearer X` |
| `test_create_fireflies_falls_back_to_env` | Module 1 | With `api_key` omitted and `FIREFLIES_API_KEY` set (monkeypatch `config`/env), the key is resolved from the env var |
| `test_create_fireflies_missing_key_raises` | Module 1 | No arg and no env var → `ValueError` mentioning `FIREFLIES_API_KEY` |
| `test_get_server_fireflies` (update) | Module 2 | Existing test in `test_mcp_registry.py` (lines 57–62) — extend/keep; it must still pass |
| `test_validate_params_fireflies_optional_key` | Module 2 | `registry.validate_params("fireflies", {})` no longer raises and fills `api_key=None` (parity with the existing `chrome-devtools` defaults test) |

### Integration Tests
| Test | Description |
|---|---|
| (manual / example) `examples/test_fireflies_bearer_auth.py` | Still works when `api_key` is passed; should also work when omitted and `FIREFLIES_API_KEY` is exported |

### Test Data / Fixtures
```python
# Pattern mirrors existing tests in packages/ai-parrot/tests/unit/test_mcp_registry.py
@pytest.fixture
def registry() -> MCPServerRegistry:
    return MCPServerRegistry()

def test_create_fireflies_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("FIREFLIES_API_KEY", "env-key-123")
    # also patch navconfig.config.get if it caches at import time
    cfg = create_fireflies_mcp_server()
    assert any("env-key-123" in a for a in cfg.args)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `create_fireflies_mcp_server()` resolves the key from
      `config.get('FIREFLIES_API_KEY')` when `api_key` is not passed.
- [ ] An explicit `api_key` argument takes precedence over the env var.
- [ ] Missing key (no arg, no env var) raises
      `ValueError("FIREFLIES_API_KEY is required")`.
- [ ] `add_fireflies_mcp_server(api_key=None)` works and delegates the
      fallback to the factory.
- [ ] The `fireflies` registry descriptor's `api_key` param is
      `required=False`, `default=None`, and its description mentions the
      `FIREFLIES_API_KEY` env-var fallback.
- [ ] `registry.validate_params("fireflies", {})` no longer raises.
- [ ] Existing Bearer-header / stdio transport behaviour is unchanged
      (regression: `Authorization: Bearer <key>` still produced).
- [ ] No breaking change to existing `api_key="..."` call sites
      (`examples/test_fireflies_bearer_auth.py` still runs).
- [ ] All unit tests pass:
      `pytest packages/ai-parrot/tests/unit/test_mcp_registry.py -v`
      and the new factory tests.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> All references below verified by `read`/`grep` on branch `dev` on 2026-06-15.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/mcp/integration.py:9  (already present)
from navconfig import BASE_DIR, config

# Registry data models — packages/ai-parrot/src/parrot/mcp/registry.py
#   MCPServerDescriptor  (registry.py:62)
#   MCPServerParam       (registry.py:44)
#   MCPParamType         (registry.py:30)  → MCPParamType.SECRET
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/mcp/integration.py:1028
def create_fireflies_mcp_server(
    *,
    api_key: str,                                   # ← change to Optional[str] = None
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs,
) -> MCPServerConfig:
    # builds: command="npx", args=["mcp-remote", api_base,
    #         "--header", f"Authorization: Bearer {api_key}"], transport="stdio"

# packages/ai-parrot/src/parrot/mcp/integration.py:1348  (inside MCPEnabledMixin)
async def add_fireflies_mcp_server(
    self,
    api_key: str,                                   # ← change to Optional[str] = None
    **kwargs,
) -> List[str]:
    config = create_fireflies_mcp_server(api_key=api_key, **kwargs)
    return await self.add_mcp_server(config)

# REFERENCE PATTERN — packages/ai-parrot/src/parrot/mcp/integration.py:1232
def create_alphavantage_mcp_server(
    api_key: Optional[str] = None,
    name: str = "alphavantage",
    **kwargs,
) -> MCPServerConfig:
    api_key = api_key or config.get('ALPHAVANTAGE_API_KEY')
    if not api_key:
        raise ValueError("ALPHAVANTAGE_API_KEY is required")
    ...

# packages/ai-parrot/src/parrot/mcp/registry.py:164-181  (fireflies descriptor — CURRENT)
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
            required=True,                          # ← change to False
            # add: default=None
            description="Fireflies API key from app.fireflies.ai/account",  # ← mention env fallback
        ),
    ],
),

# REFERENCE — alphavantage descriptor (registry.py ~247-265): api_key required=False, default=None,
#   description="Alpha Vantage API key (optional; falls back to ALPHAVANTAGE_API_KEY env var)"

# Factory map already includes fireflies — NO change needed:
#   packages/ai-parrot/src/parrot/mcp/registry.py:479 import create_fireflies_mcp_server
#   packages/ai-parrot/src/parrot/mcp/registry.py:490 "fireflies": create_fireflies_mcp_server
```

### validate_params behaviour (registry.py:418-463)
- Iterates `desc.params`; if a param name is absent and `required` → collected
  as missing → `ValueError`. If absent and **not** required → `cleaned[name] =
  param.default`. So flipping `required=False, default=None` makes
  `validate_params("fireflies", {})` succeed with `api_key=None`.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `create_fireflies_mcp_server` (modified) | `config.get` | env fallback | `integration.py:9` (import), pattern at `integration.py:1247` |
| `fireflies` descriptor (modified) | `MCPServerRegistry.validate_params` | `required`/`default` fields | `registry.py:418-463` |

### Does NOT Exist (Anti-Hallucination)
- ~~A `FIREFLIES_API_KEY` read anywhere today~~ — Fireflies currently has **no**
  env-var resolution; that is precisely what this feature adds.
- ~~`os.environ.get('FIREFLIES_API_KEY')` in `create_fireflies_mcp_server`~~ —
  does not exist yet. Prefer `config.get(...)` (navconfig) to match the
  AlphaVantage precedent, not raw `os.environ`.
- ~~A separate Fireflies config/settings module~~ — does not exist; the key
  flows through `navconfig.config`.
- ~~Changes to `parrot/integrations/mcp/`~~ — the MCP client lives at
  `packages/ai-parrot/src/parrot/mcp/`, NOT `parrot/integrations/mcp/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Copy the AlphaVantage pattern verbatim:
  `api_key = api_key or config.get('FIREFLIES_API_KEY')` then guard with
  `if not api_key: raise ValueError("FIREFLIES_API_KEY is required")`.
- Use `navconfig.config` (already imported), **not** raw `os.environ`, for the
  fallback — consistency with AlphaVantage (`config.get`).
- Keep the keyword-only (`*`) form of `create_fireflies_mcp_server`; only the
  default value of `api_key` changes. Backward compatible.
- Mirror the `alphavantage` descriptor's `api_key` `MCPServerParam` wording.

### Known Risks / Gotchas
- **Test regression**: `packages/ai-parrot/tests/unit/test_mcp_registry.py`
  has `test_get_server_fireflies` (lines 57–62). It currently asserts
  `method_name` and `category` only (NOT `required`), so flipping `required`
  should not break it — but verify, and add a positive test that
  `validate_params("fireflies", {})` succeeds.
- **Secret-in-args**: the resolved key is embedded in
  `args=[..., "Authorization: Bearer <key>"]`. This matches today's behaviour;
  do not log `args` at INFO. Note `logging.getLogger("MCPClient")` is set to
  INFO in this module.
- **navconfig caching**: `config` may snapshot the environment at import time;
  tests that set the env var should patch `parrot.mcp.integration.config.get`
  (or use navconfig's documented override) rather than only `monkeypatch.setenv`.
- **Descriptor relaxation implication**: with `required=False`, the activation
  endpoint can now activate Fireflies without an explicit key, relying on the
  server-side env var. This is the intended parity with AlphaVantage (resolved
  decision §8).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navconfig` | existing | `config.get('FIREFLIES_API_KEY')` (already a core dependency) |
| `mcp-remote` (npx, runtime) | existing | unchanged Fireflies transport proxy |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Scope of the env-var change — *Resolved with user (2026-06-15)*: Full
      parity with AlphaVantage — change the factory **and** the
      `add_fireflies_mcp_server` mixin to fall back to `FIREFLIES_API_KEY`,
      **and** flip the registry descriptor's `api_key` to `required=False`
      (`default=None`) so the catalog/activation endpoint treats it as optional.
- [x] Env source — *Resolved (follows AlphaVantage precedent)*: use
      `navconfig.config.get('FIREFLIES_API_KEY')`, not raw `os.environ`.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- Single feature, two-file edit (`integration.py`, `registry.py`) plus tests —
  one sequential task in one worktree. No parallelizable sub-tasks.
- **Cross-feature dependencies**: none. Operates entirely within the existing
  `parrot.mcp` subsystem on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-15 | Jesus Lara | Initial draft — FIREFLIES_API_KEY env fallback, full AlphaVantage parity |
