# TASK-2704: publish_surface — mixin method + parrot_tools wrapper

**Feature**: FEAT-492 — A2UI Surface Rehydration
**Spec**: `sdd/specs/a2ui-surface-rehydration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2700
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (goal G4, resolved: BOTH lanes). The agent-side writer:
`InfographicAuthoringMixin.publish_surface()` as the programmatic API (next
to `publish_recipe`, core package) plus a thin LLM-invocable
`PublishSurfaceTool` in the ai-parrot-tools distribution. The core→server
one-way import rule forbids the core mixin from importing the server store
at module level — the store is injected or lazily imported (spec §8 open
question: the seam is THIS task's decision; document it in the Completion Note).

---

## Scope

- Modify `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`:
  - Add `async def publish_surface(self, *, kind: str, title: str,
    envelope: "CreateSurface | dict", recipe_name: Optional[str] = None,
    recipe_owner: Optional[str] = None, recipe_params: Optional[dict] = None,
    overwrite: bool = False, surface_store: Any = None) -> str` next to
    `publish_recipe` (line 279).
  - Validate `envelope` via `CreateSurface.model_validate` (accept an
    instance or a dump); derive `surface_id` from the envelope's
    `surfaceId` (mint `uuid4().hex` when absent); persist through the store;
    return the surface_id.
  - Store resolution (the injection seam): use the explicit
    `surface_store` argument when given; otherwise a `self._surface_store`
    attribute if the hosting bot carries one; otherwise lazy-import
    `parrot.handlers.models.ui_surfaces.PgUISurfaceStore` inside the method
    under try/except ImportError with an actionable error ("install/enable
    ai-parrot-server..."). NEVER a module-level import of server code.
- Create `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py`:
  - `PublishSurfaceTool(AbstractTool)`, `name = "publish_surface"`, Pydantic
    `args_schema` (kind, title, envelope dict, optional recipe_name/
    recipe_owner/recipe_params, overwrite), full docstring (it becomes the
    LLM tool description). `_execute` delegates to the mixin method when the
    bound bot has it, else directly to the store (same seam).
- Unit tests for both lanes.

**NOT in scope**: the REST POST writer (TASK-2702); store internals
(TASK-2700); registering the tool on any agent by default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | MODIFY | `publish_surface()` method |
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | CREATE | `PublishSurfaceTool` |
| `packages/ai-parrot/tests/bots/test_publish_surface_mixin.py` | CREATE | Mixin tests (store stubbed) |
| `packages/ai-parrot-tools/tests/test_publish_surface_tool.py` | CREATE | Tool tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-09-01 against `dev`.

### Verified Imports
```python
from parrot.outputs.a2ui.models import CreateSurface   # verified: outputs/a2ui/models.py:446
from parrot.tools import AbstractTool                  # core base machinery (parrot/tools/)
# LAZY ONLY (inside the method/tool, guarded — server package may be absent):
#   from parrot.handlers.models.ui_surfaces import PgUISurfaceStore   # TASK-2700
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py:54,279
class InfographicAuthoringMixin:
    async def publish_recipe(self, name: str, descriptor: "SectionDescriptor | str",
                             owner: Optional[str] = None, delivery: Optional[dict] = None,
                             overwrite: bool = False) -> Union[InfographicRecipe, GapReport]:
        # line 279 — publish_surface() sits directly after this method;
        # match its docstring style and keyword-only argument discipline.

# Tool idiom — examples/agents/a2ui/deterministic_refresh_dashboard.py:368+
class RefreshDashboardTool(AbstractTool):
    name = "refresh_dashboard"
    description = "..."
    args_schema = RefreshDashboardArgs        # Pydantic BaseModel
    def __init__(self, runner, pctx, out_dir, **kwargs): super().__init__(**kwargs); ...
    async def _execute(self, window=None, plan=None, **kwargs) -> dict[str, Any]: ...

