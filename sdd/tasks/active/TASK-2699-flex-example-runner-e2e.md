# TASK-2699: Flex example runner + deterministic-replay integration tests

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2697, TASK-2698
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (proposal U3: both lanes). The standalone lane proves the
whole feature offline — synthetic frames, publish, byte-identical replay,
filtered variants, refresh RPC — mirroring
`examples/agents/a2ui/deterministic_refresh_dashboard.py`. The server lane
needs no code: recipes published to a shared store are already servable
through the existing `infographic_recipes` handlers; the example documents
that. Slug data is prod-only (`ENV=prod` convention), so NOTHING here may
touch QuerySource.

---

## Scope

- Create `examples/agents/a2ui/flex_dashboard_demo.py`:
  - Seed the six aliases with synthetic DataFrames (reuse/adapt the
    `flex_frames` shapes from TASK-2693's fixture; a sibling
    `flex_synthetic_data.py` module is acceptable, mirroring the example's
    `synthetic_data.py` import).
  - Instantiate `FlexDashboard`, inject frames into its `DatasetManager`
    (dataframe datasets in place of the lazy slugs — offline).
  - Publish `dashboard_descriptor()` via `publish_recipe` to a
    `FileRecipeStore`; run `RecipeRunner.run()` twice → assert byte-identical
    HTML; run once with params overrides (month / pay_code) → filtered
    variant.
  - Wire `A2UIRuntime` over the agent's ToolManager: demonstrate
    `action`+`dataModel` surface state, `callAgentFunction` →
    `refresh_dashboard`, and `export_functions()` / `agent_capabilities()`.
  - `--serve` flag (interactive-html needs an HTTP origin; `file://` breaks
    Chart.js) writing artifacts under `artifacts/flex_dashboard_demo/`.
  - Document the server lane in the module docstring (recipes → shared
    store → `infographic_recipes` handlers; no code changes).
- Integration tests (spec §4): `test_flex_dashboard_publish_replay`,
  `test_flex_dashboard_filtered_replay`, `test_flex_refresh_rpc` in
  `packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py` —
  offline, no LLM (narrative step must be absent/optional in the replay).

**NOT in scope**: real QuerySource fetches; server handler changes; CI
wiring beyond the pytest files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/flex_dashboard_demo.py` | CREATE | offline end-to-end runner |
| `examples/agents/a2ui/flex_synthetic_data.py` | CREATE | synthetic six-alias frames |
| `packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py` | CREATE | publish/replay/refresh tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (all proven by the reference example)
```python
# examples/agents/a2ui/deterministic_refresh_dashboard.py lines 74-113 — verified working set:
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.export import agent_capabilities, export_functions
from parrot.outputs.a2ui.recipes.models import LayoutSpec, RecipeParam
from parrot.outputs.a2ui.recipes.store import FileRecipeStore
from parrot.outputs.a2ui.runtime import A2UICallContext, A2UIRuntime, FunctionCallRecord, SurfaceState
from parrot.outputs.a2ui.runtime.adapters import ToolManagerExecutor
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner
import parrot.outputs.a2ui_renderers.interactive_html  # noqa: F401 — registers on import,
# ships from ai-parrot-visualizations (namespace-merged); guard with try/except
# exactly like the example's lines 115-120.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                                       # line 204
    def __init__(...)                                     # line 226 (read for store/owner wiring)
    async def run(self, name, *, params=None, pctx=None, recipe_owner=None)  # line 242
# pctx MUST be a real PermissionContext (build_principal_context) — falsy pctx
# makes DatasetManager PBAC guards fail OPEN (runner.py docstring, lines 242-268).

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
DatasetManager.add_dataset(..., dataframe=...)            # line 966 — offline injection lane
DatasetManager.add_dataframe(...)                         # line 1092 — direct frame registration
```

### Pattern anchor (read END TO END before implementing)
- `examples/agents/a2ui/deterministic_refresh_dashboard.py` (764 lines) —
  this task is a domain-specific retelling of that example: same runtime
  wiring, same `--serve` HTTP harness, same byte-identical assertion
  approach, same capabilities dump. Artifacts precedent:
  `artifacts/a2ui_deterministic_refresh/` (01_dashboard_default.html,
  03_capabilities.json, …).

### Does NOT Exist
- ~~`artifacts/a2ui_live/`~~ — never existed; write demo artifacts to
  `artifacts/flex_dashboard_demo/`.
- ~~a pytest fixture that fetches the real slugs~~ — prod-only data; tests
  use synthetic frames exclusively.
- ~~automatic renderer availability~~ — `interactive-html` import can fail
  when ai-parrot-visualizations isn't installed; integration tests must
  `pytest.importorskip` / skip cleanly in that case (mirror how existing
  a2ui integration tests guard it: see
  `packages/ai-parrot-server/tests/integration/test_a2ui_e2e.py`).

---

## Implementation Notes

### Key Constraints
- Fully offline and deterministic: no DB, no network, no LLM (narrative
  absent), stable clock inputs if any timestamps land in the HTML — replay
  must be BYTE-identical, which is an explicit acceptance criterion.
- Example must run from repo root with only
  `pip install ai-parrot ai-parrot-visualizations[a2ui]` (document in
  docstring, as the reference example does).
- Reuse `OUTPUT_DIR = REPO_ROOT / "artifacts" / "flex_dashboard_demo"`
  pattern (example line 69-70).
- Integration tests live under `packages/ai-parrot/tests/integration/`
  (FinanceReporter precedent: `test_finance_reporter_narrative_e2e.py`).

---

## Acceptance Criteria

- [ ] `python examples/agents/a2ui/flex_dashboard_demo.py` completes offline,
      producing dashboard HTML + capabilities dump under
      `artifacts/flex_dashboard_demo/`.
- [ ] Two `RecipeRunner.run()` calls with identical params produce
      byte-identical HTML.
- [ ] A params override (month/pay_code) produces a deterministic filtered
      variant.
- [ ] `callAgentFunction → refresh_dashboard` honors surface filter state;
      explicit args win.
- [ ] `--serve` works (documented HTTP-origin requirement).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py -v`
      (and skip cleanly without the renderer extra).
- [ ] Total feature diff confined to `agents/`, `examples/`,
      `packages/ai-parrot/tests/` (spec §5 final criterion).

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_flex_dashboard_e2e.py
import pytest
pytest.importorskip("parrot.outputs.a2ui_renderers.interactive_html")

async def test_flex_dashboard_publish_replay(tmp_path, flex_frames):
    ...  # publish → run twice → assert html_a == html_b (bytes)

async def test_flex_dashboard_filtered_replay(tmp_path, flex_frames):
    ...  # params={"month": "2025-10"} → subset numbers, still deterministic

async def test_flex_refresh_rpc(tmp_path, flex_frames):
    ...  # A2UIRuntime dataModel state → refresh_dashboard → filtered rerun
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2697 and TASK-2698 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
