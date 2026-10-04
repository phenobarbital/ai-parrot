# TASK-3984: Wire the tenant tooling policy into live attach, direct execute and the catalogues (M7 wiring, part 2)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3977, TASK-3980, TASK-3981, TASK-3982
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M7 tenant-tooling-policy (wiring: attach/execute/catalogue)

---

## Context

Spec §2 enforcement table rows **attach** (`POST /agents/{name}/tools` live assign, `testing.py:458` →
`policy.check_tool` per slug, `phase="attach"`), **execute** (`POST /tools/{slug}/execute`, `testing.py:363` →
`policy.check_tool(slug)`, `phase="execute"`, before `_instantiate_tool`; refusal 403) and **catalogue**
(`GET /catalog/tools`, meta-agent "list tools" `bots/studio/tools.py:547`: a tenant partition lists only entries
`check_tool` permits). AC: built-in tools are available to tenant authors only when listed in `builtin_tools`.

---

## Scope

- `testing.py` live assign: `check_tool` per tool name and per toolkit slug (`phase="attach"`) before
  `register_tools` / `register_toolkit`; refusal → 422 `tooling_not_permitted` with `details`.
- `testing.py` execute: `check_tool(slug, phase="execute")` right after resolution, before `_instantiate_tool`;
  refusal → **403** `tooling_not_permitted`.
- `tools_catalog.py`: add `access` per entry from TASK-3981's `effective_access` (tool: its access; toolkit: a
  `{"read": [...], "write": [...]}` summary, `None` when unknown) — spec AC "The catalogue carries `source` and `access`".
- `tools_catalog.py`: add `filter_catalog_for(app, subject) -> list[dict]` that returns the cached catalogue
  filtered by `check_tool` (no-op when the policy does not apply); the Studio catalogue route
  (`catalog.py::_get_tools`) is **not** edited here — FILL IN where the subject is available (see notes).
- `bots/studio/tools.py::list_available_tools`: filter through `filter_catalog_for` using the current request's
  app and the bound `studio_scope` caller tenant (`current_tool_scope()`), unfiltered when none.
- Test `test_tenant_catalogue_and_execute_respect_policy`.

**NOT in scope**: FEAT-593 writes and assign (TASK-3983); scope enforcement on execute (TASK-3990).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | attach + execute policy checks |
| `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` | MODIFY | `access` per entry; filter_catalog_for(app, subject) |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | list_available_tools filtered for a tenant caller |
| `packages/ai-parrot-server/tests/studio/test_tenant_catalogue_execute_policy.py` | CREATE | test_tenant_catalogue_and_execute_respect_policy |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.tooling_policy import TenantToolingRefused, ToolingSubject, get_tenant_tooling_policy  # TASK-3977
from parrot.tools.scope import current_tool_scope  # TASK-3976 (meta-agent tool only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
class StudioToolExecuteHandler  # :341 — cls = _resolve_registry_class(slug) :363; not_found :369; _instantiate_tool :372
class StudioToolAssignHandler   # :399 — register_tools :451-455; toolkit loop :457-473 (cls = _resolve_registry_class(entry.slug) :458)
# packages/ai-parrot-server/src/parrot/handlers/studio/catalog.py:230-236 _get_tools (reference; see Cross-feature ordering)
# packages/ai-parrot/src/parrot/bots/studio/tools.py
@tool(name="list_available_tools", ...)  # :545-548
async def list_available_tools() -> list:  # :549 — imports _build_catalog lazily from parrot.handlers.tools_catalog (:551)
def _require_app()  # used at :562 by list_existing_agents
```

### Does NOT Exist
- ~~a tenant-aware catalogue~~ — none today.
- ~~core importing the server at module top~~ — `bots/studio/tools.py` already imports `parrot.handlers.*` lazily inside the tool (:540, :551); keep it lazy.
- ~~`StudioBaseView._scope()` / `_studio_partition()`~~ — FEAT-605 W2.1 / FEAT-621 W1; not on `dev` @ 32b1a45d4.

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
      "path": "packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/studio/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tenant_catalogue_execute_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolExecuteHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioToolAssignHandler.post",
    "sym:packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py#_build_catalog",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#list_available_tools"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- One helper in `testing.py`, `_policy_check(slug, phase) -> web.Response | None`, used by both handlers.
- The GLOBAL partition is unchanged (no `apply_to_global`): helper is a no-op when `subject.tenant is None`.

### Spec ambiguity (record in Completion Note)
- The Studio catalogue route lives in `catalog.py` (`_get_tools`, `:230-236`), which the spec does not list in
  M7's path but which serves `GET /catalog/tools`. This task adds `filter_catalog_for` and filters the meta-agent
  tool; wiring `catalog.py` needs the request subject (FEAT-605 `_scope()`), so it is done here **only if** that
  API is on `dev`; otherwise record it as a follow-up for the FEAT-605 C35/C36 route rows.

### Cross-feature ordering
- `testing.py` and core `bots/studio/tools.py` are on the X16 per-file list: merge after the FEAT-621 W2/W3 task
  for each file (and after FEAT-605 W1.3 for `testing.py`) and rebase.
- Tenant subjects need FEAT-621 W1 `_studio_partition()` + FEAT-605 W2.1.

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `_policy_check` and call it in execute (403) and attach (422) — *why*: enforcement table rows.
2. Add `filter_catalog_for` — *why*: one filter for HTTP and meta-agent catalogues.
3. Filter `list_available_tools` for a tenant caller — *why*: enforcement table row "catalogue".
4. Test: tenant catalogue omits `shell`; `/tools/shell/execute` 403; assign `shell` 422; GLOBAL unchanged.

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# FILL IN: disambiguate — in StudioToolExecuteHandler.post, insert directly below the not_found return that
#   follows `cls = _resolve_registry_class(slug)` (testing.py:363-369):
        if (refused := self._policy_check(slug, phase="execute", status=403)) is not None:
            return refused
# and in StudioToolAssignHandler.post before `bot.tool_manager.register_tools(assign_request.tools)` (:453) and
#   at the top of the toolkit loop (:457): `self._policy_check(..., phase="attach", status=422)`
# FILL IN: _StudioTestingMixin._policy_check(slug, *, phase, status) -> web.Response | None
```

