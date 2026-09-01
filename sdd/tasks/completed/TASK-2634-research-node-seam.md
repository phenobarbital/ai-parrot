# TASK-2634: ResearchNode partner seam (dev_loop)

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2632
**Assigned-to**: unassigned

---

## Context

Implements the `ResearchNode` half of **spec §3 Module 5**, satisfying the spec's
D1 requirement that **one shared mechanism** serves both the dev-flow's
`IdeationNode` and the ops flow's `ResearchNode` — no forked copy.

Smaller than TASK-2633 because the coordinator already exists and `ResearchNode`
takes only the same optional kwarg plus one call.

⚠️ **FEAT-479 (`devflow-telemetry-accounting`) also edits `nodes/research.py`** and
has tasks in progress there. Keep this change strictly additive and coordinate
before merging.

---

## Scope

- Add an optional `coordinator: ComplementaryResearchCoordinator | None = None`
  kwarg to `ResearchNode.__init__` (`research.py:218`).
- Call the coordinator once before the `sdd-research` dispatch (`research.py:423`)
  and fold the findings into the dispatch payload.
- Wire the coordinator wherever `ResearchNode` is constructed (dev_loop factories).
- Unit tests, including the byte-identical no-coordinator guard.

**NOT in scope**: `IdeationNode` (TASK-2633); any change to the Jira-then-dispatch
ordering, `/sdd-spec` / `/sdd-task` invocation, or worktree creation; anything
FEAT-479 owns (telemetry rendering).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | Optional kwarg + one coordinator call |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | MODIFY | Inject the coordinator |
| `packages/ai-parrot/tests/flows/dev_loop/test_research_partner_seam.py` | CREATE | Seam tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_flow.complementary_research import ComplementaryResearchCoordinator
from parrot.flows.dev_loop.dispatchers import ClaudeCodeDispatcher   # research.py:37
from parrot.flows.dev_loop.models import BugBrief, ResearchOutput    # research.py:41-45
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):                                     # line 195
    def __init__(self, *, dispatcher: ClaudeCodeDispatcher, ...)     # line 218
        object.__setattr__(self, "_dispatcher", dispatcher)          # line 231
    async def execute(...) -> ResearchOutput:                        # line 262
        brief: BugBrief = shared["bug_brief"]                        # line 269
    research_out: ResearchOutput = await self._dispatcher.dispatch(  # line 423
        ..., output_model=ResearchOutput,                            # line 426
    )
# Ordering pinned by a unit test — Jira issue is created BEFORE the dispatch
# (spec §4 test_research_node_creates_jira_then_dispatches, research.py:282).
# Allowed tools include "SlashCommand" so the subagent runs /sdd-spec and
# /sdd-task (research.py:376-385). Do NOT change this.
```

### Does NOT Exist

- ~~a `coordinator` kwarg on `ResearchNode`~~ — new; must default to `None`.
- ~~a shared partner seam already in `dev_loop`~~ — the coordinator lives in
  `dev_flow/complementary_research.py`; `dev_loop` imports it. This cross-package
  import direction is intentional (dev_flow owns the seam, per spec §3 Module 4).
- ~~partner authority over the SDD document~~ — `ResearchNode`'s Claude seat keeps
  sole authorship, slash-command execution, and worktree creation. The partner
  contributes findings only (spec §1: this narrows FEAT-405's non-goal rather than
  reversing it).

---

## Implementation Notes

### Pattern to Follow

Mirror TASK-2633's `IdeationNode` seam exactly — same kwarg name, same
`Optional` handling, same "coordinator never raises" assumption. If the two seams
diverge in shape, one of them is wrong.

```python
findings = None
if self._coordinator is not None:
    findings = await self._coordinator.research(...)
# fold into the dispatch payload
```

### Key Constraints

- **Byte-identical when disabled**, same as TASK-2633.
- Do not disturb the Jira-then-dispatch ordering (`research.py:282`) — it is
  pinned by an existing test.
- Do not touch the `SlashCommand` allowed-tools list.
- `object.__setattr__` for instance attrs, matching `research.py:231`.
- Async throughout; `self.logger`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_flow/nodes/ideation.py` — the sibling seam
  from TASK-2633; keep them symmetrical.

---

## Acceptance Criteria

