# TASK-2330: Crew/flow `FlowResult` parity contract test

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2326, TASK-2327, TASK-2328, TASK-2329
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (§3) and is the regression guard for
**G5** — the goal that the two executors cannot silently drift apart again.

FEAT-447 exists because `AgentCrew` and `AgentsFlow` return the *same*
`FlowResult` dataclass but populate it to wildly different degrees, and
nothing in the test suite noticed. Tasks 2326-2329 close today's gap; this
task makes tomorrow's gap fail CI.

The test asserts **field-population parity**: run equivalent work through
both executors and assert that the set of `FlowResult` fields left at their
dataclass defaults is the same for both, modulo one documented exemption —
`summary`, which AgentsFlow leaves empty by design because it does not
inherit `SynthesisMixin` (`flow/flow.py:11-12,217`).

---

## Scope

- Create `packages/ai-parrot/tests/bots/flows/test_result_fidelity.py`.
- Implement the parity test: the same mock agents driven through
  `AgentCrew` and through `AgentsFlow` produce `FlowResult`s whose
  **non-default field sets are equal**, excluding `summary`.
- Implement `NodeExecutionInfo`-level parity: for both executors, the same
  metadata fields are populated (`model`, `provider`, `usage`, `tool_calls`,
  `client`, `execution_time`, `status`).
- Implement the regression assertion that the existing flow suites are
  unchanged and passing (spec AC-level check, run as a documented command —
  not a test that shells out to pytest).
- Encode the exemption list as a module-level constant with a comment
  explaining WHY each entry is exempt, so a future exemption requires a
  deliberate edit.

**NOT in scope**:
- Any production-code change. This task is tests only. If the parity test
  fails, the fix belongs in TASK-2326/2328/2329 — report it, do not patch
  production code from here.
- Refactoring `AgentCrew`'s result-assembly paths (spec Non-Goals). Its eight
  `FlowResult(...)` call sites stay as they are.
- Asserting numeric equality of `total_time` between executors — they run
  different work. Assert *populated-ness*, not values.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/flows/test_result_fidelity.py` | CREATE | The parity contract test suite |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22. Tasks 2326-2329 will
> have shifted `core/result.py` and `flow/flow.py` — re-`grep -n` before use.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:270,353
from parrot.bots.flows.core.result import FlowResult, NodeExecutionInfo

# verified: packages/ai-parrot/src/parrot/bots/flows/core/context.py:55
from parrot.bots.flows.core.context import FlowContext

# verified: packages/ai-parrot/src/parrot/models/responses.py:72,1119
from parrot.models.responses import AIMessage, AgentResponse

# AgentsFlow — verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:217
# AgentCrew  — verified: packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
# CHECK packages/ai-parrot/src/parrot/bots/flows/__init__.py for the public
# import path before writing the import line — do NOT guess it.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                              # line 353
    output: Any                                # line 368
    responses: Dict[str, Any] = {}             # line 371
    summary: str = ""                          # line 374  ← THE ONE EXEMPTION
    nodes: List[NodeExecutionInfo] = []        # line 377
    execution_log: List[Dict[str, Any]] = []   # line 380
    total_time: float = 0.0                    # line 383
    status: FlowStatus = FlowStatus.COMPLETED   # line 386
    errors: Dict[str, str] = {}                # line 389
    metadata: Dict[str, Any] = {}              # line 392
    def to_dict(self) -> Dict[str, Any]: ...   # line 541

@dataclass
class NodeExecutionInfo:                       # line 270
    node_id: str                               # line 280
    node_name: str                             # line 283
    provider: Optional[str] = None             # line 286
    model: Optional[str] = None                # line 289
    execution_time: float = 0.0                # line 292
    tool_calls: List[Dict[str, Any]] = []      # line 295
    status: Literal[...] = "pending"           # line 298
    error: Optional[str] = None                # line 301
    client: Optional[str] = None               # line 304
    usage: Optional[Dict[str, Any]] = None     # line 307
    def to_dict(self) -> Dict[str, Any]: ...   # line 324
```

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                # line 72
    input: str; output: Any
    model: str; provider: str              # REQUIRED
    usage: CompletionUsage                 # REQUIRED — has .model_dump()
    tool_calls: List[ToolCall] = []

class AgentResponse(BaseModel):            # line 1119
    response: Optional[AIMessage]
    output: Optional[Any]
