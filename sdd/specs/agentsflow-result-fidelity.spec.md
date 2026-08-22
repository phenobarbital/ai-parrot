---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow Result Fidelity

**Feature ID**: FEAT-447
**Date**: 2026-08-22
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.27.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentCrew` and `AgentsFlow` both return the same `FlowResult` dataclass
(`parrot/bots/flows/core/result.py:353`), and `FlowResult` is the documented,
public contract every consumer codes against — telemetry adapters,
`OutputFormatter`, persistence via `PersistenceMixin`, the dev-loop/dev-flow
runners, and user code reading `result.nodes[i].usage`.

`AgentCrew` populates that contract faithfully. **`AgentsFlow` does not.**
`AgentsFlow._aggregate_result()` (`flow/flow.py:955-1055`) silently drops most
of the run's information, and every loss below was verified against the source
on `dev` @ `49ef7b39`:

1. **All per-node LLM metadata is lost.** `AgentNode.execute()` returns an
   *envelope dict* — `{"response", "output", "execution_time", "prompt"}`
   (`core/node.py:321-325`). `_aggregate_result` forwards that envelope
   straight into `build_node_metadata(response=resp, ...)`
   (`flow/flow.py:988-996`), but `build_node_metadata` only unwraps
   `AgentResponse` / `AIMessage` instances (`core/result.py:654,671`). A plain
   `dict` falls through to the `elif response is not None:` branch
   (`core/result.py:680`), where `getattr(dict, "model", None)` is `None`.
   Net effect for **every node of every AgentsFlow run**: `usage is None`,
   `tool_calls == []`. Token accounting and tool-call auditing are impossible
   for flows, while identical crews report them correctly.
2. **Every run-level field stays at its dataclass default.** The
   `FlowResult(...)` call at `flow/flow.py:1051` passes only
   `output/nodes/responses/errors/status`, so `total_time == 0.0`,
   `execution_log == []`, `metadata == {}`. This is not a
   data-availability problem: `run_started_at` (`flow/flow.py:1436`) and
   `durations` (`flow/flow.py:1437,1840`) are in scope, and the
   `flow_completed` event three lines later already computes the exact
   wall-clock figure (`flow/flow.py:1934`) — it is emitted to listeners and
   then thrown away instead of being assigned to `total_time`. Consequently
   `FlowResult.__repr__` always prints `time=0.00s` (`core/result.py:414-418`)
   and the `total_execution_time` alias (`core/result.py:480`) always returns
   `0.0`. Compare `AgentCrew`, which sets all four
   (`crew/crew.py:2079-2087`).
3. **`FlowResult.nodes` ordering is nondeterministic.** `_aggregate_result`
   iterates `for nid in completed | failed` (`flow/flow.py:983`) — a *set
   union*. Execution order is discarded, and the surviving order varies with
   string hashing across processes, so `result.nodes` cannot be rendered as a
   run timeline and snapshot-style assertions over it are inherently flaky.
   `FlowContext.completion_order: List[str]` (`core/context.py:81`) already
   records the true order and is already maintained by `mark_completed`
   (`core/context.py:197`) — `_aggregate_result` simply never receives `ctx`.
4. **`node_results` returns envelopes instead of outputs.** The
   `FlowResult.node_results` property unwraps via `hasattr(resp, "output")`
   (`core/result.py:445`). AgentsFlow's `responses` dict holds envelope
   *dicts*, for which `hasattr` is `False`, so callers get the whole
   `{"response": ..., "output": ..., "prompt": ...}` mapping where crews give
   the scalar answer. The `agent_results` alias (`core/result.py:492`)
   inherits the same defect.
5. **`NodeExecutionInfo.client` is dead everywhere.** The field is declared
   (`core/result.py:307`) and serialised (`core/result.py:342`), but
   `build_node_metadata`'s constructor call (`core/result.py:698-708`) never
   passes it — so it is `None` for crews *and* flows.

The unifying cause is that `build_node_metadata` is a *shared* helper
(`core/result.py:619`) used by both executors, but it only understands the
shapes AgentCrew happens to pass. Fixing this inside the shared helper repairs
AgentsFlow and makes the two executors incapable of drifting apart again.

### Goals

- **G1** — Per-node LLM metadata (`model`, `provider`, `usage`, `tool_calls`,
  `client`) survives an AgentsFlow run with the same fidelity as an AgentCrew run.
- **G2** — `FlowResult.total_time`, `execution_log`, and `metadata` are
  populated by `AgentsFlow`, from data the scheduler already tracks.
- **G3** — `FlowResult.nodes` is ordered deterministically by actual
  completion order.
- **G4** — The `FlowResult.output` shape contract (scalar for a single leaf,
  `dict[node_id, Any]` for a fan-out) is pinned in docstrings and tests
  rather than left as undocumented emergent behaviour; `node_results`
  returns scalar outputs for both executors.
- **G5** — Envelope unwrapping lives in exactly **one** shared helper used by
  both executors, guarded by a contract test asserting field-population parity.
- **G6** — Strictly additive: no existing `FlowResult` /
  `NodeExecutionInfo` field changes type or meaning; no public signature
  loses a parameter.

### Non-Goals (explicitly out of scope)

- **Populating `FlowResult.summary` for AgentsFlow.** `AgentsFlow`
  deliberately does not inherit `SynthesisMixin` (`flow/flow.py:11-12,217`);
  synthesis stays opt-in via the standalone `synthesize_results` util. This
  spec leaves `summary == ""` and does not treat it as a fidelity loss.
- **Changing `output`'s scalar-vs-dict polymorphism**, or adding a parallel
  always-a-dict `outputs` field. Decided: document the existing contract, do
  not alter or duplicate it (§8 Q2).
- **Any breaking change** to `FlowResult`, `NodeExecutionInfo`, or
  `build_node_metadata` (§8 Q3).
- **Refactoring `AgentCrew`'s result-assembly paths.** Crew benefits
  automatically through the shared helper; its eight `FlowResult(...)` call
  sites are not rewritten.
- **Emitting `NodeExecutionInfo` entries for skipped nodes.**
  `NodeExecutionInfo.status` is a closed `Literal["completed", "failed",
  "pending", "running"]` (`core/result.py:298`); adding a `"skipped"` member
  would be a breaking widening. Skipped node IDs are surfaced through
  `metadata` instead (§2 Data Models).
- Retiring the now-legacy `parrot.models.crew.build_agent_metadata`
  (`models/crew.py:322`), which no flows/crew code path calls any more.

---

## 2. Architectural Design

### Overview

Three additive layers, deliberately ordered so the shared-helper fix lands
first and the executor-level fixes build on it.

**Layer 1 — `core/result.py`: teach the shared helper the envelope shape.**
Add a module-private `_unwrap_response(response)` that normalises any
node/agent return value to the structured object carrying LLM metadata:

- an envelope `dict` containing a `"response"` key → return `dict["response"]`
  (recursively, so a nested envelope resolves);
- anything else → return unchanged.

`build_node_metadata` calls it once at the top of its body, before the
existing `isinstance` ladder. AgentCrew passes `AgentResponse` objects
(`crew/crew.py:1968-1975`), which the helper returns untouched — so crew
behaviour is bit-identical, while AgentsFlow's envelopes now resolve to the
same `AgentResponse` the ladder already knows how to mine. The same call also
lets `build_node_metadata` populate the dead `client` field from the agent's
concrete client class name.

**Layer 2 — `flow/flow.py`: stop discarding what the scheduler measured.**
`_aggregate_result` gains three keyword-only, defaulted parameters — `ctx`,
`run_started_at`, `skipped` — and uses them to:

- order `node_infos` by `ctx.completion_order`, appending any node absent
  from that list (failures recorded via `mark_failed`, which does not append
  to `completion_order`) in sorted order for stability;
- set `total_time` from the run clock;
- build `execution_log` as one entry per node;
- build `metadata` with the run's mode and counts.

`run_flow` additionally passes `response=` to `ctx.mark_completed`
(`flow/flow.py:1881`) and stores the built `NodeExecutionInfo` into
`ctx.node_metadata`, so a `FlowContext` inspected after a run — including a
checkpointed/resumed one — carries the same fidelity as the `FlowResult`.
Both fields already exist and are already documented as populated
(`core/context.py:78,193-194`); only AgentsFlow neglects them.

**Layer 3 — `core/result.py`: unwrap envelopes on read, and pin the contract.**
`FlowResult.node_results` recognises the envelope dict and returns
`resp["output"]`. `FlowResult.output` and `_aggregate_result` gain docstrings
stating the scalar/dict contract verbatim, and tests lock it in both directions.

### Component Diagram

```
AgentNode.execute()                         AgentCrew._run_*()
  │ {"response": AgentResponse,               │ AgentResponse
  │  "output", "execution_time", "prompt"}    │
  └───────────────┬───────────────────────────┘
                  ▼
        _unwrap_response()            ← NEW (Layer 1, shared)
                  │  AgentResponse | AIMessage | Any
                  ▼
        build_node_metadata()         ← existing isinstance ladder, now reached
                  │  NodeExecutionInfo(model, provider, usage, tool_calls, client)
     ┌────────────┴────────────┐
     ▼                         ▼
