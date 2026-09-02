# TASK-2731: Per-judge attribution for the QA review panel

**Feature**: FEAT-496 — Dev-Loop Dispatch Event Legibility
**Spec**: `sdd/specs/dev-loop-dispatch-event-legibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2724, TASK-2725
**Assigned-to**: unassigned

---

## Context

Spec §1 root cause 6, §3 Module 7, §5 AC8.

`JudgePanelReviewDispatcher.review` (`code_review.py:775-800`) fans out every
judge concurrently through `asyncio.gather`, and every one of them dispatches
with the **same** `node_id=node_id` (i.e. `"qa"`). Their events therefore
interleave on one Redis stream with nothing distinguishing them. The panel
does record per-judge outcomes — but only at the very end, via
`JudgeVerdictRecorded` (`code_review.py:812-830`). While the review is
running, which can be many minutes, the console shows an undifferentiated
blur.

The fix is the same `DispatchLabels` mechanism as TASK-2730, applied at the
review layer: each judge's dispatch gets `judge_id`, `agent` and `model`.
`AbstractCodeReviewDispatcher.review` (`code_review.py:108`) already funnels
every non-panel reviewer through one `self._dispatcher.dispatch(...)` call at
`code_review.py:138`, so threading a `labels` parameter down the review
hierarchy is a small, well-bounded change.

---

## Scope

- Add `labels: Optional[DispatchLabels] = None` to
  `AbstractCodeReviewDispatcher.review` (`code_review.py:108`) and forward it
  to `self._dispatcher.dispatch(...)` (`code_review.py:138`).
- Thread it through every override:
  `CodexAdversarialReviewDispatcher.review` (`code_review.py:282`),
  `ParallelPerspectiveReviewDispatcher.review` (`code_review.py:360`),
  `JudgePanelReviewDispatcher.review` (`code_review.py:775`), and
  `MantleAdversarialReviewDispatcher.review` (`mantle.py:187`).
- In `JudgePanelReviewDispatcher.review`, build **one `DispatchLabels` per
  judge** inside the `asyncio.gather` fan-out, carrying `judge_id`, the
  judge's backend as `agent`, and `spec.model`.
- In `ParallelPerspectiveReviewDispatcher.review`, label the primary and
  adversary sides distinctly (`judge_id="primary"` /
  `judge_id="codex-adversarial"`, matching the labels already used at
  `code_review.py:385-386`).
- Label QANode's own dispatches with their subagent name:
  `nodes/qa.py:475`, `:866`, `:969`, `:1037`, `:1150`.
- Tests asserting per-judge labels.

**NOT in scope**: the dev-agent pool (TASK-2730); dispatcher internals;
session state; console HTML; changing the panel's majority decision rule.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | `labels` through the review hierarchy; per-judge labels in the panel |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/mantle.py` | MODIFY | accept `labels` on the overriding `review` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | label QANode's own dispatches with their subagent |
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY or CREATE | per-judge label assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# add (created by TASK-2722):
from parrot.flows.dev_loop.models import DispatchLabels
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                      # line 87
    agent_name: str                                           # line 103
    advisory: bool = False                                    # line 104

    async def review(self, *, brief: BaseModel, run_id: str, node_id: str,
                     cwd: str, session_host: Optional[SessionHost] = None,
                     round: str = "") -> CodeReviewVerdict:   # line 108
        try:
            return await self._dispatcher.dispatch(           # line 138  ← THE choke point
                brief=brief, profile=self.build_review_profile(),
                output_model=CodeReviewVerdict, run_id=run_id,
                node_id=node_id, cwd=cwd, session_host=session_host,
            )                                                 # lines 139-146
        except Exception as exc:                              # line 147
            # degrade-on-infra-error: returns a PASSING verdict
            # with a nit finding                              # lines 148-159

    @abstractmethod
    def build_review_profile(self) -> BaseModel: ...          # lines 161-163

class ClaudeCodeReviewDispatcher(AbstractCodeReviewDispatcher)# line 193
class CodexCodeReviewDispatcher(AbstractCodeReviewDispatcher) # line 214
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher)  # line 245
    async def review(...)                                     # line 282
        verdict = await super().review(...)                   # lines 302-309
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher)  # line 319
    async def review(...)                                     # line 360
        primary_result, adversary_result = await asyncio.gather(
            self._primary.review(...), self._adversary.review(...),
            return_exceptions=True)                           # lines 370-379
        # fixed side labels "primary" / "codex-adversarial"   # lines 385-386
class JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher)# line 574
    def _build_judge(self, spec: JudgeSpec
                     ) -> Tuple[str, AbstractCodeReviewDispatcher]:  # line 712
    async def review(...)                                     # line 775
        judges = [self._build_judge(spec) for spec in self._judge_specs]  # 785
        results = await asyncio.gather(*(
            judge.review(brief=brief, run_id=run_id, node_id=node_id,
                         cwd=cwd, session_host=session_host, round=round)
            for _judge_id, judge in judges), return_exceptions=True)  # 787-800
        # per-judge JudgeVerdictRecorded actions              # lines 812-830

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/mantle.py
class MantleAdversarialReviewDispatcher(AbstractCodeReviewDispatcher)  # line 106
    async def review(self, *, brief, run_id, node_id: str, cwd,
                     session_host=None, round="")             # line 187
        with usage_attribution(run_id, seat=node_id):         # line 220

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
    # QANode's own dispatches (subagent sdd-qa / triage worker):
    #   node_id=self.name                                     # lines 475, 866, 969, 1037
    #   node_id="qa"                                          # line 1150
    verdict = await self._active_reviewer(shared).review(...)  # line 863
```

### Does NOT Exist

- ~~a `MantleCodeDispatcher` development dispatcher~~ — `mantle.py` defines
  only the profile (`:65`) and the **review** dispatcher (`:106`). Its
  `review()` (`:187`) does not delegate to a development `dispatch()`, so it
  accepts `labels` and may simply ignore it (or use it to enrich its
  `usage_attribution` seat) — it has no dispatch payload to stamp.
- ~~a `judge_id` field on any dispatch payload today~~ — judge identity
  exists only on `JudgeVerdictRecorded`, emitted after the fact.
- ~~per-judge `node_id`s~~ — every judge dispatches under the same `node_id`.
  Do **not** change `node_id` to a per-judge value: `NodeId` is a closed
  `Literal` in `session_state.py:140` and a `qa.judge1` seat would be
  swallowed. Identity travels in `labels`, not in `node_id`.
- ~~`JudgeSpec.model` being non-empty~~ — an empty model means the backend's
  own default; pass it through as-is.

### Existing behaviour that MUST NOT change

```python
# code_review.py:147-159 — degrade-on-infra-error returns a PASSING verdict.
# code_review.py: panel decision rule — strict majority of NON-errored judges;
#   a tie, or errored judges forming a majority, escalates (passed=False).
```

---

## Implementation Notes

### Thread, then fan out

Add the parameter to the ABC first and forward it at the single
`self._dispatcher.dispatch(...)` call (`code_review.py:138`). Every non-panel
reviewer inherits the behaviour for free. Then override-by-override, forward
it up through `super().review(...)`.

In the panel:

```python
results = await asyncio.gather(*(
    judge.review(
        brief=brief, run_id=run_id, node_id=node_id, cwd=cwd,
        session_host=session_host, round=round,
        labels=DispatchLabels(
            judge_id=judge_id,
            agent=spec.agent,
            model=spec.model or "",
            subagent="sdd-secondopinion" if getattr(judge, "advisory", False) else "",
            attempt=_attempt_from(round),
        ),
    )
    for (judge_id, judge), spec in zip(judges, self._judge_specs)
), return_exceptions=True)
```

`judges` and `self._judge_specs` are already zipped together later at
`code_review.py:812-814`, so the pairing is an established pattern in this
method — reuse it rather than re-deriving the spec from the judge.

### Key Constraints

- **Do not change `node_id`.** Judge identity rides in `labels.judge_id`.
- **Do not change the decision rule** or the degrade-on-infra-error path.
- Labels are metadata: a judge whose underlying dispatcher does not accept
  `labels` must still run (best-effort, same as TASK-2730).
- Keep `JudgeVerdictRecorded` exactly as it is — this task adds *live*
  attribution, it does not replace the terminal record.
- `code_review.py` uses lazy imports inside `_build_judge` for a documented
  circular-import reason (`code_review.py:715-725`) — do not hoist them.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:812-830` — the existing per-judge attribution at the end of the panel; the live labels should use the same `judge_id` values.
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:385-386` — the fixed `"primary"` / `"codex-adversarial"` side labels to reuse for the parallel reviewer.

---

## Acceptance Criteria

- [ ] `AbstractCodeReviewDispatcher.review` accepts `labels=` and forwards it to `self._dispatcher.dispatch(...)`.
- [ ] Every `review()` override accepts and forwards `labels=` (`CodexAdversarialReviewDispatcher`, `ParallelPerspectiveReviewDispatcher`, `JudgePanelReviewDispatcher`, `MantleAdversarialReviewDispatcher`).
- [ ] In a 3-judge panel, each judge's dispatch receives a **distinct** `judge_id`, with the correct `agent` and `model`.
- [ ] `judge_id` values match the ones used for `JudgeVerdictRecorded`.
- [ ] `ParallelPerspectiveReviewDispatcher` labels its two sides `"primary"` and `"codex-adversarial"`.
- [ ] QANode's own dispatches carry their `subagent` name in the labels.
- [ ] `node_id` is unchanged for every judge (still `"qa"`).
- [ ] The panel's majority decision rule and the degrade-on-infra-error path are unchanged, with their existing tests passing untouched.
- [ ] A judge whose dispatcher does not accept `labels` still runs.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_code_review.py  (additions)

class RecordingReviewDispatcher:
    """Stands in for a judge's underlying development dispatcher."""
    def __init__(self): self.calls = []
    async def dispatch(self, *, brief, profile, output_model, run_id,
                       node_id, cwd, session_host=None, labels=None):
        self.calls.append((node_id, labels))
        return CodeReviewVerdict(passed=True, findings=[])


class TestJudgePanelLabels:
    async def test_each_judge_gets_a_distinct_judge_id(self):
        panel = JudgePanelReviewDispatcher(judges=[...3 specs...])
        await panel.review(brief=..., run_id="r1", node_id="qa", cwd="/wt")
        ids = [labels.judge_id for _n, labels in recorded_calls]
        assert len(set(ids)) == 3

    async def test_judge_labels_carry_backend_and_model(self):
        ...
        assert labels.agent in {"claude-code", "codex", "mantle"}

    async def test_node_id_is_still_qa(self):
        """NodeId is a closed Literal — identity must ride in labels."""
        assert all(n == "qa" for n, _l in recorded_calls)

    async def test_judge_ids_match_verdict_records(self, session_host):
        """Live labels and the terminal JudgeVerdictRecorded must agree."""
        ...

    async def test_decision_rule_unchanged(self):
        """Majority + fail-closed escalation still behave exactly as before."""
        ...

    async def test_judge_without_labels_kwarg_still_runs(self):
        ...


class TestParallelPerspectiveLabels:
    async def test_sides_are_labelled(self):
        ...
        assert {l.judge_id for _n, l in calls} == {"primary", "codex-adversarial"}
```

