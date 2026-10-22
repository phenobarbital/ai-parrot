# TASK-3971: [W3.6] Assistant session partitioning by (tenant, user) + cleanup_studio_assistants hook (M10)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3959, TASK-3970
**Assigned-to**: unassigned
**Spec task label**: W3.6 (spec §3 "Task plan")

---

## Context

Spec §2 "Assistant session partitioning", C30, X17, AC24; Jesus review R4. Today one session entry
`SESSION_KEY = "_studio_assistant"` (`meta_agent.py:27`) names one instance in the app-level cache
`_studio_assistant_instances` (`:33`), reused whatever the tenant (`:57-75`); the instance has no
explicit `chatbot_id` (`:68`) so its memory key is its name; `ask` gets neither `user_id` nor
`session_id` (falls back to a fresh uuid and `"anonymous"`, `bots/base.py:1110-1111`); `DELETE`
(`:123-133`) pops the one entry and drops the instance without cleanup. Switching tenants in one
login reuses the other tenant's history and toolset.

Unblocks: **U-SV** (assistant safe to expose per tenant).

---

## Scope

- Partition key `(tenant or "-", user_id)` → string `"<tenant|->:<user_id>"`; opted in with `scope.tenant is None` ⇒ 422 `tenant_required` before any instance is touched.
- `session[SESSION_KEY]` becomes `{partition: {"instance": <name>, "session_id": <uuid>}}`; a request reads/writes only its own partition.
- `app[_ASSISTANTS_APP_KEY]` keyed by `(tenant or "-", user_id, instance_name)`; each cached instance records its partition; a lookup whose recorded partition differs is a miss.
- Build with `AgentStudioAgent(name=…, chatbot_id=f"agent_studio:{tenant or '-'}", api_key=…)` (replaces `:68`).
- `bot.ask(question=…, user_id=user.user_id, session_id=<partition session_id>)`.
- `DELETE` pops only the current partition's entry and awaits that instance's cleanup once.
- `cleanup_studio_assistants(app)` `on_cleanup` hook, appended once per app by `setup_studio_routes` via `install_startup_hook_once(app, cleanup_studio_assistants, signal="on_cleanup")` (every host mode).