AgentsFlow._aggregate_result()   AgentCrew  (unchanged — already faithful)
  │  + ctx / run_started_at / skipped        ← NEW (Layer 2)
  │  → ordered nodes, total_time,
  │    execution_log, metadata
  ▼
FlowResult ──→ node_results (envelope-aware)  ← NEW (Layer 3)
     └────────→ FlowContext.node_metadata / .responses  ← NEW (Layer 2)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `build_node_metadata` (`core/result.py:619`) | modifies | Prepends `_unwrap_response()`; passes `client=`. Sole shared seam (G5). |
| `FlowResult` (`core/result.py:353`) | populates | No field added or retyped; previously-default fields now carry values. |
| `FlowResult.node_results` (`core/result.py:439`) | modifies | Envelope-aware unwrap; `agent_results` alias inherits the fix. |
| `AgentsFlow._aggregate_result` (`flow/flow.py:955`) | extends | Three keyword-only defaulted params. |
| `AgentsFlow.run_flow` (`flow/flow.py:1059`) | modifies | Passes new args; enriches `ctx.mark_completed`. |
| `FlowContext` (`core/context.py:55`) | populates | `responses` + `node_metadata` filled by AgentsFlow. No schema change. |
| `AgentCrew` (`crew/crew.py`) | benefits | Untouched; gains `client` via the shared helper. |
| `FlowLifecycleAdapter` (`flow/telemetry.py:51`) | unaffected | Event payloads unchanged. |
| `PersistenceMixin` (`core/storage`) | benefits | Persisted results now carry timing/usage. |
| `FlowCheckpointer` (`core/checkpoint/`) | verify | `ctx.node_metadata` now non-empty → snapshot round-trip must stay serialisable. |

