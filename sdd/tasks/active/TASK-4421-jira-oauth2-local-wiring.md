# TASK-4421: Toolkit Wiring for oauth2_local

**Feature**: FEAT-696 — JiraToolkit upgrades
**Spec**: `sdd/specs/jiratoolkit-upgrades.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4419, TASK-4420
**Assigned-to**: unassigned

---

## Context

> Implements spec Module 4 — wires `auth_type="oauth2_local"` into
> `JiraToolkit.__init__` and `_pre_execute`. This is the security-sensitive
> task: it normalises `oauth2_local` to the existing `oauth2_3lo` code path
> with a single-user bypass, and adds the identity guard (S9). Depends on
> TASK-4419 (local store) and TASK-4420 (parity tools — serialized because
> both modify `jiratoolkit.py`). Also modifies `jira_config.py`.

---

## Scope

- In `__init__`: when `auth_type="oauth2_local"`, build `FileTokenCredentialResolver.from_env()`
  if no resolver was passed, then set `self.auth_type = "oauth2_3lo"` and
  `self._local_single_user = True`.
- In `_pre_execute`: when `_local_single_user`, allow missing PermissionContext /
  user_id with a fixed key `"local:cli"`. Add identity guard: if a
  PermissionContext IS present, its `channel` must be in `allowed_channels`.
- Modify `jira_config.py`: add `"oauth2_local"` to `auth_type` literal and
  `knowledge_base: str | None` field.
- Write tests for the wiring and identity guard.

**NOT in scope**: the new tools (TASK-4420), the local store (TASK-4419),
CLI (TASK-4422), or KB model (TASK-4417).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | `__init__` + `_pre_execute` changes |
| `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` | MODIFY | Add `oauth2_local` + `knowledge_base` |
| `packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.jira_local_auth import FileTokenCredentialResolver  # created by TASK-4419
from parrot.auth.exceptions import AuthorizationRequired               # verified: jiratoolkit.py:60
```

### Existing Signatures to Use
```python
# jiratoolkit.py
class JiraToolkit(AbstractToolkit):                                     # L742
    def __init__(self, ..., credential_resolver: Any = None, ...):      # L844
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:  # L1242
    # L1251: if self.auth_type != "oauth2_3lo": ... return None
    # L1263: perm_ctx = kwargs.get("_permission_context")
    # L1276: user_id = getattr(perm_ctx, "user_id", None)
    # L1286: user_key = f"{channel}:{user_id}"

# jira_config.py:19
    auth_type: Literal["basic_auth", "token_auth", "oauth"] | None = None
```

### Does NOT Exist
- ~~`self._local_single_user`~~ — does not exist yet; this task adds it
- ~~`JiraToolkitConfig.knowledge_base`~~ — does not exist yet; this task adds it
- ~~`"oauth2_local"` in `jira_config.py` Literal~~ — not yet; this task adds it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit._pre_execute",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jira_config.py#JiraToolkitConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The normalisation (`self.auth_type = "oauth2_3lo"`) means all 11 existing
  `oauth2_3lo` branches work untouched — only the `_pre_execute` guard changes.
- The identity guard (S9) MUST reject a PermissionContext with a channel not
  in `allowed_channels`. Default channels: `{"cli", "local"}`.
- The single-user bypass in `_pre_execute` must be reachable ONLY through
  `oauth2_local`. A server deploy using `oauth2_3lo` must still require a
  PermissionContext.

---

## Implementation Blueprint

### Steps (in order)
1. Modify `jira_config.py` — *why*: add `oauth2_local` to the Literal and `knowledge_base` field.
2. Modify `__init__` in `jiratoolkit.py` — *why*: normalise `oauth2_local` to `oauth2_3lo`.
3. Modify `_pre_execute` — *why*: add single-user bypass with identity guard.
4. Write tests — *why*: validates the wiring and the guard.

### `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'auth_type: Literal\["basic_auth", "token_auth", "oauth"\]' packages/ai-parrot-tools/src/parrot_tools/jira_config.py)
# REPLACE `auth_type: Literal["basic_auth", "token_auth", "oauth"] | None = None` (verified: jira_config.py:19)
    auth_type: Literal["basic_auth", "token_auth", "oauth", "oauth2_local"] | None = None
    knowledge_base: str | None = Field(default=None, description="Path to YAML knowledge base file")
