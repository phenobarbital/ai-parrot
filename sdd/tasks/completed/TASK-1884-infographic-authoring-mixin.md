# TASK-1884: InfographicAuthoringMixin — tier-1 authoring API

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1882, TASK-1883
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-326. A **cooperative mixin** (spec G-1; pattern of
`parrot/bots/mixins/model_switching.py`) composable onto `PandasAgent` and any
`DatasetManager`-bearing agent: `class MyAgent(InfographicAuthoringMixin, PandasAgent)`. It
wires a pre-configured `InfographicToolkit` into the agent and adds the tier-1 authoring flow:
validate descriptor → build section datasets via the agent's REPL → render → persist → return
a `ProvenanceDescriptor` (datasets/params/mapping + snapshot timestamps, **no python code**).

---

## Scope

- Implement `parrot/bots/mixins/infographic_authoring.py` with `InfographicAuthoringMixin`:
  - `__init__` kwargs to receive/construct the `InfographicToolkit` (accept a pre-built
    toolkit instance OR the pieces: `artifact_store`, `recipe_store`, `template_dirs`) and
    register its tools on the agent (study how `PandasAgent`/`AbstractBot` attach toolkits).
  - `async def generate_infographic(self, template, descriptor, params=None) ->
    tuple[InfographicRenderResult, ProvenanceDescriptor]` — tier-1 flow per spec §2.
  - System-prompt affordance: inject descriptor/section guidance the same cooperative way
    `IntentRouterMixin`/`ModelSwitchingMixin` hook `create_system_prompt`/`get_client` —
    do NOT override methods non-cooperatively.
- MRO safety: composing with `PandasAgent(IntentRouterMixin, BasicAgent)` must not break
  intent routing (test asserts).
- Export from `parrot/bots/mixins/__init__.py` (match existing export style).
- Unit tests (mock LLM/REPL — no live model calls).

**NOT in scope**: `publish_recipe` / recipe mapping (TASK-1885), system account (TASK-1886),
e2e with real CSVs (TASK-1887).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py` | CREATE | The mixin (tier-1 only) |
| `packages/ai-parrot/src/parrot/bots/mixins/__init__.py` | MODIFY | Export `InfographicAuthoringMixin` |
| `packages/ai-parrot/tests/unit/bots/test_infographic_authoring_mixin.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_sections import (       # created by TASK-1882
    SectionDescriptor, ProvenanceDescriptor,
)
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult
# infographic_toolkit.py:144 / :124
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgent(IntentRouterMixin, BasicAgent):                 # line 354
    def attach_dm(self, dm: DatasetManager) -> None: ...          # line 475
    def add_dataframe(self, name, df, metadata=None, ...) -> str: # line 2224
    def list_dataframes(self) -> Dict[str, Dict[str, Any]]: ...
    # ask() forces PythonPandasTool — the REPL used to build section datasets.

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:144
class InfographicToolkit(AbstractToolkit):
    def __init__(self, *, artifact_store, template_dirs=None, templates=None,
                 emit_a2ui=False, recipe_store=None, recipe_runner=None,
                 dataset_manager=None, **kwargs) -> None: ...     # line 177
    def set_bot(self, bot: Any) -> None: ...   # bind toolkit to the agent (enhance-mode support)
    def get_tools(self, **kwargs): ...
    async def render_data_template(...): ...   # created by TASK-1883

# Mixin pattern anchors (read BEFORE implementing):
# parrot/bots/mixins/model_switching.py — cooperative get_client()/execute_llm_call() hooks
# parrot/bots/mixins/intent_router.py — coexisting mixin whose behavior must survive
```

### Does NOT Exist
- ~~`InfographicAuthoringMixin`~~ — created HERE.
- ~~`DataInfographicAgent`~~ — deliberately NOT created (spec Non-Goal); ship the mixin only.
- ~~`PandasAgent.generate_infographic`~~ — does not exist on the base class; only via the mixin.
- ~~`AbstractBot.add_toolkit()`~~ — VERIFY the actual toolkit-attachment mechanism in
  `parrot/bots/` before use; do not assume this name `(unverified — check before use)`.

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/bots/mixins/model_switching.py structure:
#  - plain class (no AbstractToolkit/BaseModel inheritance)
#  - __init__(self, *args, <own kwargs>, **kwargs) -> super().__init__(*args, **kwargs)
#  - cooperative hooks, never hard overrides
class InfographicAuthoringMixin:
    def __init__(self, *args, infographic_toolkit=None, artifact_store=None,
                 recipe_store=None, template_dirs=None, **kwargs):
        super().__init__(*args, **kwargs)
        ...
```

