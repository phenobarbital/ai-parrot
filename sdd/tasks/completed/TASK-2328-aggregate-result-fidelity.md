# TASK-2328: Faithful `_aggregate_result` — ordering, `total_time`, `execution_log`, `metadata`

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2326
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec (§3) and fixes **G2, G3** plus the write
half of **G4**.

`AgentsFlow._aggregate_result` (`flow/flow.py:955-1055`) builds a `FlowResult`
that leaves every run-level field at its dataclass default. The
`FlowResult(...)` call at `flow/flow.py:1051` passes only
`output/nodes/responses/errors/status`, so `total_time == 0.0`,
`execution_log == []`, `metadata == {}`. This is not a data-availability
problem: `run_started_at` (`flow/flow.py:1436`) and `durations`
(`flow/flow.py:1437,1840`) are in scope in `run_flow`, and the
`flow_completed` event emitted three lines after the aggregation call already
computes the exact wall-clock figure (`flow/flow.py:1934`) — it goes to
listeners and is then discarded. Consequently `FlowResult.__repr__` always
prints `time=0.00s` (`core/result.py:414-418`) and `total_execution_time`
(`core/result.py:480`) always returns `0.0`. `AgentCrew` sets all four
(`crew/crew.py:2079-2087`).

Separately, `node_infos` is built by iterating `for nid in completed | failed`
(`flow/flow.py:983`) — a **set union**. True execution order is discarded and
the surviving order varies with string hashing across processes, so
`result.nodes` cannot be rendered as a timeline and order assertions are
inherently flaky. `FlowContext.completion_order` (`core/context.py:81`)
already records the real order and is already maintained by `mark_completed`
(`core/context.py:197`) — `_aggregate_result` simply never receives `ctx`.

TASK-2326 must land first: it is what makes `build_node_metadata` extract
`usage`/`tool_calls` from the envelopes this method passes it.

---

## Scope

- Add three **keyword-only, defaulted** parameters to `_aggregate_result`
  (`flow/flow.py:955`): `ctx: Optional[FlowContext] = None`,
  `run_started_at: Optional[float] = None`, `skipped: Optional[set[str]] = None`.
- **Deterministic ordering**: build `node_infos` in `ctx.completion_order`
  order, then append the residue — `(completed | failed) - set(completion_order)`
  — in **sorted** order. Fall back to the current behaviour when `ctx is None`.
- **`total_time`**: compute from `run_started_at` using the same monotonic
  clock the scheduler uses (`asyncio.get_running_loop().time()`). Leave `0.0`
  when `run_started_at is None`.
- **`execution_log`**: one entry per completed-or-failed node, in the same
  deterministic order, each with exactly these five keys:
  `node_id`, `node_name`, `status`, `execution_time`, `error`.
- **`metadata`**: populate `mode`, `node_count`, `completed_count`,
  `failed_count`, `skipped`, `leaves` (see spec §2 Data Models).
- **Docstring the output contract** on `_aggregate_result`: scalar when a
  single executed leaf, `dict[node_id, Any]` on a fan-out.
- Add the 8 unit tests below.

**NOT in scope**:
- Wiring the new kwargs at the call site, `ctx.mark_completed(response=…)`, and
  `ctx.node_metadata` — that is TASK-2329. This task only makes
  `_aggregate_result` *able* to use them; it stays fully backward-compatible
  when called with the old argument list.
- Populating `FlowResult.summary`. AgentsFlow does not inherit
  `SynthesisMixin` by explicit design (`flow/flow.py:11-12,217`). **Do not add it.**
- Changing the leaf-detection logic (`flow/flow.py:999-1026`) or the
  `output` computation (`flow/flow.py:1028-1046`). Document them; do not alter them.
- Changing `NodeExecutionInfo.execution_time`'s source. Keep using
  `durations[nid]`, NOT the envelope's own `"execution_time"` — see Gotchas.
- Emitting `NodeExecutionInfo` entries for skipped nodes. `status` is a closed
  literal with no `"skipped"` member (`core/result.py:298`); widening it would
  be breaking. Skipped IDs go in `metadata["skipped"]` only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | `_aggregate_result`: 3 new kwargs, ordering, `total_time`, `execution_log`, `metadata`, docstring |