```

### Reference test files to mirror in style

```
packages/ai-parrot/tests/bots/flows/test_agents_flow.py    — AgentsFlow integration setup
packages/ai-parrot/tests/bots/flows/test_scheduler.py      — scheduler-level fixtures
packages/ai-parrot/tests/test_crew_sequential_regression.py — AgentCrew driving pattern
packages/ai-parrot/tests/conftest.py                        — shared fixtures
```

### Does NOT Exist

- ~~`FlowResult.is_complete()` / `.validate()` / `.assert_parity()`~~ — no such
  methods. Compare via `to_dict()` (`core/result.py:541`) or field access.
- ~~`FlowResult.outputs`~~ (plural) — no such field.
- ~~`NodeExecutionInfo.status == "skipped"`~~ — not a valid literal (line 298).
- ~~A shared `AbstractExecutor` base class for `AgentCrew`/`AgentsFlow`~~ —
  does not exist. `AgentsFlow(PersistenceMixin)` (`flow/flow.py:217`); the two
  classes share only `FlowResult` and `build_node_metadata`.
- ~~`AgentsFlow.summary` being populated~~ — it is not, by design. That is the
  exemption, not a bug to fix.

---

## Implementation Notes

### Pattern to Follow

```python
# Encode the exemption deliberately, so widening it requires an explicit edit.
PARITY_EXEMPT_FIELDS = frozenset({
    # AgentsFlow does NOT inherit SynthesisMixin (flow/flow.py:11-12, 217) —
    # synthesis is opt-in via the standalone synthesize_results util.
    # Leaving `summary` empty for flows is a design decision (FEAT-447 Non-Goals),
    # NOT a fidelity loss.
    "summary",
})


def _populated_fields(result: FlowResult) -> set[str]:
    """Field names whose value differs from the dataclass default."""
```

### Key Constraints

- **Use a real `CompletionUsage`, never a bare `MagicMock`**, in every fixture.
  `build_node_metadata` calls `usage_obj.model_dump()` (`core/result.py:670,679`),
  and a Mock returns a Mock — every assertion downstream becomes vacuous.
- Assert *populated-ness*, not equality of values. The two executors run
  different orchestration, so timings, node ids, and log contents differ.
- Give the failure messages teeth: on mismatch, print WHICH fields diverged and
  in which direction. A future engineer hitting this test should not have to
  read the test to understand the regression.
- Tests only. If parity fails, the bug is in TASK-2326/2328/2329 — report it in
  the Completion Note; do not patch production code from this task.
- Follow the async test conventions already used in
  `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` (pytest-asyncio).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:2079-2087` — the
  faithful crew reference the flow side is being held to.
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:955` —
  `_aggregate_result`, the flow side under test.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/bots/flows/test_result_fidelity.py` exists
- [ ] `test_flow_vs_crew_field_parity` passes: non-default `FlowResult` field sets are equal modulo `PARITY_EXEMPT_FIELDS` (spec AC-parity, G5)
- [ ] `NodeExecutionInfo` parity holds for `model`, `provider`, `usage`, `tool_calls`, `client`, `execution_time`, `status`
- [ ] `PARITY_EXEMPT_FIELDS` contains exactly `{"summary"}`, with the rationale in a comment
- [ ] Failure messages name the diverging fields and the direction of divergence
- [ ] Suite passes: `pytest packages/ai-parrot/tests/bots/flows/test_result_fidelity.py -v` (spec AC15)
- [ ] Full flow + crew suites green: `pytest packages/ai-parrot/tests/bots/flows/ packages/ai-parrot/tests/test_flow_primitives/ packages/ai-parrot/tests/flows/checkpoint/ packages/ai-parrot/tests/test_crew_sequential_regression.py packages/ai-parrot/tests/test_crew_parallel_regression.py packages/ai-parrot/tests/test_crew_final_regression.py -v` (spec AC13, AC14)
- [ ] `ruff check` clean on the new test file (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_result_fidelity.py

PARITY_EXEMPT_FIELDS = frozenset({"summary"})   # see Implementation Notes


async def test_flow_vs_crew_field_parity():
    """Same agents through AgentsFlow and AgentCrew populate the same
    FlowResult fields, modulo the documented `summary` exemption."""


async def test_node_execution_info_parity():
    """NodeExecutionInfo carries model/provider/usage/tool_calls/client for
    both executors."""


async def test_parity_exemptions_are_explicit():
    """PARITY_EXEMPT_FIELDS == {"summary"} — widening it must be deliberate."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§4, §5 AC15, G5)
2. **Check dependencies** — TASK-2326, 2327, 2328, 2329 MUST all be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code — confirm the public import path for `AgentsFlow`/`AgentCrew` in `packages/ai-parrot/src/parrot/bots/flows/__init__.py` rather than guessing
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope — tests only
6. **Verify** every acceptance criterion
7. **Move this file** to `sdd/tasks/completed/TASK-2330-crew-flow-parity-test.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Parity findings**: (any field that diverged and which upstream task owns the fix)

**Deviations from spec**: none | describe if any
