# TASK-2090: UsageReport model, usage.json and the markdown section

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2089
**Assigned-to**: unassigned

---

## Context

Implements **Module 7a** of the spec. `run_bundle.py` already renders a per-**node**
table with token columns (`run_bundle.py:61-67`), but there is no per-**agent**
view: you cannot ask "which seat spent what, on which model, over how many
rounds?" — which is the whole point of running a mixed model fleet.

This task introduces `UsageReport` as the **single source of truth**, serialises
it to `usage.json`, and renders a markdown section into the existing bundle. The
HTML rendering is TASK-2091, built from the same model so the three views cannot
disagree.

The report is a pure **consumer**: rounds and tokens arrive from the
`ClientRoundEvent`s emitted by TASK-2089 and from the existing `DispatchState`
telemetry. It performs no accumulation of its own beyond summing already-final
per-round numbers for display.

---

## Scope

- Create `dev_loop/usage_report.py` with `AgentUsage` and `UsageReport`
  (Pydantic v2, frozen, following the `run_bundle._Frozen` convention).
- Implement `build_usage_report(snapshot, run_id) -> UsageReport`, attributing
  usage to agent seats.
- Implement `render_usage_markdown(report) -> str`.
- Write `usage.json` alongside the existing run bundle output.
- Fold the markdown section into the existing bundle rendering, reusing
  `_format_tokens` (`run_bundle.py:365`).
- Honour the **no-fake-zeros** rule: unreported values render `—`, never `0`
  (`run_bundle.py:120-123` states this contract for `RunTotals`).
- Write unit tests.

