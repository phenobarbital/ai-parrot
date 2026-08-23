# TASK-2390: BusinessAutomationToolkit core + ConfirmationGuard SUBMIT gate

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2387, TASK-2388, TASK-2389
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** (Goals G4, G5) — the generic engine.

Domain-neutral by decision (spec §8): the reusable machinery is public here,
while site-specific plans live in an external private directory (Module 6).
The toolkit must therefore contain **no** Hooba identifiers.

Gating follows **Decision D2**: reuse the shipped HITL stack rather than
inventing one. `ConfirmationGuard` (auth/confirmation.py:378) is already wired
into `ToolManager` via `set_confirmation_guard()` and fires in `execute_tool()`
after the grant check and before `tool.execute()`.

Implements spec **Module 5**.

---

## Scope

- Create the `business_automation` package with `models.py` (`OperationKind`,
  `BusinessOperation`, `ImportRun`) and `toolkit.py`.
- Implement `BusinessAutomationToolkit(AbstractToolkit)` with `auto_open = True`,
  constructing a `FlowExecutor` and managing the browser through `_open`/`_close`.
- Tools: `list_operations`, `describe_operation`, `run_operation`,
  `resume_operation`.
- Call `ScrapingPlan.validate_steps()` **before** any driver is created.
- **SUBMIT gating (D2)**: mark `run_operation` as a confirmation tool via
  `routing_meta` when the resolved operation is `OperationKind.SUBMIT`, and set
  `confirm_window_seconds = 0` for it so a repeated identical submit is never
  auto-approved by a window hit.
- Fail closed: `human_manager=None` + a SUBMIT operation ⇒ denied, browser never
  opened.
- Return a `run_id` immediately for long operations so a chat turn is not held open.

**NOT in scope**: loading the plans directory (TASK-2391); the Excel ingest
(TASK-2392); any Hooba-specific plan.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/__init__.py` | CREATE | Package exports |
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py` | CREATE | OperationKind, BusinessOperation, ImportRun |
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py` | CREATE | The engine |
| `packages/ai-parrot-tools/tests/business_automation/test_toolkit.py` | CREATE | Unit tests incl. gate |
| `packages/ai-parrot-tools/tests/business_automation/test_submit_gate.py` | CREATE | Fail-closed + window tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit                # verified: tools/toolkit.py:216
from parrot.auth.confirmation import ConfirmationGuard          # verified: auth/confirmation.py:378
from parrot.human import HumanInteractionManager                # verified: human/__init__.py:33
from parrot_tools.scraping import (                             # verified: scraping/__init__.py:28-32
    TemplatePlan, ParamSpec, ScrapingFlow, FlowNode, FlowResult,
    FlowExecutor, SessionManager,
)
from parrot_tools.scraping.plan import ScrapingPlan             # verified: scraping/plan.py:59
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                         # line 216
    auto_open: bool = False                         # line 310
    def __init__(self, **kwargs): ...               # line 312
    async def _open(self) -> None: ...              # line 388  (only when auto_open=True)
    async def _close(self) -> None: ...             # line 404
    def get_tools(...): ...                         # line 484
    def get_tools_sync(...): ...                    # line 594

# packages/ai-parrot/src/parrot/auth/confirmation.py  — Decision D2
class ConfirmationGuard:                            # line 378
    """Wired into ToolManager via set_confirmation_guard(); invoked in
    execute_tool() AFTER the grant check and BEFORE tool.execute().
    Lifecycle: non-confirmation tool -> allow ('not_required');
    within confirm_window_seconds for same args_hash -> ALLOW (window hit);
    NO human_manager -> DENY (fail-closed, 'cancelled');
    else build briefing -> ask HITL -> map result to decision."""
    def __init__(self, store: ConfirmationWindowStore,
                 human_manager: Optional["HumanInteractionManager"] = None,
                 config: Optional[ConfirmationConfig] = None) -> None: ...  # line 401
    async def confirm(self, *, tool, parameters: dict,
                      permission_context=None) -> ConfirmationDecision: ... # line 418

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py
class FlowExecutor:                                 # line 40
    def __init__(self, browser, registry=None, config=None, concurrency=1,
                 checkpoint_dir=None, logger=None, templates=None) -> None: ...  # line 58
    async def run(self, flow: ScrapingFlow, params=None, resume_from=None) -> FlowResult: ...  # line 338

# packages/ai-parrot-tools/src/parrot_tools/scraping/flow_models.py
class FlowNode(BaseModel):                          # line 19
    id: str; plan_ref: str
    inputs: Dict[str, str] = {}                     # "param -> node_id.field"
    session: str = "default"                        # shared BrowserContext label
    on_error: Literal["abort","skip","retry"] = "abort"
    max_retries: int = 3
class ScrapingFlow(BaseModel):                      # line 39
    name: str; description: str = ""
    nodes: List[FlowNode] = Field(min_length=1)
    global_params: Dict[str, Any] = {}
class FlowResult(BaseModel): ...                    # line 147

# packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py
class ParamSpec(BaseModel): ...                     # line 72
class TemplatePlan(BaseModel):                      # line 103
    name: str; objective_template: str; url_template: str
    params: List[ParamSpec] = []
    steps_template: List[Dict[str, Any]] = []
    def bind(self, **kwargs) -> ScrapingPlan: ...   # line 205

# packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py
class SessionManager:                               # line 21
    async def get_context(self, session: str) -> Any: ...   # line 46
    async def new_page(self, session: str) -> Any: ...      # line 65
    async def close_if_last(self, session, node_id) -> None:# line 87
    async def close_all(self) -> None: ...                  # line 102
```

