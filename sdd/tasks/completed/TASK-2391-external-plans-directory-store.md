# TASK-2391: External plans directory loader + anonymized fixtures

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2390
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** (Goal G4).

Per the spec's public/private seam, the engine is public and the site plans are
not. This task builds the loader for a plans directory that lives **outside the
repository**, plus anonymized in-repo fixtures so the engine is testable without
any private material.

Implements spec **Module 6**.

---

## Scope

- Implement `PlanDirectoryStore` loading `BusinessOperation`, `TemplatePlan` and
  `ScrapingFlow` definitions from a configurable directory path.
- Schema-validate every definition on load; refuse the whole directory on a
  malformed file rather than silently skipping it.
- Run the credential lint from TASK-2389: reject any plan carrying a literal
  `password`.
- Support hot-reload on change.
- Ship anonymized fixtures under
  `packages/ai-parrot-tools/tests/business_automation/fixtures/` for a generic
  `acme-books` site — never Hooba.

**NOT in scope**: authoring the Hooba plans (out of repo, Deliverable X).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/store.py` | CREATE | PlanDirectoryStore |
| `packages/ai-parrot-tools/tests/business_automation/fixtures/acme-books/` | CREATE | Anonymized fixture plans |
| `packages/ai-parrot-tools/tests/business_automation/test_store.py` | CREATE | Loader tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot_tools.scraping import TemplatePlan, ParamSpec, ScrapingFlow, FlowNode  # verified: scraping/__init__.py:28-29
from parrot_tools.business_automation.models import BusinessOperation, OperationKind  # created by TASK-2390
```

### Existing Signatures to Use

```python
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

- ~~a plan registry that reads from the repo tree~~ — `PlanRegistry` (scraping/registry.py:20) exists but is URL-fingerprint keyed for scraped plans. This store is operation-keyed and reads an **external** directory. Do not conflate them.
- ~~Hooba fixtures~~ — fixtures are for a fictional `acme-books` site. No test may reference `app.hooba.com`.

---

## Implementation Notes

### Key Constraints
- **Fail the whole directory, not the file.** A silently-skipped malformed
  operation means an agent later reports "operation not found" for something the
  operator believes exists.
- Treat directory contents as untrusted input — it is authored outside the repo
  and drives a browser against a financial system.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] A well-formed directory loads all operations, templates and flows
- [ ] A malformed definition rejects the whole directory with the file and reason named
- [ ] A plan containing a literal `password` is rejected by the lint
- [ ] Hot-reload picks up a changed file without a restart
- [ ] Fixtures contain no reference to Hooba
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/business_automation/test_store.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.business_automation.store import PlanDirectoryStore


class TestPlanDirectoryStore:
    def test_loads_fixture_dir(self, fixture_plans_dir):
        store = PlanDirectoryStore(fixture_plans_dir); store.load()
        assert "register_expense" in store.operations

    def test_malformed_rejects_whole_dir(self, fixture_plans_dir, tmp_path):
        (fixture_plans_dir / "broken.operation.json").write_text("{ not json")
        with pytest.raises(ValueError, match="broken.operation.json"):
            PlanDirectoryStore(fixture_plans_dir).load()

    def test_literal_password_rejected(self, fixture_plans_dir):
        (fixture_plans_dir / "leaky.template.json").write_text(
            '{"name":"x","url_template":"http://x/","objective_template":"o",'
            '"steps_template":[{"action":"authenticate","password":"hunter2"}]}')
        with pytest.raises(ValueError, match="password"):
            PlanDirectoryStore(fixture_plans_dir).load()
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
7. **Move this file** to `sdd/tasks/completed/TASK-2391-external-plans-directory-store.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Created `PlanDirectoryStore` (store.py) using a file-naming
convention (`*.operation.json` → `BusinessOperation`, `*.template.json` →
`TemplatePlan`, `*.flow.json` → `ScrapingFlow`). `load()` parses every file
into LOCAL registries first and only commits them to
`self.operations`/`self.templates`/`self.flows` after the entire directory
validates successfully — so a malformed file rejects the whole directory
with the filename and reason named, AND leaves any previously-loaded good
state untouched on a failed reload (tested explicitly). Reused
`lint_literal_credentials` (added to `scraping/models.py` in TASK-2389)
rather than reimplementing the credential lint — every `.template.json`'s
`steps_template` is checked before the `TemplatePlan` is even constructed.
`reload_if_changed()` compares a `{path: mtime}` snapshot against the one
captured at the last successful `load()`; any added/removed/modified file
triggers a full reload. Anonymized fixtures ship under
`tests/business_automation/fixtures/acme-books/`: two operations
(`register_expense`, SUBMIT-kind; `list_clients`, READ-kind) each with
their own template + single-node flow. 12 new tests pass (load, malformed
JSON, schema violation, credential lint rejection + never-logs-the-secret,
a clean `credential_provider`-based auth template passing the lint, hot
reload with and without changes, missing directory, no site references in
either the fixtures or generated test data). Full
`packages/ai-parrot-tools/tests/scraping/` + `tests/business_automation/`
suites (843 tests) re-run — same 7 pre-existing, unrelated
`CrawlEngine`/FEAT-013 failures, zero regressions. `ruff check` clean
except the same `UP006`/`UP007`/`UP035` pyupgrade-style debt already
established by this feature's other files.

**Deviations from spec**: None of substance. The file-naming convention
(`*.operation.json`/`*.template.json`/`*.flow.json`) was not literally
specified by the task (only implied by the test scaffold's
`broken.operation.json`/`leaky.template.json` filenames) — chose the
straightforward, self-documenting convention the test names already hinted
at, rather than inventing a different directory layout (e.g. subfolders per
type).