### Data Models

No new model. The **envelope** that Layer 1 normalises is an existing,
verified shape (`core/node.py:321-325`):

```python
# AgentNode.execute() return value — NOT a Pydantic model, a plain dict.
{
    "response": AgentResponse,   # carries model/provider/usage/tool_calls
    "output": Any,               # scalar answer
    "execution_time": float,     # node-measured seconds
    "prompt": str,
}
```

`FlowResult.metadata` keys written by `AgentsFlow` (new, additive):

```python
{
    "mode": str,            # "explicit" | "definition" | "legacy"
    "node_count": int,      # len(nodes) materialized
    "completed_count": int,
    "failed_count": int,
    "skipped": list[str],   # skipped node_ids (see Non-Goals)
    "leaves": list[str],    # node_ids that produced `output`
}
```

`FlowResult.execution_log` entry shape written by `AgentsFlow`, matching the
`list[dict]` type already declared (`core/result.py:380`):

```python
{
    "node_id": str,
    "node_name": str,
    "status": str,          # "completed" | "failed"
    "execution_time": float,
    "error": str | None,
}
```

### New Public Interfaces

None. The only signature change is additive and keyword-only:

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
def _aggregate_result(
    self,
    nodes: dict[str, Any],
    results: dict[str, Any],
    errors: dict[str, BaseException],
    completed: set[str],
    failed: set[str],
    edges: Optional[list[Any]] = None,
    durations: Optional[dict[str, float]] = None,
    *,
    ctx: Optional[FlowContext] = None,        # NEW — ordering source
    run_started_at: Optional[float] = None,   # NEW — total_time source
    skipped: Optional[set[str]] = None,       # NEW — metadata only
) -> FlowResult:
    ...
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
def _unwrap_response(response: Optional[Any]) -> Optional[Any]:
    """Normalise a node/agent return value to its metadata-bearing object."""
```

---

## 3. Module Breakdown

### Module 1: Shared envelope unwrapping
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/result.py`
- **Responsibility**: Add `_unwrap_response()`; call it at the top of
  `build_node_metadata` (before `core/result.py:645`); populate `client=` in
  the returned `NodeExecutionInfo`. Recursion-safe and depth-bounded.
- **Depends on**: nothing (leaf change). **Fixes G1, G5.**

