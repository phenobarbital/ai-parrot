# TASK-2181: PlanFileStore — plans_dir loader with {params.<name>} substitution

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2179
**Assigned-to**: unassigned

---

## Context

`plan_name` mode loads versioned, git-diffable plan files from a
configurable `plans_dir` — the mode the daily Security Advisory pipeline
uses. Per-run parameters use `{params.<name>}` placeholders substituted at
**load time**, before validation, because the frozen executor resolves only
its three runtime placeholder families and must not be extended.
Implements spec §3 Module 3.

---

## Scope

- Implement `parrot/tools/execution_plan/store.py`: `PlanFileStore` with
  `__init__(plans_dir: Path)` and
  `load(plan_name: str, params: dict | None = None) -> ExecutionPlan`.
- Resolution: `plans_dir/<plan_name>.yaml` | `.yml` | `.json` (that
  precedence); unknown plan ⇒ `PlanLoadError` listing available names.
- `{params.<name>}` substitution over **string leaves** of the parsed
  document, BEFORE `ExecutionPlan.model_validate()`:
  - a string that is EXACTLY one `{params.<name>}` placeholder resolves to
    the param's native value (int stays int);
  - an embedded placeholder interpolates as text;
  - a referenced param missing from `params` ⇒ `PlanLoadError`;
  - a supplied param never referenced ⇒ `PlanLoadError` (nothing silent).
- Do NOT touch the executor's runtime placeholders: `{nodes.<id>.output}`,
  `{artifacts.<id>}`, `{item}`/`{item.<field>}`/`{index}` pass through
  substitution UNCHANGED.
- Define `PlanLoadError(ValueError)` in the same module.
- Migrate `sdd/artifacts/example_plan.json` into a shipped example
  `plans/daily_security_sweep.json` (repo-level `plans/` directory or the
  docs example dir — match where the spec's consumer expects it; if
  unclear, put it under `examples/plans/`): replace `"date": "{input}"`
  with `"date": "{params.date}"`. It must load through `PlanFileStore`
  with `params={"date": "..."}` in a test.

**NOT in scope**: toolkit wiring of `plan_name` into `plan_execute`
(TASK-2184), DB-backed store (v2), any YAML schema beyond what
`ExecutionPlan.model_validate` already enforces.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/store.py` | CREATE | `PlanFileStore` + `PlanLoadError` |
| `examples/plans/daily_security_sweep.json` | CREATE | Migrated example (`{params.date}`) |
| `packages/ai-parrot/tests/tools/execution_plan/test_store.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import ExecutionPlan   # after TASK-2179
import yaml    # PyYAML — already in the dependency tree
```

### Existing Signatures to Use
```python
# parrot/bots/flows/plan/models.py (landed by TASK-2179)
class ExecutionPlan(BaseModel):   # :272 — name, objective, nodes, metadata
#   model_config = ConfigDict(extra="forbid") — unknown keys in a plan file
#   fail validation loudly; do not pre-filter them.
# Pydantic validation performs the plan's internal checks (unique ids,
# cycles, declared deps, store_as rules) — the store does NOT re-implement
# any of that; it only substitutes params and calls model_validate.

# sdd/artifacts/example_plan.json — source for the migrated example;
#   its "{input}" placeholder is the thing being replaced.
```

### Does NOT Exist
- ~~`{input}` resolution anywhere~~ — not in the executor
  (node.py `_resolve_args` :290-328 resolves ONLY
  `{nodes.<id>.output}` / `{artifacts.<id>}` / `{item}`/`{index}`), and the
  store must NOT introduce it. `{params.<name>}` is the only
  parameterization syntax.
- ~~`{params.*}` at runtime~~ — after `load()` returns, no `{params...}`
  string may remain anywhere in the plan (assert in tests).
- ~~partial/param-default semantics~~ — no defaults, no optional params in
  v1; exact match both directions or `PlanLoadError`.

---

## Implementation Notes

### Pattern to Follow
```python
# Walk nested dict/list/str exactly like models._iter_strings does
# (parrot/bots/flows/plan/models.py:477) but rebuilding the structure;
# regex for placeholders: r"\{params\.([A-Za-z_][A-Za-z0-9_]*)\}"
```

### Key Constraints
- Load is sync CPU-trivial I/O — keep `load()` synchronous; the toolkit
  calls it from async code without blocking concerns (small files).
- Track referenced vs supplied param names in one pass; report BOTH missing
  and unused sets in a single `PlanLoadError` message (planner-style: all
  issues at once).
- `plans_dir` may not exist / not be configured ⇒ the toolkit (TASK-2184)
  raises the structural error; `PlanFileStore.__init__` itself raises on a
  nonexistent directory.

### References in Codebase
- `parrot/bots/flows/plan/models.py:477` — `_iter_strings` walking pattern.
- `parrot/bots/flows/plan/paths.py` — `render_key` shows the exact-match →
  native-value convention to mirror.

---

## Acceptance Criteria

- [ ] `PlanFileStore(plans_dir).load("daily_security_sweep",
  params={"date": "2026-08-06"})` returns a valid `ExecutionPlan`
- [ ] YAML and JSON both load; precedence yaml > yml > json documented
- [ ] Exact-placeholder native-value rule verified (int param stays int)
- [ ] Missing param, unused param, unknown plan name each raise
  `PlanLoadError` with actionable messages
- [ ] Runtime placeholders pass through UNCHANGED (test with a plan mixing
  `{artifacts.x}`, `{item}`, `{params.y}`)
- [ ] Migrated example file ships and loads; no `{input}` remains in it
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/execution_plan/test_store.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_store.py
class TestPlanFileStore:
    def test_loads_yaml_and_json(self, plans_dir): ...
    def test_exact_placeholder_native_value(self, plans_dir): ...
    def test_embedded_placeholder_interpolates(self, plans_dir): ...
    def test_missing_param_raises(self, plans_dir): ...
    def test_unused_param_raises(self, plans_dir): ...
    def test_unknown_plan_lists_available(self, plans_dir): ...
    def test_runtime_placeholders_untouched(self, plans_dir): ...
    def test_migrated_example_loads(self): ...
    def test_no_params_placeholder_survives_load(self, plans_dir): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2179 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/execution-plan-tool.json` → `"in-progress"`
5. **Implement**, 6. **Verify**, 7. **Move this file** to
   `sdd/tasks/completed/`, 8. **Update index** → `"done"`, 9. **Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
