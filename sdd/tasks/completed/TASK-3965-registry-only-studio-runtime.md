# TASK-3965: [W2.2] Wire the storage runtime into the registry-only mount (M4)

**Feature**: FEAT-605 — Agent Studio — Tenant Scope, Owner-Controlled Visibility & Host Mount
**Spec**: `sdd/specs/agentstudio-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3957, TASK-3958
**Assigned-to**: unassigned
**Spec task label**: W2.2 (spec §3 "Task plan")

---

## Context

Spec §2 "Registry-only lifecycle" item 2, C32, C39, X8, X10, AC18, AC26. `setup_registry_only`
(TASK-3957) installs only the manager-level lifecycle for non-Studio bots. Studio runtime
instances rely on FEAT-621's `StudioAgentRuntime` (expiry, identity-based cleanup, in-flight
retention), whose hooks are installed by `add_studio_runtime_hooks(app)`. `BotManager.setup()`
calls it (FEAT-621 M7); this task makes `setup_registry_only` call it once too, then removes the
"incomplete lifecycle — not recommended to tenant hosts" warning from the contract doc.

Kept separate from W0.2 (early subset, no storage code) and from FEAT-621's runtime task (which must
not edit `setup_registry_only`, C39). Storage's lifecycle tests are NOT repeated here.

Unblocks: **U-FS** (registry-only mount recommendable to tenant hosts).

---

## Scope

- `setup_registry_only`: call `add_studio_runtime_hooks(app)` exactly once (inside the idempotent branch).
- Docs: drop the "incomplete lifecycle" marker; state the documented mount order and that the reverse order behaves the same.
- Tests through `setup_registry_only` + `setup_studio_routes`, documented order and reverse, with a
  `database`-backend `StudioStorage` over the FEAT-621 fake: `test_registry_only_installs_studio_runtime`,
  `test_registry_only_runtime_hooks_once`, `test_registry_only_shutdown_runs_studio_shutdown`.

**NOT in scope**: Any Studio lifecycle behaviour (expiry, three versions, in-flight retention, shutdown cleaning) — FEAT-621 owns and tests it (`test_lifecycle_registry_only_mount`, `test_session_expiry`, `test_three_versions_cleanup_once`, `test_inflight_survives_replacement`, `test_shutdown_cleans_all`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `setup_registry_only` calls FEAT-621 `add_studio_runtime_hooks(app)` once |
| `docs/agent_studio_api.md` | MODIFY | Remove 'incomplete lifecycle' note; registry-only mount recommendable to tenant hosts |
| `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` | MODIFY | Flip `test_registry_only_marked_incomplete` to assert the note is gone |
| `packages/ai-parrot-server/tests/manager/test_registry_only_studio_runtime.py` | CREATE | Registry-only + Studio runtime wiring tests |

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
from parrot.manager.manager import BotManager  # verified: tests/manager/test_reload_agent.py:17-20
from parrot.handlers.studio import setup_studio_routes  # TASK-3957 signature

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

from parrot.manager.studio_runtime import add_studio_runtime_hooks, StudioAgentRuntime  # FEAT-621 W2 runtime task (storage M7)
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories            # FEAT-621 W1
```

### Existing Signatures to Use
```python
# manager/manager.py (after TASK-3957)
class BotManager:
    def setup_registry_only(self, app, *, import_modules=False, load_definitions=False) -> None

# --- Created by FEAT-621 (agentstudio-db-storage); NOT on dev at 32b1a45d4. Verify each name after the
# --- FEAT-621 task named in "Cross-feature ordering" merges; if a name differs, FEAT-621's wins (package rule).

# manager/studio_runtime.py (FEAT-621 W2 "Runtime + cache + lifecycle + builder + BotManager hooks")
def add_studio_runtime_hooks(app: web.Application) -> None   # appends install_studio_runtime (on_startup) +
                                                             #   shutdown_studio_runtime (on_cleanup), once per app
# install_studio_runtime awaits ensure_studio_storage(app) FIRST; installs BotManager.studio only when
#   app["studio_storage"].backend == "database" (X8)
```

### Does NOT Exist
- ~~`add_studio_runtime_hooks`~~, ~~`manager/studio_runtime.py`~~ — FEAT-621 W2 (must be merged first)
- ~~a composite `on_startup` hook~~ — dropped by C39; do not create

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/agent_studio_api.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_registry_only_studio_runtime.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup_registry_only"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror FEAT-621's own call in `BotManager.setup()` (storage M7) — one function call, nothing else.

### Key Constraints
- Exactly one call per app (it is inside `setup_registry_only`'s idempotent branch; FEAT-621's hook also guards once per app).
- Never touch a Studio instance from the manager-level hooks (X8).
- Startup order is guaranteed by FEAT-621 (`install_studio_runtime` awaits storage resolution first); do not add ordering code.

