# TASK-2653: Single-task collapse rule + INFO deployment log + planner backend respect

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (goals G3/G4). Lives entirely in dev_loop node code and
benefits both flows. Makes `PlannerOutput.suggested_pool` consumed for the
first time, adds the operator-visible deployment log, and stops the planner
hardcoding claude-code specs.

---

## Scope

- **Collapse rule** in `DevelopmentNode`: when the per-spec task index is
  readable and contains exactly one `TASK-`, deploy a single agent — the
  first model from `PlannerOutput.suggested_pool` (read from shared data),
  falling back to the first configured `pool_config` spec. More than one
  task ⇒ full configured pool. Unreadable index ⇒ keep today's degradation
  (warning at `development.py:202-206`). No new typed field, no
  `_SHARED_DATA_ALLOWLIST` change (`planner_output` is already allowlisted).
- **INFO deployment log** in `_execute_pool`, immediately after
  `pool = DevAgentPool.build(...)` (`development.py:633`): count + each
  worker as `wN=<backend>:<model>`, e.g.
  `Deploying 2 dev sub-agents: w1=nova:zai.glm-5, w2=nova:qwen.qwen3-coder-480b-a35b-v1:0`.
  Also log at INFO when the collapse rule reduces to one agent (say why).
- **Planner backend respect**: `PlannerNode._resolve_pool`
  (`planner.py:246-299`) derives specs from the configured pool (brief
  `dev_agents` / injected pool) instead of always
  `DevAgentSpec(agent="claude-code")` (`:286`, `:298`); keep claude-code as
  the fallback when nothing is configured.
- Unit tests for all three behaviors (caplog for the logs).

**NOT in scope**: dev_flow plan threading (TASK-2652), model-plan module
(TASK-2651), review/console work.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | collapse rule + INFO logs |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py` | MODIFY | `_resolve_pool` backend respect |
| `packages/ai-parrot/tests/flows/dev_loop/test_single_task_collapse.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.base import DevAgentSpec  # models/base.py:412
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py (verified 2026-09-01)
# :142-220 execute() — entry; :400-415 _resolve_pool_config (reads shared["work_brief"|"bug_brief"].dev_agents)
# :421-534 _execute_single; :608-704 _execute_pool
# :633  pool = DevAgentPool.build(pool_cfg, self._dispatcher_builder, self._pool_max)
#       ← INFO deployment log goes IMMEDIATELY after this line (none exists today)
# :202-206 unreadable-index degradation warning (keep)
# :212-218 existing INFO "should_fan_out(...) -> False" (style precedent)
# self.logger name: parrot.node.development (bots/flows/core/node.py:121,:131-133)

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/planner.py
# :246-299 _resolve_pool — brief override wins, else first-wave width capped at _pool_max
# :286,:298 DevAgentSpec(agent="claude-code") hardcoded (replace with configured-pool derivation)
# :171 planner_out.model_copy(update={"suggested_pool": pool_cfg}) — suggested_pool is set here

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
# :282-395 run_wave; :320-322 round-robin; :348-377 retry-on-next-worker
# DevAgentPool.build capping warning at :138-144
```

### Does NOT Exist
- ~~Any existing consumer of `PlannerOutput.suggested_pool`~~ — this task creates the FIRST one (`planner.py:171` sets it; nothing reads it as of 2026-09-01).
- ~~A `single_agent_sufficient` flag / new typed result~~ — deliberately NOT added (spec resolved decision); the task count IS the signal.
- ~~An INFO deployment log in `_execute_pool`~~ — none exists today.
- ~~`_SHARED_DATA_ALLOWLIST` changes~~ — forbidden; `planner_output` is already in the allowlist (`dev_loop/checkpoint.py`).

---

## Implementation Notes

### Key Constraints
- Grep for how `DevelopmentNode` currently reads the task index (the
  `:202-206` degradation path shows the read primitive) and reuse it for
  the task count — do not invent a second index reader.
- Collapse only SHRINKS the pool (config is authoritative; never grow).
- Log via the existing `self.logger`, INFO level, message format from the
  spec (G4); match existing message style at `:212-218`.
- The planner change must keep `claude-code` as fallback when no pool is
  configured — existing dev_loop behavior unchanged in that case.

### References in Codebase
- `development.py:454-473` — existing single-agent honour/warn block (style)
- `agent_pool.py:150` — worker materialization via `agent_builder.build_dispatcher`

---

## Acceptance Criteria

- [ ] One TASK in readable index ⇒ one worker, first `suggested_pool` model; INFO says so
- [ ] Multi-task index ⇒ all configured specs deployed
- [ ] Empty/absent `suggested_pool` ⇒ first configured spec used
- [ ] Unreadable index ⇒ existing warning + degradation preserved
- [ ] INFO log enumerates `wN=backend:model` for every worker (caplog-tested)
- [ ] `_resolve_pool` derives from configured pool; claude-code only as fallback
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_single_task_collapse.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_single_task_collapse.py
import pytest

class TestSingleTaskCollapse:
    def test_single_task_collapses_to_first_suggested(self, caplog): ...
    def test_multi_task_deploys_full_pool(self): ...
    def test_collapse_fallback_to_configured_spec(self): ...
    def test_unreadable_index_degrades_as_today(self, caplog): ...
    def test_deployment_info_log_lists_workers(self, caplog): ...

class TestPlannerPoolBackends:
    def test_resolve_pool_respects_configured_backends(self): ...
    def test_resolve_pool_claude_code_fallback(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — none
3. **Verify the Codebase Contract** first (grep/read each anchor)
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-01
**Notes**:
- **Collapse rule**: `DevelopmentNode._collapse_for_single_task()` +
  `_first_suggested_spec()`. Called from `execute()` immediately BEFORE
  `first_wave = scheduler.next_wave()`, so the pre-existing
  `should_fan_out(...)` INFO reports the pool that will really deploy
  rather than the pre-collapse one. Reuses the already-built scheduler
  (`len(scheduler._tasks)`), so no second index read — the same private
  read and `# noqa: SLF001` convention the existing `_count_tasks`
  (`development.py:308`) uses.