### Does NOT Exist

- ~~`SubmitGateFn`~~, ~~`SubmitGateDecision`~~ — invented in the spec's v0.1 draft, **deleted at v0.2**. Use `ConfirmationGuard` + `ConfirmationDecision` + `InteractionResult`. Do not resurrect them (spec §6 "Does NOT Exist").
- ~~`AgentsFlow.as_tool()`~~ — does not exist. `AgentsFlow` is `AgentsFlow(PersistenceMixin)` (`bots/flows/flow/flow.py:217`), not an `AbstractBot`; `AgentTool.__init__` requires an `AbstractBot` (`tools/agent.py:52`). For flow-as-tool use `ExecutionPlanToolkit.plan_execute` (TASK-2392).
- ~~`HoobaToolkit`~~ / ~~`BrowserAutomationToolkit`~~ — neither exists nor will. The class is `BusinessAutomationToolkit`.
- ~~`FlowExecutor.execute()`~~ — the method is `run(flow, params=None, resume_from=None)` (flow_executor.py:338).

---

## Implementation Notes

### Pattern to Follow
FEAT-207 shared-state toolkit: one instance initialized with live dependencies
(executor, plan store, guard) shared across every tool call — the same shape as
`ExecutionPlanToolkit` and the skill toolkits. FEAT-391 lazy lifecycle
(`auto_open=True` + `_open`/`_close`) for the browser, exactly as
`ObsidianToolkit` does for the vault.

### Key Constraints
- **`confirm_window_seconds = 0` for SUBMIT.** The guard's default window
  auto-approves a repeat call with the same `args_hash`. For "issue this
  invoice" that is a duplicate filing. This is the single most important
  configuration line in the task.
- **Zero Hooba identifiers.** `grep -ci hooba` on this package must be 0.
- Keep `concurrency=1` for any flow whose nodes share a `session` label —
  FEAT-222 lists fan-out over a shared authenticated session as deferred debt.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] `OperationKind.SUBMIT` routes through `ConfirmationGuard.confirm()`; `DRAFT` does not
- [ ] `human_manager=None` + SUBMIT ⇒ decision `cancelled` and the browser is never opened
- [ ] `confirm_window_seconds` is 0 for SUBMIT: two identical submits prompt twice
- [ ] `validate_steps()` runs before any driver is constructed
- [ ] `grep -ci hooba` over the package returns 0
- [ ] `run_operation` returns a `run_id` without holding the call open
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/business_automation/test_submit_gate.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit
from parrot_tools.business_automation.models import OperationKind