### Cross-feature ordering (package X16)
- Cross-feature ordering: needs **FEAT-621 W2** "Runtime + cache + lifecycle + builder + BotManager hooks" merged (`add_studio_runtime_hooks`, X8, X16) and FEAT-621 W1 "Backend selection + partition hook" (`StudioStorage`, fake).
- Cross-feature ordering: `manager/manager.py` — FEAT-621 W2's runtime task merges first; this task rebases on it.

### References in Codebase
- FEAT-621 `manager/studio_runtime.py`

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the call inside `setup_registry_only` after the three manager hooks — *why*: AC18/AC26.
2. Remove the doc warning and flip the doc test — *why*: C32 "until W2.2 merges".
3. Write the wiring tests in both host call orders.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# anchor: inside BotManager.setup_registry_only, AFTER `        app.on_cleanup.append(self._cleanup_all_bots)`
#   (occurrences: 2 — FILL IN: disambiguate; the one inside setup_registry_only, not setup() :2288)
        from parrot.manager.studio_runtime import add_studio_runtime_hooks  # FEAT-621 W2

        add_studio_runtime_hooks(app)
```
**Why**: C39: storage owns the Studio lifecycle; this spec only calls it. FILL IN whether a module-level import is safe (avoid a cycle with FEAT-621's module).

### `docs/agent_studio_api.md` (MODIFY)
```markdown
<!-- In the "Mounting Studio in a host" part written by TASK-3958: REMOVE the "incomplete lifecycle —
     not recommended to tenant hosts" sentence; ADD: "setup_registry_only installs the Studio runtime hooks
     (FEAT-621 add_studio_runtime_hooks) once; the documented order and its reverse behave the same." -->
```
**Why**: AC26 last sentence.

### `packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py` (MODIFY)
```python
# REPLACE test_registry_only_marked_incomplete with:
def test_registry_only_no_longer_marked_incomplete():
    assert "incomplete lifecycle" not in DOC.read_text(encoding="utf-8")
```
**Why**: Keeps the doc pin truthful.

### `packages/ai-parrot-server/tests/manager/test_registry_only_studio_runtime.py` (CREATE)
```python
"""FEAT-605 W2.2 — registry-only mount installs FEAT-621's Studio runtime once."""
from __future__ import annotations

async def test_registry_only_installs_studio_runtime(aiohttp_client): ...
    # documented order and reverse; after startup app["bot_manager"].studio is a StudioAgentRuntime and storage
    #   was resolved first. Mutation: drop the add_studio_runtime_hooks call ⇒ RED.
async def test_registry_only_runtime_hooks_once(aiohttp_client): ...       # two calls + two prefixes ⇒ each hook once
async def test_registry_only_shutdown_runs_studio_shutdown(aiohttp_client): ...
    # on cleanup shutdown_studio_runtime runs once and cleans a warm Studio entry once; _cleanup_all_bots never sees it
```
**Why**: Spec §4 mutation rows for the registry-only mount.

### FILL IN checklist
- [ ] `manager.py` — disambiguate the anchor (inside `setup_registry_only`); import placement
- [ ] test bodies with a `database`-backend `StudioStorage` over `InMemoryStudioRepositories`

---

## Acceptance Criteria

- [ ] AC18 (Studio part): `setup_registry_only(app)` calls `add_studio_runtime_hooks(app)` once; storage is resolved before the runtime whatever the host call order
- [ ] AC26: the mount installs storage's runtime hooks once, starts in the documented order and the reverse, shutdown runs `shutdown_studio_runtime` once; the contract doc no longer marks `setup_registry_only` incomplete
- [ ] Mutation: remove the call ⇒ `test_registry_only_installs_studio_runtime` RED

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/manager/test_registry_only_studio_runtime.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_registry_only.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_feat605_contract_doc.py -q`

---

## Test Specification

> Minimal test scaffold. The agent must make these pass. Rule 6 / spec §4: requests are
> built with `aiohttp_client` or `make_mocked_request` plus a real
> `navigator_session.data.SessionData` at `request[SESSION_OBJECT]`; never patch
> `_get_user`, `_resolve_session` or `_scope` (they are the join under test).

```python
# packages/ai-parrot-server/tests/manager/test_registry_only_studio_runtime.py
async def test_registry_only_installs_studio_runtime(aiohttp_client): ...
async def test_registry_only_runtime_hooks_once(aiohttp_client): ...
async def test_registry_only_shutdown_runs_studio_shutdown(aiohttp_client): ...
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3965 agentstudio-tenant-visibility verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: setup_registry_only now calls add_studio_runtime_hooks once; doc marker removed; wiring tests in both mount orders. Mutation (call removed) turned 7 tests RED. Also adjusted test_registry_only_hooks_once counts (+2 startup, +2 cleanup) for the added runtime hook pair.

**Deviations from spec**: none