### Module 2: Envelope-aware `node_results`
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/result.py`
- **Responsibility**: `FlowResult.node_results` (line 439) returns
  `resp["output"]` for envelope dicts; document the `output` scalar/dict
  contract on the `output` field and the `content`/`final_result` aliases.
- **Depends on**: nothing. **Fixes G4** (read side).

### Module 3: Faithful `_aggregate_result`
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: Add the three keyword-only params; order `node_infos`
  by `ctx.completion_order`; populate `total_time`, `execution_log`,
  `metadata`; docstring the leaf/output contract.
- **Depends on**: Module 1. **Fixes G2, G3, G4** (write side).

### Module 4: `run_flow` wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: Pass `ctx=ctx, run_started_at=run_started_at,
  skipped=skipped` at the `_aggregate_result` call (line 1926); pass
  `response=` at `ctx.mark_completed` (line 1881); write per-node
  `NodeExecutionInfo` into `ctx.node_metadata`.
- **Depends on**: Module 3.

### Module 5: Parity contract test
- **Path**: `packages/ai-parrot/tests/bots/flows/test_result_fidelity.py` (new)
- **Responsibility**: Assert an AgentsFlow run and an equivalent AgentCrew run
  populate the same `FlowResult`/`NodeExecutionInfo` fields — the regression
  guard that keeps the executors from drifting again.
- **Depends on**: Modules 1-4. **Fixes G5.**

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_unwrap_response_envelope` | 1 | `{"response": AgentResponse, ...}` → the `AgentResponse`. |
| `test_unwrap_response_passthrough` | 1 | `AgentResponse`, `AIMessage`, `str`, `None` returned unchanged. |
| `test_unwrap_response_nested_envelope` | 1 | Envelope wrapping an envelope resolves; bounded, no infinite recursion. |
| `test_unwrap_response_dict_without_response_key` | 1 | A plain `{"output": ...}` dict is NOT treated as an envelope. |
| `test_build_node_metadata_from_envelope` | 1 | Envelope input yields non-`None` `usage`, non-empty `tool_calls`, correct `model`/`provider`. |
| `test_build_node_metadata_crew_shape_unchanged` | 1 | Bare `AgentResponse` produces byte-identical `to_dict()` vs. pre-change baseline. |
| `test_build_node_metadata_sets_client` | 1 | `client` is the concrete client class name, not `None`. |
| `test_node_results_unwraps_envelope` | 2 | `node_results` returns scalar outputs, not envelope dicts. |
| `test_node_results_crew_shape_unchanged` | 2 | `AgentResponse` responses still unwrap via `.output`. |
| `test_aggregate_result_total_time` | 3 | `total_time > 0` and `≈ now - run_started_at`. |
| `test_aggregate_result_execution_log` | 3 | One entry per completed+failed node, with the documented keys. |
| `test_aggregate_result_metadata_keys` | 3 | All six `metadata` keys present and correctly valued. |
| `test_aggregate_result_node_order` | 3 | `[n.node_id for n in result.nodes]` matches `ctx.completion_order`. |
| `test_aggregate_result_failed_node_included` | 3 | A node failed via `mark_failed` (absent from `completion_order`) still appears. |
| `test_aggregate_result_backward_compatible_call` | 3 | Calling without the three new kwargs still returns a valid `FlowResult`. |
| `test_output_single_leaf_is_scalar` | 3 | Single leaf → scalar output (contract lock). |
| `test_output_multi_leaf_is_dict` | 3 | Fan-out → `dict[node_id, scalar]` (contract lock). |

### Integration Tests

| Test | Description |
|---|---|
| `test_flow_run_populates_usage` | End-to-end `run_flow` with a mock agent: every `result.nodes[i].usage` is non-`None`. |
| `test_flow_run_total_time_nonzero` | `repr(result)` no longer shows `time=0.00s`. |
| `test_flow_vs_crew_field_parity` | Same agents through `AgentsFlow` and `AgentCrew`: the set of non-default `FlowResult` fields is equal, modulo the documented `summary` exemption. |
| `test_flow_context_carries_metadata` | After `run_flow`, `ctx.responses` and `ctx.node_metadata` are populated. |
| `test_checkpoint_roundtrip_with_metadata` | `FlowContext.to_snapshot()` still round-trips with `node_metadata` non-empty. |
| `test_existing_flow_suites_green` | `test_scheduler.py`, `test_agents_flow.py`, `test_explicit_edges.py`, `test_flow_telemetry.py` unchanged and passing. |

### Test Data / Fixtures

```python
@pytest.fixture
def agent_response_with_usage():
    """AgentResponse whose AIMessage carries usage + tool_calls."""
    ...  # build via parrot.models.responses.AIMessage / AgentResponse

@pytest.fixture
def node_envelope(agent_response_with_usage):
    """The exact dict AgentNode.execute() returns (core/node.py:321)."""
    return {
        "response": agent_response_with_usage,
        "output": "answer",
        "execution_time": 0.42,
        "prompt": "q",
    }
```

---

## 5. Acceptance Criteria

- [ ] **AC1** — `_unwrap_response()` exists in `core/result.py`, is called by
  `build_node_metadata`, and is recursion-bounded.
- [ ] **AC2** — After an `AgentsFlow.run_flow()` with agents returning usage,
  every `NodeExecutionInfo` in `FlowResult.nodes` has `usage is not None`,
  and `tool_calls` matches the agent's tool calls.
- [ ] **AC3** — `NodeExecutionInfo.client` is populated (non-`None`) for both
  AgentsFlow and AgentCrew runs.
- [ ] **AC4** — `FlowResult.total_time > 0` after any non-empty
  `run_flow()`; `total_execution_time` and `__repr__` reflect it.
- [ ] **AC5** — `FlowResult.execution_log` has exactly one entry per
  completed-or-failed node, each with the five documented keys.
- [ ] **AC6** — `FlowResult.metadata` contains `mode`, `node_count`,
  `completed_count`, `failed_count`, `skipped`, `leaves`.
- [ ] **AC7** — `[n.node_id for n in result.nodes]` equals
  `ctx.completion_order` for all-successful runs, and is deterministic across
  repeated runs (verified with `PYTHONHASHSEED` varied).
- [ ] **AC8** — `FlowResult.node_results` returns scalar outputs for
  AgentsFlow runs; no value is an envelope dict.
- [ ] **AC9** — The `output` scalar-vs-dict contract is documented on the
  `output` field and on `_aggregate_result`, and locked by two tests.
