# TASK-3950: Assistant tools on services; save_agent_bundle; per-partition toolset

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Assistant tools on services (M9)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3937, TASK-3938, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 row `meta_agent.py` + core `bots/studio/tools.py` (tools call the services in database mode:
`create_yaml_agent` → `StudioAgentService.create`, `write_*_file` → `StudioAssetService.put`, new `save_agent_bundle`
→ `StudioDraftService.save_bundle`; partition = `StudioPartition.from_scope(current_context().kwargs["studio_scope"].caller)`
when FEAT-605 binds it, else GLOBAL), §3 Module 9 (omit `save_agent_draft` on tenant partitions), X11.
The assistant's own session/instance partitioning is FEAT-605's (W3.6).

---

## Scope

- `bots/studio/tools.py`: helper `_studio_partition_and_services()` (lazy server imports, as the module already does);
  in database mode route `create_yaml_agent`, `write_identity_file`/`write_kb_file`/`write_skill_file` (via
  `_write_asset_file`), `publish_skill_to_catalog` through services; add HITL-gated `save_agent_bundle(name, bundle)`;
  `build_studio_tools(*, declarative_only: bool = False)` omits `save_agent_draft` and includes `save_agent_bundle`
  when `declarative_only`.
- `bots/studio/agent.py`: `AgentStudioAgent` accepts `declarative_only: bool = False` and passes it to
  `build_studio_tools` in `agent_tools()`.
- `meta_agent.py`: `_get_or_create_assistant` builds the assistant with
  `declarative_only = not storage.services.drafts.python_drafts_allowed(part)` (database mode) — tenant ⇒ True.

**NOT in scope**: Assistant identity/instance partitioning (FEAT-605 W3.6); `studio_scope` binding (FEAT-605 W2.1/W3.5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/studio/tools.py` | MODIFY | tools on services; save_agent_bundle; per-partition toolset |
| `packages/ai-parrot/src/parrot/bots/studio/agent.py` | MODIFY | declarative_only flag passed to build_studio_tools |
| `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` | MODIFY | toolset built per partition |
| `packages/ai-parrot-server/tests/studio/test_assistant_tools_db_mode.py` | CREATE | assistant tool routing + toolset tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/studio/tools.py — server modules are imported LAZILY, function-body-local (module docstring :22-31)
async def save_agent_draft(name: str, source: str) -> dict:                    # :162 (occurrences: 1)
async def create_yaml_agent(                                                    # :274 (occurrences: 1)
async def _write_asset_file(agent_name: str, kind: str, filename: str, content: str) -> dict:   # :342 (occurrences: 1)
async def publish_skill_to_catalog(                                             # :459
def build_studio_tools() -> list:                                               # :569
from parrot.utils.helpers import current_context                                # :41
# packages/ai-parrot/src/parrot/bots/studio/agent.py
class AgentStudioAgent(SkillRegistryMixin, Agent):                              # :54
        return [*super().agent_tools(), *build_studio_tools()]                  # :108 (occurrences: 1)
# packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py
    async def _get_or_create_assistant(self, session, *, api_key) -> AgentStudioAgent:   # :57
        agent = AgentStudioAgent(name=f"agent_studio_{uuid.uuid4().hex[:8]}", api_key=api_key)   # :68
    async def post(self):                                                       # :77 (occurrences: 1)
```

### Does NOT Exist
- ~~`save_agent_bundle`~~ — created here. ~~`RequestContext.kwargs["studio_scope"]`~~ — bound by FEAT-605
  (W2.1 builder, W3.5 meta-agent); absent ⇒ GLOBAL.
- Spec §3 M9 lists only `tools.py` and `meta_agent.py`; `agent.py` is added because the toolset is assembled in
  `AgentStudioAgent.agent_tools()` (`agent.py:108`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/studio/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/bots/studio/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_assistant_tools_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#build_studio_tools",
    "sym:packages/ai-parrot/src/parrot/bots/studio/tools.py#create_yaml_agent",
    "sym:packages/ai-parrot/src/parrot/bots/studio/agent.py#AgentStudioAgent"
  ]
}
```

---

## Implementation Notes

- Parallelism: routes tools through StudioDraftService (TASK-3937), StudioSkillCatalogService (TASK-3938) and Agent/Asset services (transitive via TASK-3935/15); meta_agent.py reads the partition hook and storage helpers finalised by TASK-3944 (_base.py)
- Cross-feature ordering: X16 — FEAT-605 W3.6 (assistant partitioning) needs W3.5 and this task merged;
  Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/meta_agent.py` or core `bots/studio/tools.py` merges **after** this task and rebases on it.
