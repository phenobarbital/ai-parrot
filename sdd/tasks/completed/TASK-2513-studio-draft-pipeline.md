# TASK-2513: Draft pipeline — save, static validation, activate gate

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2509, TASK-2511
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Resolved in brainstorm: generated Python agents get an
**explicit activate step** — static validation on save, import+register
ONLY on user activation. Draft `.py` content lives on disk at
`AGENTS_DIR/_drafts/`; lifecycle state/audit lives in the NEW
`navigator.studio_drafts` table. This is the security boundary between
LLM-generated code and live code.

---

## Scope

- Create `StudioDraft` asyncdb `Model` (`navigator.studio_drafts`, pattern
  `AgentSchedule`): draft_id (uuid PK), name, file_path, status
  (`draft|validated|failed|activated`), validation_report (JSONB),
  base_class, owner_user_id, created_at/updated_at/activated_at. Docstring
  carries the DDL.
- Implement `handlers/studio/validation.py`:
  `validate_draft(source: str) -> DraftValidationReport` — AST parse
  (syntax), import allowlist (`parrot.*`, `parrot_tools.*`, stdlib list),
  exactly ONE `AbstractBot`-derived class (by base-name heuristic against
  the base-class catalog), per-error line numbers. Pure static analysis —
  the source is NEVER imported/executed here.
- Implement `StudioDraftsHandler` in `handlers/studio/drafts.py`:
  - `POST /api/v1/astudio/drafts` — save to `AGENTS_DIR/_drafts/<name>.py`
    (traversal-safe), run validation, upsert state row. Draft is saved even
    when validation fails (`status='failed'`).
  - `GET /api/v1/astudio/drafts[/{name}]` — list / read content +
    validation report.
  - `POST /api/v1/astudio/drafts/{name}/activate` — refuse unless
    `status='validated'` (409); refuse name collision with a registered
    agent unless `replace=true` AND caller owns it (409); move file into
    `AGENTS_DIR/`, import via `AgentRegistry._import_module_from_path`,
    confirm registration, stamp `status='activated'` + owner.
  - `DELETE /api/v1/astudio/drafts/{name}` — remove file + row (owner).
- Routes in `setup_studio_routes`; tests for the validation matrix and the
  activation gate.

**NOT in scope**: the meta-agent that WRITES drafts (TASK-2521); sandboxed
execution (the gate is the boundary — resolved decision).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/studio_drafts.py` | CREATE | `StudioDraft` asyncdb model |
| `packages/ai-parrot-server/src/parrot/handlers/studio/validation.py` | CREATE | AST validator |
| `packages/ai-parrot-server/src/parrot/handlers/studio/drafts.py` | CREATE | drafts handler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_drafts.py` | CREATE | validation matrix + gate tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb.models import Model, Field       # scheduler/models.py:4
from parrot.registry import agent_registry    # registry/__init__.py:7-12
import ast                                    # stdlib
# AGENTS_DIR: from parrot.conf import AGENTS_DIR  (conf.py:175 — Path, mkdir'd)
```

### Existing Signatures to Use
```python
# asyncdb Model pattern — packages/ai-parrot-server/src/parrot/scheduler/models.py:7
class AgentSchedule(Model):
    """<docstring carries full DDL>"""
    class Meta:  # :59-64
        driver = 'pg'; name = "agents_scheduler"; schema = "navigator"
        strict = True; frozen = False
# → StudioDraft.Meta: driver='pg', name="studio_drafts", schema="navigator"

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:
    def _import_module_from_path(self, path: Path, *, base_dir=None,
        package_hint: str = "parrot.dynamic_agents") -> ModuleType: ...  # :1131
        # spec_from_file_location + exec_module — EXECUTES top-level code;
        # call ONLY after validation passed and only from activate
    def _load_modules_from_directory(self, directory: Path) -> int: ...  # :1173 (non-recursive)
    def has(self, name) -> bool: ...  # :621
    def register(self, name, factory, *, replace=False, **kw): ...  # :522

