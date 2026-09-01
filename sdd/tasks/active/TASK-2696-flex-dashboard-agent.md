# TASK-2696: FlexDashboard agent class (datasets, toolkits, kb wiring)

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2694, TASK-2695
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The agent itself — mirroring `agents/finance_reporter.py`
(FEAT-420) structurally: mixin composition, `register_datasets()` +
`configure()` override, `skill_paths` anchored to the file's own location.
Adds this feature's specifics: six `query_slug` datasets, WorkingMemory +
Infographic toolkits, `use_kb=True` with the TASK-2695 docs, and
`output_routing=True`.

---

## Scope

- Implement `agents/flex_dashboard.py`:
  - `@register_agent(name="flex_dashboard")`
  - `class FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)`
    with `agent_id = "flex_dashboard"`, `narrative_skill = "flex-narrative"`,
    `skill_paths = [Path(__file__).resolve().parent / "flex_dashboard" / "skills"]`,
    `DASHBOARD_RECIPE_NAME = "flex-program-dashboard"`.
  - `__init__`: pass `output_routing=True` and attach `WorkingMemoryToolkit`
    + `InfographicToolkit` via the `tools=` list; `use_kb=True`.
  - `async def register_datasets(self)`: six
    `self._dataset_manager.add_dataset(name=<alias>, query_slug=<slug>,
    description=…, usage_guidance=…)` calls using the FROZEN aliases from
    spec §2 (`msl`, `finance`, `hours`, `employees`, `region_utilization`,
    `rep_utilization`). Lazy — no fetch at construction.
  - `async def _load_kb_docs(self)`: read `agents/flex_dashboard/kb/*.md`
    and `await self.kb_store.add_facts([...])` with
    `{"content": <text>, "metadata": {"category": "kpi", "kpi": <stem>}}`.
  - `async def configure(self, app=None, queries=None)`: call
    `register_datasets()`, then `super().configure(...)`, then
    `_load_kb_docs()` (kb_store exists once `use_kb=True` __init__ ran).
  - Import `agents/flex_dashboard/transformers.py` at module import so
    transformers register (decorator side effect).
- Unit tests: `test_agent_datasets` (six aliases, source kind `query_slug`),
  `test_kb_docs_loaded`, plus a mixin-order test mirroring
  `test_narrative_mixin_composed_first`.

**NOT in scope**: descriptor + refresh tool (TASK-2697), skills content
(TASK-2698), example runner (TASK-2699).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard.py` | CREATE | agent class |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_agent.py` | CREATE | unit tests (no network/DB) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.data import PandasAgent                    # verified: agents/finance_reporter.py:41
from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin  # verified: agents/finance_reporter.py:42
from parrot.registry import register_agent                  # verified: agents/finance_reporter.py:44
from parrot.tools.working_memory import WorkingMemoryToolkit  # verified: working_memory/__init__.py:2; agents/porygon.py:9
from parrot.tools.infographic_toolkit import InfographicToolkit  # verified: examples/simple_infographic_agent.py:102
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):           # line 379
    def __init__(self, name="Pandas Agent", ..., tools: List[AbstractTool] = None,
                 df=None, query=None, ..., output_routing: bool = False, **kwargs)  # line 406
    # __init__ ALWAYS creates self._dataset_manager = DatasetManager()  (line 459)
    async def configure(self, ...)                          # line 874 — accepts queries kwarg

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                      # line 501
    async def add_dataset(self, name, ..., query_slug=None, ...,
                          permanent_filter=None, ...)       # line 966
    # exactly ONE of query_slug / query / table / dataframe (lines 1031-1037)

# packages/ai-parrot/src/parrot/bots/abstract.py  (AbstractBot — PandasAgent base)
#   __init__ kwargs: use_kb: bool = False (line 287), local_kb (line 288),
#   kb=[...] → self._kb (line 555); use_kb=True builds self.kb_store =
#   KnowledgeBaseStore(kb_embedding_model=..., kb_dimension=...) (lines 560-565)
#   configure_kb() → await self.kb_store.add_facts(self._kb) (lines 1453-1458)

