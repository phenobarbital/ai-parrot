# TASK-3964: [W2.1] Studio access service + _studio_partition() override (M2)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3956, TASK-3959, TASK-3960
**Assigned-to**: unassigned
**Spec task label**: W2.1 (spec §3 "Task plan")

---

## Context

Spec §2 "Access rule", "Stamping, reserved fields and names", "Storage partition", "Request context
for tools", Module 2, C6, C16, C22, C24, X4, X5, X11, §8 Q2. One service applies one rule to every
Studio record: turn a storage row (or, with no resolver, a legacy FEAT-467 record) into a
`StudioVisibilityRecord` and answer `can_see` / `can_manage` / `access_tag`; produce the visibility
fields; build `StudioAgentRef` and — via the ONE builder `build_tool_scope` — the `studio_scope`
context object (name frozen for FEAT-622); reject reserved keys; stamp owner/tenant/visibility/
`allowed_groups`; validate a requested visibility (`tenant_required`, `groups_required`,
`groups_not_allowed`). Also override FEAT-621's `StudioBaseView._studio_partition()`: GLOBAL with no
resolver, `StudioPartition.from_scope(scope)` with a tenant, `StudioTenantRequired` when opted in
without a tenant — so an opted-in host never touches the GLOBAL partition.

This task also carries the request-model additions every Wave-3 handler needs
(`VisibilityUpdateRequest`, `visibility`/`allowed_groups` on `CreateAgentRequest` and
`SkillPublishRequest`) — relocated from W4.1 so W3.1–W3.3 do not depend on a later task.

---

## Scope

- Create `handlers/studio/access.py`: `RESERVED_KEYS`, `StudioTenantRequired`, `StudioVisibilityRecord`,
  `StudioAgentRef`, `StudioToolScope`, `build_tool_scope(scope, agent=None)`, `StudioAccess` with
  `agent()`, `draft()`, `skill()` lookups, `can_see`, `can_manage`, `access_tag`, `visibility_fields`,
  `agent_ref`, static `reject_reserved_keys(payload)`, `stamp(*, visibility, allowed_groups)`,
  `validate_visibility(*, visibility, allowed_groups) -> str | None`.
- In `_base.py`: `async _access() -> StudioAccess`, the `_studio_partition()` override (§2 code block),
  `_check_record_access(access, rec, kind, name, *, manage=False)` (the one 404→403 helper every Wave-3
  handler uses; named to avoid `_ToolingViewMixin._authorize`, `toolkit_config.py:36`) and `_tenant_required()` (422 helper). With no resolver, `_access()` builds its scope from
  `_get_user()` (`user_id`, `is_superuser`, `groups`) so `can_manage` equals FEAT-467 `_require_owner`.
- In `models.py`: `VisibilityUpdateRequest`; `visibility: VisibilityLevel = "private"` and
  `allowed_groups: list[str] = []` on `CreateAgentRequest` and `SkillPublishRequest`.
- Tests: `test_partition_from_scope`, `test_null_tenant_row_never_in_tenant`,
  `test_owner_in_other_tenant_invisible`, `test_admin_bounded_to_tenant`, `test_groups_intersection`,
  `test_no_resolver_is_global`, `test_reserved_keys_rejected`, `test_visibility_validation`.

**NOT in scope**: Using the service inside any handler (TASK-3966..15); binding `studio_scope` at call sites (TASK-3969 test/ask, TASK-3970 meta-agent; FEAT-622 execute/options/chat); the storage tables, repositories and services themselves (FEAT-621); `SaveDraftRequest` fields (TASK-3967 owns drafts.py).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/access.py` | CREATE | `StudioAccess`, records/refs, `build_tool_scope`, reserved keys, stamp, visibility validation, `StudioTenantRequired` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | `_access()`, `_studio_partition()` override, `_check_record_access()`, `_tenant_required()` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` | MODIFY | `VisibilityUpdateRequest`; `visibility`/`allowed_groups` on `CreateAgentRequest`, `SkillPublishRequest` |
| `packages/ai-parrot-server/tests/studio/test_access.py` | CREATE | Access-rule and partition unit tests over the FEAT-621 fake |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified for this task at `32b1a45d4`, `dev`). The implementing agent MUST use these
> exact imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed, VERIFY it
> exists first with `grep` or `read`. Paths are relative to the repo root unless a line says
> otherwise; `S/` = `packages/ai-parrot-server/src/parrot/handlers/`.