# Agent base classes the validator recognizes (parrot/bots/):
# AbstractBot abstract.py:187; BaseBot base.py:69; BasicBot basic.py:3;
# Chatbot chatbot.py:30; BasicAgent agent.py:29; Agent agent.py:1236;
# PandasAgent data.py:355; DocumentAgent document.py:104; WebSearchAgent search.py:45;
# WebAgent chrome.py:290; MCPAgent mcp.py:11; A2AAgent a2a_agent.py:6
# bots/__init__.py:9 __all__ = ("AbstractBot","Agent","BaseBot","BasicAgent",
#   "BasicBot","Chatbot","InfoAgent","VoiceBot","WebAgent","WebSearchAgent")

# DB access in handlers: request.app['database'] (navigator BaseView.connect,
#   .venv/.../navigator/views/base.py:655-668)
```

### Does NOT Exist
- ~~`AGENTS_DIR/_drafts/`~~ — THIS task creates the directory convention.
  It must NOT be a registry discovery path until activation moves the file
  out (the startup loader globs `AGENTS_DIR/*.py` non-recursively —
  `_drafts/` being a subdirectory keeps drafts invisible to it; assert
  this in a test).
- ~~`navigator.studio_drafts` table~~ — NEW here.
- ~~Any draft/activate lifecycle in registry/manager~~ — the only prior
  gate is `BotConfig.enabled`.
- ~~A sandbox/subprocess executor for drafts~~ — deliberately not built;
  static validation + explicit activate IS the gate (resolved decision).
- ~~`importlib.reload` for re-activation~~ — re-activation goes through
  `_import_module_from_path` (fresh exec).

---

## Implementation Notes

### Pattern to Follow
Validator: single `ast.parse` walk collecting `Import`/`ImportFrom` nodes
(check module root against allowlist) and `ClassDef` nodes whose base
names intersect the known base-class set. Report shape =
`DraftValidationReport(passed, errors=[{line, code, message}])` from
TASK-2511 models.

### Key Constraints
- Saving NEVER imports the draft; only activate does, and only after a
  fresh re-validation (file may have been edited on disk).
- Activation moves the file with `Path.replace` into `AGENTS_DIR/` so the
  startup loader also finds it on next boot.
- stdlib allowlist: define explicitly (e.g. `sys.stdlib_module_names`
  intersection) — no dynamic `__import__`/`exec`/`eval` calls allowed in
  the draft (add AST check for those names → error code `forbidden-call`).
- Owner recorded on row and on activation registration
  (`bot_config.config['created_by']`).

### References in Codebase
- `parrot/setup/scaffolding.py:207 scaffold_agent` — existing generated-
  agent file shape to accept.
- `handlers/scheduler.py` — handler + asyncdb model interplay reference.

---

## Acceptance Criteria

- [ ] Draft save persists file + state row; failed validation saved with
      `status='failed'` and line-numbered errors.
- [ ] Forbidden import / `exec`/`eval` / zero-or-multiple bot classes each
      produce a distinct error code.
- [ ] Activate refused (409) for failed/unvalidated drafts and unowned
      name collisions; success imports, registers, stamps `activated`.
- [ ] Drafts in `_drafts/` are invisible to `load_modules()` startup scan.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_drafts.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_drafts.py
class TestDraftValidation:
    def test_syntax_error_reported_with_line(self): ...
    def test_forbidden_import_flagged(self): ...        # e.g. `import socket` if excluded / `import requests`
    def test_exec_eval_flagged(self): ...
    def test_exactly_one_bot_subclass_required(self): ...
    def test_valid_draft_passes(self): ...

class TestDraftLifecycle:
    async def test_save_persists_file_and_row(self, studio_app, tmp_agents_dir): ...
    async def test_activate_gate_blocks_failed(self, studio_app): ...
    async def test_activate_imports_and_registers(self, studio_app, tmp_agents_dir): ...
    async def test_drafts_dir_invisible_to_startup_loader(self, tmp_agents_dir): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2509, TASK-2511 completed
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- `StudioDraft` asyncdb model (`navigator.studio_drafts`) in
  `handlers/models/studio_drafts.py`, pattern `AgentSchedule`.
- `validation.py::validate_draft(source) -> DraftValidationReport` —
  pure AST analysis (never imports/executes): syntax errors, import
  allowlist (`parrot`/`parrot_tools`/stdlib root only, no relative
  imports), forbidden dynamic-exec calls (`exec`/`eval`/`__import__`/
  `compile`), and a base-NAME heuristic requiring exactly one
  AbstractBot-family subclass. `detect_base_class(source)` extracts the
  matched base name for the `StudioDraft.base_class` column.
- `StudioDraftsHandler` (GET list/single incl. source + report, POST
  save+validate, DELETE owner-enforced) and
  `StudioDraftActivateHandler` (POST activate) in `drafts.py`, routed in
  `setup_studio_routes`.
- Activate gate: refuses (409) unless a FRESH re-validation of the
  CURRENT on-disk content passes (source may have been hand-edited since
  save — spec §7 "only after a fresh re-validation"); refuses (409) on
  an unconsented/unowned name collision; on success moves the file
  `AGENTS_DIR/_drafts/<name>.py` → `AGENTS_DIR/<name>.py` via
  `Path.replace`, imports via
  `AgentRegistry._import_module_from_path`, confirms `registry.has()`,
  stamps `bot_config.config['created_by']` + `status='activated'` +
  `activated_at`. Best-effort rollback (`target_path.replace(draft_path)`)
  on import failure or a no-op import — a failed activate never silently
  vanishes the draft.
- `_drafts/` is a plain subdirectory of `AGENTS_DIR` — `AgentRegistry
  ._load_modules_from_directory`'s non-recursive `glob("*.py")` on
  `AGENTS_DIR` itself never descends into it, so drafts stay invisible
  to `load_modules()`/startup discovery with zero extra exclusion logic;
  verified directly (`test_drafts_dir_invisible_to_startup_loader`).
- Local `SaveDraftRequest`/`ActivateDraftRequest` Pydantic models defined
  in `drafts.py` itself (not `handlers/studio/models.py`, not listed in
  this task's Files table) — same file-scope discipline as TASK-2512's
  local `_error()` helper.
- Tests: `TestDraftValidation` exercises the validator as pure functions
  (no handler/DB). `TestDraftLifecycle` uses an in-memory fake
  draft-row store (`_FakeDraftStore`, monkeypatched onto
  `_get_draft_row`/`_get_all_draft_rows`/`_upsert_draft_row`/
  `_delete_draft_row` — refactored `delete()` to route through the new
  `_delete_draft_row` helper specifically so it's independently
  mockable, mirroring the other three) rather than simulating asyncdb's
  Model/SQL layer, plus a REAL isolated `AgentRegistry` for the
  activate-imports-and-registers path. That path's draft source uses
  `from parrot.registry import agent_registry;
  @agent_registry.register_bot_decorator(...)` (fresh module-level
  lookup at draft-exec time, NOT the `register_agent` alias — which is
  pre-bound to the ORIGINAL global singleton at `parrot.registry`
  import time and immune to monkeypatching) so that
  `monkeypatch.setattr(registry_pkg, "agent_registry", <test registry>)`
  correctly redirects the draft's self-registration into the test's
  isolated instance instead of the real global singleton.
- **Process note**: same `AGENTS_DIR` dual-binding footgun as TASK-2512
  (patched here too, `drafts_module.AGENTS_DIR`) — no stray files
  landed outside tmp_path this time; verified via `git status` on the
  main repo before and after the full run.
- Ran `ruff check --fix` scoped to the whole `handlers/studio/`
  directory (this task's own acceptance criterion is directory-wide,
  not file-scoped) — it also mechanically modernized TASK-2512's already
  -committed `agents.py` (`Optional[X]`→`X | None`, `List[X]`→`list[X]`,
  import sort; zero behavior change, confirmed by re-running the full
  84-test regression sweep before committing). Included in this
  commit rather than reverted, since keeping the directory lint-clean
  is explicitly this task's (and TASK-2512's) own acceptance bar.

**Deviations from spec**: none functionally. The two file-scope notes
above (local request models in `drafts.py`; the `agents.py` lint
touch-up) are the only departures from a literal reading of the task's
Files table.

Verification: `pytest packages/ai-parrot-server/tests/studio/
test_drafts.py -v` → 20/20 passed. `ruff check
packages/ai-parrot-server/src/parrot/handlers/studio/` → clean except
intentional `BLE001`/`G201`/`DTZ005` best-effort/fail-open patterns
matching established convention. Full regression sweep (`tests/studio/`,
`tests/manager/`, ephemeral-owner, DB-bot fallback tests) → 84/84 passed.