- Core must never import `ai-parrot-server` at module import time — keep every server import function-local.
- Tool results stay dicts; refusals surface the X14 code in the dict (`error_code`).

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

### `packages/ai-parrot/src/parrot/bots/studio/tools.py` (MODIFY)
```python
# AFTER `def _require_user_id() -> str:` block — new helper:
async def _studio_partition_and_services(app: Any) -> tuple[Any, Any] | None:
    """(partition, services) in database mode, else None. Partition from studio_scope.caller when bound (X11)."""
    from parrot.handlers.studio.storage.models import StudioPartition   # lazy: server satellite
    # FILL IN: storage = app.get("studio_storage"); backend != database ⇒ None; scope =
    #   (current_context().kwargs or {}).get("studio_scope"); part = StudioPartition.from_scope(scope.caller) if scope
    #   else StudioPartition.GLOBAL; return part, storage.services
    raise NotImplementedError
# FILL IN: database branches in create_yaml_agent / _write_asset_file / publish_skill_to_catalog;
#   @tool(requires_confirmation=True) async def save_agent_bundle(name: str, bundle: dict) -> dict;
#   def build_studio_tools(*, declarative_only: bool = False) -> list.
```
### `packages/ai-parrot/src/parrot/bots/studio/agent.py` (MODIFY)
```python
# :108 (occurrences: 1)
        return [*super().agent_tools(), *build_studio_tools(declarative_only=self._declarative_only)]
# FILL IN: __init__ accepts declarative_only: bool = False → self._declarative_only.
```
### `packages/ai-parrot-server/src/parrot/handlers/studio/meta_agent.py` (MODIFY)
```python
# :68 — FILL IN: compute declarative_only from the partition (tenant ⇒ True) and pass it to AgentStudioAgent(...).
```
### `packages/ai-parrot-server/tests/studio/test_assistant_tools_db_mode.py` (CREATE)
```python
"""FEAT-621 M9 (AC4, AC15)."""
# FILL IN: test_assistant_toolset_per_partition (tenant toolset lacks save_agent_draft, has save_agent_bundle);
#   test_tools_write_through_services (create_yaml_agent → ai_agents row; write_kb_file → asset row; nothing under
#   AGENTS_DIR); test_save_agent_bundle_policy_refusal; test_global_toolset_unchanged.
```

---

## Acceptance Criteria

- [ ] Tenant partition toolset lacks `save_agent_draft` and has `save_agent_bundle` (`test_assistant_toolset_per_partition`, AC15).
- [ ] In database mode the tools write through services; nothing under `AGENTS_DIR` (AC4).
- [ ] Existing `tests/studio/test_meta_agent.py` passes unmodified (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_assistant_tools_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_meta_agent.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_assistant_toolset_per_partition` | AC15 |
| `test_tools_write_through_services` | AC4 |
| `test_save_agent_bundle_policy_refusal` | AC13 |
| `test_global_toolset_unchanged` | regression |

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
   `feat(agentstudio-db-storage): TASK-3950 — Assistant tools on services; save_agent_bundle; per-partition toolset`.
8. Close with `scripts/sdd/close_task.sh TASK-3950 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
