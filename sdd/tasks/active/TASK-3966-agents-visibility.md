# TASK-3966: [W3.1] Agents visibility — list filter, 404/403, create gate + stamp + name_taken, PATCH policy, visibility PATCH handler (M6)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3964
**Assigned-to**: unassigned
**Spec task label**: W3.1 (spec §3 "Task plan")

---

## Context

Spec §2 route rows for `/agents`, `/agents/{name}`, `POST /agents`, `PATCH /agents/{name}`,
`/agents/{name}/reload`, `DELETE /agents/{name}`, `PATCH /agents/{name}/visibility`; Module 6; C4,
C14, C25; AC3–AC6, AC8–AC11, AC23. Applies the access service to the agents handler that FEAT-621 W3
has already switched to `StudioAgentService` (tenant path) with `_legacy_*` bodies (no resolver).

Unblocks: **U-SV** (lists, "mine/shared", sharing dialog data).

---

## Scope

- List: tenant path ⇒ only rows `can_see`; each item gets `visibility_fields`; resolver + tenant None ⇒ empty list. Legacy ⇒ unchanged + additive fields (`access: "global"`).
- `GET /agents/{name}`: invisible ⇒ `_not_found` (identical to absent); visible ⇒ 200 with the six fields (C14).
- `POST /agents`: `_require_author` ⇒ reserved keys in `config`/`definition` ⇒ 400 `reserved_config_key` ⇒ `validate_visibility` (422 `tenant_required`/`groups_required`/`groups_not_allowed`) ⇒ stamp ⇒ FEAT-621 `StudioNameConflict` ⇒ `_name_taken` (replaces `duplicate`, `agents.py:255-261`, both paths). Tenant path: `StudioToolingRefused` ⇒ 422 `tooling_not_permitted` (C35, raised by FEAT-621's `StudioToolingGate`).
- `PATCH /agents/{name}` (verb added by FEAT-621 W3, §2.9a there): 404 / 403 / `_require_author` / reserved keys before `StudioAgentService.patch`; pass the record version as `authorized_version` (X6).
- `POST /agents/{name}/reload`: opted in ⇒ 404 / 403 before the reload; tenant path ⇒ `manager.studio.reload(StudioAgentKey(scope.tenant, name))`; legacy path unchanged and ungated (G9).
- `DELETE /agents/{name}`: 404 / 403.
- New `StudioAgentVisibilityHandler.patch`: `can_manage`; `VisibilityUpdateRequest`; 422 codes; `StudioAgentService.update_visibility(..., guard=StudioWriteGuard(authorized_version=…))`. Route registration is TASK-3972 (tests register it on their own app).
- Update `test_agents_lifecycle.py:155` (`duplicate` → `name_taken`).

**NOT in scope**: Route registration of `/agents/{name}/visibility` (TASK-3972); files/tooling/testing routes (TASK-3969); the PATCH route body/version semantics (FEAT-621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` | MODIFY | Visibility filter, 404/403, create gate/stamp/name_taken, PATCH policy, reload/delete gates, `StudioAgentVisibilityHandler` |
| `packages/ai-parrot-server/tests/studio/test_agents_visibility.py` | CREATE | Actor matrix for agents (owner/peer/other tenant/admin/superuser/no resolver), names per tenant |
| `packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py` | MODIFY | `duplicate` → `name_taken` (plain-host behaviour change, :155) |

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
from .access import StudioAccess, StudioTenantRequired  # TASK-3964
from .models import CreateAgentRequest, VisibilityUpdateRequest  # verified CreateAgentRequest models.py:38; VisibilityUpdateRequest TASK-3964

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from .storage.models import StudioAgentKey, StudioNameConflict, StudioToolingRefused, StudioWriteGuard  # FEAT-621 W0
```

### Existing Signatures to Use
```python
# S/studio/agents.py (verified at 32b1a45d4 — FEAT-621 W3 rewrites these bodies; re-anchor after rebasing)
class _StudioAgentsMixin                    # :39 ; _manager :42 ; _check_duplicate :89 ; _error :150
class StudioAgentsHandler                   # :167 ; get :175 ; _get_one :182 ; _get_all :193 ; post :209 ;
                                            #   existing = await self._check_duplicate(slug) :255 ; created_by stamp :281 ; delete :373
class StudioAgentReloadHandler              # :443 ; post :450 ; result = await manager.reload_agent(name) :464
# S/studio/_base.py (TASK-3959/09): _require_author, _not_found, _name_taken, _tenant_required, _access, _studio_partition

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

# FEAT-621 W2/W3: StudioAgentService.create/patch/update_visibility/delete(..., guard=StudioWriteGuard), get_version;
#   StudioAgentsHandler.patch (new verb, §2.9a); manager.studio.reload(key)
```

### Does NOT Exist
- ~~an owner check on `POST /agents/{name}/reload`~~ today — add it opted-in only
- ~~`StudioAgentVisibilityHandler`~~ — created here
- ~~`manager.get_bot(name)` on the tenant path~~ — forbidden (A2: cross-tenant bug); use `manager.studio` / `get_studio_bot`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/agents.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_agents_visibility.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#StudioAgentsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#StudioAgentReloadHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#_StudioAgentsMixin"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Check order per addressed route: (automatic `_studio_gate`) → partition/`StudioTenantRequired` → lookup → `can_see` else `_not_found` → `can_manage` else 403 → `_require_author` where the row says so → write with `authorized_version`.

### Key Constraints
- **Request fields (TASK-3964 review)**: TASK-3964 deliberately does NOT add `visibility`/`allowed_groups` to `CreateAgentRequest` (no handler read them, they would have been silently dropped). THIS task adds `visibility: Literal["private", "tenant", "groups"] = "private"` and `allowed_groups: list[str] = Field(default_factory=list)` to `CreateAgentRequest` in `models.py` together with the agents `POST` handler code that reads and stamps them (add `models.py` to this task's files if missing).
- 404 body identical to absent (AC5); 409 `name_taken` body non-enumerating (AC11); 403 for visible-not-manageable (AC6) incl. reload when opted in.
- Legacy path: FEAT-467 behaviour except the documented changes (`name_taken`, additive fields) — AC3.
- `StudioStaleAuthorization` ⇒ re-read, re-authorise and retry once, then 409 `version_conflict` (X6).
- Anchors below were verified at `32b1a45d4` (before FEAT-621 W3). FEAT-621 W3 rewrites these handler bodies (`_legacy_*` + store paths): re-run every `grep -c` after rebasing on it and re-locate each anchor; a count of `0` means drift — stop and report (spec §6 Edit Sites note).

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Handler switch: agents, files, tooling" merged first on `studio/agents.py` (per-file rule, X16) — it adds `PATCH /agents/{name}` and the service-backed bodies — plus FEAT-621 W2 "Agent/asset/tooling services" and the runtime task (`manager.studio.reload`).
- Cross-feature ordering: tooling refusals come from FEAT-621's `StudioToolingGate`, which calls FEAT-622 Wave 1 (M7 core `enforce_tenant_tooling`) — already required by FEAT-621 W2.

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py` — legacy suite (one assertion changes)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3; re-anchor the five `agents.py` sites — *why*: per-file rule.
2. Apply the access service to list, GET, POST, PATCH, reload, DELETE in the check order above — *why*: §2 route table.
3. Add `StudioAgentVisibilityHandler` — *why*: G4 / AC9.
4. Update the legacy assertion; write the actor matrix.

### `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _get_all(self):' agents.py) — :193 (re-anchor after FEAT-621 W3)
#   FILL IN: tenant path — try: part = await self._studio_partition() except StudioTenantRequired: return empty list;
#   filter records with access.can_see; merge access.visibility_fields(rec) into each item.
# occurrences: 1 (verified: grep -c '    async def _get_one(self, name: str):' agents.py) — :182
#   FILL IN: rec = await access.agent(name); if rec is None or not access.can_see(rec): return self._not_found("agent", name)
# occurrences: 1 (verified: grep -c '        existing = await self._check_duplicate(slug)' agents.py) — :255
#   FILL IN: replace the duplicate pre-check with StudioNameConflict ⇒ self._name_taken(slug) (no list-scan pre-check, spec §2)
# occurrences: 1 (verified: grep -c '        config_dict["created_by"] = user.user_id' agents.py) — :281
#   FILL IN: tenant path stamps via access.stamp(...); legacy keeps created_by
# occurrences: 1 (verified: grep -c '            result = await manager.reload_agent(name)' agents.py) — :464
#   FILL IN: opted in ⇒ 404/403 first; tenant path ⇒ await manager.studio.reload(StudioAgentKey(scope.tenant, name))


@is_authenticated()
@user_session()
class StudioAgentVisibilityHandler(_StudioAgentsMixin, StudioBaseView):
    """``PATCH {prefix}/agents/{name}/visibility`` (FEAT-605 G4)."""

    async def patch(self):
        """can_manage; VisibilityUpdateRequest; 422 tenant_required/groups_required/groups_not_allowed."""
        # FILL IN: body parse (400 invalid_request), lookup → 404/403, validate_visibility → 422,
        #   StudioAgentService.update_visibility(part, name, visibility=…, allowed_groups=…,
        #   guard=StudioWriteGuard(authorized_version=rec_version)) — bounded by AC9, X6, X13.
        raise NotImplementedError
```
**Why**: Spec M6 skeleton. Keep each verb ≤ 60 lines; use `_check_record_access` (TASK-3964) for every 404/403 decision — never re-implement it.

### `packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert (await _decode(response))["code"] == "duplicate"' test_agents_lifecycle.py) — :155
        assert (await _decode(response))["code"] == "name_taken"
```
**Why**: AC3 documented plain-host change.

### `packages/ai-parrot-server/tests/studio/test_agents_visibility.py` (CREATE)
```python
"""FEAT-605 M6 — agents route matrix (aiohttp_client, prefixed app, real resolver + SessionData, FEAT-621 fake)."""
from __future__ import annotations

async def test_list_filters_by_access(aiohttp_client): ...
async def test_get_invisible_identical_404(aiohttp_client): ...
async def test_get_returns_visibility_fields(aiohttp_client): ...
async def test_authoring_denied_create_and_patch(aiohttp_client): ...     # test_authoring_denied[POST /agents], [PATCH /agents/{name}]
async def test_reserved_keys_rejected_on_create(aiohttp_client): ...
async def test_name_taken_only_inside_tenant(aiohttp_client): ...         # same slug in two tenants ⇒ 201 both
async def test_reload_gate_opted_in_only(aiohttp_client): ...             # mutation: drop the opted-in gate ⇒ RED
async def test_visibility_patch_rules(aiohttp_client): ...
async def test_patch_agent_policy_row(aiohttp_client): ...                # 404 / 403 / authoring_denied (AC23)
```
**Why**: Spec §4 mutation rows `_require_author`, `per-tenant conflict → name_taken`, `opted-in-only gates`.

### FILL IN checklist
- [ ] five `agents.py` edit sites + the visibility handler; bounded by spec §2 route rows, AC3–AC11, AC23
- [ ] `test_agents_visibility.py` bodies (owner / peer / other tenant / tenant admin / global superuser / no resolver)

---

## Acceptance Criteria

- [ ] AC4/AC5/AC6/AC10 for agents: lists filtered; invisible ⇒ identical 404; visible-not-manageable ⇒ 403 incl. reload (opted in); GET returns the six fields
- [ ] AC8/AC11/AC13 for agents: reserved keys 400; per-tenant `name_taken`; `may_author=False` ⇒ 403 `authoring_denied` on POST and PATCH
- [ ] AC9 (agents): `PATCH /agents/{name}/visibility` requires `can_manage`, enforces `tenant_required`/`groups_required` (+ `groups_not_allowed`)
- [ ] AC23: `PATCH /agents/{name}` answers 404 / 403 / 403 `authoring_denied`
- [ ] AC3: legacy suite green except the documented `duplicate` → `name_taken` change
- [ ] Mutations: drop `_require_author` on POST ⇒ `test_authoring_denied_create_and_patch` RED; drop the reload gate ⇒ `test_reload_gate_opted_in_only` RED; map conflict to the old code ⇒ `test_name_taken_only_inside_tenant` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_agents_visibility.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_agents_visibility.py — see blueprint (9 tests)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3966 agentstudio-tenant-visibility verified`
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