### `packages/ai-parrot-server/src/parrot/handlers/tools_catalog.py` (MODIFY)
```python
def filter_catalog_for(app: Any, subject: "ToolingSubject | None", catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Entries the tenant policy permits; unchanged when the policy does not apply (GLOBAL partition)."""
    # FILL IN: policy = get_tenant_tooling_policy(app); no-op if subject None or (tenant None and not apply_to_global);
    #   keep entries whose check_tool does not raise TenantToolingRefused
```

### `packages/ai-parrot/src/parrot/bots/studio/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return _build_catalog()' bots/studio/tools.py)
# REPLACE `    return _build_catalog()` (verified: bots/studio/tools.py:553) with:
    catalog = _build_catalog()
    # FILL IN: scope = current_tool_scope(); if scope is None return catalog; else
    #   filter_catalog_for(app, ToolingSubject(tenant=scope.caller.tenant, agent_id=None, actor=scope.caller.user_id,
    #   phase="attach"), catalog)
    return catalog
```

### FILL IN checklist
- [ ] `_policy_check` — subject construction and response shape; bounded by X14 (422 attach / 403 execute).
- [ ] `filter_catalog_for` — no-op conditions; bounded by P-Q3 (GLOBAL unchanged).
- [ ] `list_available_tools` — scope-derived subject; bounded by enforcement table row "catalogue".

---

## Acceptance Criteria

- [ ] Catalogue entries carry `access` (`"read"`/`"write"`/`None` or a per-method summary for toolkits).
- [ ] A tenant partition's catalogue omits `shell` under `deny_all()`; includes `wiki` when listed.
- [ ] `POST /tools/shell/execute` → 403 `tooling_not_permitted`; live assign of `shell` → 422 `tooling_not_permitted`.
- [ ] The GLOBAL partition is unchanged (existing `test_testing_surface.py`, `test_meta_agent.py` pass).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tenant_catalogue_execute_policy.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -q`
- `pytest packages/ai-parrot-server/tests/test_tools_list_route.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_tenant_catalogue_execute_policy.py
async def test_tenant_catalogue_and_execute_respect_policy(host_plugins):
    """Tenant catalogue omits shell; execute shell 403 / assign shell 422 tooling_not_permitted; GLOBAL unchanged."""
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (tramo B1, sequential fallback)
**Date**: 2026-10-02
**Notes**: _StudioTestingMixin._policy_check (async: partition lookup) used by execute (403, via StudioToolExecuteHandler._executable_refusal) and attach (422, StudioToolAssignHandler._attach_refusal before any registration); tools_catalog: access per entry (toolkit {read,write} summary / tool access / None) + filter_catalog_for(app, subject, catalog); meta-agent list_available_tools (bots/studio/tools/introspection.py) filtered when a studio_scope is bound (no app => fail closed). Spec ambiguity resolved: FEAT-605 _studio_partition exists on this branch so the Studio catalogue route (catalog.py::StudioCatalogHandler._tools_for_caller) IS wired (file outside the Files table; authorised by the task's Spec-ambiguity note). Assign post extracted _agent_owner to keep its complexity (14) from growing. Order on execute: 404 -> tenant policy 403 -> confirmation 403.
**Mutation evidence**: filter no-op => catalogue + meta-agent tests RED; execute check removed => RED; attach check removed => RED; meta filter removed => RED; catalog route unfiltered => RED; access forced None => access test RED; all restored.

**Deviations from spec**: none (handler modules are now packages; edit sites re-anchored)
