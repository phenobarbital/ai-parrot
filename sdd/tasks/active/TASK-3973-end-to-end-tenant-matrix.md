# TASK-3973: [W4.2] End-to-end tenant matrix (M12)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3965, TASK-3966, TASK-3967, TASK-3968, TASK-3969, TASK-3970, TASK-3971, TASK-3972
**Assigned-to**: unassigned
**Spec task label**: W4.2 (spec §3 "Task plan")

---

## Context

Spec §4 "Integration Tests (coverage matrix through routed requests)", "Test Data / Fixtures",
Module 12, AC4–AC6, AC11, AC15, AC22, AC25. One routed suite over a prefixed app with a real
resolver, a real `SessionData`, a `view_wrapper` seam double built from `web.View` (not a Mock),
`app["bot_manager"]` via `setup_registry_only`, and the FEAT-621 fake store — every actor × state
row, every route of the §2 table, one mutation note per guard.

---

## Scope

- `scoped_app` fixture per spec §4.
- Actor/state rows: owner, same-tenant peer, tenant admin, global superuser under a tenant URL, different tenant (incl. the record's own owner), resolver + tenant None, `studio_enabled=False`, `may_author=False`, no resolver, names, one session two tenants (assistant), same-name agents on a shared memory backend, registry-only mount, tooling policy.
- Route coverage: every §2 row incl. `/me`, skills PUT/DELETE/resync, execute, `/toolkits/{slug}/schema`, `/catalog/{kind}`, `/keys`, `/assistant` POST/DELETE.
- `test_same_name_agents_shared_memory_backend` (two tenants, same agent name, one memory backend: disjoint histories because the runtime `chatbot_id` is the `agent_id`; mutation: build without `chatbot_id` ⇒ RED).
- A module docstring table mapping each §4 mutation-plan guard to its test (AC22 evidence).

**NOT in scope**: Fixing behaviour (a failing row goes back to its owning task); storage lifecycle tests (FEAT-621).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_tenant_matrix.py` | CREATE | The §4 actor × state × route matrix + mutation-evidence table |

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
from aiohttp import web
from navigator_session.data import SessionData  # precedent tests/handlers/test_ui_surfaces_scope.py:18
from parrot.handlers.scope import RequestScope  # TASK-3956
from parrot.handlers.studio import setup_studio_routes  # TASK-3957
from parrot.manager.manager import BotManager  # setup_registry_only (TASK-3957/10)

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify after the FEAT-621 task
# --- named in "Cross-feature ordering" merges; FEAT-621's names win any conflict.

from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories  # FEAT-621 W1
```

### Existing Signatures to Use
```python
# all FEAT-605 routes (spec §2 "Route policy"); FEAT-621 fake + runtime (A2, A3, A5)
```

### Does NOT Exist
- ~~patching `_get_user`, `_resolve_session` or `_scope`~~ — forbidden (spec §4; `tests/studio/test_integration.py:78-90` is NOT a precedent)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tenant_matrix.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
`packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py` (real `SessionData`); `aiohttp_client` over a prefixed app.

### Key Constraints
- Real `ScopeResolver` installed on the app; the seam double is a `web.View` subclass whose `_iter` stashes the tenant then calls `super()._iter()`.
- The fake must enforce `UNIQUE(tenant, name)` and raise the same signals as the real store (spec §4).

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **all FEAT-621 W3** tasks merged (X16 "Wave 4 closes after storage W3") and FEAT-621 W2 runtime/builder (`chatbot_id = str(agent_id)`, A5) for `test_same_name_agents_shared_memory_backend`.
- Cross-feature ordering: the tooling-policy and execute/options rows need FEAT-622 Waves 1, 2 and 4 (M7, M8, M3b) merged.

### References in Codebase
- spec §4 (matrix, fixtures, mutation plan)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Build `scoped_app` (resolver, seam double, `setup_registry_only`, `setup_studio_routes(prefix=…, view_wrapper=…)`, fake storage).
2. Parametrise actor × state × route; assert identical 404 bodies byte-for-byte.
3. Add the shared-memory test and the mutation-evidence docstring.

### `packages/ai-parrot-server/tests/studio/test_tenant_matrix.py` (CREATE)
```python
"""FEAT-605 M12 — end-to-end tenant matrix.

Mutation evidence (spec §4): <guard> → <test>  (FILL IN: one line per row of the §4 mutation plan, with the
revert you performed and the RED result).
"""
from __future__ import annotations

import pytest

PREFIX = "/api/v1/{tenant}/astudio"


@pytest.fixture
def scoped_app(): ...   # FILL IN per spec §4 "Test Data / Fixtures"

async def test_owner_rows(aiohttp_client, scoped_app): ...
async def test_peer_rows(aiohttp_client, scoped_app): ...
async def test_tenant_admin_rows(aiohttp_client, scoped_app): ...
async def test_global_superuser_under_tenant_url(aiohttp_client, scoped_app): ...
async def test_other_tenant_identical_404(aiohttp_client, scoped_app): ...
async def test_resolver_tenant_none(aiohttp_client, scoped_app): ...
async def test_studio_disabled_every_route_but_me(aiohttp_client, scoped_app): ...
async def test_authoring_denied_every_create_path(aiohttp_client, scoped_app): ...
async def test_no_resolver_feat467_unchanged(aiohttp_client): ...
async def test_names_per_tenant(aiohttp_client, scoped_app): ...
async def test_assistant_one_session_two_tenants(aiohttp_client, scoped_app): ...
async def test_same_name_agents_shared_memory_backend(aiohttp_client, scoped_app): ...
async def test_registry_only_mount_orders(aiohttp_client): ...
async def test_tooling_policy_rows(aiohttp_client, scoped_app): ...
```
**Why**: Spec §4 matrix rows, one test per row group.

### FILL IN checklist
- [ ] fixture + 14 tests + mutation-evidence docstring; bounded by spec §4 and AC22

---

## Acceptance Criteria

- [ ] Every §4 integration-matrix row asserted through routed requests; every §2 route covered
- [ ] AC25: same-name agents in two tenants keep disjoint histories on a shared memory backend (mutation: build without `chatbot_id` ⇒ RED)
- [ ] AC22: each guard of the §4 mutation plan was reverted and its test went RED (evidence in the module docstring)

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tenant_matrix.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_tenant_matrix.py — see blueprint
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3973 agentstudio-tenant-visibility verified`
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