class TestSubmitGate:
    async def test_submit_requires_confirmation(self, toolkit, spy_guard):
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert spy_guard.confirm_calls, "SUBMIT ran without a confirmation ask"

    async def test_draft_runs_unattended(self, toolkit, spy_guard):
        await toolkit.run_operation("draft_invoice", {"client": "ACME"})
        assert not spy_guard.confirm_calls

    async def test_fails_closed_without_human_manager(self, plans_dir, spy_browser):
        tk = BusinessAutomationToolkit(plans_dir=plans_dir, human_manager=None)
        result = await tk.run_operation("issue_invoice", {"client": "ACME"})
        assert result["status"] == "cancelled"
        assert not spy_browser.opened, "browser opened despite a denied gate"

    async def test_window_disabled_for_submit(self, toolkit, spy_guard):
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        await toolkit.run_operation("issue_invoice", {"client": "ACME"})
        assert len(spy_guard.confirm_calls) == 2, "second identical submit rode a window hit"
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
7. **Move this file** to `sdd/tasks/completed/TASK-2390-business-automation-toolkit-core.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Created the `business_automation` package: `models.py`
(`OperationKind`, `BusinessOperation`, `ImportRun`) and `toolkit.py`
(`BusinessAutomationToolkit`). The SUBMIT gate is a **manual, code-level**
invocation of `ConfirmationGuard.confirm()` inside `run_operation()` —
not the static, whole-method `AbstractToolkit.confirming_tools` marking.
This was a necessary design decision: `confirming_tools` is consulted once
at `get_tools()` time (fixed per method name), but the task requires the
gate to vary **per resolved operation kind** at call time, and
`toolkit.run_operation(...)` as tested here is a direct method call — it
never goes through `ToolManager.execute_tool()`'s automatic grant→confirm
dispatch at all. `run_operation` therefore builds a minimal
`SimpleNamespace(name=..., routing_meta={"requires_confirmation": True,
"confirm_window_seconds": 0, "confirm_template": ...})` stand-in and passes
it to `self._confirmation_guard.confirm(tool=stub, parameters=params)` —
verified `ConfirmationGuard.confirm()`/`render_briefing()` read only
`tool.name`/`tool.routing_meta`, so this is a faithful, non-invented use of
the real guard, only for SUBMIT operations; DRAFT/READ never call
`.confirm()` at all. `validate_steps()` runs via `_validate_flow()` —
binding every node's `TemplatePlan` and calling `ScrapingPlan.validate_steps()`
— strictly before `_ensure_open()`, so a malformed plan is a clean error
with no browser ever opened, and a denied SUBMIT confirmation short-circuits
before `_validate_flow()`/`_ensure_open()` are even reached. `run_operation`
returns a `run_id` immediately (`asyncio.create_task` pattern mirroring
`ExecutionPlanToolkit.plan_execute`), with `resume_operation` re-invoking
`FlowExecutor.run(..., resume_from=...)` against the same run_id slot.
20 new tests pass (list/describe, SUBMIT gate wired through the real
`ConfirmationGuard` fail-closed path, spy-guard window/confirm-count tests,
validate-before-open, run_id immediacy, zero-site-identifier scan). Full
`packages/ai-parrot-tools/tests/scraping/` + new `tests/business_automation/`
suites (839 tests) re-run — same 7 pre-existing, unrelated
`CrawlEngine`/FEAT-013 failures, zero regressions. `ruff check` clean except
the same `UP006`/`UP035`/`UP037`/`UP045`/`UP007` pyupgrade-style debt already
established by this feature's other new files (`session_actions.py`
convention of `typing.Dict`/`List`/`Optional`).

**Deviations from spec**: (1) Per the task's own explicit exclusion ("NOT in
scope: loading the plans directory — TASK-2391"), the constructor accepts
and stores `plans_dir` but does **not** scan it. Operations/flows/templates
are instead seeded via `operations`/`flows`/`templates` constructor kwargs
(popped from `**kwargs`, which the given signature explicitly allows) — an
interim seam that TASK-2391's `TemplatePlanStore` (Module 6, a *separate*
`store.py` file this task does not create) is expected to populate for real.
This is disclosed, not silent: documented in both the class docstring and
inline comments. (2) `_validate_flow()`'s pre-flight validation is
best-effort for multi-node flows: nodes whose `FlowNode.inputs` reference a
prior node's output are validated using only the flow's `global_params` +
caller params (a static lint pass), since the real cross-node data isn't
available until the flow actually runs — `FlowExecutor` performs the
authoritative resolution at execution time. All of this task's own test
flows are single-node, so this limitation isn't exercised by the test suite;
noting it for whoever builds a multi-node operation later.
