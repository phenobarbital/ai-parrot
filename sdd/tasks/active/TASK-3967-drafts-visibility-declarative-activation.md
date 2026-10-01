# TASK-3967: [W3.2] Drafts visibility + declarative activation on the tenant path (M7)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3964, TASK-3962, TASK-3963
**Assigned-to**: unassigned
**Spec task label**: W3.2 (spec §3 "Task plan")

---

## Context

Spec §2 "Declarative activation (tenant path)", route rows for `/drafts*`, Module 7, C3, C35; AC9–AC13,
AC27. On the tenant path a draft is a declarative definition in `ai_agent_drafts`; Python `source`
⇒ 422 `declarative_only`; activation creates or updates the `ai_agents` row from the draft (no
module import, no `AGENTS_DIR` write); the draft's tooling is re-checked against
`TenantToolingPolicy` at save and activation (through FEAT-621's `StudioToolingGate`).

---

## Scope

- List/GET: filter + identical 404 + visibility fields (as agents).
- `POST /drafts` tenant path: `_require_author`; Python `source` ⇒ 422 `declarative_only`; reserved keys ⇒ 400; a `(tenant, name)` draft the caller cannot manage ⇒ `_name_taken` before anything is written; `validate_visibility`; stamp; `StudioDraftService.save_bundle`; `StudioToolingRefused` ⇒ 422 `tooling_not_permitted`.
- `POST /drafts/{name}/activate` tenant path: `can_see` else 404; `can_manage` else 403; `_require_author`; `StudioDraftService.activate(part, name, owner=…, replace=…, guard=…)`; row present and (`replace=false` or not manageable) ⇒ `_name_taken`; tooling re-checked (C35).
- Legacy path keeps the D1/D3 guards from TASK-3962/08 (as carried by FEAT-621 W3's `_legacy_*` bodies).
- `DELETE /drafts/{name}`: 404 / 403.
- `SaveDraftRequest` gains `visibility`/`allowed_groups` (and the declarative definition field per FEAT-621, if W3 did not add it).
- New `StudioDraftVisibilityHandler.patch`. Route registration is TASK-3972.

**NOT in scope**: Draft service/transaction semantics and the bundle shape (FEAT-621 W2 "Draft + catalogue services"); defining `TenantToolingPolicy` (FEAT-622); D2 on the legacy path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | Tenant-path save/activate, visibility filter, 404/403, `SaveDraftRequest` fields, `StudioDraftVisibilityHandler` |
| `packages/ai-parrot-server/tests/studio/test_drafts_tenant.py` | CREATE | Tenant-path drafts: declarative_only, activation imports nothing, replace rules, authoring gate, tooling policy |

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
from .models import VisibilityUpdateRequest  # TASK-3964

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from .storage.models import StudioNameConflict, StudioToolingRefused, StudioWriteGuard  # FEAT-621 W0
# StudioDraftService.save_bundle / activate(part, name, *, owner, replace=False, guard, target_guard=None) /
#   update_visibility / python_drafts_allowed  — FEAT-621 W2 "Draft + catalogue services" (X6)
```

### Existing Signatures to Use
```python
# S/studio/drafts.py (verified at 32b1a45d4; FEAT-621 W3 rewrites; re-anchor)
class SaveDraftRequest(BaseModel)          # :32
class _StudioDraftsMixin                   # :45 ; _get_draft_row :65 ; _upsert_draft_row :93
class StudioDraftsHandler                  # :155 ; _get_one :168 ; _get_all :177 (rows = … :178) ; post :181 ; delete :243
class StudioDraftActivateHandler           # :270 ; post :279 ; _import_module_from_path :364 (legacy only)
```

### Does NOT Exist
- ~~Python drafts on the tenant path~~ — refused, 422 `declarative_only` (C3)
- ~~`_import_module_from_path` or any `AGENTS_DIR` write on the tenant path~~ — never called there
- ~~`python_drafts_disabled`~~ — not a code; `declarative_only` is (C28)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_drafts_tenant.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftActivateHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#SaveDraftRequest"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Same check order as TASK-3966; activation ownership/name rules follow spec §2 bullet list verbatim.

### Key Constraints
- No module import and no file move on the tenant path (AC12) — the storage runtime builds lazily on first `get_studio_bot`.
- Activation stamps the draft's owner, tenant, visibility and `allowed_groups` onto the agent row.
- Anchors below were verified at `32b1a45d4` (before FEAT-621 W3). FEAT-621 W3 rewrites these handler bodies (`_legacy_*` + store paths): re-run every `grep -c` after rebasing on it and re-locate each anchor; a count of `0` means drift — stop and report (spec §6 Edit Sites note).

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Handler switch: drafts, catalogue, testing" merged first on `studio/drafts.py` (per-file rule) plus FEAT-621 W2 "Draft + catalogue services" and the runtime task.
- Cross-feature ordering: TASK-3962/08 (D1/D3) merged before FEAT-621 W3, which carried them into `_legacy_*` — confirm they are present after rebasing.
- Cross-feature ordering: `TenantToolingPolicy` refusals need FEAT-622 Wave 1 (M7 core) — already a prerequisite of FEAT-621 W2.

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_drafts.py`, `test_drafts_d1.py`, `test_drafts_d3.py` — legacy path must stay green

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3; re-anchor — *why*: per-file rule.
2. Apply the tenant-path rules to save and activate; keep the legacy branch untouched — *why*: C3 / AC12.
3. Add the visibility handler and request fields.
4. Write tests; the activation test spies on the import path.

### `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class SaveDraftRequest' drafts.py) — :32 ; ADD:
    visibility: Literal["private", "tenant", "groups"] = "private"
    allowed_groups: list[str] = Field(default_factory=list)
# FILL IN: tenant-path POST /drafts and POST /drafts/{name}/activate per spec §2 "Declarative activation" —
#   bounded by AC11, AC12, AC13, AC27; map StudioNameConflict ⇒ self._name_taken(name),
#   StudioToolingRefused ⇒ 422 tooling_not_permitted, Python source ⇒ 422 declarative_only.


@is_authenticated()
@user_session()
class StudioDraftVisibilityHandler(_StudioDraftsMixin, StudioBaseView):
    """``PATCH {prefix}/drafts/{name}/visibility``."""

    async def patch(self):
        # FILL IN: same contract as StudioAgentVisibilityHandler.patch, via StudioDraftService.update_visibility
        raise NotImplementedError
```
**Why**: Spec M7 skeleton.

### `packages/ai-parrot-server/tests/studio/test_drafts_tenant.py` (CREATE)
```python
"""FEAT-605 M7 — tenant-path drafts."""
from __future__ import annotations

async def test_python_draft_refused_on_tenant_path(aiohttp_client): ...     # 422 declarative_only (mutation: accept source ⇒ RED)
async def test_activation_imports_nothing(aiohttp_client): ...               # spy on the import path (mutation: call it ⇒ RED)
async def test_activation_replace_rules(aiohttp_client): ...                 # absent ⇒ create; replace=false ⇒ name_taken; foreign ⇒ name_taken
async def test_draft_name_taken_before_write(aiohttp_client): ...
async def test_authoring_denied_on_draft_and_activate(aiohttp_client): ...
async def test_draft_tooling_policy_on_save_and_activate(aiohttp_client): ...  # stdio MCP refused (C35)
async def test_draft_visibility_patch(aiohttp_client): ...
```
**Why**: Spec §4 mutation rows `declarative_only`, `no import on activation`.

### FILL IN checklist
- [ ] tenant-path save/activate branches; bounded by spec §2 "Declarative activation"
- [ ] `StudioDraftVisibilityHandler.patch`; bounded by AC9
- [ ] seven tests over the FEAT-621 fake

---

## Acceptance Criteria

- [ ] AC12: tenant path — Python-source draft ⇒ 422 `declarative_only`; activation creates/updates the `ai_agents` row and imports no module
- [ ] AC11 (drafts/activation): `name_taken` per tenant, identical body
- [ ] AC13 (drafts): `may_author=False` ⇒ 403 `authoring_denied` on POST /drafts and activate
- [ ] AC9 (drafts) visibility PATCH; AC27 (drafts): tooling policy enforced at save and activation
- [ ] Legacy suites (`test_drafts.py`, `test_drafts_d1.py`, `test_drafts_d3.py`) green
- [ ] Mutations: accept Python source ⇒ `test_python_draft_refused_on_tenant_path` RED; call the import path ⇒ `test_activation_imports_nothing` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_drafts_tenant.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts_d1.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts_d3.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_drafts_tenant.py — see blueprint (7 tests)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3967 agentstudio-tenant-visibility verified`
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
