# TASK-3969: [W3.4] Derivative route gates — test/ask context, tools/toolkits/tooling/files gates, tooling policy, execute/options scope (M9)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3964, TASK-3961
**Assigned-to**: unassigned
**Spec task label**: W3.4 (spec §3 "Task plan")

---

## Context

Spec §2 route rows for test/ask, tools assign, toolkits, toolkit-config/options/MCP, `/toolkits/{slug}/me`,
files, and `/tools/{slug}/execute` (C16, C35, C36), Module 9, AC5, AC6, AC20, AC27, AC28. Every
addressed derivative route answers the identical 404 for another tenant; files GET gets a 403 only
in opted-in hosts (`test_files.py:350 test_get_does_not_require_ownership` stays green without a
resolver); test/ask binds `studio_scope = build_tool_scope(scope, agent_ref)` and runs on the tenant
path inside `manager.studio.use(StudioAgentKey(scope.tenant, name), …)`; tooling writes pass
`TenantToolingPolicy`; options and execute run the FEAT-622 mandatory scope checks before any side
effect; host writes on execute fail closed (zero writes).

Unblocks: **U-FS** (host toolkits can read the context).

---

## Scope

- `testing.py`: `StudioTestingHandler.post`/`.delete` ⇒ 404 invisible before `_get_or_create_test_bot` / `session.pop` (`:319`); tenant path through `manager.studio.use(...)` (replaces `get_bot` at `:216`); bind `studio_scope` at `:270`; re-check on every ask. `StudioToolAssignHandler.post` ⇒ 404 then `can_manage` (replaces `:438` when opted in). Execute: host write tools refused with zero writes; FEAT-622 standalone-tool scope check before `instance.execute` (`:393`).
- `toolkits.py` `StudioToolkitsHandler.post` ⇒ 404 before `_require_owner` (`:311`).
- `toolkit_config.py` `_ToolingViewMixin._authorize` ⇒ 404 before the owner check (`:45`); options ⇒ FEAT-622 scope check before `config_options(param)` (`:158`).
- `toolkit_overrides.py` `_spec` (`:83`) ⇒ 404 invisible; no owner requirement.
- `files.py` `get` (`:170`) ⇒ 404; opted in ⇒ 403 when not manageable; `put` (`:216`) / `delete` (`:280`) ⇒ 404 before the owner check (`:236`, `:300`).
- Tooling writes on the tenant path (assign, toolkits, toolkit-config, MCP servers): `TenantToolingPolicy` on the final normalised config before persistence (via FEAT-621 `StudioToolingGate` / FEAT-622 `enforce_tenant_tooling`); refusals ⇒ 422 `tooling_not_permitted`.

**NOT in scope**: Defining the policy, the scope-enforcement gate in `AbstractTool.execute`/`config_options` or the confirmation mechanism (FEAT-622); scope binding in `chat.py`, execute and options (FEAT-622 M5 binds those; this task binds only test/ask).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | test/ask + stop gates, `studio_scope` binding, tenant-path `manager.studio.use`, assign gate, execute host-write/scope rules |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | 404 before the owner check; tooling policy on assign |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | 404 before the owner check; options scope check; tooling policy on PUT/MCP |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | 404 for an invisible agent in `_spec` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | MODIFY | 404 on get/put/delete; opted-in 403 on GET when not manageable |
| `packages/ai-parrot-server/tests/studio/test_derivative_gates.py` | CREATE | Identical 404 across derivative routes; opted-in-only files GET gate; test/ask context |
| `packages/ai-parrot-server/tests/studio/test_tooling_policy_routes.py` | CREATE | C35/C36: stdio MCP refused, options/execute scope enforced, host write fails closed |

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
from .access import build_tool_scope  # TASK-3964

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from .storage.models import StudioAgentKey, StudioToolingRefused  # FEAT-621 W0
# manager.studio.use(key, *, session_id=None, request=None) — FEAT-621 W2 runtime (X7)
# --- Created by FEAT-622 (agentstudio-host-toolkits); verify names after its waves merge:
# enforce_tenant_tooling(app, tooling, *, subject), ToolingSubject — FEAT-622 Wave 1 M7 core (X15, X18)
# ensure_tool_scope / automatic gate in AbstractTool.execute and the wrapped config_options — FEAT-622 Wave 4 M3b
# approval-token confirmation — FEAT-622 Wave 2 M8
```

### Existing Signatures to Use
```python
# S/studio/testing.py (verified at 32b1a45d4; FEAT-621 W3 + FEAT-622 rewrite parts; re-anchor)
class StudioTestingHandler           # :226 ; post :235 ; bot = await manager.get_bot(agent_name, new=True, …) :216 (in _get_or_create_test_bot :182) ;
                                     #   async with bot.session(request=self.request, app=self.request.app) as live_bot: :270 ;
                                     #   delete :312 ; bot_name = session.pop(key, None) … :319