- [ ] **AC10** — `ctx.responses` and `ctx.node_metadata` are non-empty after
  `run_flow()`.
- [ ] **AC11** — **Additive-only**: no `FlowResult` or `NodeExecutionInfo`
  field changed type or meaning; no existing parameter removed or reordered;
  `_aggregate_result` still callable with its pre-change argument list (AC
  covered by `test_aggregate_result_backward_compatible_call`).
- [ ] **AC12** — `FlowResult.summary` remains `""` for AgentsFlow (Non-Goal
  respected; no `SynthesisMixin` inheritance added).
- [ ] **AC13** — Crew regression suites pass untouched:
  `pytest packages/ai-parrot/tests/test_crew_sequential_regression.py packages/ai-parrot/tests/test_crew_parallel_regression.py packages/ai-parrot/tests/test_crew_final_regression.py -v`
- [ ] **AC14** — Flow suites pass:
  `pytest packages/ai-parrot/tests/bots/flows/ packages/ai-parrot/tests/test_flow_primitives/ packages/ai-parrot/tests/flows/checkpoint/ -v`
- [ ] **AC15** — New suite passes:
  `pytest packages/ai-parrot/tests/bots/flows/test_result_fidelity.py -v`
- [ ] **AC16** — `ruff check` and `mypy` clean on all changed files.
- [ ] **AC17** — `docs/architecture/07-agentcrew.md` documents the
  `FlowResult` fidelity contract and the `output` shape rule.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was read from
> source on branch `dev` @ `49ef7b39` on 2026-08-22. Line numbers WILL drift
> as the implementation edits these files — re-verify with `grep -n` before
> relying on a number, but treat the *names and shapes* as authoritative.

### Verified Imports

