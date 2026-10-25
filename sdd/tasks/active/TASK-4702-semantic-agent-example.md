# TASK-4702: End-to-end example — Agent with SemanticLayerToolkit + DatasetManager hand-off

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4477, TASK-4479, TASK-4481
**Assigned-to**: unassigned

---

## Context

Owner request (2026-10-25): a runnable, end-to-end example of an **Agent** that consumes the
semantic layer AND has a **DatasetManager toolkit assigned**, demonstrating the full governed flow
of spec §2: catalog → `sl_query_metrics` on a DuckDB warehouse → `sl_save_result_as_dataset`
hand-off into a subject-scoped `DatasetManager` → the Agent analyzing the saved dataframe with
the DatasetManager tools. This is the reference wiring hosts copy (`dataset_manager_factory`,
`PermissionContext`, policy side-file), exercised by a no-real-LLM smoke test.

---

## Scope

- Create `examples/semantic/agent_semantic_example.py`: self-contained builders —
  `build_warehouse(tmp dir) -> duckdb file`, `build_models_dir(...)` (own-format `orders` model +
  `orders.policy.yaml` with roles/RLS/mask, mirroring the §4 fixtures), `build_toolkits(...)` →
  `(SemanticLayerToolkit, DatasetManager)` with a `dataset_manager_factory` returning the
  subject/session-scoped manager, and `build_agent(...)` → `Agent` with BOTH toolkits assigned.
  A `main()` (guarded by `if __name__ == "__main__":`) runs the scripted tool sequence directly
  (no LLM needed) and prints the governed SQL + saved-dataset summary; with an LLM configured via
  env it instead drives the Agent with a natural-language KPI question.
- Create `examples/semantic/README.md`: what it shows, how to run, where production wiring differs
  (real `DataPlanePolicyGuard` evaluator from navigator-auth, real audit sink, HTTP factory
  precedent `handlers/datasets.py::_get_dataset_manager`).
- Create `packages/ai-parrot-semantic/tests/test_example_agent.py`: imports the example's builders
  (no real LLM) and asserts the full chain: `sl_query_metrics` rows match the hand-computed DuckDB
  expectation; `sl_save_result_as_dataset` lands the dataframe in the factory's `DatasetManager`
  (`add_dataframe` called, dataframe listed); the agent object holds tools from BOTH toolkits.

**NOT in scope**: new toolkit features; real-LLM integration tests (`PARROT_TEST_REAL_LLM` paths);
docs/tools/semantic-layer.md (TASK-4481 owns it — the README may link to it only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/semantic/agent_semantic_example.py` | CREATE | runnable example (builders + `main()`) — **gitignored: stage with `git add -f`** |
| `examples/semantic/README.md` | CREATE | run instructions + production-wiring notes — stage with `git add -f` if ignored |
| `packages/ai-parrot-semantic/tests/test_example_agent.py` | CREATE | no-LLM smoke test over the example's builders |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified on `dev` @ `71999bd06` (2026-10-25), except satellite symbols which are
> fixed by spec §3 and land with TASK-4463..4479 (re-verify in the worktree before use).
> `grep` is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
from parrot.bots import Agent                       # verified: packages/ai-parrot/src/parrot/bots/__init__.py:12; class at bots/agent.py:1576
from parrot.tools.dataset_manager import DatasetManager   # verified: class DatasetManager(AbstractToolkit) at dataset_manager/tool.py:499 — it IS a toolkit
from parrot.auth import PermissionContext, UserSession, DataPlanePolicyGuard, RlsRegistry  # verified: auth/__init__.py lazy map
# Satellite (exists only after TASK-4477/4479 — spec §3 M10 fixes the names):
# from parrot.semantic.toolkit import SemanticLayerToolkit
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):              # line 499
    def add_dataframe(self, name, df, description=None, metadata=None, is_active=True,
                      computed_columns=None, usage_guidance=None) -> str   # line 1091
# spec §2 New Public Interfaces — SemanticLayerToolkit.__init__ kwargs incl.
#   dataset_manager_factory, allow_raw_sql=False, static_subject=None (M10)
# spec §4 fixtures — duckdb_warehouse / models_dir / pctx_factory shapes to mirror in the example
```

### Does NOT Exist
- ~~`examples/semantic/`~~ — created here. **`examples/**/*.py` is gitignored** (known repo rule):
  the example files MUST be staged with `git add -f` or the commit silently omits them.
- ~~A public LLM-free `Agent.run_tools()` demo helper~~ — the no-LLM path calls the toolkit tools
  directly (`await toolkit.query_metrics(...)` etc.); do not invent an Agent API for it.
- ~~`parrot.semantic` on `dev`~~ — satellite lands with TASK-4463+; this task runs in the feature
  worktree where it exists.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/semantic/agent_semantic_example.py",
      "action": "CREATE"
    },
    {
      "path": "examples/semantic/README.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_example_agent.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent"
  ]
}
```

---

## Implementation Notes

- The example's guard: a small in-file allow-all evaluator double for `DataPlanePolicyGuard`
  (clearly commented "demo only — production wires navigator-auth's evaluator"), so the governed
  path (PBAC → RLS push-down → masking → positive guard → audit) actually executes rather than
  being bypassed with `governed: false`.
- The `dataset_manager_factory` must return a **per-subject** `DatasetManager` (spec AC10); the
  example builds one per `PermissionContext` and comments why a shared instance is refused.
- Subject: build `PermissionContext(UserSession(user_id, tenant_id, roles, metadata={"programs": [...]}))`
  so the RLS rule in `orders.policy.yaml` visibly filters rows — print row counts for two subjects
  to make the governance observable.
- Tools from both toolkits on one Agent: pass them via the Agent's tools/toolkits wiring exactly as
  an existing example under `examples/` does (read one first; do not guess the kwarg name).

### Key Constraints
- Async-first; `asyncio.run(main())`; `logging`, never `print` **except** the example's final
  human-readable summary (examples are exempt from the no-print rule by precedent — check a
  sibling example; otherwise use a logger with a stream handler).
- Pydantic v2; Google-style docstrings; 120-column lines; `ruff check` clean (TID251 applies —
  no `sidemantic`, no `requests`/`httpx`).
- Worktree testing: `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add
  `:packages/ai-parrot-server/src` only if server imports appear — they should not).

