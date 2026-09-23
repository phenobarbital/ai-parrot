# TASK-3659: AgentToolingStore + Studio tooling request/response models

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3645, TASK-3646, TASK-3652, TASK-3657
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (5), §3 Module 7 (store part), design research S4/S5/S9/S10; AC1, AC2, AC3,
AC5. The store is the SINGLE writer of agent-level tooling: it validates, splits secrets into the
vault under the **agent owner's** id (`vault_owner`), keeps masked values untouched, and persists
to the DB row or the agent's own YAML.

---

## Scope

- Append to `handlers/studio/models.py`: `ToolkitConfigPutRequest`, `AgentToolkitsResponse`,
  `ToolkitPersistResponse`, `AgentMcpServersPutRequest`, `ToolkitOptionsResponse`,
  `AgentMcpServersResponse` (shapes in spec §3 M7).
- Create `tooling_store.py` with `AgentToolingStore(handler)`:
  - `load(name) -> ToolingState` (a small dataclass/BaseModel: `tooling: NormalizedTooling`,
    `editable: bool`, `reason: str | None`, `owner: str | None`, `source: "database"|"registry"`).
    DB row → `normalize_tooling([], mcp_servers=row.mcp_servers, toolkit_config=row.toolkit_config)`;
    registry → from `meta.bot_config.toolkits` / `.mcp_servers`; editability for registry agents =
    same guards as `update_agent_tooling` (check without writing). Unknown → `LookupError`.
  - `put_toolkit(name, slug, req) -> ToolkitSpec`: resolve class (`_resolve_toolkit_class`-like, or
    `dataset_manager`/`wiki`/`infographic` explicit); schema = `cls.config_schema(slug)["schema"]` (or
    `build_schema_envelope`); validate (`config_model(**params)` when set, else `jsonschema` Draft 2020-12
    over the introspected schema, ignoring masked values); reject `x-server-managed` keys (ValueError);
    `paths = secret_paths(schema, params)`; values equal to `SECRET_MASK` keep the existing ref; new
    values are merged into the existing vault entry (`retrieve` → update → `store_vault_credential(owner, toolkit_vault_name(slug, name), merged)`)
    and removed from params; persist; return the spec.
  - `delete_toolkit(name, slug)`: remove spec + `delete_vault_credential(owner, vault_name)`.
  - `put_mcp_servers(name, servers) -> list[AgentMCPServerSpec]`: vault `headers`/`auth_config`/`env`
    per server under `mcp_vault_name(server, name)`; mask sentinel keeps the existing entry; replace list.
- Persistence: DB → `row.set("toolkit_config", {...slug: spec.model_dump(exclude={"slug"})})` /
  `row.set("mcp_servers", [...])` + `await row.update()` inside `db.acquire()`; registry →
  `registry.update_agent_tooling(name, toolkits=..., mcp_servers=...)`.
- Errors: `PermissionError` (read-only), `ValueError` (invalid params — message lists names),
  `RuntimeError` (vault unavailable) — the handler (TASK-3660) maps them.