```python
# verified: packages/ai-parrot/src/parrot/bots/flows/core/__init__.py:38,72
from parrot.bots.flows.core import build_node_metadata

# verified: packages/ai-parrot/src/parrot/bots/flows/core/result.py:270,353,619
from parrot.bots.flows.core.result import (
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status,
)

# verified: packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:39
from ..core.result import build_node_metadata          # intra-package form

# verified: packages/ai-parrot/src/parrot/models/responses.py:72,1119
from parrot.models.responses import AIMessage, AgentResponse

# verified: packages/ai-parrot/src/parrot/bots/flows/core/context.py:55
from parrot.bots.flows.core.context import FlowContext

# verified: packages/ai-parrot/src/parrot/bots/flows/core/types.py — FlowStatus
from parrot.bots.flows.core.types import FlowStatus
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class NodeExecutionInfo:                       # line 270
    node_id: str                               # line 280
    node_name: str                             # line 283
    provider: Optional[str] = None             # line 286
    model: Optional[str] = None                # line 289
    execution_time: float = 0.0                # line 292
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)   # line 295
    status: Literal["completed","failed","pending","running"] = "pending"  # line 298
    error: Optional[str] = None                # line 301
    client: Optional[str] = None               # line 304  ← NEVER POPULATED
    usage: Optional[Dict[str, Any]] = None     # line 307
    @property
    def agent_id(self) -> str: ...             # line 313 (alias for node_id)
    @property
    def agent_name(self) -> str: ...           # line 318 (alias for node_name)
    def to_dict(self) -> Dict[str, Any]: ...   # line 324 (emits `client`, line 342)

@dataclass
class FlowResult:                              # line 353
    output: Any                                # line 368
    responses: Dict[str, Any] = {}             # line 371
    summary: str = ""                          # line 374  ← by design for flows
    nodes: List[NodeExecutionInfo] = []        # line 377
    execution_log: List[Dict[str, Any]] = []   # line 380  ← flow leaves empty
    total_time: float = 0.0                    # line 383  ← flow leaves 0.0
    status: FlowStatus = FlowStatus.COMPLETED   # line 386
    errors: Dict[str, str] = {}                # line 389
    metadata: Dict[str, Any] = {}              # line 392  ← flow leaves empty
    def __setattr__(self, name, value) -> None: ...        # line 404 (coerces summary→str)
    def __repr__(self) -> str: ...                         # line 414 (prints total_time)
    @property
    def content(self) -> Optional[Any]: ...                # line 424 (alias: output)
    @property
    def final_result(self) -> Optional[Any]: ...           # line 429 (alias: output)
    @property
    def success(self) -> bool: ...                         # line 434
    @property
    def node_results(self) -> Dict[str, Any]: ...          # line 439 ← envelope bug
    @property
    def completed(self) -> List[str]: ...                  # line 452
    @property
    def failed(self) -> List[str]: ...                     # line 466
    @property
    def total_execution_time(self) -> float: ...           # line 480 (alias: total_time)
    @property
    def agents(self) -> List[NodeExecutionInfo]: ...       # line 487 (alias: nodes)
    @property
    def agent_results(self) -> Dict[str, Any]: ...         # line 492 (alias: node_results)
    def __getitem__(self, item: str) -> Any: ...           # line 498
    def to_dict(self) -> Dict[str, Any]: ...               # line 541

# module-level helpers, same file
def _serialise_result_value(value: Any) -> Any: ...        # line 44
def determine_run_status(...) -> str: ...                  # line 242
def _serialise_tool_calls(tool_calls: Any) -> List[Any]: ...  # line 589
def _normalise_status(status: str) -> Literal[...]: ...    # line 604
def build_node_metadata(                                   # line 619  ← SHARED SEAM
    node_id: str,
    agent: Optional[Any],
    response: Optional[Any],
    output: Optional[Any],
    execution_time: float,
    status: str,
    error: Optional[str] = None,
) -> NodeExecutionInfo: ...
    # isinstance ladder: AgentResponse @654 → AIMessage @671 → else-getattr @680
    # agent fallback for provider/model @690-694; constructor @698 (no client=)
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class AgentNode(Node):                                     # line 193
    async def execute(self, ctx, deps, **kwargs) -> Any:   # line 281
        # returns the ENVELOPE dict @ lines 321-325:
        #   {"response": <AgentResponse>, "output": <Any>,
        #    "execution_time": <float>, "prompt": <str>}
    # other execute() overrides: line 393, line 470 (EndNode; unwraps
    # dict["output"] itself @485-486)
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                         # line 55
    initial_task: str                                      # line 71
    results: Dict[str, Any]                                # line 72
    responses: Dict[str, Any]                              # line 75  ← flow leaves empty
    node_metadata: Dict[str, NodeExecutionInfo]            # line 78  ← flow leaves empty
    completion_order: List[str]                            # line 81  ← ORDERING SOURCE
    errors: Dict[str, Exception]                           # line 84
    active_tasks: Set[str]                                 # line 87
    completed_tasks: Set[str]                              # line 90
    shared_data: Dict[str, Any]                            # line 93
    def mark_completed(                                    # line 177
        self, node_id: str, result: Any = None,
        response: Any = None,
        metadata: Optional[NodeExecutionInfo] = None,
    ) -> None: ...
        # appends completion_order @197; stores result @200, response @202
```

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                        # line 217
    def _notify_node_event(self, ...) -> None: ...         # line 437
    def _aggregate_result(                                 # line 955  ← MODIFY
        self, nodes, results, errors, completed, failed,
        edges: Optional[list[Any]] = None,
        durations: Optional[dict[str, float]] = None,
    ) -> FlowResult: ...
        # node_infos loop over `completed | failed` (set union) @983  ← order bug
        # build_node_metadata(response=resp, output=resp, ...) @988    ← envelope bug
        # leaf detection @999-1026; output unwrap @1028-1046
        # FlowResult(output/nodes/responses/errors/status ONLY) @1051  ← field bug
    async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult: ...  # line 1059
        # completed/failed/skipped/results/errors  @1428-1432
        # run_started_at = loop.time()             @1436   ← total_time source
        # started_at / durations                   @1436-1437
        # durations[nid] = loop.time() - started_at @1840
        # ctx.mark_failed(nid, event.error)        @1866
        # ctx.mark_completed(nid, result=...)      @1881   ← no response=/metadata=
        # self._aggregate_result(...)              @1926   ← pass new kwargs here
        # flow_completed event already computes the elapsed run @1934
```

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py  — REFERENCE (faithful)
build_node_metadata(agent_id, agent, response, result, execution_time, 'completed')  # @1968
context.mark_completed(agent_id, result=result, response=response)                   # @1964
FlowResult(output=..., responses=..., nodes=agents_info, errors=...,
           execution_log=self.execution_log, total_time=total_time,
           status=status, metadata={'mode': 'sequential', ...})                      # @2079-2087
# other FlowResult sites: 1835, 2202, 2219, 2589, 2801, 2956, 3229
```

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                # line 72
    input: str; output: Any; response: Optional[str]; data: Optional[Any]
    model: str; provider: str              # required fields
    usage: CompletionUsage                 # required — has .model_dump()
    stop_reason / finish_reason: Optional[str]
    tool_calls: List[ToolCall] = []

class AgentResponse(BaseModel):            # line 1119
    session_id / user_id / agent_id / agent_name: Optional[str]
    status: str = "success"
    question: Optional[str]
    response: Optional[AIMessage]          # ← nested AIMessage carries usage
    data: Optional[str]; output: Optional[Any]
    attributes: Dict[str, str]; created_at: datetime
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_unwrap_response()` | `build_node_metadata()` | called first in body | `core/result.py:645` |
| `build_node_metadata()` | `AgentsFlow._aggregate_result` | existing call | `flow/flow.py:988` |
| `build_node_metadata()` | `AgentCrew` | existing calls | `crew/crew.py:1346,1398,1968,2035,2323` |
| `build_node_metadata()` | `DecisionFlowNode` / `InteractiveDecisionNode` | existing calls (`agent=None`) | `flow/nodes.py:399,1129` |
| `_aggregate_result(ctx=…)` | `FlowContext.completion_order` | attribute read | `core/context.py:81` |
| `_aggregate_result(run_started_at=…)` | `run_flow` local | kwarg | `flow/flow.py:1436` |
| `run_flow` | `ctx.mark_completed(response=…, metadata=…)` | existing params | `core/context.py:181-182` |
| `FlowResult.node_results` | envelope dict | `"output"` key read | `core/node.py:323` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentsFlow._build_result()`~~ — the method is named **`_aggregate_result`**
  (`flow/flow.py:955`). There is no `_build_result` anywhere in the package.