- [ ] `ResearchNode(coordinator=None)` produces a **byte-identical** dispatch payload to pre-feature
- [ ] Findings reach the `sdd-research` dispatch payload when a coordinator is injected
- [ ] Jira-then-dispatch ordering unchanged (existing test still passes)
- [ ] `SlashCommand` allowed-tools list unchanged
- [ ] The seam is shape-identical to TASK-2633's (D1: one mechanism, not a fork)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_research_partner_seam.py -v`
- [ ] Existing research-node tests still pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -k research -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`

---

## Test Specification

```python
class TestResearchNodePartnerSeam:
    async def test_unchanged_when_coordinator_none(self):
        """GUARD: dispatch payload byte-identical to pre-feature behavior."""

    async def test_findings_reach_dispatch_payload(self):
        """Injected coordinator's findings appear in the sdd-research payload."""

    async def test_jira_created_before_dispatch_still_holds(self):
        """Existing ordering guarantee is not disturbed."""

    async def test_degraded_partner_does_not_fail_run(self):
        """Coordinator returns None => research proceeds single-agent."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 5) and TASK-2633's implementation — the two seams
   must be symmetrical.
2. **Check dependencies** — TASK-2632 in `sdd/tasks/completed/`. TASK-2633 need not
   be complete, but read it if it is.
3. **Verify the Codebase Contract** — **re-read `research.py` carefully**: FEAT-479
   is actively editing this file, so line numbers and surrounding code may have moved.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** — strictly additive.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2634-research-node-seam.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below, noting any FEAT-479 conflict encountered.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-01
**Notes**: FEAT-479 had already fully merged to `dev` before this task
started (confirmed: `devflow-telemetry-accounting` index shows all tasks
`done`, `completed_at` set) — no live conflict encountered; the current
`research.py`/`factories.py` on disk already reflect its changes and the
Codebase Contract's line numbers were re-verified against that state.

Added `coordinator: Optional[ComplementaryResearchCoordinator] = None` to
`ResearchNode.__init__` (`object.__setattr__`, matching the file's
existing pattern) and one coordinator call in `execute()`, placed
alongside the EXISTING wiki-search/graph-memory context-injection block
(right after Jira resolution, right before dispatch — same place, same
mechanism). `factories.py` (`dev_loop`, NOT `dev_flow` — a different file
from TASK-2633's) gained a mirrored `research_coordinator` kwarg
(defaults to a fresh inert `ComplementaryResearchCoordinator()`), wired
into `ResearchNode` in `research_factory`.

5 tests in `test_research_partner_seam.py`, all passing: the
coordinator-omitted guard is IDENTITY-equal (`sent_brief is good_brief`,
not just field-equal — see Deviation 1), findings reach the dispatch
payload, Jira-then-partner-then-dispatch ordering holds, a degraded/
`None` coordinator still completes the run, and `SlashCommand`
allowed-tools stays unchanged. Full `pytest packages/ai-parrot/tests/flows/dev_loop/`
sweep (1129 passed, 3 pre-existing `sdd-secondopinion`-prompt-parity
failures reproduce identically on unmodified `dev`) and
`pytest packages/ai-parrot/tests/flows/dev_flow/` (216 passed) both show
zero regressions. `ruff check` clean on all three changed/created files
(pre-existing lint debt count on `research.py`/`factories.py` unchanged
from `dev` baseline after fixing the import-order-only findings my own
edits introduced).

**Deviations from spec**:
1. **No new field on `BugBrief`/`WorkBrief`.** Unlike `IdeationNode`
   (TASK-2633), which has a small LOCAL `_IdeationBrief` model it fully
   owns, `ResearchNode` dispatches the SHARED `BugBrief`/`WorkBrief`
   model — not in this task's Files to Create/Modify list
   (`models.py`/`base.py` untouched). `research.py` already has a
   sanctioned, existing mechanism for exactly this kind of best-effort
   supplementary content: the wiki-search/graph-memory blocks append a
   labeled `## <Section>\n<text>` string to `extra_context_parts`, which
   only then triggers a SINGLE `brief.model_copy(update={"description":
   ...})` if non-empty. The partner's findings are folded in via the
   identical mechanism (`## Complementary research findings\n<rendered>`)
   rather than inventing a second injection path or a new shared-model
   field. Consequence: with the coordinator disabled/omitted AND no wiki/
   graph-memory context either, `dispatch_brief` is not just field-equal
   but OBJECT-IDENTICAL to the original `brief` (no `model_copy` call
   happens at all) — a strictly stronger "byte-identical" guarantee than
   TASK-2633's, verified directly (`test_unchanged_when_coordinator_none`
   asserts `sent_brief is good_brief`).
2. **`slug` is the resolved Jira issue key** (lowercased, e.g.
   `"ops-1"`), not a title-derived slugification. Unlike `IdeationNode`
   (no stable identifier exists before the ideation dispatch, forcing a
   provisional slugify-from-title), `ResearchNode` already resolves a
   real, stable, unique identifier — the Jira ticket — strictly BEFORE
   the coordinator call (ordering pinned by the pre-existing
   `test_research_node_creates_jira_then_dispatches` test, left
   untouched). Reusing it avoids inventing a second slugification
   algorithm and gives `sdd/proposals/<jira-key>.research.md` a
   naturally unique, human-traceable name.