---

## Implementation Blueprint

### Steps (in order)
1. Read one existing `examples/` agent script for the Agent construction/toolkit-assignment
   pattern — *why*: the Agent kwargs are not re-verified here.
2. Write `agent_semantic_example.py` builders (warehouse → models dir → toolkits → agent) + `main()`.
3. Write the smoke test against the builders; hand-compute the expected DuckDB aggregate.
4. Write the README.

### FILL IN checklist
- [ ] Agent toolkit-assignment kwarg (from the sibling example).
- [ ] `orders` model + policy YAML bodies (mirror spec §4 fixtures).
- [ ] Hand-computed expected rows for the seeded warehouse.

---

## Acceptance Criteria

- [ ] `python examples/semantic/agent_semantic_example.py` runs end-to-end with no LLM and no
      network: prints governed SQL, per-subject row counts (RLS visibly different), and the saved
      dataset name.
- [ ] The Agent is constructed with BOTH `SemanticLayerToolkit` and `DatasetManager` tools attached.
- [ ] `sl_save_result_as_dataset` hand-off works through the per-subject factory; a shared-manager
      factory is shown (commented) as refused (AC10).
- [ ] `test_example_agent.py` passes; the example files are committed (staged with `git add -f`).

---

## Validation Commands

> File-level pytest only — run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src`
> in the feature worktree.

- `pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_example_agent.py
import pytest

from examples.semantic.agent_semantic_example import (  # path added via sys.path or importlib — examples/ is not a package
    build_warehouse, build_models_dir, build_toolkits, build_agent,
)


@pytest.mark.asyncio
async def test_example_full_chain(tmp_path):
    # FILL IN: build warehouse + models dir; build toolkits for subject A;
    #          result = await sl_toolkit.query_metrics(SemanticQuery(model="orders", metrics=["revenue"], ...))
    #          assert rows == hand-computed expectation (RLS-filtered for subject A)
    #          saved = await sl_toolkit.save_result_as_dataset(result.result_id, "demo")
    #          assert the factory's DatasetManager lists the dataframe
    ...


def test_example_agent_has_both_toolkits(tmp_path):
    # FILL IN: agent = build_agent(...); tool names include sl_query_metrics AND a DatasetManager tool
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`) §2 (pipeline + New Public Interfaces),
   §4 fixtures, AC10.
3. **Check dependencies** — TASK-4477 and TASK-4479 are `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; satellite symbols are re-verified in the
   worktree (they do not exist on `dev`).
5. **Implement** exactly the files above; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands; also run the example
   script itself once and paste its output into the Completion Note.
7. **Commit** only the listed files (`git add -f examples/semantic/...`):
   `feat(semantic-layer): TASK-4702 — e2e example: Agent with SemanticLayerToolkit + DatasetManager`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4702 semantic-layer verified` and fill in the
   Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