### Verified Imports
```python
from parrot.handlers.scope import RequestScope, VisibilityLevel, normalize_visibility, scope_grants  # TASK-3956
from pydantic import BaseModel, Field  # verified: S/studio/models.py:14

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from parrot.handlers.studio.storage.models import (  # FEAT-621 W0 "Storage models" (spec storage §2.4)
    StudioPartition, StudioAgentRecord, StudioDraftRecord, StudioSkillRecord,
)
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories  # FEAT-621 W1 "Repositories" (tests)
```

### Existing Signatures to Use
```python
# S/studio/_base.py (after TASK-3959)
class StudioBaseView:
    async def _scope(self) -> RequestScope
    def _opted_in(self) -> bool
    async def _get_user(self) -> StudioUser          # user_id, groups (list), is_superuser
# S/studio/models.py
class CreateAgentRequest(BaseModel):   # :38
class SkillPublishRequest(BaseModel):  # :78

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

# handlers/studio/storage/models.py (FEAT-621 W0)
@dataclass(frozen=True, slots=True)
class StudioPartition:
    tenant: str | None
    GLOBAL: ClassVar["StudioPartition"]                       # StudioPartition(None)
    @classmethod
    def from_scope(cls, scope: Any) -> "StudioPartition"      # duck-typed on .tenant
class StudioAgentRecord:  agent_id: UUID; tenant: str | None; name: str; owner: str; visibility: str;
                          allowed_groups: tuple[str, ...]; ...; version: int ; @property tooling_ref
class StudioDraftRecord:  draft_id: UUID; tenant; owner; name; visibility; allowed_groups; ...
class StudioSkillRecord:  skill_id: UUID; tenant; owner; visibility; allowed_groups; name; ...
# handlers/studio/_base.py (FEAT-621 W1 "Backend selection + partition hook")
async def _studio_partition(self) -> StudioPartition       # returns StudioPartition.GLOBAL — THIS task overrides
def _studio_storage(self) -> StudioStorage
```

### Does NOT Exist
- ~~`StudioAccess`~~, ~~`StudioVisibilityRecord`~~, ~~`StudioAgentRef`~~, ~~`StudioToolScope`~~, ~~`build_tool_scope`~~, ~~`StudioTenantRequired`~~, ~~`VisibilityUpdateRequest`~~ — created here
- ~~`StudioPartition`~~, ~~`StudioBaseView._studio_partition()`~~, ~~`InMemoryStudioRepositories`~~ — FEAT-621 W0/W1 (must be merged first)
- ~~a sentinel tenant for tenant-less rows~~ — tenant-NULL rows are the GLOBAL partition (C24, X2)
- ~~`STUDIO_VISIBILITY_DDL`~~, ~~`ensure_studio_visibility_schema`~~ — v0.1 only; do not create

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/access.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_access.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/models.py#CreateAgentRequest",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/models.py#SkillPublishRequest"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`parrot.handlers.scope.scope_grants` (TASK-3956) is the `grants ∪ administers` primitive; `StudioAccess`
adds the tenant-bound owner branch on top — never re-implement the grant rule.