---

## Agent Instructions

1. **Read the spec** — §1 root cause 6, §3 Module 7, §5 AC8.
2. **Check dependencies** — TASK-2724 and TASK-2725 must be in `sdd/tasks/completed/` (the judge backends are Claude- and Codex-shaped).
3. **Verify the Codebase Contract** — read `code_review.py:108-160` and `:775-830` before editing; note the lazy imports in `_build_judge`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** — ABC first, then each override, then the panel fan-out.
6. **Verify** all acceptance criteria; the unchanged-decision-rule one is the safety check.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `AbstractCodeReviewDispatcher.review` accepts `labels:
Optional[DispatchLabels] = None` and forwards it to
`self._dispatcher.dispatch(...)`, with an inner narrow `except TypeError`
(retrying once without labels) so a dispatcher that hasn't declared
`labels=` still actually runs the review rather than silently degrading to
a fabricated pass. Threaded through `CodexAdversarialReviewDispatcher`,
`ParallelPerspectiveReviewDispatcher` (labels its two sides `"primary"` /
`"codex-adversarial"`), `JudgePanelReviewDispatcher` (one `DispatchLabels`
per judge, zipped with `self._judge_specs`), and
`MantleAdversarialReviewDispatcher` (no dispatch payload to stamp; folds
`judge_id` into its `usage_attribution` seat instead, per the task's own
guidance). `node_id` is unchanged everywhere — identity rides in `labels`.
QANode's three own dispatches (deterministic `sdd-qa` gate, the
`sdd-codereview` reviewer call, and the `sdd-worker` triage dispatch) are
now labelled with their subagent name.

Found and fixed a real bug while writing the panel/parallel label tests:
building each judge's/side's `DispatchLabels`-carrying coroutine directly
inside the `asyncio.gather(...)` argument list means a duck-typed
reviewer's `TypeError` (no `labels=` parameter) is raised while the
argument list is being *constructed* — before any coroutine is scheduled —
so `return_exceptions=True` cannot catch it and the exception propagates
out of `review()` entirely, crashing the *whole* panel/parallel dispatch
for every judge, not just the non-compliant one. Fixed by wrapping each
judge's/side's dispatch in its own coroutine (`_review_one_judge`,
`_review_side`) with its own inner `except TypeError` fallback, so the
call — and any resulting exception — happens inside a scheduled coroutine
where `return_exceptions=True` (and the per-call fallback) can actually
help. 12 new tests (7 in `test_judge_panel.py`, 5 across
`test_code_review.py`/qa test files already covered by existing suites);
all pre-existing tests in `test_code_review.py` (44), `test_judge_panel.py`
(25), and the qa test files (53) pass unchanged; full `dev_loop` suite
green (same 3 pre-existing unrelated failures in
`test_recovery_lifecycle.py`).

**Deviations from spec**: none — the per-judge/per-side coroutine wrapper
was necessary to make the spec's own "a judge whose dispatcher does not
accept labels still runs" acceptance criterion actually hold, not a
deviation from it.