**NOT in scope**: aiohttp views and routes (TASK-3660); options lookups (TASK-3660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` | MODIFY | Tooling request/response models |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | CREATE | AgentToolingStore: load / put_toolkit / delete_toolkit / put_mcp_servers |
| `packages/ai-parrot-server/tests/studio/test_tooling_store.py` | CREATE | Unit tests (fake vault, fake DB/registry) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import (AgentMCPServerSpec, NormalizedTooling, SECRET_MASK, ToolkitSpec, MCP_SECRET_FIELDS,
                               mcp_vault_name, normalize_tooling, toolkit_vault_name)  # TASK-3645
from parrot.tools.config_schema import build_schema_envelope, secret_paths  # TASK-3646
from parrot.security.vault_utils import store_vault_credential, retrieve_vault_credential, delete_vault_credential  # vault_utils.py:84/:135/:172
from parrot.conf import AGENTS_DIR  # verified: handlers/studio/toolkits.py:23
from parrot.tools.dataset_manager.tool import DatasetManager  # verified: handlers/studio/toolkits.py:28
from parrot.knowledge.wiki import LLMWikiToolkit  # verified: handlers/studio/toolkits.py:27
from parrot.tools.infographic_toolkit import InfographicToolkit  # verified: handlers/studio/toolkits.py:30
from asyncdb.exceptions import NoDataFound  # verified: handlers/studio/agents.py:23
from ..models import BotModel  # verified: handlers/studio/agents.py:34
from .toolkits import _resolve_toolkit_class  # verified: handlers/studio/toolkits.py:154
import jsonschema  # core dep jsonschema>=4.20 (packages/ai-parrot/pyproject.toml:91)
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

# packages/ai-parrot-server/src/parrot/handlers/studio/models.py — last class is `class ByokKeyRequest(BaseModel)` (append after it); StudioError at :23
# packages/ai-parrot/src/parrot/security/vault_utils.py
async def store_vault_credential(user_id: str, vault_name: str, secret_params: Dict[str, Any]) -> None  # :84 (upsert)
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]  # :135 (KeyError if absent)
async def delete_vault_credential(user_id: str, vault_name: str) -> None  # :172
# packages/ai-parrot/src/parrot/registry/registry.py — AgentRegistry.update_agent_tooling(name, *, toolkits=None, mcp_servers=None) -> Path  (TASK-3657)
#   raises KeyError / PermissionError
```

### Does NOT Exist
- ~~`AgentToolingStore`~~, ~~`handlers/studio/tooling_store.py`~~ — this task creates them.
- ~~storing secrets under the *caller's* id for agent-level config~~ — always the agent OWNER (a superuser editing someone else's agent must not re-home the vault entry; AC3).
- ~~a synthetic service principal for the vault~~ — rejected in brainstorm.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/models.py#StudioError",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#_StudioAgentsMixin._get_db_agent",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#_StudioAgentsMixin._registry_agent_owner",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#store_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#retrieve_vault_credential",
    "sym:packages/ai-parrot/src/parrot/security/vault_utils.py#delete_vault_credential"
  ]
}
```

---

## Implementation Notes

- Owner resolution mirrors `StudioToolkitsHandler.post`: DB → `str(row.created_by)`; registry →
  `handler._registry_agent_owner(meta)`. `owner is None` → treat as read-only
  (`PermissionError("agent has no owner; cannot store secrets")`).
- Keep functions ≤ ~60 lines: split into `_resolve_class(slug)`, `_validate(cls, schema, params)`,
  `_split_secrets(...)`, `_persist(state, toolkits, mcp)`.
- Never log params; log slug + agent + counts only.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Append the models — *why*: TASK-3660 handlers and TASK-3663 codegen import them.
2. Implement `load` + editability — *why*: GET and every write start from it.
3. Implement `_split_secrets` with mask handling — *why*: AC2 + "PUT with the mask leaves the vault untouched".
4. Implement put/delete toolkit, put MCP servers, `_persist` — *why*: AC1/AC5.
5. Tests with monkeypatched vault functions, a fake BotModel row and a fake registry.

### `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` (MODIFY — append)
```python
# occurrences: 1 (verified: grep -c '^class ByokKeyRequest(BaseModel):' models.py) — append after that class


class ToolkitConfigPutRequest(BaseModel):
    """``PUT /astudio/agents/{name}/toolkits/{slug}`` payload (FEAT-593)."""

    params: dict[str, Any] = Field(default_factory=dict)
    user_overridable: list[str] = Field(default_factory=list)


class AgentToolkitsResponse(BaseModel):
    """``GET /astudio/agents/{name}/toolkits`` — specs are masked dumps."""

    agent: str
    editable: bool
    reason: str | None = None
    toolkits: list[dict[str, Any]] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class ToolkitPersistResponse(BaseModel):
    """Response of every agent-level tooling write."""

    agent: str
    slug: str | None = None
    reload_required: bool = True
    persisted: bool = True


class AgentMcpServersPutRequest(BaseModel):
    """``PUT /astudio/agents/{name}/mcp-servers`` payload (replaces the list)."""

    servers: list[dict[str, Any]] = Field(default_factory=list)


class AgentMcpServersResponse(BaseModel):
    """``GET /astudio/agents/{name}/mcp-servers`` — masked dumps."""

    agent: str
    editable: bool
    reason: str | None = None
    servers: list[dict[str, Any]] = Field(default_factory=list)


class ToolkitOptionsResponse(BaseModel):
    """``GET …/toolkits/{slug}/options/{param}``."""

    options: list[dict[str, str]] = Field(default_factory=list)