class StudioToolExecuteHandler       # :341 ; post :344 ; result = await instance.execute(**execute_request.args) :393
class StudioToolAssignHandler        # :399 ; post :408 ; self._require_owner(owner, user) :438
# S/studio/toolkits.py: StudioToolkitsHandler :221 ; post :281 ; _require_owner :311
# S/studio/toolkit_config.py: _ToolingViewMixin :29 ; _authorize :36 ; _require_owner(state.owner, …) :45 ;
#   StudioToolkitOptionsHandler :132 ; config_options(param) :158 ; StudioAgentMcpServersHandler :176 (put :194)
# S/studio/toolkit_overrides.py: StudioUserToolkitOverrideHandler :76 ; _spec :83
# S/studio/files.py: StudioFilesHandler :162 ; get :170 (exists, _owner = … :184) ; put :216 (… :236) ; delete :280 (… :300)
# core: AbstractBot.session(..., **ctx_kwargs) — packages/ai-parrot/src/parrot/bots/abstract.py:4143 ;
#   RequestContext kwargs → self.kwargs — packages/ai-parrot/src/parrot/utils/helpers.py:28,36
```

### Does NOT Exist
- ~~`manager.get_bot(name)` on the tenant path~~ — forbidden (A2); use `manager.studio.use(...)`
- ~~an owner check on `GET /agents/{name}/files`~~ today — add it opted-in only
- ~~`studio_scope` in `RequestContext.kwargs`~~ today — bound here at test/ask

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/files.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_derivative_gates.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_policy_routes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioTestingHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolExecuteHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolAssignHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#_ToolingViewMixin",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#StudioToolkitOptionsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/files.py#StudioFilesHandler",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.session"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`_check_record_access(access, rec, kind, name, manage=…)` from TASK-3964 (`_base.py`) for every 404/403 decision; never duplicate the rule.

### Key Constraints
- Identical 404 body on every addressed route for another tenant (AC5).
- Files GET gate only when opted in (G9, AC3, `test_get_does_not_require_ownership`).
- `studio_scope.agent.tenant == studio_scope.caller.tenant` (AC20); nothing bound without a resolver.
- Tooling refusals before persistence and before any process start (C35); scope refusals before any resource acquisition (C36).
- Anchors below were verified at `32b1a45d4` (before FEAT-621 W3). FEAT-621 W3 rewrites these handler bodies (`_legacy_*` + store paths): re-run every `grep -c` after rebasing on it and re-locate each anchor; a count of `0` means drift — stop and report (spec §6 Edit Sites note).

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Handler switch: agents, files, tooling" (files.py, toolkit_config.py, toolkits.py, toolkit_overrides.py) and "Handler switch: drafts, catalogue, testing" (testing.py) merged first, per file; FEAT-621 W1 "Tooling identity plumbing" (M13) is already first on `toolkit_overrides.py`.
- Cross-feature ordering: C35 needs FEAT-622 Wave 1 (M7 core) and Wave 2 (M7 wiring on the FEAT-593 write/assign/attach/execute paths, which edits `testing.py`/`toolkits.py`); serialise per file with those FEAT-622 tasks.
- Cross-feature ordering: C36 assertions (`test_options_scope_enforced`, `test_execute_standalone_scope_enforced`, `test_execute_host_write_fails_closed`) need FEAT-622 Wave 2 M8 and Wave 4 M3b merged; but X16 also makes FEAT-622 Wave 4 (M5) wait for this task "for the asserted bindings". Order: FEAT-622 M3b (+M8) → this task → FEAT-622 M5. If M3b cannot land first, split the C36 assertions into a follow-up (spec ambiguity, reported).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_files.py:350` — must stay green without a resolver

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3 (and FEAT-622 tasks on the same files); re-anchor each site.
2. Add the per-route 404/403 checks and the opted-in files GET gate.
3. Switch test/ask to `manager.studio.use(...)` on the tenant path and bind `studio_scope`.
4. Wire C35/C36 calls at the tooling-write, options and execute sites.
5. Write both test modules.

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            async with bot.session(request=self.request, app=self.request.app) as live_bot:' testing.py) — :270
# REPLACE with (opted in only; plain host binds nothing):
            ctx = {"studio_scope": build_tool_scope(scope, access.agent_ref(rec))} if self._opted_in() else {}
            async with bot.session(request=self.request, app=self.request.app, **ctx) as live_bot:
# occurrences: 1 (verified: grep -c '        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)' testing.py) — :216
#   FILL IN: tenant path ⇒ manager.studio.use(StudioAgentKey(scope.tenant, name), session_id=…, request=…) (lease) — bounded by A2
# occurrences: 1 (verified: grep -c '        bot_name = session.pop(key, None) if session is not None else None' testing.py) — :319 → 404 first
# occurrences: 1 (verified: grep -c '        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial' testing.py) — :438 → 404, then can_manage
#   FILL IN: execute (:393) — FEAT-622 standalone scope check + host-write fail-closed — bounded by C36 / AC28
```
**Why**: Spec M9 skeleton (testing.py rows).

### `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        exists, _owner = await self._resolve_agent(agent_name)' files.py) — :184 (GET)
#   FILL IN: 404 invisible; opted in ⇒ 403 when not can_manage; plain host unchanged (test_files.py:350)
# occurrences: 2 (verified: grep -c '        exists, owner = await self._resolve_agent(agent_name)' files.py) — :236 (put), :300 (delete)
#   FILL IN: disambiguate — quote the following `user = await self._get_user()` per site; 404 before the owner check
```
**Why**: Spec M9 skeleton (files.py rows).

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial' toolkits.py) — :311
#   FILL IN: insert the 404 check above; tenant-path tooling write ⇒ policy (C35)
```
**Why**: Spec M9 skeleton.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._require_owner(state.owner, await self._get_user())' toolkit_config.py) — :45
#   FILL IN: 404 before the owner check in _authorize
# occurrences: 1 (verified: grep -c 'config_options(' toolkit_config.py) — :158
#   FILL IN: FEAT-622 mandatory scope check before config_options acquires any resource (C36)
```
**Why**: Spec M9 skeleton.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _spec(self, name: str, slug: str):' toolkit_overrides.py) — :83
#   FILL IN: 404 when the agent is invisible; no owner requirement (own override allowed)
```
**Why**: Spec route row `/toolkits/{slug}/me`.

### `packages/ai-parrot-server/tests/studio/test_derivative_gates.py` (CREATE)
```python
"""FEAT-605 M9 — derivative route gates."""
from __future__ import annotations

async def test_other_tenant_identical_404_every_route(aiohttp_client): ...
async def test_files_get_gate_opted_in_only(aiohttp_client): ...        # mutation: gate without resolver ⇒ test_files.py:350 RED
async def test_test_ask_context_has_scope_and_agent(aiohttp_client): ...  # agent.tenant == caller.tenant; nothing bound without resolver
async def test_test_ask_rechecks_visibility(aiohttp_client): ...       # downgrade mid-session ⇒ next ask 404
async def test_assign_and_toolkits_manage_gate(aiohttp_client): ...
```
**Why**: Spec §4 mutation rows `opted-in-only gates`, `context kwargs`.