| `packages/ai-parrot/tests/bots/flows/test_scheduler.py` | MODIFY | Add the 8 unit tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22. TASK-2326 will have
> shifted `core/result.py`; `flow/flow.py` should be untouched, but
> re-`grep -n` before relying on any number.

### Verified Imports

```python
# already imported at packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:39
from ..core.result import build_node_metadata
# also already imported in that file: FlowResult, determine_run_status,
#   NodeExecutionInfo — CHECK the existing import block before adding anything.

# verified: packages/ai-parrot/src/parrot/bots/flows/core/context.py:55
from ..core.context import FlowContext        # intra-package form

# verified: packages/ai-parrot/src/parrot/bots/flows/core/types.py
from ..core.types import FlowStatus           # imported LOCALLY inside the
                                              # method today @ flow/flow.py:1044-ish
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                        # line 217
    def _aggregate_result(                                 # line 955  ← MODIFY
        self,
        nodes: dict[str, Any],
        results: dict[str, Any],
        errors: dict[str, BaseException],
        completed: set[str],
        failed: set[str],
        edges: Optional[list[Any]] = None,
        durations: Optional[dict[str, float]] = None,
    ) -> FlowResult: ...
        # node_infos = []                              @982
        # for nid in completed | failed:               @983   ← SET UNION, the order bug
        #     resp = results.get(nid)                  @985
        #     info = build_node_metadata(              @988
        #         node_id=nid,
        #         agent=getattr(node, "agent", None),
        #         response=resp,          ← envelope; TASK-2326 makes this work
        #         output=resp,            ← LEAVE AS IS (see Gotchas)
        #         execution_time=(durations or {}).get(nid, 0.0),   @993
        #         status=status_str, error=...,
        #     )
        # leaf detection (explicit / definition / legacy)  @999-1026
        # if len(leaves) == 1 and leaves[0] in results:    @1028  → scalar
        #     unwraps leaf_result["output"]                @1033-1034
        # else: multi-leaf fan-out → dict[node_id, scalar] @1038-1046
        # status_str = determine_run_status(len(completed), len(failed))  @1048
        # return FlowResult(output/nodes/responses/errors/status ONLY)    @1051 ← FIX

    async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult: ...  # line 1059
        # completed / failed / skipped / results / errors   @1428-1432
        # run_started_at = loop.time()                       @1436
        # started_at / durations                             @1436-1437
        # durations[nid] = loop.time() - started_at.get(...)  @1840
        # ctx.mark_failed(nid, event.error)                  @1866
        # ctx.mark_completed(nid, result=event.result)       @1881
        # self._aggregate_result(...) call site              @1926   ← TASK-2329 edits this
        # flow_completed event, already computes elapsed     @1929-1935
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                         # line 55
    completion_order: List[str]                            # line 81  ← ORDERING SOURCE
    completed_tasks: Set[str]                              # line 90
    errors: Dict[str, Exception]                           # line 84
    def mark_completed(self, node_id, result=None,
                       response=None, metadata=None) -> None: ...  # line 177
        # appends to completion_order @197
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/result.py
@dataclass
class FlowResult:                              # line 353
    output: Any                                # line 368
    responses: Dict[str, Any] = {}             # line 371
    summary: str = ""                          # line 374  ← LEAVE EMPTY (by design)
    nodes: List[NodeExecutionInfo] = []        # line 377
    execution_log: List[Dict[str, Any]] = []   # line 380  ← POPULATE
    total_time: float = 0.0                    # line 383  ← POPULATE
    status: FlowStatus = FlowStatus.COMPLETED   # line 386
    errors: Dict[str, str] = {}                # line 389
    metadata: Dict[str, Any] = {}              # line 392  ← POPULATE
    def __repr__(self) -> str: ...             # line 414  (prints total_time)

class NodeExecutionInfo:                       # line 270
    node_id: str; node_name: str               # lines 280, 283
    execution_time: float = 0.0                # line 292
    status: Literal["completed","failed","pending","running"]  # line 298 ← NO "skipped"
    error: Optional[str] = None                # line 301

def determine_run_status(...) -> str: ...      # line 242
```

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — REFERENCE, DO NOT EDIT
result = FlowResult(
    output=current_input, responses=responses, nodes=agents_info, errors=errors,
    execution_log=self.execution_log,     # crew has self.execution_log; FLOW DOES NOT
    total_time=total_time,
    status=status,
    metadata={'mode': 'sequential', 'agent_sequence': agent_sequence},
)                                              # @2079-2087
```

### Required `metadata` and `execution_log` shapes (spec §2 Data Models)

```python
metadata = {
    "mode": str,            # "explicit" | "definition" | "legacy"
    "node_count": int,      # len(nodes) materialized
    "completed_count": int,
    "failed_count": int,
    "skipped": list[str],   # skipped node_ids
    "leaves": list[str],    # node_ids that produced `output`
}

