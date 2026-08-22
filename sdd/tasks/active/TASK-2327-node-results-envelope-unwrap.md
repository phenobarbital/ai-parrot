# TASK-2327: Envelope-aware `FlowResult.node_results` + document the `output` shape contract

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3) and the read side of **G4**.

`FlowResult.node_results` (`core/result.py:439`) unwraps each stored response
via `hasattr(resp, "output")` (`core/result.py:445`). AgentsFlow's `responses`
dict holds the **envelope dicts** returned by `AgentNode.execute()`
(`core/node.py:321-325`), and `hasattr({...}, "output")` is `False` — so flow
callers get the whole `{"response": ..., "output": ..., "prompt": ...}`
mapping where crew callers get the scalar answer. The public
`agent_results` alias (`core/result.py:492`) inherits the same defect.

Separately, `FlowResult.output` has an undocumented polymorphic contract —
scalar when the run has a single leaf, `dict[node_id, Any]` on a fan-out
(`flow/flow.py:1028-1046`). The decision on FEAT-447 was to **keep** that
polymorphism and pin it in docs and tests rather than change or duplicate it
(spec §8 Q2, Non-Goals). This task writes the documentation half; TASK-2328
writes the `_aggregate_result` docstring half and the two contract tests.

Logically independent of TASK-2326, but it edits the SAME file
(`core/result.py`), so it cannot run in a parallel worktree.

---

## Scope

- Make `FlowResult.node_results` (`core/result.py:439`) envelope-aware: when a
  stored response is a `dict` containing an `"output"` key, return
  `resp["output"]`. Preserve today's behaviour for every other shape
  (`None` → `None`; object with `.output` → `resp.output`; else `resp`).
- Document the `output` scalar-vs-dict contract in the docstrings of:
  - the `output` field (`core/result.py:368`),
  - the `content` property (`core/result.py:424`),
  - the `final_result` property (`core/result.py:429`).
- Add the 2 unit tests below.

