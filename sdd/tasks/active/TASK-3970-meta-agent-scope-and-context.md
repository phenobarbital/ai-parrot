# TASK-3970: [W3.5] Meta-agent scope and context — studio_scope binding, gated/stamped/filtered tools (M10)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3964
**Assigned-to**: unassigned
**Spec task label**: W3.5 (spec §3 "Task plan")

---

## Context

Spec §2 "Request context for tools", route row `POST /assistant`, Module 10, C12, C16, AC13, AC14, AC20.
The meta-agent's tools must obey the same gate, stamping, filtering and tenant path as the routes:
`save_agent_draft` (refuses Python source on the tenant path), `create_yaml_agent`,
`publish_skill_to_catalog` (stamp the real user + tenant, never `owner="agent_studio"`; per-tenant
`name_taken`), `list_existing_agents` (only what the caller can see in its tenant), and
`_require_agent_owner` (refuses an agent of another tenant). The handler binds
`studio_scope = build_tool_scope(scope)` (agent=None). Core `ai-parrot` reads it duck-typed
(no server import at module level).

---

## Scope

- `meta_agent.py:110`: when opted in, pass `studio_scope=build_tool_scope(await self._scope())` to `agent.session(...)`.
- Core `tools.py`: add `_studio_caller()` (duck-typed: `current_context().kwargs.get("studio_scope")` → `.caller`, else None).
  - `save_agent_draft` (`:162`): caller present and `may_author` False ⇒ `PermissionError("authoring_denied")`; tenant path + Python source ⇒ `PermissionError("declarative_only")`.
  - `create_yaml_agent` (`:274`): gate; tenant path writes the agents store, stamped (replaces `created_by` at `:320`).
  - `publish_skill_to_catalog` (`:459`): gate; `owner=user_id` (not `"agent_studio"`, `:513`), tenant, `private`; per-tenant `name_taken`.
  - `list_existing_agents` (`:560`): tenant path ⇒ names of store rows the scope can see.
  - `_require_agent_owner` (`:84`): refuse an agent whose tenant ≠ `caller.tenant`.
  - Tooling written by these tools passes `TenantToolingPolicy` (through FEAT-621 services) — C35.
- Tests with scope present/absent.

**NOT in scope**: Assistant session/instance partitioning and `chatbot_id` (TASK-3971); the service calls themselves (FEAT-621 W3 "Assistant tools on services" switches the tools to services first).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | MODIFY | Bind `studio_scope` at `agent.session(...)` (opted in) |
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | `_studio_caller()`; gate/stamp/filter in the four tools; tenant check in `_require_agent_owner` |
| `packages/ai-parrot-server/tests/studio/test_meta_agent_scope.py` | CREATE | Tools with scope present/absent; authoring_denied; filter; publish stamp |

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
from parrot.utils.helpers import current_context  # verified: packages/ai-parrot/src/parrot/bots/studio/tools.py:41
from .access import build_tool_scope  # TASK-3964 (server side, meta_agent.py only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/studio/tools.py (core; no server import at module level :25-32)
def _require_user_id() -> str                                              # :61
async def _require_agent_owner(app: Any, agent_name: str, user_id: str) -> None   # :84
async def save_agent_draft(...)                                            # :162 ; row = StudioDraft(**fields, owner_user_id=user_id) :238
async def create_yaml_agent(...)                                           # :274 ; config_dict["created_by"] = user_id :320
async def publish_skill_to_catalog(...)                                    # :459 ; owner="agent_studio", :513
async def list_existing_agents() -> list                                   # :560
# packages/ai-parrot/src/parrot/utils/helpers.py: RequestContext :7 ; **kwargs → self.kwargs :28, :36
# S/studio/meta_agent.py
            async with agent.session(request=self.request, app=self.request.app, user_id=user.user_id) as bot:  # :110
```

### Does NOT Exist
- ~~a module-level import of `ai-parrot-server` in core tools~~ — forbidden (`tools.py:25-32`); read `studio_scope` duck-typed
- ~~`_studio_caller`~~ — created here
- ~~a tenant check in `_require_agent_owner`~~ today — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/studio/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_meta_agent_scope.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#_require_agent_owner",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#save_agent_draft",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#create_yaml_agent",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#publish_skill_to_catalog",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#list_existing_agents",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py#StudioAssistantHandler.post"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`_require_user_id()` (`tools.py:61`) — fail-closed accessor over `current_context()`; `_studio_caller()` follows the same shape but returns `None` when nothing is bound (plain host).

### Key Constraints
- Duck typing only: `getattr(getattr(ctx, "kwargs", {}).get("studio_scope"), "caller", None)`; type-check, never truth-check a Mapping value (spec §7).
- With no `studio_scope` bound (plain host), tool behaviour is FEAT-467 (except the `owner="agent_studio"` stamp, which is always the real user — AC14).
- Refusal codes surface as `PermissionError("authoring_denied")` / `PermissionError("declarative_only")` (spec M10).
- Anchors were verified at `32b1a45d4` (before FEAT-621 W3 "Assistant tools on services", which rewrites these files): re-run every `grep -c` after rebasing; `0` means drift — stop and report.

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Assistant tools on services" merged first (same files: `meta_agent.py`, core `bots/studio/tools.py`; per-file rule, X16) plus FEAT-621 W2 services.
- Cross-feature ordering: FEAT-622 Wave 4 (M5) asserts this task's meta-agent binding — FEAT-622 M5 merges after this task (X16).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_meta_agent.py` — existing suite (exercises the core tools)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3 "Assistant tools on services"; re-anchor.
2. Bind `studio_scope` in `meta_agent.py` — *why*: C16/AC20.
3. Add `_studio_caller()` and apply gate/stamp/filter per tool — *why*: AC13/AC14.
4. Write tests with scope present and absent.