**NOT in scope**: Studio runtime instance memory identity (`chatbot_id = str(agent_id)`, FEAT-621 builder, C31); sticky sessions across pods (storage non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | MODIFY | Partitioned session entry + instance cache, explicit `chatbot_id`, explicit `user_id`/`session_id` to `ask`, partition-only DELETE, `cleanup_studio_assistants` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | Register `cleanup_studio_assistants` once per app (hook registration only) |
| `packages/ai-parrot-server/tests/studio/test_assistant_partition.py` | CREATE | Alternating tenants in one session, toolset not shared, partition-only DELETE, tampered session, memory key, app cleanup |

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
from parrot.bots.studio import AgentStudioAgent  # verified: S/studio/meta_agent.py:20
from navigator_auth.decorators import is_authenticated, user_session  # verified: S/studio/meta_agent.py:19
# setup_studio_routes' guard helper: install_startup_hook_once (TASK-3957, studio/__init__.py)
```

### Existing Signatures to Use
```python
# S/studio/meta_agent.py
SESSION_KEY = "_studio_assistant"                                         # :27
_ASSISTANTS_APP_KEY = "_studio_assistant_instances"                       # :33
class StudioAssistantHandler(StudioBaseView)                              # :45
    def _instances(self) -> dict[str, AgentStudioAgent]                   # :55
    async def _get_or_create_assistant(self, session, *, api_key)          # :57
        agent = AgentStudioAgent(name=f"agent_studio_{uuid.uuid4().hex[:8]}", api_key=api_key)   # :68
    async def post(self)                                                  # :77 ; bot.ask(question=ask_request.query) :111
    async def delete(self)                                                # :123 ; instance_key = session.pop(SESSION_KEY, None) … :125 ; instances.pop :131
# packages/ai-parrot/src/parrot/bots/base.py:1110-1111 — ask() falls back to uuid4 session and "anonymous" user
# packages/ai-parrot/src/parrot/bots/abstract.py:1959-1984 — memory_key_id from chatbot_id, else name
```

### Does NOT Exist
- ~~a tenant or user in the assistant's session key or instance cache key~~ (`:27`, `:33`) — added here
- ~~`user_id`/`session_id` passed to the assistant's `ask`~~ (`:111`) — added here
- ~~instance cleanup on `DELETE /assistant`~~ (`:131`) — added here
- ~~`cleanup_studio_assistants`~~ — created here

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
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_assistant_partition.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py#StudioAssistantHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py#StudioAssistantHandler._get_or_create_assistant",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py#setup_studio_routes"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Spec §2 "Assistant session partitioning" bullet list is the contract; M10 skeleton `_assistant_partition(scope, user) -> str`.

### Key Constraints
- The assistant is not a Studio agent: its identity is `agent_studio:<tenant|->` + explicit `user_id`/`session_id` (X17).
- A cached instance whose recorded partition differs from the request's is never returned.
- Cleanup of each instance exactly once (DELETE or app cleanup).
- Hook installed through `install_startup_hook_once` — once per app across prefixes (AC17, X10).
- Anchors were verified at `32b1a45d4` (before FEAT-621 W3 "Assistant tools on services", which rewrites these files): re-run every `grep -c` after rebasing; `0` means drift — stop and report.

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W3** "Assistant tools on services" merged first on `meta_agent.py` (X16 "FEAT-605 W3.6 … needs W3.5 and STORAGE W3 'Assistant tools on services'").
- Cross-feature ordering: `studio/__init__.py` — serialise with FEAT-621 W1 "Backend selection + partition hook" (whichever first).

### References in Codebase
- `packages/ai-parrot-server/tests/studio/test_meta_agent.py` — existing suite

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rebase on FEAT-621 W3 and TASK-3970; re-anchor `:27`, `:68`, `:125`.
2. Add `_assistant_partition`, restructure the session entry and cache — *why*: C30.
3. Build with explicit `chatbot_id`; pass `user_id`/`session_id` to `ask` — *why*: memory key partitioned (R4).
4. Partition-only DELETE with cleanup; add `cleanup_studio_assistants` and register it.
5. Tests through `aiohttp_client` with a real `SessionData` and a resolver switching tenants in one session.

### `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'SESSION_KEY = "_studio_assistant"' meta_agent.py) — :27  (value shape changes; name kept)
# occurrences: 1 (verified: grep -c '        agent = AgentStudioAgent(name=f"agent_studio_{uuid.uuid4().hex[:8]}", api_key=api_key)' meta_agent.py) — :68
# occurrences: 1 (verified: grep -c '        instance_key = session.pop(SESSION_KEY, None) if session is not None else None' meta_agent.py) — :125

def _assistant_partition(scope, user) -> str:
    """'<tenant|->:<user_id>' (spec M10)."""
    return f"{scope.tenant or '-'}:{user.user_id}"


async def cleanup_studio_assistants(app) -> None:
    """on_cleanup: clean every cached assistant instance exactly once."""
    instances = app.get(_ASSISTANTS_APP_KEY) or {}
    # FILL IN: pop each entry, await its cleanup() once (log and continue on error) — bounded by AC24 / "each instance once".

# FILL IN in StudioAssistantHandler:
#   - post: opted in and scope.tenant None ⇒ self._tenant_required() BEFORE touching any instance;
#     _get_or_create_assistant(session, partition=…, api_key=…): cache key (tenant|-, user_id, name), recorded partition
#     must match; AgentStudioAgent(name=…, chatbot_id=f"agent_studio:{scope.tenant or '-'}", api_key=api_key);
#     bot.ask(question=…, user_id=user.user_id, session_id=entry["session_id"])
#   - delete: pop only session[SESSION_KEY][partition]; await that instance's cleanup once
```
**Why**: C30 / AC24.

### `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` (MODIFY)
```python
# inside setup_studio_routes, next to the reconcile hook install (TASK-3957):
    from .meta_agent import cleanup_studio_assistants

    install_startup_hook_once(app, cleanup_studio_assistants, signal="on_cleanup")