**NOT in scope**:
- `_unwrap_response` / `build_node_metadata` — that is TASK-2326.
- `_aggregate_result`'s docstring and the two `test_output_*` contract tests —
  those are TASK-2328 (they live in `flow/flow.py`'s test surface).
- **Changing `output`'s polymorphism, or adding an `outputs` field.**
  Explicitly rejected (spec Non-Goals). Document it; do not "improve" it.
- Changing what `FlowResult.responses` stores. Whether it should hold
  unwrapped `AgentResponse` objects is an OPEN question (spec §8) — status
  quo (raw envelopes) is the default, and `node_results` unwrapping on read
  is precisely what makes the status quo acceptable.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/result.py` | MODIFY | Envelope-aware `node_results`; contract docstrings |
| `packages/ai-parrot/tests/test_flow_primitives/test_result.py` | MODIFY | Add the 2 unit tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22. Re-`grep -n` before
> relying on any line number — TASK-2326 may have shifted this file.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:353
from parrot.bots.flows.core.result import FlowResult
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                              # line 353
    output: Any                                # line 368  ← DOCUMENT the contract
    responses: Dict[str, Any] = {}             # line 371  ← holds ENVELOPES for flows
    summary: str = ""                          # line 374
    nodes: List[NodeExecutionInfo] = []        # line 377
    execution_log: List[Dict[str, Any]] = []   # line 380
    total_time: float = 0.0                    # line 383
    status: FlowStatus = FlowStatus.COMPLETED   # line 386
    errors: Dict[str, str] = {}                # line 389
    metadata: Dict[str, Any] = {}              # line 392

    @property
    def content(self) -> Optional[Any]: ...    # line 424  ← alias for output
    @property
    def final_result(self) -> Optional[Any]: ...  # line 429  ← alias for output
    @property
    def node_results(self) -> Dict[str, Any]: ...  # line 439  ← THE BUG
        # for node_id, resp in self.responses.items():   @442
        #     if resp is None:            → None         @443-444
        #     elif hasattr(resp, "output") → resp.output  @445-446  ← dicts miss this
        #     else:                        → resp         @447-448
    @property
    def agent_results(self) -> Dict[str, Any]: ...  # line 492  ← alias, inherits fix
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:321-325
# The envelope shape node_results must unwrap:
{"response": <AgentResponse>, "output": <Any>, "execution_time": <float>, "prompt": <str>}
```

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py — REFERENCE ONLY, DO NOT EDIT
# The output contract you are documenting, as implemented today:
#   leaf detection                       @999-1026
#   if len(leaves) == 1 and in results:  @1028  → scalar (unwraps dict["output"] @1033)
#   else: multi-leaf fan-out             @1038  → dict[node_id, scalar] @1040-1046
```

### Does NOT Exist

- ~~`FlowResult.outputs`~~ (plural) — no such field. FEAT-447 explicitly does
  NOT add one (spec §8 Q2 resolved).
- ~~`FlowResult.node_outputs`~~ — not a property. It is `node_results` (line 439).
- ~~`FlowResult.get_output(node_id)`~~ — no such method. Use `node_results[node_id]`
  or `__getitem__` (`core/result.py:498`).
- ~~`FlowResult.summary` being populated for AgentsFlow~~ — it stays `""` by
  design; `AgentsFlow` does not inherit `SynthesisMixin` (`flow/flow.py:11-12,217`).
- ~~`_unwrap_response`~~ — created by TASK-2326. If that task has landed you MAY
  reuse it, but `node_results` needs the `"output"` key, not the `"response"`
  key, so it is a DIFFERENT unwrap. Do not conflate the two.

---

## Implementation Notes

### Pattern to Follow

```python
@property
def node_results(self) -> Dict[str, Any]:
    """Map node IDs to their scalar output values.

    Handles both response shapes stored by the two executors:

    * ``AgentCrew`` stores ``AgentResponse`` objects → read ``.output``.
    * ``AgentsFlow`` stores ``AgentNode.execute()`` envelope dicts
      (``{"response", "output", "execution_time", "prompt"}``) → read
      the ``"output"`` key.

    Returns:
        Mapping of node_id → scalar output (never an envelope dict).
    """
```

### Key Constraints

- Order the branches so the envelope check runs BEFORE the generic
  `hasattr(resp, "output")` check only if needed — a `dict` has no `.output`
  attribute, so either order works, but be explicit and add a comment.
- Do not mutate `self.responses`. `node_results` is a read-only projection.
- The docstring you add to `output` is the normative statement of the contract
  for the whole feature — make it unambiguous about WHEN each shape appears
  (single executed leaf vs. fan-out), and reference `_aggregate_result`.
- Additive only: no field added, retyped, or removed (spec G6 / AC11).

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:1964` —
  `context.mark_completed(agent_id, result=result, response=response)`, i.e.
  why crew's `responses` hold bare `AgentResponse` objects and flows' do not.

---

## Acceptance Criteria

- [ ] `node_results` returns scalar outputs for AgentsFlow runs; no value is an envelope dict (spec AC8)
- [ ] `node_results` behaviour for `AgentResponse` / `None` / plain values is UNCHANGED
- [ ] `agent_results` alias returns the same corrected values
- [ ] The `output` scalar-vs-dict contract is documented on the `output` field and both aliases (spec AC9, docs half)
- [ ] Both unit tests pass: `pytest packages/ai-parrot/tests/test_flow_primitives/test_result.py -v`
- [ ] Crew regression suites green: `pytest packages/ai-parrot/tests/test_crew_sequential_regression.py packages/ai-parrot/tests/test_crew_parallel_regression.py packages/ai-parrot/tests/test_crew_final_regression.py -v`
- [ ] `ruff check` and `mypy` clean on `core/result.py` (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot/tests/test_flow_primitives/test_result.py

def test_node_results_unwraps_envelope():
    """A FlowResult whose responses hold AgentNode envelopes yields scalars."""
    result = FlowResult(
        output="x",
        responses={
            "n1": {"response": <AgentResponse>, "output": "answer-1",
                   "execution_time": 0.1, "prompt": "q"},
        },
    )
    assert result.node_results == {"n1": "answer-1"}
    assert result.agent_results == {"n1": "answer-1"}   # alias inherits the fix


def test_node_results_crew_shape_unchanged(agent_response_with_usage):
    """AgentResponse responses still unwrap via .output; None stays None."""
    result = FlowResult(
        output="x",
        responses={"a1": agent_response_with_usage, "a2": None, "a3": "plain"},
    )
    assert result.node_results["a1"] == agent_response_with_usage.output
    assert result.node_results["a2"] is None
    assert result.node_results["a3"] == "plain"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§2 Layer 3, §6)
2. **Check dependencies** — none. If TASK-2326 already landed, re-`grep -n` this file: its line numbers have shifted.
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** every acceptance criterion
7. **Move this file** to `sdd/tasks/completed/TASK-2327-node-results-envelope-unwrap.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
