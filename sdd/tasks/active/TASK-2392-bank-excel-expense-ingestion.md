# TASK-2392: Bank-statement Excel ingestion via ExecutionPlan (+ checkpoint discriminator)

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2390, TASK-2391
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** (Goal G7).

The agent must accept a bank-statement Excel over chat and register each
transaction as an expense. `TelegramAgentWrapper` already forwards uploads as
`agent.ask(attachments=[...])` (wrapper.py:300, 1461-1552), and
`ExecutionPlanToolkit.plan_execute` runs a tool-call DAG on `AgentsFlow` with
**zero LLM tokens** while it executes — the right substrate for an N-row loop.

**Decision D3 carries a hazard this task must defuse**: `_checkpoint_token` is
`sha256(global_params)[:8]` (flow_executor.py:271), keyed on parameters *only*.
Two legitimate imports of different statements for the same period would collide
on one checkpoint, and the second import would resume the first and **silently
skip every row**.

Implements spec **Module 9**.

---

## Scope

- Build an `ExecutionPlan` that iterates `ExcelLoader` row-mode Documents and
  invokes the `register_expense` operation once per row.
- Execute through `ExecutionPlanToolkit.plan_execute`; surface progress via
  `plan_status` / `plan_artifacts` rather than holding the chat turn open.
- **Inject `ImportRun.statement_digest` (sha256 of the source bytes) into
  `flow.global_params`** so distinct statements never share a checkpoint token.
- Place checkpoints under `${PARROT_STATE_DIR}/business_automation/checkpoints/<operation>/`
  with directory mode `0700` and file mode `0600`, outside the Obsidian vault and
  every wiki storage root.
- Reconciliation step: compare rows-in vs registrations-out and report the delta.

**NOT in scope**: retention/archival cron (that is Module 8's scheduler);
authoring the `register_expense` plan (out of repo).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py` | CREATE | Excel -> ExecutionPlan |
| `packages/ai-parrot-tools/tests/business_automation/test_ingest.py` | CREATE | Row mapping, digest, perms |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit   # verified: tools/execution_plan/toolkit.py:62
from parrot_loaders.excel import ExcelLoader                           # verified: parrot_loaders/excel.py:21
from parrot_tools.business_automation.models import ImportRun          # created by TASK-2390
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py
class ExecutionPlanToolkit(AbstractToolkit):        # line 62
    """Lets a plain BasicAgent trigger a deterministic tool-call DAG
    (ExecutionPlan) through a bounded tool call, with ZERO LLM tokens spent
    while it executes."""
    async def plan_status(self, run_id: str) -> ToolResult: ...       # line 385
    async def plan_artifacts(self, run_id: str) -> ToolResult: ...    # line 408
    async def plan_execute(self, objective=None, plan_name=None,
                           params=None) -> ToolResult: ...            # line 432
    async def plan_validate(self, objective=None, plan_name=None,
                            params=None) -> ToolResult: ...           # line 462
    async def _execute_flow(self, flow: AgentsFlow, ...):             # line 284
        await flow.run_flow(ctx)                                      # line 301

# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):                  # line 21
    output_mode: Literal["sheet","row"] = "sheet"   # line 56  <- use "row" here
    async def _load_row_mode(self, path) -> List[Document]: ...       # line 258

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py — THE D3 HAZARD
def _checkpoint_token(global_params: Dict[str, Any]) -> str:          # line 271
    #   sha256(json.dumps(global_params, sort_keys=True))[:8]
    #   "an identical parameter set resolves deterministically — which is what
    #    resume_from relies on"   <-- collision risk for two statements, same period
def _checkpoint_path(self, flow, token) -> Optional[Path]:            # line 282
    #   {checkpoint_dir}/{flow.name}.{token}.checkpoint.json
async def _write_checkpoint(self, flow, token, node_results):         # line 290
    #   persists ONLY result.extracted_data
```

### Does NOT Exist

- ~~`AgentsFlow.as_tool()`~~ — does not exist (see spec §6). Use `ExecutionPlanToolkit.plan_execute`.
- ~~`ExcelLoader(mode="row")`~~ — the kwarg is `output_mode` (excel.py:56).
- ~~`FlowExecutor.run(..., run_id=...)`~~ — `run()` takes `(flow, params=None, resume_from=None)` only (flow_executor.py:338). Checkpoint identity comes from `global_params`, which is exactly why D3 needs the digest injected there.

---

## Implementation Notes

### Key Constraints
- **The digest is not optional.** Without it, re-importing a corrected statement
  for the same quarter silently registers nothing. The failure is invisible —
  rows are skipped, not errored — which is the worst possible failure mode for
  bookkeeping.
- Checkpoints hold client names and amounts. `0700`/`0600`, and never inside the
  vault or a wiki root (both are mirrored/ingested surfaces).
- Keep the per-row loop sequential over one authenticated session.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] N rows produce N `register_expense` invocations
- [ ] Two imports with the same `period` but different bytes produce DIFFERENT checkpoint files
- [ ] A mid-run kill resumes without duplicate registrations
- [ ] Checkpoint dir is 0700 and files 0600
- [ ] The checkpoint path is outside the Obsidian vault and every wiki storage root
- [ ] Reconciliation reports rows-in vs registrations-out
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/business_automation/test_ingest.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest, stat
from parrot_tools.business_automation.ingest import build_import_plan


class TestIngest:
    async def test_one_node_per_row(self, three_row_xlsx):
        plan = await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert len(plan.nodes) == 3

    async def test_checkpoint_token_differs_per_statement(self, xlsx_a, xlsx_b):
        a = await build_import_plan(xlsx_a, period="2026-Q1")
        b = await build_import_plan(xlsx_b, period="2026-Q1")
        assert a.global_params["statement_digest"] != b.global_params["statement_digest"]

    async def test_checkpoint_permissions(self, three_row_xlsx, checkpoint_dir):
        await build_import_plan(three_row_xlsx, period="2026-Q1")
        assert stat.S_IMODE(checkpoint_dir.stat().st_mode) == 0o700
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2392-bank-excel-expense-ingestion.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