### `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            async with agent.session(request=self.request, app=self.request.app, user_id=user.user_id) as bot:' meta_agent.py) — :110
# REPLACE with:
            ctx = {"studio_scope": build_tool_scope(await self._scope())} if self._opted_in() else {}
            async with agent.session(request=self.request, app=self.request.app, user_id=user.user_id, **ctx) as bot:
```
**Why**: AC20: the meta-agent binds `studio_scope` with `agent=None`; nothing bound without a resolver.

### `packages/ai-parrot/src/parrot/bots/studio/tools.py` (MODIFY)
```python
# AFTER `def _require_user_id() -> str:` block (:61-81) — add:
def _studio_caller() -> Any:
    """``current_context().kwargs['studio_scope'].caller`` or None (duck-typed; no server import)."""
    ctx = current_context()
    kwargs = getattr(ctx, "kwargs", None)
    scope = kwargs.get("studio_scope") if isinstance(kwargs, dict) else None
    return getattr(scope, "caller", None)

# occurrences: 1 (verified: grep -c 'async def _require_agent_owner(app: Any, agent_name: str, user_id: str) -> None:' tools.py) — :84
#   FILL IN: caller present ⇒ refuse an agent whose tenant != caller.tenant (ValueError "not found" — no disclosure)
# occurrences: 1 (verified: grep -c '        owner="agent_studio",' tools.py) — :513
#   FILL IN: owner=user_id; tenant=caller.tenant; visibility "private"; conflict ⇒ "name_taken"
# occurrences: 1 (verified: grep -c 'async def list_existing_agents() -> list:' tools.py) — :560
#   FILL IN: tenant path ⇒ only names of store rows the caller can see (reuse FEAT-605 rule via the services' partition)
# save_agent_draft (:162) / create_yaml_agent (:274): FILL IN gate (PermissionError('authoring_denied')),
#   tenant-path Python source ⇒ PermissionError('declarative_only') — bounded by AC13 / C3
```
**Why**: Spec M10 skeleton; core never imports the server package.

### `packages/ai-parrot-server/tests/studio/test_meta_agent_scope.py` (CREATE)
```python
"""FEAT-605 M10 — meta-agent tools under a bound studio_scope."""
from __future__ import annotations

async def test_tools_without_scope_unchanged(): ...
async def test_authoring_denied_meta_tools(): ...        # save_agent_draft / create_yaml_agent / publish_skill_to_catalog
async def test_save_agent_draft_python_refused_tenant_path(): ...
async def test_list_existing_agents_filtered(): ...      # mutation: return all names ⇒ RED
async def test_publish_skill_stamps_user(): ...          # owner != "agent_studio" (mutation: restore literal ⇒ RED)
async def test_require_agent_owner_other_tenant_refused(): ...
async def test_assistant_binds_studio_scope(aiohttp_client): ...
```
**Why**: Spec §4 mutation row `meta-agent filter / stamp`.

### FILL IN checklist
- [ ] the five core tool edits + handler binding (re-anchored); bounded by AC13, AC14, AC20
- [ ] seven tests (bind a real `RequestContext` with `studio_scope=build_tool_scope(RequestScope(...))`, never a Mock)

---

## Acceptance Criteria

- [ ] AC13 (meta-agent): `may_author=False` ⇒ `save_agent_draft`, `create_yaml_agent`, `publish_skill_to_catalog` raise `PermissionError('authoring_denied')`
- [ ] AC14: `publish_skill_to_catalog` stamps the calling user and tenant (never `"agent_studio"`); `list_existing_agents` returns only names the scope can see in its tenant
- [ ] AC20 (meta-agent): `RequestContext.kwargs['studio_scope']` is bound by `build_tool_scope` with `agent=None`; nothing bound without a resolver
- [ ] Mutations: return unfiltered names ⇒ `test_list_existing_agents_filtered` RED; restore `owner="agent_studio"` ⇒ `test_publish_skill_stamps_user` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent_scope.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_meta_agent_scope.py — 7 tests (see blueprint)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3970 agentstudio-tenant-visibility verified`
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
