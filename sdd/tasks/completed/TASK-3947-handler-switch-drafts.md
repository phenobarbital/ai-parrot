# TASK-3947: Handler switch: declarative drafts and atomic activation; Python drafts gated

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: drafts, catalogue, testing (part 1: drafts.py)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3937, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 row `drafts.py` and "Python drafts gate", §2.9 drafts rows, §2.5a draft activation, decision 3, X14
(`declarative_only` 422, shared with FEAT-605).

---

## Scope

- `POST /drafts`: body `{name, source}` (Python, legacy) or `{name, bundle}` (declarative). Declarative →
  `StudioDraftService.save_bundle` (`expected_version` compared to the draft version on update). Python on a tenant
  partition or with `python_drafts_allowed(part)` false → 422 `declarative_only`, no file written, nothing imported.
- `GET /drafts[/{name}]`: added `kind`, `bundle` (declarative only), `tenant`, `visibility`, `allowed_groups`,
  `version`; legacy drafts get `kind: "python"`.
- `POST /drafts/{name}/activate`: declarative → `StudioDraftService.activate` (`replace`, `expected_version`,
  `target_expected_version`); response adds `agent_id`, `version`; concurrent → 409 `version_conflict`.
- Legacy bodies (incl. FEAT-605 W1.4/W1.5 D1/D3 guards) moved verbatim into `_legacy_*`.

**NOT in scope**: FEAT-605's `PATCH /drafts/{name}/visibility` (FEAT-605 W3.2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | MODIFY | declarative drafts, activation, Python gate; _legacy_* moves |
| `packages/ai-parrot-server/tests/studio/test_drafts_db_mode.py` | CREATE | database-mode draft route tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py
class SaveDraftRequest(BaseModel):            # :32
class ActivateDraftRequest(BaseModel):        # :39
class _StudioDraftsMixin:                     # :45
    def _drafts_dir(self) -> Path:            # :48 (occurrences: 1)
class StudioDraftsHandler(_StudioDraftsMixin, StudioBaseView):          # :155 — get :162, post :181, delete :243
class StudioDraftActivateHandler(_StudioDraftsMixin, StudioBaseView):   # :270 — post :279
```

### Does NOT Exist
- ~~`{name, bundle}` draft body~~ — added here.

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
      "path": "packages/ai-parrot-server/tests/studio/test_drafts_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py#StudioDraftActivateHandler"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioDraftService from TASK-3937 (services/drafts.py) and helpers from TASK-3944 (_base.py); sole FEAT-621 writer of studio/drafts.py
- Cross-feature ordering: X16 "Before STORAGE W3" — FEAT-605 W1.4 (D1, draft overwrite) and W1.5 (D3, ownerless
  takeover) on `drafts.py` merge **first**; this task rebases on them and its `_legacy_*` bodies carry those guards
  verbatim. Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/drafts.py` merges **after** this task and rebases on it.
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

### `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` (MODIFY)
```python
# SaveDraftRequest (:32): FILL IN — accept either `source` or `bundle: StudioAgentBundle` (exactly one) — 422 otherwise.
# StudioDraftsHandler.post (:181): filesystem ⇒ _legacy_post; source given ⇒ gate
#   (not svc.python_drafts_allowed(part) ⇒ 422 declarative_only) then _legacy_post; bundle ⇒ save_bundle.
# StudioDraftActivateHandler.post (:279): FILL IN declarative path per §2.5a; legacy drafts unchanged.
```
### `packages/ai-parrot-server/tests/studio/test_drafts_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 drafts (AC8, AC15, AC16)."""
# FILL IN: test_bundle_save_and_activate_shapes; test_tenant_python_draft_refused (422 declarative_only, no file
#   written, sys.modules unchanged); test_concurrent_activation_http (one 200, one 409);
#   test_activate_replace_target_expected_version; test_stale_draft_update_409; test_legacy_python_draft_global.
```

---

## Acceptance Criteria

- [ ] Tenant partition: `{name, source}` → 422 `declarative_only`, no file written, nothing imported (`test_tenant_python_draft_refused`, AC15).
- [ ] Declarative save + activate return the §2.9 shapes; concurrent activation → one 200 and one 409 (AC8, AC16).
- [ ] Existing `tests/studio/test_drafts.py` passes unmodified in filesystem mode (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_drafts_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_drafts.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_bundle_save_and_activate_shapes` | AC16 |
| `test_tenant_python_draft_refused` | AC15 |
| `test_concurrent_activation_http` | AC8 |
| `test_activate_replace_target_expected_version` | §2.9 |
| `test_stale_draft_update_409` | AC8 |
| `test_legacy_python_draft_global` | regression |

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
   `feat(agentstudio-db-storage): TASK-3947 — Handler switch: declarative drafts and atomic activation; Python drafts gated`.
8. Close with `scripts/sdd/close_task.sh TASK-3947 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit 2619c594c. Database-mode drafts POST(bundle)/GET/activate; 10 new tests on real PG; 7 mutations RED. GAPS: DELETE /drafts/{name} has no database-mode path (not listed in task; StudioDraftService.delete exists) so DB drafts cannot be deleted over HTTP; drafts.py is 595 lines (>500 budget); _legacy_post complexity 21 is the verbatim legacy body.

**Deviations from spec**: none