# packages/ai-parrot/src/parrot/stores/kb/store.py
class KnowledgeBaseStore:
    async def add_facts(self, facts: List[Dict[str, Any]])  # line 99 — "content" key required

# Pattern anchor — agents/finance_reporter.py
@register_agent(name="finance_reporter")                    # line 85
class FinanceReporter(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):  # line 86
    skill_paths: List[Path] = [SKILLS_DIR]                  # line 96 (anchored to __file__, line 62)
    async def register_datasets(self) -> None: ...          # line 153
    async def configure(self, app=None, queries=None):      # line 179
        await self.register_datasets()
        await super().configure(app=app, queries=queries)
```

### Does NOT Exist
- ~~`DatasourceManager` / `DataSourceManager` / `DatasSourceManager`~~ — the
  real class is `DatasetManager`; the agent attribute is the PRIVATE
  `self._dataset_manager` (there is no public `datasource_manager`).
- ~~`PandasAgent(datasets=...)` kwarg~~ — datasets register via
  `self._dataset_manager.add_dataset(...)` in `configure()`, or `df=`/`query=`.
- ~~`add_dataset(slug=...)`~~ — the kwarg is `query_slug=`.
- ~~a kb frontmatter/doc loader in core~~ — `_load_kb_docs` reads files and
  builds fact dicts itself.
- ~~`local_kb=True` for this agent~~ — proposal U2 chose the file-based
  `use_kb` plane, not the pgvector local KB.

---

## Implementation Notes

### Key Constraints
- **agents/ is gitignored** (`/agents/` rule): commit with
  `git add -f agents/flex_dashboard.py agents/flex_dashboard/` — verify
  files are actually tracked before finishing (same pattern note as
  `test_finance_reporter_descriptors.py:10-14`).
- `skill_paths` must be anchored to `Path(__file__)`, never cwd
  (`finance_reporter.py:52-62` explains the FEAT-420 bug this avoids).
- Do NOT pass `template_dirs` to `InfographicToolkit` unless the directory
  is guaranteed to exist — it validates eagerly (finance_reporter.py:132-146).
- Tests: no network/DB — instantiation must succeed offline; dataset adds
  are lazy; kb embedding model lazy-loads on first `add_facts`, so mock or
  use a tiny model per existing kb tests (grep
  `packages/ai-parrot/tests` for `KnowledgeBaseStore` usage before writing).
- LLM default: follow FinanceReporter (`llm = "google:gemini-3.5-flash"`,
  overridable via kwarg).

### References in Codebase
- `agents/finance_reporter.py` — the structural template.
- `agents/porygon.py` — WorkingMemoryToolkit attachment precedent.

---

## Acceptance Criteria

- [ ] `FlexDashboard` loads by file path, registers as `flex_dashboard`,
      instantiates offline.
- [ ] Six aliases registered lazily with source kind `query_slug`
      (incl. `query_slug="Finance_results_bi"` verbatim capitalization).
- [ ] `use_kb=True`; configure loads one fact per kb doc.
- [ ] `output_routing=True`; WorkingMemory + Infographic toolkits attached.
- [ ] Mixin order: `NarrativeMixin, InfographicAuthoringMixin, PandasAgent`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_agent.py -v`
- [ ] `ruff check agents/flex_dashboard.py` clean; files force-added to git.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_agent.py
# Load agents/flex_dashboard.py by file path (importlib.util) — copy the
# _load_finance_reporter() helper from test_finance_reporter_descriptors.py.

async def test_agent_datasets(flex_agent):
    await flex_agent.register_datasets()
    entries = flex_agent._dataset_manager  # inspect registered entries
    # six aliases present, each with source kind "query_slug"

async def test_kb_docs_loaded(flex_agent):
    ...  # after configure/_load_kb_docs: one fact per agents/flex_dashboard/kb/*.md

def test_mixin_order():
    from parrot.bots.mixins import InfographicAuthoringMixin, NarrativeMixin
    assert FlexDashboard.__mro__.index(NarrativeMixin) < FlexDashboard.__mro__.index(InfographicAuthoringMixin)
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2694 and TASK-2695 must be in `sdd/tasks/completed/`
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
