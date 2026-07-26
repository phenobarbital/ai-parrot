# TASK-1920: JudgePanelReviewDispatcher — N-judge majority code review

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1918
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Generalizes the single hardcoded judge seam
(`ParallelPerspectiveReviewDispatcher._run_judge`, code_review.py:460,
Claude-shaped profile :500-506) into a configurable N-judge panel with
majority decision. This is the lowest-contention module in the feature
(only `code_review.py` + `conf.py`) — safe to implement early/in parallel.

---

## Scope

- Implement `JudgePanelReviewDispatcher(AbstractCodeReviewDispatcher)` in
  `parrot/flows/dev_loop/code_review.py`:
  - ctor: `judges: List[JudgeSpec]` (default from
    `default_judge_panel()`), `decision: str = "majority"`, plus the redis/
    concurrency params the sibling dispatchers take.
  - Builds one dispatcher per judge via `build_dispatcher()`
    (agent_builder.py:98) mapping `JudgeSpec → DevAgentSpec`.
  - Each judge reviews independently with the SAME neutral brief; the codex
    judge uses the `sdd-secondopinion` profile (adversarial, advisory
    conventions preserved).
  - Decision: `passed = strict majority of non-errored judges`; tie OR an
    abstention/infra-error that breaks majority → escalate outcome
    (`passed=False` + escalation marker consumed by QANode's existing
    advisory/escalation path); majority of panel down → escalate
    (fail-closed).
  - Aggregated `CodeReviewVerdict.findings` tagged with `source=<judge>`
    (reuse `AdversarialFinding.source` convention, models.py:793).
- Register in `CodeReviewDispatcherFactory` as `"judge-panel"`.
- Add `DEV_LOOP_JUDGE_PANEL` conf key (JSON spec of judges; empty → default
  panel), following the `DEV_LOOP_CODEREVIEW_*` block style (conf.py:928-999).
- Unit tests with stubbed judge dispatchers.

**NOT in scope**: QANode changes (none needed — dispatcher is pluggable),
FeedbackRouterNode (TASK-1923), session-state recording of verdicts (the
NODE records actions, not the dispatcher — TASK-1925 wires it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py` | MODIFY | New dispatcher + factory registration |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_LOOP_JUDGE_PANEL` |
| `packages/ai-parrot/tests/flows/dev_loop/test_judge_panel.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory  # verified 2026-07-27
from parrot.flows.dev_loop.agent_builder import build_dispatcher           # verified 2026-07-27
from parrot.flows.dev_loop.models import JudgeSpec, JudgePanelConfig, default_judge_panel  # from TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py  (verified 2026-07-27)
class AbstractCodeReviewDispatcher(ABC):   # :59 — advisory=False :74, review() :80
class CodeReviewDispatcherFactory:         # :133 — register :139, create :148
# Registered names: "claude-code" :159, "codex" :180, "gemini" :200,
#                   "codex-adversarial" :220 (advisory), "parallel" :292 (advisory)
class ParallelPerspectiveReviewDispatcher: # :293
    # ctor: primary, adversary, judge_dispatcher=None, judge_enabled=False (:312-325)
    # _merge_verdicts :357/:411
    # _run_judge :460 — SINGLE judge, hardcoded Claude-shaped profile :500-506
    #   ← the exact seam this task generalizes; follow its dispatch/parse flow

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:98
def build_dispatcher(spec: DevAgentSpec, *, redis_url, max_concurrent,
    stream_ttl_seconds, config_getter=...) -> Tuple[DevLoopCodeDispatcher, BaseModel]: ...
# 7 backends, default model per env (:136-201)

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class CodeReviewVerdict(BaseModel):   # :757 — passed, findings, summary, files_modified
class AdversarialFinding(CodeReviewFinding):  # :793 — source, disposition

# packages/ai-parrot/src/parrot/conf.py — style reference
# DEV_LOOP_CODEREVIEW_AGENT :928-934, DEV_LOOP_ADVERSARIAL_MODEL :986-988,
# DEV_LOOP_CODEREVIEW_JUDGE :995-999
```

### Does NOT Exist
- ~~`judges: List[...]` anywhere in code_review.py~~ — only the single optional `judge_dispatcher` (default off). This task creates the panel.
- ~~`DEV_LOOP_JUDGE_PANEL`~~ — this task creates it.
- ~~`sdd-secondopinion` in `ClaudeCodeDispatchProfile`~~ — Codex-only profile (models.py:557,:884); route the adversarial judge through the codex backend.
- ~~`gate_ttl_for("review_escalation")`~~ — KeyError; TTL read directly from conf (qa.py:473). The dispatcher does NOT open gates — QANode owns that.

---

## Implementation Notes

### Pattern to Follow
`ParallelPerspectiveReviewDispatcher` (code_review.py:293) is the template:
concurrent judge execution (`asyncio.gather` with per-judge error capture),
verdict merge, advisory semantics. Generalize `_run_judge`'s profile
construction using `build_dispatcher()` per `JudgeSpec` instead of the
hardcoded Claude profile.

### Key Constraints
- Judge-down degradation mirrors the existing `_resolve_side` behavior
  (errored side → nit advisory finding); decide with remaining judges.
- Majority math on NON-errored judges; document tie/abstention → escalate in
  the class docstring (spec §5 criterion).
- Async throughout; `self.logger` for per-judge outcomes.
- Do not modify existing registered dispatchers' behavior.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:293-` — template
- `sdd/specs/devloop-enhancement.spec.md` §2 (panel decision rules), §4 (test matrix)

---

## Acceptance Criteria

- [ ] `CodeReviewDispatcherFactory.create("judge-panel", ...)` returns the new dispatcher
- [ ] 2/3 pass → passed; 1/3 pass → failed; 2/2 split → escalate (never pass)
- [ ] One judge errored → decision from remaining; majority errored → escalate (fail-closed)
- [ ] Findings tagged `source=<judge>`
- [ ] `DEV_LOOP_JUDGE_PANEL` unset → `default_judge_panel()` used
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_judge_panel.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_judge_panel.py
# Stub judges as fakes returning canned CodeReviewVerdict / raising.
def test_majority_pass(): ...
def test_majority_fail(): ...
def test_tie_escalates(): ...
def test_judge_down_degrades_to_remaining(): ...
def test_majority_down_escalates(): ...
def test_findings_source_tagged(): ...
def test_factory_registration(): ...
def test_default_panel_from_conf_unset(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 QA + Judge Panel, §6, §7)
2. **Check dependencies** — TASK-1918 completed
3. **Verify the Codebase Contract** — re-grep line anchors; FEAT-375 code is on dev, but check whether FEAT-377 merge shifted `code_review.py`
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