# PgUISurfaceStore surface (TASK-2700):
#   async def save(self, record: UISurfaceRecord, *, overwrite: bool = False) -> str
#   UISurfaceRecord(surface_id, kind, title, envelope, catalog_id, agent_id,
#                   user_id, session_id, recipe_name, recipe_owner,
#                   recipe_params, created_at, updated_at)
```

### Does NOT Exist
- ~~`InfographicAuthoringMixin.publish_surface`~~ — THIS task creates it
- ~~`parrot_tools.ui_surfaces` / `PublishSurfaceTool`~~ — THIS task creates them
- ~~a module-level `from parrot.handlers...` import in core~~ — FORBIDDEN
  (one-way import rule); lazy/injected only
- ~~`parrot.tools.ui_surfaces` physical module in core~~ — the meta_path
  finder redirects `parrot.tools.ui_surfaces` → `parrot_tools.ui_surfaces`
  automatically; create ONLY the parrot_tools file
- ~~auto-registration of the tool on agents~~ — out of scope

---

## Implementation Notes

### Pattern to Follow
- Mixin: mirror `publish_recipe`'s Google-style docstring, keyword-only args,
  and return discipline.
- Tool: mirror `RefreshDashboardTool` (args_schema + `_execute` + injected
  collaborators via `__init__`). Every tool MUST have a clear docstring —
  it is the LLM's tool description (project rule).

### Key Constraints
- `envelope` accepted as `CreateSurface` instance OR dict dump; always stored
  as `model_dump(by_alias=True, mode="json")` (the `persist_envelope`
  convention, baking.py:399).
- Attribution: `user_id`/`agent_id`/`session_id` for the record come from the
  hosting bot's context when available (`self.name` etc.) or explicit kwargs;
  never invented.
- `overwrite=False` + existing surface_id → raise `ValueError` (store's
  `save` semantics from TASK-2700).
- Async throughout; `self.logger` on the mixin.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` — host mixin
- `examples/agents/a2ui/deterministic_refresh_dashboard.py` — tool idiom
- `CLAUDE.md` §Tool-Centric Architecture — tools live in ai-parrot-tools

---

## Acceptance Criteria

- [ ] `publish_surface()` validates, persists, returns surface_id; accepts
      instance and dict envelopes
- [ ] Core module imports CLEANLY without ai-parrot-server installed
      (`python -c "import parrot.bots.mixins.infographic_authoring"`); the
      guarded path raises an actionable error only when actually used
- [ ] `PublishSurfaceTool` exposes name/description/args_schema and delegates
      correctly (store stubbed in tests)
- [ ] `from parrot.tools.ui_surfaces import PublishSurfaceTool` resolves via
      the meta_path redirect
- [ ] All tests pass:
      `pytest packages/ai-parrot/tests/bots/test_publish_surface_mixin.py packages/ai-parrot-tools/tests/test_publish_surface_tool.py -v`
- [ ] No linting errors on the two implementation files

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_publish_surface_mixin.py
async def test_publish_surface_with_injected_store(): ...
async def test_publish_surface_accepts_instance_and_dict(): ...
async def test_publish_surface_derives_recipe_ref_fields(): ...
async def test_publish_surface_missing_store_actionable_error(): ...
async def test_module_import_without_server_package(): ...

# packages/ai-parrot-tools/tests/test_publish_surface_tool.py
async def test_tool_schema_and_docstring(): ...
async def test_tool_execute_delegates_to_store(): ...
async def test_tool_overwrite_false_conflict_raises(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 5, §7 one-way import rule, §8 injection-seam question).
2. **Check dependencies** — TASK-2700 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing any code.
4. **Update status** in `sdd/tasks/index/a2ui-surface-rehydration.json` → `"in-progress"`.
5. **Implement**, **verify**, **move to completed**, update index, fill the
   Completion Note — INCLUDING the injection seam you chose (it resolves a
   spec §8 open question).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
