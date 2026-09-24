# TASK-3661: ToolkitConfigService (DocumentDB) + /toolkits/{slug}/me override endpoints

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3659, TASK-3660
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (6), §3 Module 8; brainstorm override policy; AC9 + AC10. Users store overrides
only for params the operator currently marks `user_overridable`; their secrets go under their
own user id. Saving an override clears the session marker so the next request rebuilds (TASK-3662).

---

## Scope

- `toolkit_persistence.py`: `COLLECTION = "user_toolkit_configs"`, `UserToolkitOverride`
  (user_id, agent_id, slug, params, secret_refs, updated_at ISO), `ToolkitConfigService` with
  `save` (upsert by the compound key), `load(user_id, agent_id)`, `remove(...) -> bool`,
  `revision(user_id, agent_id) -> str` (max `updated_at` or `""`). Mirror `MCPPersistenceService`.
- `toolkit_overrides.py`: `StudioUserToolkitOverrideHandler` for
  `/agents/{name}/toolkits/{slug}/me`: PBAC `astudio:toolkits:override` (no owner check — any
  authenticated user who can reach the agent). GET → masked override + the list of currently
  overridable params (from the agent spec via `AgentToolingStore.load`). PUT → keys ⊄
  `spec.user_overridable` → 422 `not_overridable` (details: offending names); secret params
  (per `secret_paths` on the toolkit schema) → vault under the caller's id, name
  `f"toolkit_{slug}_{agent}_user"`; mask sentinel keeps; save. DELETE → remove + delete vault entry.
- After PUT/DELETE: `session.pop(f"{name}_toolkit_overrides_rev", None)` on the request session
  (`await self._resolve_session()`).
- Register the route.

**NOT in scope**: applying overrides to sessions (TASK-3662).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | CREATE | UserToolkitOverride + ToolkitConfigService |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | CREATE | StudioUserToolkitOverrideHandler (GET/PUT/DELETE /me) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | Register the /me route |
| `packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py` | CREATE | Service + handler tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb  # verified: handlers/mcp_persistence.py:26
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential  # vault_utils.py
from parrot.tools.spec import SECRET_MASK  # TASK-3645
from parrot.tools.config_schema import secret_paths  # TASK-3646
from .tooling_store import AgentToolingStore  # TASK-3659
from .models import StudioError  # verified: toolkits.py:35
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py
@dataclass(slots=True)
class StudioUser: user_id: str; email; username; groups; is_superuser: bool = False  # :102-119
class StudioBaseView(BaseView):  # :121
    async def _get_user(self) -> StudioUser: ...                 # :164
    def _require_owner(self, resource_owner, user) -> None: ...  # :230 — raises web.HTTPForbidden; superuser bypass
    async def _pbac_gate(self, resource: str, action: str): ...  # :308 — returns a denial response or None
# packages/ai-parrot-server/src/parrot/handlers/studio/agents.py
class _StudioAgentsMixin:
    def _manager(self)  # :42 — request.app.get("bot_manager")
    def _registry(self)  # :46 — manager.registry
    async def _get_db_agent(self, name) -> BotModel | None  # :51 — `db = self.request.app.get("database")`;
        #   `async with await db.acquire() as conn: BotModel.Meta.connection = conn; await BotModel.get(name=name)`
    @staticmethod
    def _registry_agent_owner(meta) -> str | None  # :106 — str(bot_config.config["created_by"])
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py — handler pattern to copy (decorators + error helper + PBAC + owner):
@is_authenticated()
@user_session()
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):  # :217-219
    def _error(self, message, *, status, code=None, details=None):  # :227 → json_response(StudioError(...).model_dump(), status=)
    async def post(self):  # :286-316 — `if (denied := await self._pbac_gate("toolkits", "astudio:toolkits:assign")) is not None: return denied`
        # owner = str(db_agent.created_by) if db agent else self._registry_agent_owner(meta); self._require_owner(owner, user)
# packages/ai-parrot-server/src/parrot/handlers/studio/byok.py — vault error convention: `except RuntimeError` → 503 code="vault_unavailable" (:104-109)

# packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py
COLLECTION: str = "user_mcp_configs"  # :31
class MCPPersistenceService:  # :36
    async def save_user_mcp_config(self, config) -> None:  # :49 — `async with DocumentDb() as db: await db.update_one(COLLECTION, query, update_data, upsert=True)` (:84-85)
    async def load_user_mcp_configs(self, user_id: str, agent_id: str) -> List[...]:  # :94 — db.read(COLLECTION, query) (:117-118)
    async def remove_user_mcp_config(self, user_id, agent_id, server_name) -> bool:  # :136
# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py: async def _resolve_session(self) -> Any  # :141 (dict-like session)
```

### Does NOT Exist
- ~~`user_agent_toolkits`~~ as storage — that is the unrelated OAuth-enablement collection; never reuse it.
- ~~`ToolkitConfigService`~~ / ~~`user_toolkit_configs`~~ — this task creates them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/mcp_persistence.py#MCPPersistenceService"
  ]
}
```

---

## Implementation Notes

The `/me` route path segment `me` must not clash with the TASK-3660 `{slug}` routes: `/agents/{name}/toolkits/{slug}/me` is more specific than `/agents/{name}/toolkits/{slug}` — aiohttp matches exact segments, so both coexist.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Service mirroring MCPPersistenceService — *why*: proven DocumentDB upsert pattern.
2. Handler with overridable-param check and user-scoped vault — *why*: AC9.
3. Session marker pop — *why*: next request rebuilds the session view (S11).
4. Route + tests.