- ~~`FlowResult.outputs`~~ — no plural field exists, and this spec does not add
  one (§8 Q2). Only `output` (singular).
- ~~`FlowResult.node_count` / `.mode` / `.leaves`~~ — not fields; they go
  inside the existing `metadata` dict.
- ~~`NodeExecutionInfo.status == "skipped"`~~ — not a valid literal
  (`core/result.py:298`). Skipped IDs live in `FlowResult.metadata["skipped"]`.
- ~~`AgentsFlow.execution_log`~~ — no such instance attribute. `AgentCrew`
  has `self.execution_log` (`crew/crew.py:2084`); AgentsFlow does not, so the
  log must be built inside `_aggregate_result`.
- ~~`AgentsFlow(SynthesisMixin)`~~ — AgentsFlow inherits **only**
  `PersistenceMixin` (`flow/flow.py:217`), by explicit design
  (`flow/flow.py:11-12`). Do not add it.
- ~~`parrot.bots.flows.core.result._unwrap_response`~~ — **to be created** by
  Module 1; it does not exist yet.
- ~~`packages/ai-parrot/tests/bots/flows/test_result_fidelity.py`~~ — **to be
  created** by Module 5.
- ~~`parrot.vectorstores`~~ / ~~`parrot/bots/orchestration/`~~ /
  ~~`parrot/bots/flow/`~~ — all removed packages; never import from them.
- `parrot.models.crew.build_agent_metadata` (`models/crew.py:322`) **does**
  exist but is **legacy** — no flows/crew code path calls it. Do not "fix" it
  and do not route new code through it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Additive-only discipline.** Every change either populates a
  previously-default field or adds a keyword-only defaulted parameter. If a
  fix seems to require retyping a field, stop and escalate (§8 Q4) — do not
  make it breaking.
- **Fix at the shared seam.** Envelope unwrapping belongs in
  `_unwrap_response`, called from `build_node_metadata` — **not** duplicated
  into `_aggregate_result`. That single-seam property is the whole point of G5.
- Google-style docstrings + strict type hints on every new/changed function
  (project rule).
- Use `self.logger` — never `print` — for any new diagnostics.
- `_unwrap_response` must be defensive: it receives arbitrary user objects.
  Bound the recursion (a small explicit depth cap) and never raise; on
  anything unexpected, return the input unchanged so `build_node_metadata`
  degrades exactly as it does today.
- Preserve the existing `try/except ImportError` guard around
  `parrot.models.responses` (`core/result.py:651,684`) — it keeps
  `build_node_metadata` importable in trimmed installs.

### Known Risks / Gotchas

- **Silent crew regression is the top risk.** `build_node_metadata` is on
  AgentCrew's hot path (5 call sites). Land Module 1 with the crew regression
  suites (AC13) green *before* touching `flow.py`.
- **`output=resp` is passed alongside `response=resp`** at
  `flow/flow.py:988-996`. Because `output` is non-`None`, the `if output is
  None` recovery branches (`core/result.py:666,675`) never fire — so
  unwrapping `response` alone is sufficient, but do not "helpfully" also
  rewrite the `output` argument: `_aggregate_result` computes
  `FlowResult.output` separately at lines 1028-1046, and changing the
  per-node `output` argument would alter `NodeExecutionInfo` semantics
  (breaking, violates G6).
- **`durations` vs. envelope `execution_time`.** Two timings now coexist: the
  scheduler's `durations[nid]` (includes spawn/queue overhead) and the node's
  own `envelope["execution_time"]`. Keep using `durations` for
  `NodeExecutionInfo.execution_time` — changing the source would shift
  existing numbers. Note the distinction in the docstring.
- **Failed nodes are absent from `completion_order`.** `mark_failed`
  (`flow/flow.py:1866`) does not append to it, so ordering by
  `completion_order` alone would drop failures. Append the residue
  (`(completed | failed) - set(completion_order)`) in sorted order.
- **Retries overwrite `durations[nid]`** (`flow/flow.py:1840` runs on every
  completion event). `execution_time` therefore reflects the *last* attempt —
  pre-existing behaviour, documented here, not changed.
