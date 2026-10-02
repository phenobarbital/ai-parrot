# TASK-3927: Tooling identity plumbing: ToolingState.tooling_ref, ref-keyed overrides, purge_agent

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W1 — Tooling identity plumbing (M13)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3923
**Assigned-to**: unassigned

---

## Context

Spec §2.5c (immutable identity), §2.8 rows `tooling_store.py` / `toolkit_overrides.py` / `handlers/agent.py` /
`toolkit_persistence.py`, §3 Module 13, X3, X17. Every vault name, override document key and session cache key is
derived from the tooling ref instead of the URL name. For legacy agents the ref IS the bare name, so this task
changes no key and no behaviour on its own; it lands before any Studio row can exist.

---

## Scope

- `ToolingState` gains `tooling_ref: str`; `AgentToolingStore.load` sets it to `name` for the `database` and
  `registry` sources (the `studio` source is TASK-3934).
- `_split_secrets`, `put_mcp_servers`, `delete_toolkit` compute vault names from `state.tooling_ref`.
- `toolkit_overrides.py`: override documents (`ToolkitConfigService().load/save/remove(user_id, ref, …)`), the
  `…_user` vault name (`toolkit_override_vault_name(slug, ref)`) and the session revision key
  (`f"{ref}_toolkit_overrides_rev"`) use the ref obtained from `AgentToolingStore.load(name)`.
- `handlers/agent.py::_apply_user_toolkit_overrides`: `ref = agent_tooling_ref(agent)` replaces `agent.name` in
  `svc.load`, `svc.revision` and both session keys.
- `ToolkitConfigService.purge_agent(agent_ref) -> list[UserToolkitOverride]` (delete clean-up, §2.5c).
- Test `test_legacy_identities_unchanged` + unit tests of `purge_agent`.

**NOT in scope**: The `studio` source branch and `StudioToolingService` (TASK-3934); handler `expected_version` (TASK-3946); Postgres overrides store (TASK-3954).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | ToolingState.tooling_ref; vault names from the ref |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | override docs, _user vault name and session key from the ref |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | MODIFY | ToolkitConfigService.purge_agent |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | _apply_user_toolkit_overrides keyed by agent_tooling_ref |
| `packages/ai-parrot-server/tests/studio/test_tooling_identity.py` | CREATE | legacy byte-identity + purge_agent tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.tools.spec import agent_tooling_ref, toolkit_override_vault_name   # TASK-3923
from parrot.tools.spec import toolkit_vault_name, mcp_vault_name               # tooling_store.py:23-33
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride  # toolkit_overrides.py:18
from parrot.security.vault_utils import delete_vault_credential                # tooling_store.py:16-20
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
@dataclass
class ToolingState:                     # line 47 — tooling; editable; reason; owner; source: Literal["database","registry"] (:50-54)
class AgentToolingStore:                # line 78
    async def load(self, name: str) -> ToolingState                                   # :84
    async def delete_toolkit(self, name: str, slug: str) -> None                       # :193
        await delete_vault_credential(state.owner, toolkit_vault_name(slug, name))     # :201 (occurrences: 1)
    async def put_mcp_servers(self, name, servers) -> list[AgentMCPServerSpec]         # :204
            vault_name = mcp_vault_name(candidate.name, name)                          # :221 (occurrences: 1)
    async def _split_secrets(...)                                                      # :250
        vault_name = toolkit_vault_name(slug, name)                                    # :263 (occurrences: 1)
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py — key sites :109, :157, :170, :183, :186, :199, :200, :204
        vault_name = f"toolkit_{slug}_{name}_user"                                 # :170 (occurrences: 1)
            await delete_vault_credential(user.user_id, f"toolkit_{slug}_{name}_user")  # :200 (occurrences: 1)
        session.pop(f"{name}_toolkit_overrides_rev", None)                           # :186, :204 (occurrences: 2)
# packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py
class UserToolkitOverride(BaseModel): user_id; agent_id; slug; params; secret_refs; updated_at   # :17
class ToolkitConfigService:             # :28 ; COLLECTION :14
    async def save(self, override) -> None                       # :31
    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]   # :37
    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool           # :53 (anchor, occurrences: 1)
    async def revision(self, user_id: str, agent_id: str) -> str                     # :63
# packages/ai-parrot-server/src/parrot/handlers/agent.py — _apply_user_toolkit_overrides :1082
            overrides = await svc.load(str(user_id), agent.name)           # :1099 (occurrences: 1)
            marker_key = f"{agent.name}_toolkit_overrides_rev"            # :1102
            marker = f"...:{await svc.revision(str(user_id), agent.name)}"  # :1103
            request_session[f"{agent.name}_tool_manager"] = base          # :1130 (occurrences: 1)
```

### Does NOT Exist
- ~~`ToolingState.tooling_ref`~~, ~~`ToolkitConfigService.purge_agent`~~ — created here.
- ~~A `studio` value in `ToolingState.source`~~ — TASK-3934 widens the Literal.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#ToolingState",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.load",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore._split_secrets",
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#ToolkitConfigService",
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._apply_user_toolkit_overrides"
  ]
}
```

---

## Implementation Notes

- Parallelism: imports toolkit_override_vault_name and agent_tooling_ref from TASK-3923 (core tools/spec.py); first FEAT-621 writer of tooling_store.py, toolkit_overrides.py, toolkit_persistence.py and handlers/agent.py (TASK-3934, -25, -33 follow)
- Cross-feature ordering: X16 "Identity files" — this task (STORAGE W1 M13) merges **first** on
  `studio/tooling_store.py`, `studio/toolkit_overrides.py`, `handlers/toolkit_persistence.py` and `handlers/agent.py`;
  TOOLKITS M9 (R3 consumer) follows on every one of them and makes no edit to `toolkit_persistence.py` /
  `handlers/agent.py`. Do not wait for TOOLKITS: there is no sibling dependency for STORAGE W1.
- `_apply_user_toolkit_overrides` is a method of `AgentTalk(BaseView)` (`handlers/agent.py:116`); if the
  class moved, correct the Complexity Contract symbol.
- `purge_agent`: delete every `user_toolkit_configs` document with `agent_id == ref` and return them (callers delete
  each `…_user` vault entry under its `user_id`). Best-effort callers; the method itself raises on driver errors.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Add `tooling_ref` to `ToolingState` and set it in every `load` return — *why*: one field carries identity (X17).
2. Swap `name` → `state.tooling_ref` at the three vault-name sites — *why*: never derive identity from the URL.
3. Thread the ref through `toolkit_overrides.py` (get the state once per verb) and `handlers/agent.py`.
4. Add `purge_agent`; write tests asserting byte-identical legacy keys (mutation: use the ref for nothing ⇒ still
   green for legacy; use a hardcoded prefix ⇒ RED).

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class ToolingState:' tooling_store.py) — field appended after `source` (:54)
    tooling_ref: str = ""   # tooling identity (spec §2.5c): == name for database/registry sources
