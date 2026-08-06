# TASK-2183: PlanPlanner — objective mode planner client with one repair round

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2179, TASK-2182
**Assigned-to**: unassigned

---

## Context

`objective` mode: the agent says "do X" and the toolkit's internal planner —
a dedicated LLM call with structured output — authors the `ExecutionPlan`
once. The plan schema (~2.9K tokens) lives in the planner's request, not in
the agent's tool prompt. If validation fails, exactly ONE repair round
re-prompts with the `ValidationReport` (whose messages are written for a
planner model to correct from), then gives up. Implements spec §3 Module 4.

---

## Scope

- Implement `parrot/tools/execution_plan/planner.py`:
  - `resolve_planner_client(planner_llm) -> AbstractClient`: accept
    `"provider:model"` string | `AbstractClient` class or instance |
    model_config dict — mirror `ModelSwitchingMixin`'s `secondary_llm`
    resolution logic (READ that mixin first and reuse/adapt its resolution
    path; if it exposes a reusable helper, call it instead of copying).
  - `PlanPlanner` with `__init__(planner_llm, catalog:
    list[ToolCatalogEntry])`, `async author(objective: str) ->
    ExecutionPlan`, `async repair(plan_json: dict, report:
    ValidationReport) -> ExecutionPlan`.
  - Prompt construction: system prompt with the planning rules (tool-only
    nodes, `store_as` key discipline, the three runtime placeholder
    families, `{artifacts.<id>}` only in `for_each.source`/args) + the
    rendered catalog + the JSON Schema from
    `ExecutionPlan.model_json_schema()` as the structured-output contract.
  - Output handling: parse/validate the model's JSON into `ExecutionPlan`
    via `model_validate`; a Pydantic error counts as a failed round (its
    message feeds the repair prompt just like a `ValidationReport`).
- No implicit default model: `PlanPlanner` is only constructed when
  `planner_llm` was configured; resolution errors are structural
  (`ValueError` with the accepted formats named).
- Unit tests use a canned client double — NO network, NO real provider.

**NOT in scope**: the acquire→validate→execute orchestration and when
repair is invoked (TASK-2184 owns the loop; this task provides
`author`/`repair` as building blocks), catalog construction (TASK-2182).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/planner.py` | CREATE | `PlanPlanner` + client resolution |
| `packages/ai-parrot/tests/tools/execution_plan/test_planner.py` | CREATE | Unit tests with client double |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import ExecutionPlan          # after TASK-2179
from parrot.bots.flows.plan.validator import ValidationReport
from .catalog import ToolCatalogEntry                     # after TASK-2182
# AbstractClient base — verify the exact import used by
# parrot/bots/mixins/model_switching.py and mirror it.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/mixins/model_switching.py
secondary_llm: Union[str, dict, AbstractClient, None] = None   # :92
# ^ THE reference for accepted planner_llm formats. Read how this mixin
#   resolves each format into a live client (same file) and reuse that
#   logic. Do not invent a new format.

# parrot/bots/flows/plan/models.py (landed by TASK-2179)
class ExecutionPlan(BaseModel):   # :272 — model_json_schema() is the
#   structured-output contract; verified byte-equivalent to
#   sdd/artifacts/execution_plan.schema.json.

# parrot/bots/flows/plan/validator.py
class ValidationReport:   # :70 — str(report) yields one issue per line,
#   already phrased for planner self-correction; embed it verbatim in the
#   repair prompt.
```

### Does NOT Exist
- ~~a default planner model~~ — no `"anthropic:claude-…"` fallback
  anywhere; unset `planner_llm` means objective mode is OFF (enforced by
  TASK-2184, but this module must not add a default either).
- ~~multi-round repair~~ — `repair()` exists as ONE building block;
  callers invoke it at most once (spec: 1 authoring + ≤1 repair).
- ~~provider-specific structured-output APIs assumed on AbstractClient~~ —
  verify what the resolved client actually exposes (e.g. `ask()` kwargs)
  before using it; if native structured output is not uniformly available,
  embed the schema in the prompt and parse the JSON response, validating
  with `model_validate`. Do NOT call provider SDKs directly.
- ~~`agent.add_system_prompt()`~~ — does not exist anywhere; irrelevant
  here (the planner builds its own request).

---

## Implementation Notes

### Key Constraints
- One LLM call per `author()` / per `repair()` — no internal retry loops
  beyond what the client itself does.
- Prompt size discipline: catalog entries use the bounded `args_summary`
  from TASK-2182; never dump full tool JSON schemas.
- Deterministic-friendly: planner temperature/thinking config comes from
  the resolved client config; do not hardcode sampling params here beyond
  passing through what `planner_llm` dict/instance specifies.
- Log (INFO) objective length, catalog size, and round outcome — never the
  full prompt at INFO (DEBUG only).

### References in Codebase
- `parrot/bots/mixins/model_switching.py` — client resolution reference.
- `parrot/rerankers/` (llm reranker, ships from ai-parrot-embeddings) —
  precedent for an LLM inside a non-agent component, if present in the
  installed tree.

---

## Acceptance Criteria

- [ ] `resolve_planner_client` accepts string / instance / class / dict;
  anything else raises `ValueError` naming the accepted formats
- [ ] `author()` returns a validated `ExecutionPlan` from a canned
  well-formed response; malformed JSON or schema-invalid plan raises a
  typed error carrying the parse/validation detail
- [ ] `repair()` prompt contains the `ValidationReport` text verbatim and
  returns the corrected plan from the double
- [ ] Exactly one client call per author/repair invocation (asserted on
  the double)
- [ ] No default model constant anywhere in the module
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/execution_plan/test_planner.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_planner.py
@pytest.fixture
def canned_client():
    """AbstractClient double returning scripted responses:
    valid-plan JSON | invalid-then-valid | garbage."""

class TestResolvePlannerClient:
    def test_provider_model_string(...): ...
    def test_instance_passthrough(...): ...
    def test_dict_config(...): ...
    def test_invalid_format_raises(...): ...

class TestPlanPlanner:
    async def test_author_valid_plan(...): ...
    async def test_author_invalid_json_raises_typed(...): ...
    async def test_repair_embeds_report_and_returns_plan(...): ...
    async def test_single_call_per_round(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2179 and TASK-2182 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — especially the ModelSwitchingMixin
   resolution path and what the resolved client's ask/completion surface
   actually looks like
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