- Task count is the **total** in the index (matching `_count_tasks` and
  the spec's literal "exactly one `TASK-`"), not the pending count. A
  resumed run whose index has 9 tasks with 8 done therefore still gets
  the full pool; `should_fan_out` already handles that case by
  dispatching sequentially. Called out here in case the pending-count
  semantic is preferred later.
- Collapse only SHRINKS: an already-single-slot config returns untouched
  and silently (test: `test_collapse_never_grows_a_single_seat_pool`), and
  the isolation mode is preserved.
- Source precedence is spec-literal: first spec of
  `PlannerOutput.suggested_pool` (this is its FIRST consumer ever —
  set at `planner.py:171`, read by nothing before now), falling back to
  `pool_cfg.agents[0]`. The INFO log names which source won.
- **INFO deployment log** placed immediately after
  `DevAgentPool.build(...)` — the only point where requested specs have
  become the actual worker list (replicas expanded, `pool_max` cap
  applied). Format: `Deploying 2 dev sub-agent(s) for FEAT-486:
  w1=nova:zai.glm-5, w2=nova:qwen.qwen3-coder-480b-a35b-v1:0`, with
  `<backend default>` for an empty model string.
- **Planner backend respect**: `PlannerNode.__init__` gains
  `development_pool_config`, and both hardcoded
  `DevAgentSpec(agent="claude-code", ...)` literals (`:286`, `:298`) now
  route through a new `_derive_specs(count)` that spreads the derived
  width over the configured backends round-robin (width 3 over 2
  backends ⇒ 2 + 1, counts always summing to the requested width, source
  specs never mutated). With nothing configured it returns exactly the
  old single claude-code spec — byte-identical fallback.
- `_SHARED_DATA_ALLOWLIST` untouched; no new typed field or flag; no
  `TOPOLOGY_VERSION` bump.
- 15 new unit tests pass. Full `tests/flows/dev_loop/` run: 1206 passed,
  3 failed — all three failures (`test_qa_codereview.py::
  test_review_brief_carries_deterministic_qa_results`,
  `test_secondopinion_brief.py::test_dual_source_bodies_identical`,
  `test_subagent_parity.py::test_prompt_parity[sdd-secondopinion]`) were
  verified to fail identically on unmodified `dev`, i.e. pre-existing and
  unrelated. `tests/flows/dev_flow/` also green.
- Ruff: `planner.py` at exact parity with `dev` (6 pre-existing
  default-ruleset findings, unchanged); `development.py` +1, which is the
  RUF100 on my `# noqa: SLF001` — deliberately consistent with the
  identical pre-existing noqa at `:308` (the repo ships no ruff config,
  so SLF001 is not in bare-ruff's default set). New code uses modern
  `X | None` / `dict[...]` annotations so it adds zero UP00x findings to
  these legacy-typed modules.

**Deviations from spec**: ONE, deliberate and minimal — **a 4th file was
touched**: `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py`.

Rationale: the task's AC requires `_resolve_pool` to "derive from the
configured pool", but `build_dev_loop_node_factories` never passed its
(already-existing) `development_pool_config` parameter to
`PlannerNode` — `factories.py:224-229`. Without one line forwarding it,
`PlannerNode.development_pool_config` would be permanently `None` and the
whole planner half of this task would be unreachable dead code. This
repo has explicit precedent for rejecting exactly that: the
`require_deployment_approval` docstring in the same file records a code
review flagging "dead-end wiring with no real activation path". No
FEAT-486 task lists `dev_loop/factories.py`, so rather than silently
skip the AC or silently exceed scope, the edit was made as a single
additive line passing an already-in-scope local variable, with a
`None`-preserving default (zero behaviour change for any caller that
configures no pool). Flagged here and in the run summary for the PR
reviewer.

Second-order effect worth reviewing: for dev_loop feature-mode runs that
DO configure a pool, `PlannerOutput.suggested_pool` content changes from
`[claude-code x N]` to the configured backends. This is safe because
`suggested_pool` had no consumers prior to this task, and `PlannerOutput`
content does not enter the FEAT-480 input fingerprint (only
`execution_policy` does).