# FILL IN: every ToolingState(...) built in load() passes tooling_ref=name — bounded by test_legacy_identities_unchanged.
# :201  await delete_vault_credential(state.owner, toolkit_vault_name(slug, state.tooling_ref))
# :221  vault_name = mcp_vault_name(candidate.name, state.tooling_ref)
# :263  vault_name = toolkit_vault_name(slug, state.tooling_ref)   # FILL IN: _split_secrets must receive `state`
#       (or the ref) — check its signature at :250 and thread it through without changing behaviour.
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` (MODIFY)
```python
# :170 (occurrences: 1)  vault_name = toolkit_override_vault_name(slug, ref)
# :200 (occurrences: 1)  await delete_vault_credential(user.user_id, toolkit_override_vault_name(slug, ref))
# :186, :204 (occurrences: 2 — disambiguate by enclosing verb put/delete)  session.pop(f"{ref}_toolkit_overrides_rev", None)
# FILL IN: in get/put/delete obtain `ref = (await AgentToolingStore(self).load(name)).tooling_ref` once, and pass
#   it to ToolkitConfigService load/save/remove (:109, :157, :183, :199) — bounded by §2.8 row toolkit_overrides.
```

### `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` (MODIFY)
```python
# AFTER — insert below the body of `    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:`
# occurrences: 1 (verified: toolkit_persistence.py:53)
    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override documents for ``agent_ref`` and return them (spec §2.5c clean-up)."""
        # FILL IN: same DocumentDB access pattern as remove(); find_many by agent_id == agent_ref, delete_many,
        #   return the parsed documents — bounded by X3 (key is {user_id, agent_id: <ref>, slug}).
        raise NotImplementedError
```

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# :1099 (occurrences: 1) — insert `ref = agent_tooling_ref(agent)` on the line above, then:
            overrides = await svc.load(str(user_id), ref)
            marker_key = f"{ref}_toolkit_overrides_rev"
            marker = f"{getattr(agent, '_tooling_revision', '')}:{await svc.revision(str(user_id), ref)}"
# :1130 (occurrences: 1)
            request_session[f"{ref}_tool_manager"] = base
```

### `packages/ai-parrot-server/tests/studio/test_tooling_identity.py` (CREATE)
```python
"""FEAT-621 M13 — legacy identities byte-identical (AC12)."""
# FILL IN: test_legacy_identities_unchanged — for a registry/YAML agent and a database (ai_bots) agent, capture the
#   vault names written by put_toolkit/put_mcp_servers, the override document agent_id, and the two session keys
#   written by _apply_user_toolkit_overrides; assert they equal today's f-strings with the bare name.
#   Requests are built with make_mocked_request + request["NAV_SESSION"] (ARCHITECTURE R6). DocumentDB/vault calls
#   are replaced at the module boundary (store/retrieve/delete_vault_credential, ToolkitConfigService) — we own
#   neither backend in unit tests.
# FILL IN: test_purge_agent_returns_and_deletes.
```

### FILL IN checklist
- [ ] `load()` sets `tooling_ref`; `_split_secrets` receives the ref.
- [ ] three verbs in `toolkit_overrides.py` use one ref each.
- [ ] `purge_agent`.
- [ ] both tests.

---

## Acceptance Criteria

- [ ] Registry/YAML/`ai_bots` agents: vault names, override documents and session keys byte-identical to today (`test_legacy_identities_unchanged`, AC12).
- [ ] No vault name, override key or session key is computed from the URL name in the four files (grep: no `toolkit_vault_name(slug, name)` / `f"{name}_toolkit_overrides_rev"` left).
- [ ] `ToolkitConfigService.purge_agent(ref)` deletes and returns that ref's override documents.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_tooling_identity.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_legacy_identities_unchanged` | AC12 |
| `test_purge_agent_returns_and_deletes` | §2.5c delete clean-up |
| existing `test_tooling_store.py`, `test_toolkit_overrides.py` | regression (must pass unmodified) |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3927 — Tooling identity plumbing: ToolingState.tooling_ref, ref-keyed overrides, purge_agent`.
8. Close with `scripts/sdd/close_task.sh TASK-3927 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5.5)
**Date**: 2026-09-30
**Notes**: As blueprint; 9 new tests, existing tooling_store/toolkit_overrides/toolkit_config tests pass unmodified; studio suite has no new failures vs baseline. Deviations in detail: toolkit_overrides.py resolves the ref through a small _tooling_ref(name) helper that falls back to the URL name when the loaded state has no tooling_ref (the existing test fake returns a SimpleNamespace without it); purge_agent uses DocumentDb.delete_many (delete removes one doc). NOTE for later Studio tasks: other readers of the session key f'{agent_name}_tool_manager' (agent.py ~1613/2125/2276, mcp_helper.py:93) still key by agent name while _apply_user_toolkit_overrides now writes it under the ref; identical for legacy agents, but must be aligned for Studio agents.

**Deviations from spec**: none