```
FILL IN: ensure `Any` is imported in models.py.

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (CREATE — skeleton)
```python
"""Agent-level tooling persistence for Agent Studio (FEAT-593). Single writer."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

# imports exactly as listed in the Codebase Contract

logger = logging.getLogger(__name__)
_EXPLICIT = {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}
_SERVER_MANAGED = {"wiki": frozenset({"pageindex_toolkit", "graphindex_toolkit", "okf_toolkit"}),
                   "infographic": frozenset({"artifact_store"})}


@dataclass
class ToolingState:
    tooling: NormalizedTooling
    editable: bool
    reason: str | None
    owner: str | None
    source: Literal["database", "registry"]


class AgentToolingStore:
    """Load and persist agent-level toolkit / MCP configuration (DB row or agent YAML)."""

    def __init__(self, handler: Any) -> None:
        self.handler = handler  # a _StudioAgentsMixin + StudioBaseView instance

    async def load(self, name: str) -> ToolingState:
        """Raises LookupError when the agent is unknown."""
        # FILL IN: DB row via handler._get_db_agent(name) → ToolingState(source="database", editable=owner is not None);
        #   else registry meta → tooling from meta.bot_config (.toolkits, .mcp_servers); editable when bot_config
        #   is set, file is .yaml/.yml under AGENTS_DIR named {name}.yaml (reason string otherwise) — AC5

    def schema_for(self, slug: str) -> tuple[type, dict[str, Any]]:
        """(class, JSON Schema) for ``slug``; LookupError when unknown."""
        # FILL IN: cls = _EXPLICIT.get(slug) or _resolve_toolkit_class(slug); envelope via
        #   build_schema_envelope(slug, cls, server_managed=_SERVER_MANAGED.get(slug, frozenset()))

    async def put_toolkit(self, name: str, slug: str, params: dict[str, Any], user_overridable: list[str]) -> ToolkitSpec:
        """Validate, vault secrets under the owner, persist. PermissionError / ValueError / RuntimeError."""
        # FILL IN: state = await self.load(name); not editable → PermissionError(state.reason);
        #   cls, schema = self.schema_for(slug); _validate(cls, schema, params) (masked values ignored);
        #   reject x-server-managed keys; spec = await self._split_secrets(state, slug, name, schema, params, user_overridable)
        #   → replace/insert in state.tooling.toolkits → await self._persist(name, state)

    async def delete_toolkit(self, name: str, slug: str) -> None:
        """Remove the spec and delete its vault entry."""
        # FILL IN

    async def put_mcp_servers(self, name: str, servers: list[dict[str, Any]]) -> list[AgentMCPServerSpec]:
        """Vault headers/auth_config/env per server (mask keeps existing); replace the list."""
        # FILL IN

    async def _split_secrets(self, state, slug, name, schema, params, user_overridable) -> ToolkitSpec:
        """Move x-secret values into the vault entry ``toolkit_vault_name(slug, name)``."""
        # FILL IN: previous = existing spec for slug (or None); paths = secret_paths(schema, params);
        #   pop each path's value from a deep copy; value == SECRET_MASK → keep previous ref (if any);
        #   new values → merged dict; if merged: current = await retrieve (KeyError → {}); store(owner, vault, current|merged)
        #   secret_refs = {path: vault_name for kept+new}; return ToolkitSpec(slug, params=clean, user_overridable,
        #   secret_refs, vault_owner=state.owner)

    async def _persist(self, name: str, state: ToolingState) -> None:
        """DB: set toolkit_config / mcp_servers + update(); registry: update_agent_tooling()."""
        # FILL IN
```
**Why**: splitting the store from the views keeps the secret logic unit-testable without aiohttp,
and gives TASK-3661 a way to read agent defaults (`load`).

### FILL IN checklist
- [ ] `load` for DB + registry incl. editability reasons; bounded by AC5
- [ ] `schema_for` + `_validate` (config_model vs jsonschema, masked values ignored); bounded by AC6
- [ ] `_split_secrets` mask/merge logic; bounded by AC2/AC3
- [ ] `put_toolkit`, `delete_toolkit`, `put_mcp_servers`, `_persist`; bounded by AC1

---

## Acceptance Criteria

- [ ] PUT jira with `token` → vault `store_vault_credential("<owner>", "toolkit_jira_<agent>", {"token": ...})`; persisted spec has `secret_refs={"token": ...}` and no token in params (AC2, AC3).
- [ ] Re-PUT with `token == SECRET_MASK` → vault not written; ref kept.
- [ ] Superuser caller editing someone else's agent → vault owner is still the agent owner (AC3).
- [ ] `.py`/outside-AGENTS_DIR registry agent → `PermissionError` (AC5).
- [ ] Unknown param for a model-backed toolkit → `ValueError`; `x-server-managed` key → `ValueError`.
- [ ] MCP `headers`/`auth_config`/`env` never persisted raw.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_tooling_store.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.tools.spec import SECRET_MASK


@pytest.fixture
def vault(monkeypatch):
    data = {}

    async def _store(user_id, name, secrets):
        data[(user_id, name)] = dict(secrets)

    async def _retrieve(user_id, name):
        return dict(data[(user_id, name)])

    monkeypatch.setattr(store_module, "store_vault_credential", _store)
    monkeypatch.setattr(store_module, "retrieve_vault_credential", _retrieve)
    monkeypatch.setattr(store_module, "delete_vault_credential", AsyncMock())
    return data


@pytest.fixture
def db_store(monkeypatch):
    row = SimpleNamespace(name="a1", created_by=42, toolkit_config={}, mcp_servers=[], set=MagicMock(), update=AsyncMock())
    handler = SimpleNamespace(_get_db_agent=AsyncMock(return_value=row), _registry=lambda: None,
                              request=SimpleNamespace(app={}), logger=MagicMock())
    s = AgentToolingStore(handler)
    monkeypatch.setattr(s, "_persist", AsyncMock())
    return s, row


@pytest.mark.asyncio
async def test_put_jira_vaults_token_under_owner(vault, db_store):
    s, _ = db_store
    spec = await s.put_toolkit("a1", "jira", {"server_url": "https://x", "token": "t0k"}, ["token"])
    assert vault[("42", "toolkit_jira_a1")] == {"token": "t0k"}
    assert "token" not in spec.params and spec.secret_refs == {"token": "toolkit_jira_a1"}


@pytest.mark.asyncio
async def test_mask_keeps_existing(vault, db_store):
    s, _ = db_store
    await s.put_toolkit("a1", "jira", {"token": "t0k"}, [])
    # FILL IN: make load() return the persisted spec (fake state), then PUT token=SECRET_MASK and
    #   assert the vault entry is unchanged and secret_refs still has token
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
