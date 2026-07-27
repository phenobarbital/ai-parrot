# TASK-1921: PlannerNode + sdd-planner subagent — document-driven planning

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1918, TASK-1919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The feature-mode replacement for `ResearchNode`: instead of
log triage + mandatory Jira, it takes a `FeatureBrief` document
(brainstorm/proposal/spec), dispatches an `sdd-planner` subagent that
generates missing SDD artifacts (spec via `/sdd-spec`, task index via
`/sdd-task`) and the feature worktree, then derives the effective dev-agent
pool size from the task dependency graph.

---

## Scope

- Implement `PlannerNode(DevLoopNode)` in
  `parrot/flows/dev_loop/nodes/planner.py`, node id `"planner"`, registered
  via `@register_dev_loop_node`:
  - Reads `shared["feature_brief"]` (a `FeatureBrief`, placed by the
    classifier — TASK-1925).
  - Dispatches subagent `sdd-planner` with the document content as context;
    prepend graph context from
    `DevLoopGraphMemory.build_research_context()` ONLY if available (see
    contract — degrade to empty context with a debug log when absent).
  - Parses the subagent's final JSON into `PlannerOutput`.
  - Jira: pass through `FeatureBrief.jira_issue_key` — the node performs NO
    Jira creation; if a key is present it is recorded in `PlannerOutput` for
    downstream linking.
  - Pool sizing: effective `DevAgentPoolConfig` = brief's `dev_agents` if
    set; else width of the first `TaskScheduler.from_worktree()` wave,
    capped at the node's `development_pool_max` param; single task / no
    depends_on → single agent.
  - Cycle in task deps (`TaskScheduler` ValueError) → node fails with the
    diagnostic (no dev dispatch).
  - Records planner completion via existing session-state mechanisms.
- Write the `sdd-planner` subagent prompt:
  - `parrot/flows/dev_loop/_subagent_data/sdd-planner.md` (authoritative —
    the dispatcher loads ONLY from here via `load_subagent_definition`).
  - Mirror copy in `.claude/agents/sdd-planner.md`.
  - Prompt behavior (patterned on `sdd-research.md`): if `document_kind !=
    "spec"` run `/sdd-spec`; then `/sdd-task` (or validate an existing
    index); create worktree `git worktree add -b feat-<id>-<slug> ... HEAD`
    from the base branch; emit ONE final JSON matching `PlannerOutput` — no
    prose.
- Unit tests with a stubbed dispatcher.

**NOT in scope**: the `_CEL_IS_FEATURE` edge and classifier routing
(TASK-1925), DevelopmentNode changes (none), SynthesisNode (TASK-1922).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py` | CREATE | PlannerNode |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md` | CREATE | Subagent prompt (authoritative) |
| `.claude/agents/sdd-planner.md` | CREATE | Mirror of the prompt |
| `packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.base import register_dev_loop_node, DevLoopNode  # verified 2026-07-27
from parrot.flows.dev_loop.task_scheduler import TaskScheduler                    # verified
from parrot.flows.dev_loop.models import FeatureBrief, PlannerOutput, DevAgentPoolConfig  # TASK-1918
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:119  (verified 2026-07-27)
class ResearchNode(DevLoopNode):
    # execute :162-295 — THE dispatch pattern to copy (subagent dispatch,
    # JSON parse of final output, session-state recording, error paths).
    # ⚠ ResearchNode ALWAYS creates Jira (:85-89 issue-type map) — PlannerNode must NOT.
    # /sdd-spec, /sdd-task, worktree creation live in the subagent PROMPT
    # (_subagent_data/sdd-research.md:38-44), not in Python — same for sdd-planner.

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43
class TaskScheduler:
    @classmethod
    def from_worktree(cls, worktree_path, feature_slug): ...  # :111
    def next_wave(self) -> List[TaskRef]: ...  # :166  (Kahn; cycle → ValueError :128)

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class ResearchOutput(BaseModel):  # :312 — field-shape reference for PlannerOutput
class ClaudeCodeDispatchProfile(BaseModel):  # :519 — subagent Literal includes
    # "sdd-planner" after TASK-1918
```

### Does NOT Exist
- ~~`DevLoopGraphMemory` / `graph_memory.py`~~ — FEAT-377 TASK-1914/1915, in
  progress on branch `feat-377-graphindex-as-engineering-devloop`, NOT on dev
  as of 2026-07-27. **At task start, check if merged.** If yes: import and
  call `build_research_context()` per its landed signature. If no: guard the
  import (`try/except ImportError`) and proceed with empty graph context —
  the node must work without it.
- ~~`load_subagent_definition` reading from `.claude/agents/`~~ — the
  dispatcher loads ONLY from `_subagent_data/`; `.claude/agents/` is a
  human-facing mirror.
- ~~Jira issue creation in feature-mode~~ — explicitly forbidden by spec (Jira optional, link-only).
- ~~`TaskScheduler.from_index_file` returning waves for a single task~~ — single task/no deps degrades to `None`/single wave; handle both.

---

## Implementation Notes

### Pattern to Follow
Copy `ResearchNode.execute` (research.py:162-295) structure: build dispatch
profile → dispatch → parse final JSON → validate into Pydantic output →
publish to shared state. Strip the Jira-creation and log-excerpt logic.

### Key Constraints
- Async throughout; `self.logger` on dispatch start/end, degradations, and
  pool-sizing decision (log chosen pool + rationale).
- Prompt must instruct the subagent to emit ONE final JSON object matching
  `PlannerOutput` exactly — no prose, no fences (same convention as
  `sdd-research.md`).
- `document_kind: spec` → prompt path skips `/sdd-spec` (test asserts the
  rendered prompt contains the conditional instruction).
- Worktree branch naming: `feat-<id>-<slug>` per repo convention.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` — prompt template & output-JSON convention
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` — node pattern

---

## Acceptance Criteria

- [ ] `PlannerNode` registered under node id `"planner"`; dispatches `sdd-planner`; returns validated `PlannerOutput`
- [ ] No Jira toolkit call anywhere in the node (test with spy)
- [ ] Pool sizing: brief override wins; else wave-1 width capped at `development_pool_max`; single-task degrades to 1
- [ ] Dependency cycle → run fails with diagnostic, no dev dispatch
- [ ] Missing `DevLoopGraphMemory` → node still works (empty graph context, debug log)
- [ ] `sdd-planner.md` exists in `_subagent_data/` AND `.claude/agents/` (identical bodies)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_planner_node.py
# Stub the dispatcher to return canned PlannerOutput JSON.
async def test_planner_happy_path_proposal(): ...
async def test_planner_spec_passthrough_skips_sdd_spec(): ...
async def test_planner_no_jira_calls(): ...
def test_pool_sizing_brief_override(): ...
def test_pool_sizing_wave_width_capped(): ...
def test_pool_sizing_single_task(): ...
async def test_cycle_fails_before_dev_dispatch(): ...
async def test_graph_memory_absent_degrades(): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Internal Behavior item 2, §6, §7)
2. **Check dependencies** — TASK-1918, TASK-1919 completed
3. **Verify the Codebase Contract** — MUST check FEAT-377 merge status first
   (`git log dev -- packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py`);
   re-grep all anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