```
**Why**: spec §2 M4 — `JiraToolkitConfig` gains the new auth type and KB path.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)

**`__init__` — after resolving `_configured_auth`:**
```python
# FILL IN: After L888 (self.auth_type = _configured_auth.lower()), add:
#   if self.auth_type == "oauth2_local":
#       if credential_resolver is None:
#           credential_resolver = FileTokenCredentialResolver.from_env()
#       self.auth_type = "oauth2_3lo"
#       self._local_single_user = True
#   else:
#       self._local_single_user = False
# — bounded by spec §2 M4
```

**`_pre_execute` — after L1251 `if self.auth_type != "oauth2_3lo":`:**
```python
# occurrences: 1 (verified: grep -c 'if self.auth_type != "oauth2_3lo":' packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py)
# MODIFY the block starting at L1251

# FILL IN: After the early-return for non-oauth2_3lo (L1261), add:
#   if self._local_single_user:
#       perm_ctx = kwargs.get("_permission_context")
#       if perm_ctx is not None:
#           channel = getattr(perm_ctx, "channel", None) or "unknown"
#           if channel not in self.credential_resolver.allowed_channels:
#               raise AuthorizationRequired(...)  # S9 identity guard
#       user_key = "local:cli"
#       token_set = await self.credential_resolver.resolve("cli", "local")
#       ... (cache lookup, client init — same as the existing block)
#       return None
# — bounded by spec §2 M4, S9, AC10b
```

### `packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py` (CREATE)
```python
"""Tests for oauth2_local toolkit wiring (FEAT-696 M4)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOAuth2LocalMode:
    @pytest.mark.asyncio
    async def test_toolkit_runs_without_permission_context(self):
        # FILL IN: construct JiraToolkit(auth_type="oauth2_local") with mocked resolver,
        #          call a tool without PermissionContext — should succeed
        #          — bounded by spec §4 test_oauth2_local_mode
        pass

    @pytest.mark.asyncio
    async def test_oauth2_3lo_still_requires_permission_context(self):
        # FILL IN: construct JiraToolkit(auth_type="oauth2_3lo") with a resolver,
        #          call a tool without PermissionContext — should raise AuthorizationRequired
        #          — bounded by spec §7 "single-user bypass"
        pass


class TestIdentityGuard:
    @pytest.mark.asyncio
    async def test_rejects_disallowed_channel(self):
        # FILL IN: oauth2_local + PermissionContext(channel="telegram") → AuthorizationRequired
        #          — bounded by spec §4 test_local_identity_guard, AC10b
        pass

    @pytest.mark.asyncio
    async def test_allows_cli_channel(self):
        # FILL IN: oauth2_local + PermissionContext(channel="cli") → succeeds
        #          — bounded by AC10b
        pass


class TestJiraConfig:
    def test_oauth2_local_valid(self):
        from parrot_tools.jira_config import JiraToolkitConfig
        cfg = JiraToolkitConfig(auth_type="oauth2_local", knowledge_base="/tmp/kb.yaml")
        assert cfg.auth_type == "oauth2_local"
        assert cfg.knowledge_base == "/tmp/kb.yaml"
```
**Why this shape**: spec §4 test rows for M4.

### FILL IN checklist
- [ ] `jiratoolkit.py::__init__` — oauth2_local normalisation; bounded by spec §2 M4
- [ ] `jiratoolkit.py::_pre_execute` — single-user bypass + identity guard; bounded by AC10b, S9
- [ ] `test_oauth2_local_wiring.py` — all test bodies; bounded by spec §4 M4

---

## Acceptance Criteria

- [ ] With `JIRA_AUTH_TYPE=oauth2_local`, an expired token is refreshed and persisted (AC5)
- [ ] `oauth2_3lo` behaviour is unchanged; existing tests pass (AC6)
- [ ] `oauth2_local` refuses a PermissionContext whose channel is not in `allowed_channels` (AC10b)
- [ ] `JiraToolkitConfig` accepts `auth_type="oauth2_local"` and `knowledge_base`
- [ ] `ruff check` clean; no new dependency

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py -q`

---

## Test Specification

See `test_oauth2_local_wiring.py` in the blueprint above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug jiratoolkit-upgrades --feature-id FEAT-696`
2. **Read the spec** at `sdd/specs/jiratoolkit-upgrades.spec.md` — especially §2 M4 and §7
3. **Check dependencies** — TASK-4419 and TASK-4420 must be `"done"`
4. **Verify the Codebase Contract** — re-read `_pre_execute` and `__init__` (anchors may have shifted from TASK-4420)
5. **Update status** in `sdd/tasks/index/jiratoolkit-upgrades.json` → `"in-progress"`
6. **Implement** — modify `__init__`, `_pre_execute`, `jira_config.py`
7. **Verify** — run validation; also run existing oauth tests for AC6
8. **Commit** — stage `jiratoolkit.py`, `jira_config.py`, `test_oauth2_local_wiring.py`
9. **Close** with `scripts/sdd/close_task.sh TASK-4421 jiratoolkit-upgrades verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