- **Resume path.** `completed` is seeded from `ctx.completed_tasks`
  (`flow/flow.py:1428`) and `results` from `ctx.results` (line 1431) on a
  resumed run, but `run_started_at` measures only the *current* process. On
  resume, `total_time` is the resumed segment's wall clock, not the original
  run's — state this in the docstring rather than trying to reconstruct it.
- **Checkpoint serialisation.** Populating `ctx.node_metadata` puts
  `NodeExecutionInfo` dataclasses into a context that
  `FlowContext.to_snapshot()` serialises. Verify the round-trip
  (`tests/flows/checkpoint/test_flow_export.py`) — use `to_dict()`
  (`core/result.py:324`) if the snapshot path needs plain dicts.
- **`usage` from a mock.** `build_node_metadata` calls
  `usage_obj.model_dump()` when available (`core/result.py:670,679`). Test
  fixtures must use a real `CompletionUsage`, not a bare `MagicMock`, or
  `model_dump()` returns a `Mock` and assertions become meaningless.
- **AC7 determinism** needs the test run under at least two different
  `PYTHONHASHSEED` values to actually prove set-order independence.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. No new runtime or test dependency. |

---

## 8. Open Questions

**Resolved before drafting** (asked and answered at spec time, 2026-08-22):

- [x] Which fidelity gaps are in scope? — *Resolved by author*: **all four** —
  per-node metadata unwrap, run-level fields, deterministic node order, and
  the output-shape contract. Reflected in G1-G4 and Modules 1-4.
- [x] How should the multi-leaf `output` shape be handled? — *Resolved by
  author*: **keep the polymorphism, document it.** No API change; scalar for a
  single leaf, `dict[node_id, Any]` for a fan-out. No parallel `outputs`
  field. Reflected in G4, Non-Goals, AC9, and the `Does NOT Exist` list.
- [x] Is changing `FlowResult`'s public surface acceptable? — *Resolved by
  author*: **additive only.** No existing field changes type or meaning.
  Reflected in G6, AC11, and the Non-Goals.
- [x] Does this touch `AgentCrew` too? — *Resolved by author*: **shared helper
  for both.** Fix inside `build_node_metadata` so crew and flow cannot drift
  again; crew's own assembly paths are not rewritten. Reflected in G5,
  Module 1, Module 5, AC13.

**Still open:**

- [ ] Should `FlowResult.metadata["mode"]` use the internal names
  (`"explicit"` / `"definition"` / `"legacy"`) or crew-comparable ones? Crew
  writes `'sequential'` / `'parallel'` / `'loop'` (`crew/crew.py:1840,2087`),
  a different axis entirely. Decidable during implementation; default to the
  internal names — *Owner: implementer*
- [ ] Should `FlowResult.responses` keep holding raw envelope dicts for
  AgentsFlow (status quo, and what `node_results` now unwraps), or hold the
  unwrapped `AgentResponse` to match crew exactly? Changing it would alter an
  existing field's contents — likely breaking, so status quo is the default.
  Flag if the parity test (Module 5) makes it untenable — *Owner: implementer*
- [ ] Does any downstream consumer already work around `total_time == 0.0`
  (e.g. summing `node.execution_time` itself)? Populating it correctly could
  double-count in such a consumer. Grep `total_time` / `total_execution_time`
  consumers in `parrot/flows/`, `parrot/handlers/`, and the dev-loop runner
  before landing Module 3 — *Owner: implementer*
- [ ] Should `metadata["skipped"]` be a `list[str]` or a richer per-node
  record (reason, blocking predicate)? A list satisfies AC6; escalate if
  telemetry needs more — *Owner: author*

---

## Worktree Strategy

**Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree.

The five modules touch only two source files (`core/result.py`,
`flow/flow.py`) plus one new test file, and Modules 3/4 both edit
`flow/flow.py`. Parallel worktrees would conflict on every hunk, so
sequential execution in a single worktree is the only sane arrangement.

**Mandatory ordering** (each step's tests must be green before the next):

```
Module 1 (shared unwrap)  ──→  Module 3 (_aggregate_result)  ──→  Module 4 (run_flow wiring)
        │                                                                  │
        └──→ Module 2 (node_results, independent)                          ▼
                                                             Module 5 (parity contract test)
```

Module 1 lands first and alone, gated on the crew regression suites (AC13):
it is the only change that can silently break AgentCrew.

**Cross-feature dependencies**: none. No open spec currently modifies
`core/result.py` or `flow/flow.py`. Coordinate with FEAT-399
(`agentsflow-state-checkpointing`, worktree
`.claude/worktrees/feat-399-checkpointing-example`) if it is still live —
Module 4 populates `ctx.node_metadata`, which that feature's snapshot path
serialises (see §7 "Checkpoint serialisation").

**Worktree creation**:

```bash
git checkout dev
git worktree add -b feat-447-agentsflow-result-fidelity \
  .claude/worktrees/feat-447-agentsflow-result-fidelity HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-22 | Jesus Lara | Initial draft — five verified fidelity losses, three-layer additive fix |
