# TASK-1452: Implement FlowExecutor orchestration engine

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1445, TASK-1448, TASK-1449, TASK-1450, TASK-1451
**Assigned-to**: unassigned

---

## Context

FlowExecutor is the orchestration engine that ties everything together: topological sort,
input resolution, template binding, session/page management, per-node execution via
execute_plan_steps, fan-out, error handling, and checkpoint persistence.

Implements spec §Module 8 (FlowExecutor).

---

## Scope

- Create `FlowExecutor` class:
  - `__init__(browser, registry=None, config=None, concurrency=1, checkpoint_dir=None, logger=None)`
  - `run(flow, params=None, resume_from=None)` → `FlowResult`
- Implement the execution loop:
  1. Compute topological order from `flow.topological_order()`
  2. Precompute session last-use via `SessionManager.precompute_last_use()`
  3. For each node in topo order:
     a. Resolve `inputs` from prior node results
     b. Bind template (if plan_ref is a TemplatePlan name) with resolved inputs + global_params
     c. Create Page via `SessionManager.new_page(node.session)`
     d. Wrap in `PageDriver`
     e. Call `execute_plan_steps(driver, plan)`
     f. Store result in `node_results[node.id]`
     g. Persist checkpoint
     h. Call `SessionManager.close_if_last(node.session, node.id)`
- Implement input resolution: `"node_id.field"` → `node_results[node_id].extracted_data[field]`
  - `"node_id.field[N]"` → list index
  - `"node_id.field[*]"` → fan-out (clone dependent node per item)
- Implement fan-out: `asyncio.Semaphore(concurrency)` for bounded parallelism
- Implement error handling per node: abort, skip, retry
- Implement checkpoint persistence and resumption
- Write unit and integration tests

**NOT in scope**: Multiple concurrent fan-outs on shared session (sequential within session)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/flow_executor.py` | CREATE | FlowExecutor class |
| `packages/ai-parrot-tools/tests/scraping/test_flow_executor.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.executor import execute_plan_steps  # executor.py:41
from parrot_tools.scraping.plan import ScrapingPlan  # plan.py:59
from parrot_tools.scraping.models import ScrapingResult  # models.py:834
from parrot_tools.scraping.template_plan import TemplatePlan  # TASK-1448
from parrot_tools.scraping.flow_models import ScrapingFlow, FlowNode, FlowResult  # TASK-1449
from parrot_tools.scraping.drivers.page_driver import PageDriver  # TASK-1450
from parrot_tools.scraping.session_manager import SessionManager  # TASK-1451
from parrot_tools.scraping.base_registry import BasePlanRegistry  # base_registry.py
from parrot_tools.scraping.toolkit_models import DriverConfig  # toolkit_models.py:15
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def execute_plan_steps(  # line 41
    driver: AbstractDriver,
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult: ...

@dataclass
class ScrapingResult:  # models.py:834
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None

# BasePlanRegistry.get_by_name(name) -> Optional[PlanRegistryEntry]  # base_registry.py:151
```

### Does NOT Exist
- ~~`parrot_tools.scraping.flow_executor`~~ — this is what you're creating
- ~~`CrawlEngine.checkpoint()`~~ — no checkpoint mechanism exists anywhere
- ~~`execute_plan_steps` handling fan-out~~ — fan-out is FlowExecutor's responsibility

---

## Implementation Notes

### Input resolution grammar
```python
def resolve_input(ref: str, node_results: Dict[str, ScrapingResult]) -> Any:
    # "node_id.field" → node_results[node_id].extracted_data[field]
    # "node_id.field[N]" → node_results[node_id].extracted_data[field][N]
    # "node_id.field[*]" → returns full list for fan-out
    parts = ref.split(".", 1)
    node_id, field_ref = parts[0], parts[1]
    # ... parse field_ref for optional [N] or [*] suffix
```

### Fan-out pattern (from CrawlEngine)
```python
semaphore = asyncio.Semaphore(self._concurrency)
async def bounded_execute(item):
    async with semaphore:
        return await self._execute_node(item)
results = await asyncio.gather(*[bounded_execute(i) for i in fan_items], return_exceptions=True)
```

### Checkpoint persistence
```python
# After each node completes:
checkpoint = {node_id: result.extracted_data for node_id, result in self._node_results.items()}
checkpoint_path = self._checkpoint_dir / f"{flow.name}_{run_id}.json"
async with aiofiles.open(checkpoint_path, "w") as f:
    await f.write(json.dumps(checkpoint))
```

### Key Constraints
- Fan-out within a session is sequential (deferred debt)
- Retry creates a fresh Page (close old one, new_page)
- Skip cascades: if node A is skipped, dependent nodes whose required inputs come from A are also skipped

---

## Acceptance Criteria

- [ ] Simple linear flow (A → B) executes correctly
- [ ] Input resolution passes data between nodes
- [ ] Fan-out `[*]` clones dependent node per list item
- [ ] Fan-out uses bounded concurrency (Semaphore)
- [ ] `on_error="abort"` stops the flow
- [ ] `on_error="skip"` continues, cascades skip to dependents
- [ ] `on_error="retry"` retries with fresh Page up to max_retries
- [ ] Checkpoint saved after each node
- [ ] Resume from checkpoint skips completed nodes
- [ ] Multi-session flow creates distinct BrowserContexts
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_flow_executor.py -v`

---

## Completion Note

*(Agent fills this in when done)*