```
**Why**: Hook registration only; once per app across prefixes (X10).

### `packages/ai-parrot-server/tests/studio/test_assistant_partition.py` (CREATE)
```python
"""FEAT-605 W3.6 — assistant partitioned by (tenant, user)."""
from __future__ import annotations

async def test_assistant_alternating_tenants_no_history_cross(aiohttp_client): ...  # A → B → A; mutation: drop tenant from key ⇒ RED
async def test_assistant_toolset_not_shared(aiohttp_client): ...
async def test_assistant_delete_resets_only_partition(aiohttp_client): ...          # mutation: pop whole entry ⇒ RED
async def test_assistant_tampered_session_misses(aiohttp_client): ...
async def test_assistant_memory_key_user_and_tenant(aiohttp_client): ...            # shared in-memory history backend
async def test_assistant_instances_cleaned_on_app_cleanup(aiohttp_client): ...      # each instance once
async def test_assistant_partition_key(aiohttp_client): ...                         # opted in, no tenant ⇒ 422 first
```
**Why**: Spec §4 W3.6 tests + mutation rows `assistant partition key includes the tenant`, `partition-only DELETE`, `assistant instances cleaned on app cleanup`.

### FILL IN checklist
- [ ] `meta_agent.py` handler restructuring + `cleanup_studio_assistants` body; bounded by spec §2 bullets and AC24
- [ ] seven tests with a real resolver switching tenants within ONE `SessionData`; replace the LLM with a deterministic stub client (you own and cannot run the provider), never stub `_scope`

---

## Acceptance Criteria

- [ ] AC24: alternating two tenants in one authenticated session, neither history nor toolset crosses tenants; `DELETE /assistant` in one tenant leaves the other partition intact
- [ ] Assistant `chatbot_id = agent_studio:<tenant|->`; `ask` receives explicit `user_id` and `session_id`
- [ ] `cleanup_studio_assistants` appended once per app; every instance cleaned once on app cleanup
- [ ] Mutations: drop the tenant from the partition key ⇒ `test_assistant_alternating_tenants_no_history_cross` RED; pop the whole session entry on DELETE ⇒ `test_assistant_delete_resets_only_partition` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_assistant_partition.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_host_mount.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/studio/test_assistant_partition.py — 7 tests (see blueprint)
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3971 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback loop, tramo B2)
**Date**: 2026-10-02
**Notes**: Assistant partition = `"<tenant|->:<user_id>"` (`_assistant_partition`). `session[SESSION_KEY]` is now a mapping
`{partition: {"instance", "session_id"}}` (a non-mapping / malformed entry is ignored; a request reads and writes only its own
partition); the app cache is keyed `(tenant|-, user_id, instance_name)` and each instance records its partition (a mismatch is a
miss, so a tampered session / cache cannot reach another partition's instance); the toolset is built per instance; instances are
built with `chatbot_id=f"agent_studio:{tenant|-}"` (tenant-qualified `memory_key_id`) and `bot.ask(question, user_id=…, session_id=
<partition conversation id>)` passes the identity explicitly. `DELETE` pops only the caller's partition entry (the key disappears
when it was the last) and cleans that instance once; `cleanup_studio_assistants(app)` is an `on_cleanup` hook appended once per
app by `setup_studio_routes` (every host mode). An opted-in caller with no tenant now gets 422 `tenant_required` on POST and
DELETE before any instance is touched (it used to surface as 500 `build_failed`).
Mutations RED (restored): tenant out of the partition key; `chatbot_id` removed; explicit `user_id`/`session_id` removed; DELETE pops
the whole mapping; recorded-partition check removed; tenant-required check; hook registration; app cleanup not awaited; DELETE cleanup.
Tests: `test_assistant_partition.py` (8, one persistent real `SessionData` per user, real resolver, real Postgres pool).
`test_meta_agent.py`: the fake assistant's `ask` accepts the new explicit kwargs. Server suite vs baseline-package: 0 new.

**Deviations from spec**: `_get_or_create_assistant(session, *, api_key, identity=None)` (identity defaults to the anonymous
partition so the FEAT-621 toolset test still calls it bare). The ledger could not be written (read-only shared ledger).
