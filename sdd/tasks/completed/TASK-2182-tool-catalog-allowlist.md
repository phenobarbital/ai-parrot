# TASK-2182: Tool catalog + allowlist validation layering

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2179
**Assigned-to**: unassigned

---

## Context

A plan is code written by a model, and the invoking agent may share its
`ToolManager` with writers. The explicit `allowed_tools` allowlist (spec
Axis 6) is both the security boundary (a plan naming a non-allowlisted tool
fails validation before anything runs) and the planner's tool catalog (the
planner only ever sees allowlisted tools — resolving Axis 2 for free).
Implements spec §3 Module 5 (catalog + validation layering; the
`plan_validate` tool front is TASK-2184).

---

## Scope

- Implement `parrot/tools/execution_plan/catalog.py`:
  - `ToolCatalogEntry` (Pydantic, `extra="forbid"`): `name`, `description`,
    `args_summary` (compact rendering of the tool's `args_schema`: field
    name, type, required, description — bounded, no nested JSON schema
    dumps).
  - `build_catalog(tool_manager, allowed_tools: Sequence[str] | None)
    -> list[ToolCatalogEntry]`: allowlist ∩ `tool_manager.list_tools()`;
    `None` allowlist ⇒ all manager tools. Allowlisted names absent from the
    manager are reported (raise `ValueError` naming them — a misconfigured
    allowlist must not fail silently).
  - `check_allowlist(plan: ExecutionPlan, allowed_tools) ->
    list[ValidationIssue]`: one `tool_not_allowed` error-severity issue per
    offending node, phrased so a planner model can correct the plan.
- Provide `validate_with_allowlist(plan, tool_manager, allowed_tools) ->
  ValidationReport`: runs `validate_plan(plan, tool_manager)` and appends
  the allowlist issues into the same report (single combined issue list).
- Unit tests including the shared-ToolManager scenario: tool registered in
  the manager but NOT allowlisted ⇒ validation error pre-execution.

**NOT in scope**: the planner prompt that consumes the catalog (TASK-2183),
`plan_validate` tool surface (TASK-2184).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py` | CREATE | Catalog + allowlist checks |
| `packages/ai-parrot/tests/tools/execution_plan/test_catalog.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import ExecutionPlan, validate_plan   # after TASK-2179
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport
```

### Existing Signatures to Use
```python
# parrot/bots/flows/plan/validator.py (landed by TASK-2179)
def validate_plan(plan, tool_manager=None, *, check_guards=True) -> ValidationReport  # :112
@dataclass(frozen=True)
class ValidationIssue:            # :48
    node_id: Optional[str]; code: str; message: str; severity: str = "error"
@dataclass
class ValidationReport:           # :70 — .issues list; .errors/.warnings/.ok
class ToolManagerLike(Protocol):  # :37 — get_tool(name) -> Optional[Any];
                                  #        list_tools() -> List[str]

# packages/ai-parrot/src/parrot/tools/manager.py
def get_tool(tool_name) -> Optional[Any]   # ~:1118
def list_tools() -> List[str]              # ~:1142

# packages/ai-parrot/src/parrot/tools/abstract.py
args_schema: Type[BaseModel] = AbstractToolArgsSchema  # :251 — source for
#   args_summary; a tool whose args_schema IS AbstractToolArgsSchema has no
#   declared fields → args_summary = [].
```

### Does NOT Exist
- ~~a `tool_not_allowed` code in `validate_plan`~~ — the frozen validator
  knows nothing about allowlists; the code is introduced HERE, layered on
  top. Do not patch `validator.py`.
- ~~denylist support~~ — v1 is allowlist-only (spec decision).
- ~~semantic/embedding tool search for the catalog~~ — rejected in
  brainstorm (Axis 2); the catalog is a plain filtered listing.

---

## Implementation Notes

### Key Constraints
- `ValidationIssue`/`ValidationReport` are frozen/plain dataclasses — build
  a NEW report or append to `report.issues`; do not subclass.
- `args_summary` must be bounded: cap description strings (~120 chars) and
  never embed the full JSON schema — the catalog goes into a planner
  prompt.
- Pure functions where possible; no toolkit state in this module (the
  toolkit passes its own `allowed_tools`).

### References in Codebase
- `parrot/bots/flows/plan/validator.py` — issue phrasing style
  ("phrased so a planner model can correct the plan from it directly").

---

## Acceptance Criteria

- [ ] `build_catalog(mgr, None)` == all manager tools;
  `build_catalog(mgr, subset)` == exactly the subset, order-stable
- [ ] Allowlisted-but-unregistered names raise `ValueError` naming them
- [ ] Plan using a registered-but-not-allowlisted tool ⇒ combined report
  has a `tool_not_allowed` error and `.ok is False`
- [ ] `validate_with_allowlist` returns ALL issues in one report
  (validator issues + allowlist issues, one pass)
- [ ] `args_summary` bounded (no full JSON-schema dumps) and empty for
  default `AbstractToolArgsSchema`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/execution_plan/test_catalog.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_catalog.py
class TestBuildCatalog:
    def test_none_allowlist_is_all_tools(...): ...
    def test_subset_intersection(...): ...
    def test_unregistered_allowlisted_name_raises(...): ...
    def test_args_summary_bounded(...): ...

class TestAllowlistValidation:
    def test_tool_not_allowed_issue(...): ...
    def test_combined_report_single_pass(...): ...
    def test_allowlist_none_passes_everything_registered(...): ...
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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-07
**Notes**: Implemented `ArgSummary`/`ToolCatalogEntry`/`build_catalog`/
`check_allowlist`/`validate_with_allowlist` in
`packages/ai-parrot/src/parrot/tools/execution_plan/catalog.py`.
`build_catalog` preserves `tool_manager.list_tools()` order (not
allowlist order) for a stable catalog; unregistered allowlisted names
raise `ValueError` naming them. `check_allowlist` layers one
`tool_not_allowed` `ValidationIssue` per offending node on top of the
frozen validator (never patches `validator.py`). `validate_with_allowlist`
calls `validate_plan()` then appends into the SAME `report.issues` list
(mutates the dataclass in place, per the task's "do not subclass"
constraint) so the combined report is genuinely one pass. `args_summary`
is bounded (120-char description cap per arg, no JSON-schema dumps) and
empty for both `args_schema=None` and the default
`AbstractToolArgsSchema`. 10/10 new tests pass (`pytest packages/ai-
parrot/tests/tools/execution_plan/test_catalog.py -v`), including the
shared-ToolManager scenario (tool registered but not allowlisted → error
pre-execution) and the combined-report single-pass test (`unknown_tool` +
`tool_not_allowed` together). `ruff check --select F,E9` clean.

**Deviations from spec**: none