**NOT in scope**: the HTML renderer (TASK-2091); emitting round events
(TASK-2089); Bedrock client round accumulation (FEAT-404); any cost/pricing
computation (explicitly a Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/usage_report.py` | CREATE | `AgentUsage`, `UsageReport`, `build_usage_report`, `render_usage_markdown` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py` | MODIFY | Emit `usage.json`; splice the markdown section into the bundle |
| `packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, ConfigDict, Field
from parrot.flows.dev_loop.session_state import Snapshot   # verified: imported by run_bundle.py
```

`run_bundle.py` imports `RunPhase`, `Snapshot`, `NodeStatus`, `GateKind`,
`GateStatus` from `session_state` (see its import block, lines ~25-32) — reuse
the same source rather than inventing new types.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py
class _Frozen(BaseModel):                                             # line 35
    model_config = ConfigDict(frozen=True, extra="forbid")            # line 40

class NodeReport(_Frozen):                                            # line 48
    node_id: str                                                      # line 51
    status: NodeStatus = "idle"                                       # line 52
    duration_seconds: Optional[float] = None                          # line 55
    dispatcher: str = ""                                              # line 57
    message_count: int = 0                                            # line 58
    tool_use_count: int = 0                                           # line 59
    input_tokens: Optional[int] = None                                # line 61
    output_tokens: Optional[int] = None                               # line 62
    cache_creation_input_tokens: Optional[int] = None                 # line 63
    cache_read_input_tokens: Optional[int] = None                     # line 64
    total_cost_usd: Optional[float] = None                            # line 65
    num_turns: Optional[int] = None                                   # line 66
    duration_ms: Optional[int] = None                                 # line 67

class RunTotals(_Frozen):                                             # line 120
    """Run-wide aggregates. Telemetry fields are ``None`` when NO node
    reported them — a run with no reporting dispatchers must not render
    fake zeros."""                                                    # lines 121-123
    input_tokens: Optional[int] = None                                # line 132
    output_tokens: Optional[int] = None                               # line 133

class RunBundle(_Frozen):                                             # line 137
    run_id: str                                                       # line 140
    totals: RunTotals                                                 # line 147
    nodes: List[NodeReport]                                           # line 148

def _format_tokens(input_tokens: Optional[int],
                   output_tokens: Optional[int]) -> str: ...          # line 365
    # returns "—" when both are None; else "<in> in / <out> out"

# packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py
class DispatchState(_Frozen):
    dispatcher: str = ""                 # "claude-code", "codex", ...
    input_tokens: Optional[int] = None                                # line 202
    output_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None                 # line 204
    cache_read_input_tokens: Optional[int] = None                     # line 205
    total_cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    duration_ms: Optional[int] = None
class NodeState(_Frozen):
    node_id: NodeId
    dispatch: Optional[DispatchState] = None
    summary: Dict[str, str]
# usage payload absorption from dispatch.completed: lines 1259-1278
```

### Does NOT Exist

- ~~`parrot.flows.dev_loop.usage_report`~~ — this task creates it
- ~~`AgentUsage`~~ / ~~`UsageReport`~~ / ~~`build_usage_report`~~ / ~~`render_usage_markdown`~~ — created here
- ~~A per-agent (as opposed to per-node) view anywhere today~~ — `NodeReport` is keyed by `node_id` only
- ~~A `seat` field on `NodeReport` or `DispatchState`~~ — seat identity must be derived; see the open question below
- ~~Any cost/pricing table~~ — `total_cost_usd` exists on `NodeReport` but is populated only by the Claude Agent SDK; this feature adds no pricing
- ~~`AIMessage.total_usage()` in this path~~ — that is a client-layer API; the report reads `DispatchState`/events, not `AIMessage`

### Open question to resolve while implementing

Spec §8: **seat-identity granularity.** `AgentUsage.seat` needs a stable id for
pool workers (`dev-agent-1`, `dev-agent-2`). Check whether
`dev_loop/agent_pool.py` already exposes such an id; if not, derive it from
`node_id` + worker index and document the choice in the completion note.

---

## Implementation Notes

### Pattern to Follow

Follow `run_bundle.py`'s conventions exactly — frozen models, `Optional` telemetry
fields, and the no-fake-zeros discipline:

```python
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentUsage(_Frozen):
    """One agent seat's usage. None (never 0) when unreported."""
    seat: str
    node_id: str
    backend: str
    model: str
    rounds: Optional[int] = None
    input_tokens: Optional[int] = None
    ...
```

Reuse `_format_tokens` (`run_bundle.py:365`) for the markdown cells rather than
writing a second formatter — that is what guarantees `—` instead of `0`.

### Key Constraints

- **Never render a fabricated `0`.** If no dispatcher reported a value, it is
  `None` and renders `—`. `RunTotals`' docstring states this rule; the new
  report must honour it, including in the totals row.
- `usage.json` must round-trip: `UsageReport.model_validate_json(...)` on the
  written file must reproduce the model.
- No pricing, no cost estimation.
- Pydantic v2; Google-style docstrings; `self.logger` where a class exists.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py:35-149` — model conventions
- `packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py:365-420` — the existing markdown table + `_format_tokens`
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:190-225` — `DispatchState` / `NodeState`
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` — check for a seat/worker id

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop.usage_report import UsageReport, AgentUsage, build_usage_report, render_usage_markdown` works
- [ ] `build_usage_report()` produces one `AgentUsage` per agent seat with
      backend, model and rounds populated where reported
- [ ] `usage.json` is written at run end and round-trips through
      `UsageReport.model_validate_json`
- [ ] The markdown section appears in the run bundle with per-agent rows
- [ ] **Unreported values render `—`, never `0`** — including the totals row
- [ ] A run where no dispatcher reported usage still renders a valid report
- [ ] No pricing or cost figures appear anywhere in the output
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py -v` passes
- [ ] Existing `run_bundle` tests still pass
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_usage_report.py
import json
import pytest
from parrot.flows.dev_loop.usage_report import (
    AgentUsage, UsageReport, build_usage_report, render_usage_markdown,
)


@pytest.fixture
def report():
    return UsageReport(
        run_id="run-1", generated_at=0.0,
        agents=[
            AgentUsage(seat="dev-agent-1", node_id="development", backend="nova",
                       model="minimax.minimax-m2.5", rounds=7,
                       input_tokens=1000, output_tokens=250),
            AgentUsage(seat="adversarial", node_id="qa", backend="nova",
                       model="us.anthropic.claude-opus-5", rounds=1),  # no tokens
        ],
    )


class TestRendering:
    def test_dash_for_unreported(self, report):
        md = render_usage_markdown(report)
        assert "—" in md, "unreported tokens must render as an em dash"
        assert " 0 in / 0 out" not in md, "must never fabricate zeros"

    def test_rows_carry_backend_model_rounds(self, report):
        md = render_usage_markdown(report)
        assert "minimax.minimax-m2.5" in md and "nova" in md and "7" in md

    def test_no_pricing_in_output(self, report):
        assert "$" not in render_usage_markdown(report)


class TestSerialization:
    def test_json_roundtrip(self, report, tmp_path):
        p = tmp_path / "usage.json"
        p.write_text(report.model_dump_json())
        assert UsageReport.model_validate_json(p.read_text()) == report

    def test_empty_run_renders(self):
        empty = UsageReport(run_id="r", generated_at=0.0, agents=[])
        assert render_usage_markdown(empty)


class TestBuild:
    def test_one_entry_per_seat(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id="r")
        assert len({a.seat for a in rep.agents}) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Data Models, Module 7, §1 Non-Goals)
2. **Check dependencies** — verify TASK-2089 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_Frozen`, `NodeReport`, `RunTotals`, `_format_tokens` in `run_bundle.py`
   - Confirm `DispatchState`'s telemetry fields in `session_state.py`
   - **Resolve the seat-identity question** — check `agent_pool.py` before deriving your own
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2090-usage-report-model.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — **including how seat identity was resolved**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Seat identity**: how `AgentUsage.seat` is derived (spec §8 open question).

**Deviations from spec**: none | describe if any