### Key Constraints
- Async throughout; Pydantic models come from TASK-1882 — do not redefine them.
- `ProvenanceDescriptor` construction: snapshot timestamps from the DatasetManager entries
  actually used; tier="one-shot"; NEVER include REPL code (resolved brainstorm decision).
- Validation gate (TASK-1882) runs BEFORE any REPL/LLM work when the descriptor already
  declares its datasets; deficits surface to the caller for remediation
  (`add_query`/`refresh_data`).
- `self.logger` on the composed agent for lifecycle logging.

### References in Codebase
- `parrot/bots/mixins/model_switching.py` — THE pattern to mirror
- `parrot/bots/data.py:354-520` — agent init/configure flow the mixin must survive

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_infographic_authoring_mixin.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
- [ ] Imports work: `from parrot.bots.mixins import InfographicAuthoringMixin`
- [ ] MRO test: `class _T(InfographicAuthoringMixin, PandasAgent)` instantiates; intent-router
  behavior unaffected
- [ ] `generate_infographic` returns `(InfographicRenderResult, ProvenanceDescriptor)`;
  provenance contains no code
- [ ] Unmet descriptor → structured validation error BEFORE any render/persist

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_infographic_authoring_mixin.py
class TestMixinComposition:
    def test_mro_cooperative_with_pandas_agent(self): ...
    def test_toolkit_tools_registered_on_agent(self): ...

class TestGenerateInfographic:
    async def test_returns_result_and_provenance(self, mocked_agent): ...
    async def test_provenance_has_no_code(self, mocked_agent): ...
    async def test_validation_gate_blocks_before_render(self, mocked_agent): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1882, TASK-1883 in `completed/`);
3. **Verify the Codebase Contract** (especially the toolkit-attachment mechanism marked
unverified); 4. **Update index** → `"in-progress"`; 5. **Implement**; 6. **Verify criteria**;
7. **Move file to completed/**; 8. **Update index** → `"done"`; 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-24
**Notes**: Created `parrot/bots/mixins/infographic_authoring.py` with
`InfographicAuthoringMixin` — a cooperative plain-class mixin mirroring
`model_switching.py`. `__init__(*args, infographic_toolkit=None,
artifact_store=None, recipe_store=None, template_dirs=None, **kwargs)` builds
(or accepts) an `InfographicToolkit`, appends the toolkit **instance** to the
`tools=` kwarg (verified: `interfaces/tools.py:_initialize_tools` registers a
toolkit instance via `register_toolkit`), chains `super().__init__`, then calls
`toolkit.set_bot(self)`. A cooperative `configure(*args, **kwargs)` override
re-runs `set_bot` (idempotent prompt-guidance injection) before
`super().configure()`. `generate_infographic(template, descriptor, params)`
coerces a JSON-string descriptor, runs `validate_descriptor_datasets` fail-fast
BEFORE any build/render, builds the payload via the overridable
`_build_section_payload` seam, renders through `render_data_template` (data-splice)
or `render_template` (jinja), and returns `(InfographicRenderResult,
ProvenanceDescriptor)` with `tier="one-shot"` and NO code. Exported from
`mixins/__init__.py`. 7 tests pass (MRO cooperative with PandasAgent +
IntentRouterMixin intact; tools registered; provenance has no code; gate blocks
before render); ruff clean.

**Deviations from spec**: none. The REPL "build" step is exposed as the
`_build_section_payload` hook with a deterministic default (shapes declared
datasets/columns per `SectionSpec.shape`); conversational authoring drives the
agent's registered pandas REPL tools. Unit tests mock this seam and the toolkit
(no live LLM), per the task's "mock LLM/REPL" instruction.