### Key Constraints
- Access rule exactly as spec §2: `in_tenant(r) := s.tenant is not None and r.tenant is not None and r.tenant == s.tenant`; `owns := in_tenant and r.owner == s.user_id`; `administers := in_tenant and (s.may_administer or s.is_superuser)`; `grants` via the primitive; `can_see := owns or administers or grants`; `can_manage := owns or administers`.
- Not opted in ⇒ `can_see` always True; `can_manage` = FEAT-467 `_require_owner` (owner or session superuser); `access_tag` = `"global"`.
- `access_tag` ∈ `owner | admin | tenant | groups` (opted in).
- `build_tool_scope` is the ONLY builder of `studio_scope` (X11); name and module are frozen (FEAT-622 imports it).
- `validate_visibility`: non-private without a tenant ⇒ `tenant_required`; `groups` with empty `allowed_groups` ⇒ `groups_required`; `allowed_groups ⊄ scope.groups` and not (`may_administer` or `is_superuser`) ⇒ `groups_not_allowed` (§8 Q2, decided 2026-09-30).
- `_studio_partition()` override: never GLOBAL when opted in (X5).
- Every function ≤ 10 complexity / ≤ 60 lines; module ≤ 500 lines.

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W0** ("Storage models": `StudioPartition`, record types, `StudioNameConflict`) and **FEAT-621 W1** ("Repositories" incl. `InMemoryStudioRepositories`; "Backend selection + partition hook": `_studio_partition` in `_base.py`) merged (X4, X5, X16 "Cross-spec waits").
- Cross-feature ordering: `studio/_base.py` — FEAT-621 W1 "Backend selection + partition hook" merges first (this task overrides the hook it adds).
- Cross-feature ordering: FEAT-622 Wave 4 (M3b scope enforcement + M5 scope binding) waits for this task (`build_tool_scope`, X16).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/scope.py` — primitive grant rule (TASK-3956)
- FEAT-621 `handlers/studio/storage/testing.py` — the fake used in tests

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `access.py` (block below) — *why*: spec M2 skeleton; one place for the rule (G2).
2. Add `_access()`, `_studio_partition()` override and `_tenant_required()` to `_base.py` — *why*: X5 / C22; handlers map `StudioTenantRequired` to empty list / 404 / 422 per the §2 host-modes table.
3. Add the request models — *why*: Wave-3 handlers parse and stamp them.
4. Write unit tests over the FEAT-621 fake (no DB).

### `packages/ai-parrot-server/src/parrot/handlers/studio/access.py` (CREATE)
```python
"""Agent Studio access service (FEAT-605 M2): one rule for every Studio record."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from parrot.handlers.scope import RequestScope, VisibilityLevel, normalize_visibility, scope_grants

RESERVED_KEYS: frozenset[str] = frozenset({"owner", "created_by", "tenant", "visibility", "allowed_groups"})


class StudioTenantRequired(Exception):
    """Opted in and ``scope.tenant is None`` (handlers: empty list / 404 / 422 ``tenant_required``)."""


@dataclass(frozen=True)
class StudioVisibilityRecord:
    kind: Literal["agent", "draft", "skill"]
    key: str
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel
    allowed_groups: tuple[str, ...]
    source: Literal["store", "legacy"]


@dataclass(frozen=True)
class StudioAgentRef:
    """Satisfies FEAT-622 ``AgentScopeView``."""

    agent_id: str | None
    name: str
    owner: str | None
    tenant: str | None
    visibility: VisibilityLevel


@dataclass(frozen=True)
class StudioToolScope:
    """Satisfies FEAT-622 ``ToolScopeView`` — value of ``RequestContext.kwargs['studio_scope']``."""

    caller: RequestScope
    agent: StudioAgentRef | None


def build_tool_scope(scope: RequestScope, agent: StudioAgentRef | None = None) -> StudioToolScope:
    """The one builder for ``studio_scope`` (name frozen for FEAT-622, X11)."""
    return StudioToolScope(caller=scope, agent=agent)


class StudioAccess:
    """Access decisions for one request's scope (spec §2 "Access rule")."""

    def __init__(self, scope: RequestScope, *, opted_in: bool, app: Any = None) -> None:
        self.scope, self.opted_in, self._app = scope, opted_in, app

    def _in_tenant(self, r: StudioVisibilityRecord) -> bool:
        s = self.scope
        return s.tenant is not None and r.tenant is not None and r.tenant == s.tenant

    def _owns(self, r: StudioVisibilityRecord) -> bool:
        return self._in_tenant(r) and r.owner is not None and str(r.owner) == str(self.scope.user_id)

    def _grants(self, r: StudioVisibilityRecord) -> bool:
        return scope_grants(tenant=r.tenant, visibility=r.visibility, allowed_groups=r.allowed_groups, scope=self.scope)

    def can_see(self, r: StudioVisibilityRecord) -> bool:
        return True if not self.opted_in else (self._owns(r) or self._grants(r))

    def can_manage(self, r: StudioVisibilityRecord) -> bool:
        # FILL IN: not opted in ⇒ FEAT-467 _require_owner semantics (scope.is_superuser or owner == user_id);
        #   opted in ⇒ owns or (in_tenant and (may_administer or is_superuser)) — bounded by spec §2 / AC6 / AC7.
        raise NotImplementedError

    def access_tag(self, r: StudioVisibilityRecord) -> str:
        # FILL IN: "global" when not opted in; else "owner" | "admin" | "tenant" | "groups" in that precedence.
        raise NotImplementedError

    def visibility_fields(self, r: StudioVisibilityRecord) -> dict:
        """tenant, owner, visibility, allowed_groups, access, can_manage (C14, AC10)."""
        return {"tenant": r.tenant, "owner": r.owner, "visibility": r.visibility,
                "allowed_groups": list(r.allowed_groups), "access": self.access_tag(r),
                "can_manage": self.can_manage(r)}

    def agent_ref(self, r: StudioVisibilityRecord) -> StudioAgentRef:
        return StudioAgentRef(agent_id=r.key if r.source == "store" else None, name=r.name,
                              owner=r.owner, tenant=r.tenant, visibility=r.visibility)

    @staticmethod
    def reject_reserved_keys(payload: Mapping[str, Any]) -> str | None:
        """Return the first reserved key present (⇒ 400 reserved_config_key), else None."""
        if not isinstance(payload, Mapping):
            return None
        return next((k for k in RESERVED_KEYS if k in payload), None)

    def stamp(self, *, visibility: str, allowed_groups: list[str]) -> dict:
        """Server-owned owner/tenant/visibility/allowed_groups for a store write (AC8)."""
        return {"owner": self.scope.user_id, "tenant": self.scope.tenant,
                "visibility": normalize_visibility(visibility), "allowed_groups": list(allowed_groups)}

    def validate_visibility(self, *, visibility: str, allowed_groups: list[str]) -> str | None:
        """Return tenant_required | groups_required | groups_not_allowed, or None."""
        # FILL IN: spec §2 host-modes + "Stamping" + §8 Q2 — bounded by AC9.
        raise NotImplementedError

    async def agent(self, name: str) -> StudioVisibilityRecord | None:
        """Tenant path: store row (scope.tenant, name). Legacy path: FEAT-467 lookup (DB row, then registry)."""
        # FILL IN: tenant path through FEAT-621 repositories on StudioPartition.from_scope(self.scope);
        #   legacy path reuses the existing FEAT-467 lookups with source="legacy" — bounded by A1/A3.
        raise NotImplementedError

    async def draft(self, name: str) -> StudioVisibilityRecord | None: ...   # FILL IN (same contract)
    async def skill(self, skill_id: str) -> StudioVisibilityRecord | None: ...  # FILL IN (same contract)