execution_log_entry = {
    "node_id": str,
    "node_name": str,
    "status": str,          # "completed" | "failed"
    "execution_time": float,
    "error": str | None,
}
```

### Does NOT Exist

- ~~`AgentsFlow._build_result`~~ — the method is **`_aggregate_result`**
  (`flow/flow.py:955`). There is no `_build_result` anywhere in the package.
- ~~`AgentsFlow.execution_log`~~ — no such instance attribute. `AgentCrew` has
  `self.execution_log` (`crew/crew.py:2084`); AgentsFlow does **not**, so the
  log must be constructed inside `_aggregate_result`.
- ~~`FlowResult.node_count` / `.mode` / `.leaves` / `.skipped`~~ — none are
  fields. They all go INSIDE the existing `metadata` dict.
- ~~`NodeExecutionInfo.status == "skipped"`~~ — not a valid literal (line 298).
- ~~`AgentsFlow(SynthesisMixin)`~~ — inherits **only** `PersistenceMixin`
  (`flow/flow.py:217`), deliberately (`flow/flow.py:11-12`). Do not add it.
- ~~`FlowContext.execution_log`~~ / ~~`FlowContext.total_time`~~ — not fields.
  See `core/context.py:71-111` for the real field list.
- ~~`time.time()` for the run clock~~ — the scheduler uses the event loop's
  monotonic clock (`loop.time()`, `flow/flow.py:1436`). Mixing clocks yields
  nonsense. Use the same one.

---

## Implementation Notes

### Pattern to Follow

```python
# Deterministic ordering with a stable residue for failures.
# mark_failed (flow/flow.py:1866) does NOT append to completion_order, so
# ordering by completion_order alone would silently DROP failed nodes.
ordered: list[str] = []
if ctx is not None:
    seen = set()
    for nid in ctx.completion_order:
        if nid in (completed | failed) and nid not in seen:
            ordered.append(nid)
            seen.add(nid)
    ordered.extend(sorted((completed | failed) - seen))
else:
    ordered = sorted(completed | failed)   # deterministic even without ctx