### `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` (CREATE)
```python
"""Per-user toolkit overrides (FEAT-593) — DocumentDB ``user_toolkit_configs``."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from parrot.interfaces.documentdb import DocumentDb  # verified: handlers/mcp_persistence.py:26

logger = logging.getLogger(__name__)
COLLECTION: str = "user_toolkit_configs"


class UserToolkitOverride(BaseModel):
    """One user's override of one toolkit on one agent (non-secret params + vault refs)."""

    user_id: str
    agent_id: str
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ToolkitConfigService:
    """CRUD over ``user_toolkit_configs`` keyed ``(user_id, agent_id, slug)``."""

    async def save(self, override: UserToolkitOverride) -> None:
        query = {"user_id": override.user_id, "agent_id": override.agent_id, "slug": override.slug}
        async with DocumentDb() as db:
            await db.update_one(COLLECTION, query, {"$set": override.model_dump()}, upsert=True)

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        # FILL IN: db.read(COLLECTION, {"user_id":…, "agent_id":…}) → models (skip invalid docs, WARNING)
        raise NotImplementedError

    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:
        # FILL IN: mirror MCPPersistenceService.remove_user_mcp_config (:136)
        raise NotImplementedError

    async def revision(self, user_id: str, agent_id: str) -> str:
        """``max(updated_at)`` over the user's overrides for the agent, ``""`` when none."""
        overrides = await self.load(user_id, agent_id)
        return max((o.updated_at for o in overrides), default="")
```
FILL IN: verify `update_one` accepts `upsert=True` exactly as in mcp_persistence.py:85 (it passes
the update dict — copy its exact shape, `$set` or not).

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` (CREATE — skeleton)
```python
"""Per-user toolkit override endpoints (FEAT-593): /agents/{name}/toolkits/{slug}/me."""
from __future__ import annotations

# imports as listed in the Codebase Contract + navigator_auth decorators, StudioBaseView, _StudioAgentsMixin


@is_authenticated()
@user_session()
class StudioUserToolkitOverrideHandler(_StudioAgentsMixin, StudioBaseView):
    """GET/PUT/DELETE the caller's override. No owner check; PBAC ``astudio:toolkits:override``."""

    async def get(self): ...     # FILL IN — {"slug", "overridable": [...], "params": masked, "configured": bool}
    async def put(self): ...     # FILL IN — 422 not_overridable; user vault f"toolkit_{slug}_{name}_user"; save; pop session marker
    async def delete(self): ...  # FILL IN — remove + delete_vault_credential; pop session marker
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# FILL IN: after the FEAT-593 block added by TASK-3660 (anchor: its last add_view line) insert:
    from .toolkit_overrides import StudioUserToolkitOverrideHandler  # pylint: disable=import-outside-toplevel

    app.router.add_view(f"{STUDIO_PREFIX}/agents/{{name}}/toolkits/{{slug}}/me", StudioUserToolkitOverrideHandler)
```

### FILL IN checklist
- [ ] Service load/remove; bounded by MCPPersistenceService pattern
- [ ] Handler methods; bounded by AC9 (422 not_overridable, user-scoped vault)
- [ ] Route placement after TASK-3660's block

---

## Acceptance Criteria

- [ ] PUT with a non-overridable param → 422 `not_overridable` listing it (AC9).
- [ ] User secret stored under the caller's user id, never the agent owner's (AC9).
- [ ] GET is masked; DELETE removes doc + vault entry.
- [ ] Session marker `{name}_toolkit_overrides_rev` popped after PUT/DELETE.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py
import pytest
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride


@pytest.mark.asyncio
async def test_revision_empty(monkeypatch):
    svc = ToolkitConfigService()
    monkeypatch.setattr(svc, "load", lambda u, a: _async([]))
    assert await svc.revision("u", "a") == ""


async def _async(value):
    return value


@pytest.mark.asyncio
async def test_put_rejects_non_overridable(monkeypatch):
    # FILL IN: handler with AgentToolingStore.load returning a jira spec user_overridable=["token"];
    #   PUT {"server_url": "x"} → 422 not_overridable with details {"params": ["server_url"]}
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-46ab79fc5c44`, attempt `77b5cedee92c4d2c9478662edec1c19a`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `f8f5f2f86db08eb8e5c54a0350697935d1c7511d` (`feat(tool-configuration-agentstudio): TASK-3661 — engine-committed coder deliverable`)
**Lint autofix SHA**: `551c2daa6` (`style(tool-configuration-agentstudio): TASK-3661 — engine lint autofix`, 0 residual, 0 errors)
**Merge commit**: `efa7dfc90`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:8074517f889c45e88997e7e6`, `fix_commits: []`.

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (263s), 0 lint residual. Diff verified against the task's file table: `handlers/toolkit_persistence.py`
(CREATE, 63 insertions — `UserToolkitOverride` + `ToolkitConfigService`), `handlers/studio/toolkit_overrides.py`
(CREATE, 200 insertions — `StudioUserToolkitOverrideHandler` GET/PUT/DELETE `/me`), `handlers/studio/__init__.py`
(MODIFY, 4 insertions — route registration), and `tests/studio/test_toolkit_overrides.py` (CREATE, 148 insertions)
— exactly the 4 declared files, no unlisted files, nothing under `sdd/` touched.

**Deviations from spec**: none.