```
**Why**: Spec M2 skeleton plus `validate_visibility` (Q2) and a keyword-only `app` (the lookups need the storage handle — spec skeleton leaves this open). `reject_reserved_keys`/`stamp` are methods of `StudioAccess` (the skeleton's indentation under `build_tool_scope` is a typo).

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` (MODIFY)
```python
# AFTER the TASK-3959 helpers (anchor: `    def _name_taken(self, slug: str) -> web.Response:`; occurrences: 1)
    async def _access(self) -> "StudioAccess":
        """Per-request access service (lazy)."""
        from .access import StudioAccess  # local import: access.py must never import _base

        if self._opted_in():
            return StudioAccess(await self._scope(), opted_in=True, app=self.request.app)
        user = await self._get_user()
        scope = dataclasses.replace(await self._scope(), user_id=user.user_id,
                                    is_superuser=user.is_superuser, groups=frozenset(user.groups))
        return StudioAccess(scope, opted_in=False, app=self.request.app)

    async def _studio_partition(self) -> "StudioPartition":   # overrides FEAT-621 W1 (X5)
        from .access import StudioTenantRequired
        from .storage.models import StudioPartition

        if not self._opted_in():
            return StudioPartition.GLOBAL
        scope = await self._scope()
        if scope.tenant is None:
            raise StudioTenantRequired
        return StudioPartition.from_scope(scope)

    async def _check_record_access(self, access, rec, kind: str, name: str, *, manage: bool = False) -> web.Response | None:
        """404 when absent or invisible (one body, AC5); 403 when ``manage`` and not can_manage (AC6)."""
        if rec is None or not access.can_see(rec):
            return self._not_found(kind, name)
        if manage and not access.can_manage(rec):
            # FILL IN: 403 body — reuse the FEAT-467 _require_owner message (_base.py:245); the spec names no
            #   code for "visible, not manageable": use code "forbidden" — bounded by AC6.
            raise NotImplementedError
        return None

    def _tenant_required(self) -> web.Response:
        return self.json_response(StudioError(message="A tenant scope is required.", code="tenant_required").model_dump(), status=422)
# FILL IN: if FEAT-621's _studio_partition already exists in this class, REPLACE its body (do not add a second def).
```
**Why**: C22 / X5: the opted-in host never reads or writes the GLOBAL partition. FEAT-467 hosts keep `_require_owner` semantics because the no-resolver scope is rebuilt from `_get_user()` (the default resolver's superuser parsing differs from `_is_superuser`).

### `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class CreateAgentRequest(BaseModel):' models.py) — :38
# occurrences: 1 (verified: grep -c 'class SkillPublishRequest(BaseModel):' models.py) — :78
# ADD to both classes:
    visibility: Literal["private", "tenant", "groups"] = "private"
    allowed_groups: list[str] = Field(default_factory=list)

# APPEND:
class VisibilityUpdateRequest(BaseModel):
    """``PATCH …/visibility`` body (FEAT-605)."""

    visibility: Literal["private", "tenant", "groups"]
    allowed_groups: list[str] = Field(default_factory=list)
```
**Why**: Spec §2 Data Models. Add `from typing import Literal` (models.py imports only `Any` today, :11).

### `packages/ai-parrot-server/tests/studio/test_access.py` (CREATE)
```python
"""FEAT-605 M2 — StudioAccess rule and _studio_partition override."""
from __future__ import annotations

from parrot.handlers.scope import RequestScope
from parrot.handlers.studio.access import StudioAccess, StudioVisibilityRecord, build_tool_scope


def _rec(**kw) -> StudioVisibilityRecord: ...      # FILL IN defaults (kind agent, source store)

def test_owner_in_other_tenant_invisible(): ...     # mutation: drop in_tenant from owns ⇒ RED
def test_admin_bounded_to_tenant(): ...             # may_administer and is_superuser never cross tenants
def test_null_tenant_row_never_in_tenant(): ...     # mutation: drop `r.tenant is not None` ⇒ RED
def test_groups_intersection(): ...
def test_no_resolver_is_global(): ...               # opted_in=False ⇒ can_see True, access "global"
def test_reserved_keys_rejected(): ...
def test_visibility_validation(): ...               # tenant_required / groups_required / groups_not_allowed / admin exempt
async def test_partition_from_scope(aiohttp_client): ...
    # no resolver ⇒ GLOBAL; tenant ⇒ StudioPartition("acme"); resolver + tenant None ⇒ StudioTenantRequired.
    # Mutation: return GLOBAL when opted in ⇒ RED.
def test_build_tool_scope_shape(): ...
```
**Why**: Names match the spec §4 mutation table rows for M2.

### FILL IN checklist
- [ ] `access.py::StudioAccess.can_manage` / `access_tag` / `validate_visibility`; bounded by spec §2 and §8 Q2
- [ ] `access.py::StudioAccess.agent/draft/skill` — tenant path via FEAT-621 repositories, legacy path via the FEAT-467 lookups; bounded by A1/A3
- [ ] `_base.py` — replace (not duplicate) FEAT-621's `_studio_partition`; 403 body in `_check_record_access`
- [ ] `test_access.py` — all tests; partition test routed with a real resolver

---

## Acceptance Criteria

- [ ] AC4 (rule part): the access rule is tenant-bound — an owner sees none of their records under another tenant (`test_owner_in_other_tenant_invisible`)
- [ ] AC7 (rule part): `may_administer` and `is_superuser` grant read+manage inside the resolved tenant only
- [ ] AC8 (service part): reserved keys detected; stamp is server-owned
- [ ] AC23 (partition part): in an opted-in host `_studio_partition()` never returns GLOBAL (`test_partition_from_scope`)
- [ ] §8 Q2: `allowed_groups ⊄ owner groups` ⇒ `groups_not_allowed`, tenant admins exempt
- [ ] Mutations: drop `in_tenant` from `owns` ⇒ `test_owner_in_other_tenant_invisible` RED; drop `in_tenant` from administers ⇒ `test_admin_bounded_to_tenant` RED; return GLOBAL when opted in ⇒ `test_partition_from_scope` RED; drop `r.tenant is not None` ⇒ `test_null_tenant_row_never_in_tenant` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_access.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_base_scope.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_access.py
def test_owner_in_other_tenant_invisible(): ...
def test_admin_bounded_to_tenant(): ...
def test_null_tenant_row_never_in_tenant(): ...
def test_groups_intersection(): ...
def test_no_resolver_is_global(): ...
def test_reserved_keys_rejected(): ...
def test_visibility_validation(): ...
async def test_partition_from_scope(aiohttp_client): ...
def test_build_tool_scope_shape(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-tenant-visibility --feature-id FEAT-605`)
2. **Read the spec** at the path listed above for full context (§2 is normative; §3 has the task table)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-tenant-visibility.json`, AND every
   "Cross-feature ordering" item in Implementation Notes must hold (sibling feature tasks merged)
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor; a count of `0` means drift — stop and report
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-tenant-visibility.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands, and run each
   listed mutation check (revert the guard, see the named test go RED, restore by re-applying
   the edit — never with `git checkout` of the file)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3964 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