```

### Key Constraints

- **Fully backward-compatible call.** `_aggregate_result(...)` invoked with its
  pre-change positional argument list must still return a valid `FlowResult`
  (spec AC11). All three new parameters are keyword-only with defaults.
- Even without `ctx`, prefer `sorted(...)` over set-union iteration — it costs
  nothing and removes the hash-order nondeterminism unconditionally.
- Use `self.logger` — never `print` — for any new diagnostics.
- Google-style docstrings + strict type hints.
- Additive only: no `FlowResult` / `NodeExecutionInfo` field retyped (G6, AC11).

### Known Risks / Gotchas

- **Do NOT change the `output=resp` argument** at `flow/flow.py:991`. Because
  it is non-`None`, `build_node_metadata`'s `if output is None` recovery
  branches (`core/result.py:666,675`) never fire — that is fine. Rewriting it
  would change `NodeExecutionInfo` semantics (breaking, violates G6). The
  `FlowResult.output` value is computed separately at `flow/flow.py:1028-1046`.
- **Two timings now coexist**: the scheduler's `durations[nid]` (includes
  spawn/queue overhead) and the node's own `envelope["execution_time"]`
  (`core/node.py:324`). Keep `durations` as the source for
  `NodeExecutionInfo.execution_time` — switching would shift existing numbers.
  State the distinction in the docstring.
- **Retries overwrite `durations[nid]`** — `flow/flow.py:1840` runs on every
  completion event, so `execution_time` reflects the LAST attempt. Pre-existing
  behaviour; document it, do not change it.
- **Resume path**: `completed` is seeded from `ctx.completed_tasks`
  (`flow/flow.py:1428`) and `results` from `ctx.results` (line 1431). On a
  resumed run `run_started_at` measures only the CURRENT process, so
  `total_time` is the resumed segment's wall clock, not the original run's.
  Say so in the docstring; do not try to reconstruct the original.
- **Open question to settle here** (spec §8): `metadata["mode"]` vocabulary.
  Crew writes `'sequential'`/`'parallel'`/`'loop'` (`crew/crew.py:1840,2087`),
  which is a different axis entirely. **Default to the internal flow names**
  (`"explicit"`/`"definition"`/`"legacy"`) and note the divergence in the
  docstring.
- **Before landing**: grep for consumers that already work around
  `total_time == 0.0` by summing `node.execution_time` themselves — populating
  it correctly could double-count. Check `parrot/flows/`, `parrot/handlers/`,
  and the dev-loop runner (spec §8, open question). Report findings in the
  Completion Note.
- **AC7 determinism** must be proven, not assumed: run the ordering test under
  at least two different `PYTHONHASHSEED` values.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:2079-2087` — the
  faithful reference implementation. Mirror its field coverage, not its `mode` vocabulary.
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1929-1935` — the
  `flow_completed` event that already computes the elapsed run.

---

## Acceptance Criteria

- [ ] `_aggregate_result` accepts keyword-only `ctx`, `run_started_at`, `skipped`, all defaulted
- [ ] `FlowResult.total_time > 0` when `run_started_at` is supplied (spec AC4)
- [ ] `execution_log` has exactly one entry per completed-or-failed node, each with the five documented keys (spec AC5)
- [ ] `metadata` contains `mode`, `node_count`, `completed_count`, `failed_count`, `skipped`, `leaves` (spec AC6)
- [ ] `[n.node_id for n in result.nodes]` matches `ctx.completion_order`, and failed nodes absent from it still appear (spec AC7)
- [ ] Ordering is stable across at least two `PYTHONHASHSEED` values (spec AC7)
- [ ] Calling `_aggregate_result` with the pre-change argument list still works (spec AC11)
- [ ] The `output` scalar-vs-dict contract is documented on `_aggregate_result` and locked by 2 tests (spec AC9)
- [ ] `FlowResult.summary` remains `""` (spec AC12)
- [ ] All 8 unit tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_scheduler.py -v`
- [ ] Flow suites green: `pytest packages/ai-parrot/tests/bots/flows/ packages/ai-parrot/tests/test_flow_primitives/ -v` (spec AC14)
- [ ] `ruff check` and `mypy` clean on `flow/flow.py` (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_scheduler.py

def test_aggregate_result_total_time():
    """total_time > 0 and approximates now - run_started_at."""

def test_aggregate_result_execution_log():
    """One entry per completed+failed node, with the five documented keys."""

def test_aggregate_result_metadata_keys():
    """All six metadata keys present and correctly valued."""

def test_aggregate_result_node_order():
    """[n.node_id for n in result.nodes] == ctx.completion_order."""

def test_aggregate_result_failed_node_included():
    """A node failed via mark_failed (absent from completion_order) still appears."""

def test_aggregate_result_backward_compatible_call():
    """Calling without ctx/run_started_at/skipped returns a valid FlowResult."""

def test_output_single_leaf_is_scalar():
    """Single executed leaf -> scalar output (contract lock)."""

def test_output_multi_leaf_is_dict():
    """Fan-out -> dict[node_id, scalar] (contract lock)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§2 Layer 2, §6, §7)
2. **Check dependencies** — TASK-2326 MUST be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code — re-`grep -n` every anchor
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** every acceptance criterion, including the `PYTHONHASHSEED` determinism check
7. **Move this file** to `sdd/tasks/completed/TASK-2328-aggregate-result-fidelity.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below, including the `total_time` consumer grep findings

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-08-24
**Notes**:

Module 3 landed as specified. `_aggregate_result` now has three keyword-only
defaulted parameters (`ctx`, `run_started_at`, `skipped`) after the existing
`edges`/`durations` positionals, so every pre-change call site still type-checks
and still works.

- **Ordering (G3)**: `terminal = completed | failed` is materialised once, then
  walked in `ctx.completion_order` order (de-duplicated), with the residue
  `terminal - seen` appended `sorted()`. Without a `ctx` the whole set is
  `sorted()` rather than iterated — as the task asked, determinism is now
  unconditional, not merely available.
- **`total_time` (G2)**: `max(0.0, asyncio.get_running_loop().time() -
  run_started_at)`, i.e. the *same* monotonic clock the scheduler reads at
  `run_started_at`. A direct synchronous call (no running loop) logs at debug
  via `self.logger` and leaves `0.0` instead of splicing in a foreign epoch.
- **`execution_log`**: built in the same loop as `node_infos`, from the
  `NodeExecutionInfo` just constructed, so the two lists are guaranteed
  index-aligned and same-ordered. Exactly the five documented keys.
- **`metadata`**: all six keys. `skipped` is `sorted()` (determinism);
  `leaves` is the node_ids that actually produced `output` — `[leaf]` in the
  single-leaf branch, `list(output_map)` in the fan-out branch — captured by a
  new `output_leaves` variable that does not touch the existing leaf-detection
  or `output` computation.
- **`mode`**: resolved `"explicit"` / `"definition"` / `"legacy"` from
  `edges is not None` / `self._definition is not None` / else. Per the spec's
  open question I defaulted to the internal flow vocabulary, and the docstring
  states explicitly that this is a DIFFERENT axis from AgentCrew's
  `metadata['mode']` (`'sequential'`/`'parallel'`/`'loop'`), so nobody reads
  them as comparable.
- **Docstring**: the output shape contract verbatim, plus the three timing
  caveats the task required (scheduler `durations` vs. the node envelope's own
  `execution_time`; retries overwrite `durations[nid]` so the figure is the
  LAST attempt; on a resumed run `total_time` covers the resumed segment only)
  and the note that `summary` stays empty by design.

Untouched, as required: the `output=resp` argument, leaf detection, the
`output` computation, `NodeExecutionInfo.execution_time`'s source, and the
class's inheritance (no `SynthesisMixin`). No `NodeExecutionInfo` is emitted
for skipped nodes.

Tests: 8 added to `tests/bots/flows/test_scheduler.py` — the 7 named plus
`test_aggregate_result_node_order_is_deterministic` (asserts the no-`ctx` path
sorts and that repeated aggregation over a differently-ordered input set is
stable). `test_scheduler.py`: 23 passed (15 pre-existing + 8).

**AC7 determinism proof**: the ordering/output tests were run under
`PYTHONHASHSEED` = 0, 1, 42 and 12345 — 7 passed at every seed, so the order
is provably independent of string-hash randomisation, not just incidentally
stable.

Verification:
- `tests/bots/flows/` + `tests/test_flow_primitives/`: 718 passed
  (699 clean-`dev` baseline + 8 + 2 + 8 + the pre-existing count; no failures).
- `ruff` on `flow/flow.py`: 133 pre-existing findings -> 136, the delta being
  exactly 3 `UP045` from the three new `Optional[...]` parameter annotations,
  which match the file's 43 existing `Optional` annotations (the repo declares
  no `[tool.ruff]` config, so these are defaults-only findings that predate
  this feature). `test_scheduler.py` went 6 -> 5 findings: my use of
  `pytest.approx` retired a pre-existing `F401` unused-`pytest` import.
- `mypy` on `flow/flow.py`: 28 errors before, 28 after, the two sets identical
  once line numbers are normalised — no new type errors.

**`total_time` consumer audit** (the grep the Gotchas required, to rule out
double-counting when `total_time` stops being `0.0`): **no consumer works
around `total_time == 0.0`.**
- `parrot/flows/` (dev_flow, dev_loop runners) and `parrot/handlers/`: zero
  references to `total_time` / `total_execution_time` at all.
- The only place that *sums* per-node `execution_time` is
  `crew/crew.py:3381` (`total_time = sum(log['execution_time'] for log in
  self.execution_log)`) — that is AgentCrew computing its OWN `total_time`
  from its own `execution_log`, an input to a `FlowResult`, not a consumer
  compensating for AgentsFlow's zero. It is untouched by this feature.
- Remaining references are pure pass-throughs that now simply carry a real
  number: `core/result.py` (`total_execution_time` alias, `to_dict`),
  `core/storage/document.py:102` (persistence), `crew/crew.py:3691`
  (`last_crew_result.total_time`), and `models/crew.py` (the legacy
  `CrewResult`). None of them add or scale the value.

**Deviations from spec**: none.
