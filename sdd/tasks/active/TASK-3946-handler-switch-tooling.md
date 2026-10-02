# TASK-3946: Handler switch: toolkit-config, toolkits/{slug}, mcp-servers and /toolkits/{slug}/me

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: agents, files, tooling (part 3: toolkit-config, toolkits, mcp-servers, overrides)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3934, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 rows `tooling_store.py` / `toolkit_config.py` / `toolkits.py` (assign) / `toolkit_overrides.py`, §2.9
rows toolkit-config/toolkits/mcp-servers (`editable` true for Studio rows with an owner; new 422
`tooling_not_permitted`) and `/toolkits/{slug}/me` (keys from the ref; recreated agent starts `configured: false`;
`expected_version` refused with 400 there), X3, X17.

---

## Scope

- `toolkit_config.py` (`StudioAgentToolkitsHandler` get/put/delete, `StudioAgentMcpServersHandler` get/put):
  pass `expected_version` + `actor` + guard through `AgentToolingStore` to `StudioToolingService` on the studio
  source; map `StudioToolingRefused` → 422 `tooling_not_permitted`, `StudioVersionConflict` → 409.
- `tooling_store.py`: `put_toolkit`/`delete_toolkit`/`put_mcp_servers` accept an optional `guard`/`actor` and
  forward them on the studio source (legacy sources ignore them).
- `toolkits.py` (assign `POST`): Studio rows persist through the studio source; refusal mapping.
- `toolkit_overrides.py`: refuse `expected_version` with 400 `expected_version_unsupported`; Studio agents resolve
  through the studio branch (ref-derived keys already from TASK-3927).

**NOT in scope**: Server-managed key policy and execute-time scope (TOOLKITS).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | guard/expected_version/actor plumbing; error mapping |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | assign on Studio rows; refusal mapping |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | optional guard/actor pass-through to the studio source |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | expected_version refusal; Studio lookup |
| `packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py` | CREATE | database-mode tooling route tests incl. cross-tenant identity |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py
class _ToolingViewMixin(_StudioAgentsMixin):            # :29 — _authorize :36, _map_exc :48
class StudioAgentToolkitsHandler(_ToolingViewMixin, StudioBaseView):   # :68 — get :71, put :93, delete :115
class StudioAgentMcpServersHandler(_ToolingViewMixin, StudioBaseView): # :176 — get :179, put :194
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):       # :221 — get :237, post :281
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py
class StudioUserToolkitOverrideHandler(_StudioAgentsMixin, StudioBaseView):  # :76 — get :93, put :127, delete :189
```

### Does NOT Exist
- ~~`expected_version` on `/toolkits/{slug}/me`~~ — refused with 400 by design (§2.9).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#StudioAgentToolkitsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#StudioAgentMcpServersHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioToolingService via AgentToolingStore's studio branch from TASK-3934 (tooling_store.py, same file — serialised) and the helpers from TASK-3944 (_base.py); edits toolkit_overrides.py after TASK-3927 (transitive)
- Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/toolkit_config.py`, `studio/toolkits.py`, `studio/tooling_store.py` or `studio/toolkit_overrides.py` merges **after** this task and rebases on it.
  In particular TOOLKITS M9 edits `tooling_store.py`/`toolkit_overrides.py` only after STORAGE W3 (this task).
- Database mode only on the new path: `storage = self._studio_storage()`; `backend == "filesystem"` ⇒ the
  existing verb body runs unchanged, moved **verbatim** into `_legacy_<verb>` (a pure move — no drive-by edits).
- Every service-path write passes `StudioWriteGuard(authorized_version=<version of the record the access decision
  used>, expected_version=<body/query value on the §2.9 supported routes>)` and retries **once** on
  `StudioStaleAuthorization` (helper `_studio_write` from TASK-3944); a second stale ⇒ 409 `version_conflict`.
- Error mapping via `_studio_error` (TASK-3944): X14 codes and statuses only (503 `studio_storage_unavailable`,
  409 `version_conflict`, 413 `asset_too_large`/`agent_assets_quota`, 415 `binary_assets_unsupported`, 422
  `unsupported_config_key`/`tooling_not_permitted`/`name_immutable`/`declarative_only`, 409 `not_studio_agent`).
  `StudioNameConflict` answers today's `duplicate` (pre-merge state); FEAT-605 v0.2 switches it to `name_taken`.
- Partition: `part = await self._studio_partition()`; `storage.require_for(part)` before any storage call.
- Response shapes: exactly the additive changes of spec §2.9 — no key removed or renamed.

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

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` (MODIFY)
```python
# StudioAgentToolkitsHandler.put (:93): FILL IN — ev = self._expected_version(body); call
#   store.put_toolkit(name, slug, params, user_overridable, guard=..., actor=user.user_id) through
#   self._studio_write(...) when state.source == "studio"; map errors with self._studio_error.
```
### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# put_toolkit / delete_toolkit / put_mcp_servers: add keyword-only `guard: StudioWriteGuard | None = None,
#   actor: str | None = None`; FILL IN forward on source == "studio"; legacy branches unchanged.
```
### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py`, `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` (MODIFY)
```python
# FILL IN per Scope; toolkit_overrides: `if (r := self._refuse_expected_version(body_or_query)) is not None: return r`.
```
### `packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 tooling routes (AC8, AC12, AC13)."""
# FILL IN: test_cross_tenant_tooling_identity (one user owns sales in acme and beta, toolkit jira + MCP docs with
#   secrets, /toolkits/jira/me override on each: independent CRUD; delete acme/sales leaves beta intact; recreate →
#   configured false; mutation: bare name to toolkit_vault_name ⇒ RED); test_stale_tooling_writes (toolkit PUT/DELETE,
#   mcp-servers PUT → 409, rows and vault unchanged); test_tooling_policy_http (tenant PUT mcp-servers stdio → 422);
#   test_overrides_expected_version_unsupported (400); test_editable_true_for_studio_rows.
```

---

## Acceptance Criteria

- [ ] One user across two tenants gets independent secrets and overrides; delete/recreate inherits nothing (`test_cross_tenant_tooling_identity`, AC12).
- [ ] Stale `expected_version` on toolkit PUT/DELETE and mcp-servers PUT → 409, nothing written (AC8).
- [ ] Tenant stdio MCP via HTTP → 422 `tooling_not_permitted` (AC13).
- [ ] `/toolkits/{slug}/me` with `expected_version` → 400 `expected_version_unsupported`.
- [ ] Existing `test_toolkit_config.py`, `test_toolkits.py`, `test_toolkit_overrides.py` pass unmodified in filesystem mode (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_tooling_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_cross_tenant_tooling_identity` | AC12 (R3) |
| `test_stale_tooling_writes` | AC8 |
| `test_tooling_policy_http` | AC13 |
| `test_overrides_expected_version_unsupported` | §2.9 |
| `test_editable_true_for_studio_rows` | §2.9 |

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
   `feat(agentstudio-db-storage): TASK-3946 — Handler switch: toolkit-config, toolkits/{slug}, mcp-servers and /toolkits/{slug}/me`.
8. Close with `scripts/sdd/close_task.sh TASK-3946 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
