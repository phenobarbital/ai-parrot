# TASK-2633: IdeationNode partner seam and factory wiring

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2632
**Assigned-to**: unassigned

---

## Context

Implements the `IdeationNode` half of **spec §3 Module 5** — where the feature
becomes visible in the dev-flow.

The change is deliberately minimal and additive: one optional constructor kwarg, two
new `_IdeationBrief` fields, one coordinator call on **round 1 only**, and factory
wiring. With no coordinator injected, the dispatch payload must be byte-identical to
today — that is an acceptance criterion, not an aspiration.

---

## Scope

- Add an optional `coordinator: ComplementaryResearchCoordinator | None = None`
  kwarg to `IdeationNode.__init__` (`ideation.py:105`).
- Add two fields to `_IdeationBrief` (`ideation.py:69`): `partner_findings: str = ""`
  and `partner_findings_path: str = ""`.
- In `execute()` (`ideation.py:122`), call the coordinator **before the first
  `_dispatch`**, concurrently with the node's existing context-building work, and
  fold the result into the dispatch payload.
- **Round 1 only**: resume rounds (the HITL Open-Questions loop) pass empty partner
  fields. The findings are already in the document by then.
- Wire the coordinator in `build_dev_flow_node_factories` (`factories.py:41`, where
  `IdeationNode` is constructed at `factories.py:117`).
- Unit tests, including the byte-identical no-coordinator guard.

**NOT in scope**: `ResearchNode` (TASK-2634); the MCP/graph-search profile change
and `DEV_FLOW_IDEATION_MODEL` (TASK-2635); the `sdd-ideation` prompt (TASK-2636).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` | MODIFY | kwarg, 2 brief fields, round-1 coordinator call |
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | Build + inject the coordinator |
| `packages/ai-parrot/tests/flows/dev_flow/test_ideation_partner_seam.py` | CREATE | Seam tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_flow.complementary_research import ComplementaryResearchCoordinator
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher   # used ideation.py:56
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile, FeatureBrief  # ideation.py:57
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py
class _IdeationBrief(BaseModel):                                     # line 69
    mode: Literal["brainstorm", "proposal"]
    title: str
    description: str
    context: str = ""
    graph_context: str = ""
    answers: dict[str, str] = Field(default_factory=dict)
    document_path: str = ""
    round: int = 1
    # EXACTLY these 8 fields today. This task adds 2 more.

@register_dev_loop_node("dev_flow.ideation")                         # line 90
class IdeationNode(DevLoopNode):                                     # line 91
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher,
                 ideation_max_rounds: int | None = None, ...)        # line 105
    async def execute(...)                                           # line 122
    async def _dispatch(...)                                         # line 286
    def _resolve_max_rounds(self) -> int                             # line 256

# The HITL loop this must NOT disturb (ideation.py:178-196):
#   rounds_used = 0
#   while output.open_questions and host is not None and rounds_used < max_rounds:
#       ... re-dispatch with answers, document_path, round=rounds_used + 1

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py
def build_dev_flow_node_factories(..., dispatcher: Any, ...)         # line 41
    IdeationNode(dispatcher=dispatcher, ...)                         # line 117

# packages/ai-parrot/src/parrot/flows/dev_flow/models.py
class IdeationOutput(BaseModel):                                     # line 157
    document_path:167  document_kind:175  slug:183
    resumed_existing:184  open_questions:192  summary:200  committed:204
```

### Does NOT Exist

- ~~`partner_findings` / `partner_findings_path` on `_IdeationBrief`~~ — it has
  exactly the 8 fields listed above. This task adds the two.
- ~~a `coordinator` kwarg on `IdeationNode`~~ — new in this task; must default to
  `None` so existing construction paths are unaffected.
- ~~a `research` node in the dev-flow graph~~ — `dev_flow/definition.py` lists
  `research` among nodes "deliberately absent". Do NOT add a graph node; the
  coordinator is a call inside `execute()`, not a topology change.
- ~~partner participation on resume rounds~~ — explicitly out of scope (spec §1
  Non-Goals). Round 1 only.

---

## Implementation Notes

### Pattern to Follow

```python
# In execute(), round 1 only — mirror the node's existing best-effort
# graph_context construction (a None result must not break the run):
findings = None
if self._coordinator is not None:
    findings = await self._coordinator.research(...)   # returns Optional, never raises
# then pass findings into the FIRST _dispatch only
```

### Key Constraints

- **Byte-identical when disabled.** No coordinator injected ⇒ the `_IdeationBrief`
  payload and the dispatch profile must match pre-feature behavior exactly. Assert it.
- The coordinator never raises; do not wrap it in defensive try/except that would
  mask a genuine bug — it already owns degradation.
- Do not alter the HITL loop's bounds, gate semantics, or fail-closed expiry.
- Async throughout; `self.logger` for the degraded case.
- `object.__setattr__` is used for instance attrs in this node (see `ideation.py:114-116`) — follow it.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py:263-283` — the
  existing best-effort `graph_context` build; same tolerance for a `None` result.
- `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py:110-125` — construction site.

---

## Acceptance Criteria

- [ ] `_IdeationBrief` gains exactly `partner_findings` and `partner_findings_path`
- [ ] `IdeationNode(coordinator=None)` produces a **byte-identical** dispatch payload to pre-feature
- [ ] Findings reach the FIRST dispatch only; resume rounds pass empty partner fields
- [ ] Coordinator returning `None` leaves the run completing normally
- [ ] HITL round bounds and gate semantics unchanged
- [ ] Factory builds and injects the coordinator
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/ -v`
- [ ] Existing ideation tests still pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_ideation_node.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow/`

---

## Test Specification

```python
class TestIdeationPartnerSeam:
    async def test_passes_partner_findings_to_first_dispatch(self):
        """_IdeationBrief.partner_findings populated on round 1."""

    async def test_resume_round_skips_partner(self):
        """Round 2+ does not re-run the partner and passes empty partner fields."""

    async def test_unchanged_when_coordinator_none(self):
        """GUARD: dispatch payload byte-identical to pre-feature behavior."""

    async def test_degraded_partner_does_not_fail_run(self):
        """Coordinator returns None => run completes single-agent."""

    async def test_hitl_loop_bounds_unchanged(self):
        """max_rounds and fail-closed gate expiry behave as before."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 5) and `ideation.py`'s module docstring — it
   documents the HITL sequence and the design constraints you must not break.
2. **Check dependencies** — TASK-2632 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `ideation.py:69-130` and
   `factories.py:110-125`; line numbers may have shifted.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** — minimal and additive.
6. **Verify** all acceptance criteria, especially the byte-identical guard.
7. **Move this file** to `sdd/tasks/completed/TASK-2633-ideation-node-seam.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