### `packages/ai-parrot-server/tests/studio/test_tooling_policy_routes.py` (CREATE)
```python
"""FEAT-605 C35/C36 on Studio routes (FEAT-622 mechanisms)."""
from __future__ import annotations

async def test_mcp_stdio_refused_on_tenant_path(aiohttp_client): ...   # also transport/command in params; no process; host-approved config accepted
async def test_options_scope_enforced(aiohttp_client): ...
async def test_execute_standalone_scope_enforced(aiohttp_client): ...
async def test_execute_host_write_fails_closed(aiohttp_client): ...    # zero writes
```
**Why**: Spec §4 mutation rows for tooling policy and scope enforcement.

### FILL IN checklist
- [ ] every edit site above (re-anchored); bounded by spec §2 rows, AC5, AC6, AC20, AC27, AC28
- [ ] both test modules

---

## Acceptance Criteria

- [ ] AC5/AC6 for derivative routes: identical 404 for another tenant; 403 for visible-not-manageable (files GET opted-in only)
- [ ] AC3: `test_get_does_not_require_ownership` green without a resolver
- [ ] AC20: test/ask binds `studio_scope` built by `build_tool_scope`; `.agent.tenant == .caller.tenant`; nothing bound without a resolver
- [ ] AC27 (routes): tenant stdio MCP config (incl. via `params`) refused before persistence/process start; approved host config works
- [ ] AC28: execute and options refuse missing/mismatched scope before side effects; host write on execute ⇒ zero writes
- [ ] Mutations: gate files GET without a resolver ⇒ `test_files.py::test_get_does_not_require_ownership` RED; drop the context binding ⇒ `test_test_ask_context_has_scope_and_agent` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_derivative_gates.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_policy_routes.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_files.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_derivative_gates.py — 5 tests (see blueprint)
# packages/ai-parrot-server/tests/studio/test_tooling_policy_routes.py — 4 tests (see blueprint)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3969 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback loop, tramo B2)
**Date**: 2026-10-02
**Notes**: Derivative routes of an agent follow the access rule on Studio rows: toolkit-config / toolkits/{slug} / options /
mcp-servers (`_ToolingViewMixin._decide_access`, also used by `_write`'s re-authorization via `_reauthorize`), live assignment
`POST /agents/{n}/tools` + `/toolkits` (`_assign_owner` moved into `_StudioAgentsMixin`: 404 invisible / 403 not manageable; admin
allowed), files (GET is now 403 for visible-not-manageable ONLY in opted-in hosts; PUT/DELETE unchanged: 404/403), `/toolkits/{slug}/me`
(`_visible_state`: invisible ⇒ the one 404, no owner requirement — a visible agent's caller edits their OWN override),
test/ask + DELETE test (404 before the session entry is touched). test/ask binds
`studio_scope = build_tool_scope(scope, agent_ref)` through `bot.session(..., studio_scope=...)` in opted-in hosts only (nothing on a
plain host) and runs inside `manager.studio.use(...)` as before; the access decision is re-run on every ask.
Tenant partitions never call `manager.get_bot(name)` for live assignment (A2, `_live_bot`): the tenant policy (422) still answers
first (policy check moved before the live-instance lookup, zero complexity growth), an allowed tenant assignment is 404 "no live
instance" (tooling for tenant agents is persisted via toolkit-config, not live-assigned) — two B1 tests were adapted to this.
Mutations RED (restored): toolkit-config access off; `/me` visibility off; files GET opted-in 403 off; assign access `manage=False`;
`studio_scope` binding off; test DELETE 404 off; tenant `get_bot` lookup re-allowed; options/execute scope check off; owner/access
decision in options route off.
Tests: `test_derivative_gates.py` (52: identical 404 for hidden / other-tenant / absent on 16 routes, 403 matrix, peer-allowed
routes, owner+admin pass, files-GET opted-in-only, scope binding, plain host binds nothing, /me with a configured toolkit),
`test_tooling_policy_routes.py` (4: stdio MCP refused with zero processes, builtin refused, host write fails closed with zero writes,
options gates). Server suite vs baseline-package: 0 new.

**Deviations from spec**: `testing/` and `agents/` package modules instead of the single files; `test_tenant_tooling_writes.py` and
`test_tenant_catalogue_execute_policy.py` adapted (tenant live assignment is now 404). The options route for a tenant-bound toolkit
still answers 403 `tool_scope_unavailable` until TASK-3991 binds the scope there.
