---
id: F006
query_id: Q007
type: wiki_page
intent: Read BusinessAutomationToolkit, models and plans store contracts.
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — BusinessAutomationToolkit is a shipped, domain-neutral engine: READ/DRAFT unattended, SUBMIT gated by ConfirmationGuard before the browser opens, private plans dir

## Summary

`business_automation/toolkit.py::BusinessAutomationToolkit(AbstractToolkit)` (`auto_open=True`): ctor `(plans_dir, browser, credential_broker, human_manager, checkpoint_dir, credential_user_id, human_channel)`; tools `list_operations`, `describe_operation`, `run_operation(name, params)` → `{"status": "started", "run_id": ...}` (background task), `resume_operation(run_id, resume_from)`. `OperationKind.SUBMIT` triggers `_request_submit_confirmation` via `ConfirmationGuard`; DRAFT/READ never touch the guard (Decision D2). Models: `OperationKind{read,draft,submit}`, `BusinessOperation{name, description, kind, flow_ref, params: List[ParamSpec], confirm_prompt}`, `ImportRun{statement_digest, period, started_at}`. `store.py::PlanDirectoryStore(plans_dir)` loads `*.operation.json` / `*.template.json` / `*.flow.json`, rejects literal passwords in authenticate, `reload_if_changed()`. Package deliberately contains zero site names.

## Citations


- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py`
  lines: 1-16
  symbol: `module docstring`
  excerpt: |
    Contains **zero** site-specific identifiers ...; site-specific plans live in an external, private plans directory (Module 6, TASK-2391) loaded at runtime. Gating follows Decision D2: reuse the shipped HITL stack (ConfirmationGuard)

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py`
  lines: 128-260
  symbol: `BusinessAutomationToolkit.__init__/_open`
  excerpt: |
    def __init__(self, plans_dir, browser, credential_broker, human_manager, checkpoint_dir, credential_user_id, human_channel) ... self._confirmation_guard = ConfirmationGuard(  # 239

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py`
  lines: 305-378
  symbol: `run_operation`
  excerpt: |
    async def run_operation(self, name, params=None):
        if op.kind == OperationKind.SUBMIT:  # 349 → confirmation
        run_id = f"run_{uuid.uuid4().hex[:8]}"  # 373
        return {"status": "started", "run_id": run_id, "operation": op.name}

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py`
  lines: 380-422
  symbol: `resume_operation`
  excerpt: |
    async def resume_operation(self, run_id, resume_from=None)

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py`
  lines: 28-70
  symbol: `OperationKind, BusinessOperation, ImportRun`
  excerpt: |
    READ = "read"; DRAFT = "draft"; SUBMIT = "submit"
    class BusinessOperation(BaseModel): name; description; kind: OperationKind; flow_ref: str; params: List[ParamSpec]; confirm_prompt

- path: `packages/ai-parrot-tools/src/parrot_tools/business_automation/store.py`
  lines: 14-16, 41-62, 84-136
  symbol: `PlanDirectoryStore`
  excerpt: |
    - *.operation.json — BusinessOperation
    - *.template.json — TemplatePlan
    - *.flow.json — ScrapingFlow
    class PlanDirectoryStore: def __init__(self, plans_dir) / load() / reload_if_changed()

- path: `packages/ai-parrot/src/parrot/auth/confirmation.py`
  lines: 1-1
  symbol: `ConfirmationGuard`
  excerpt: |
    (wiki_related edge from toolkit.py)
