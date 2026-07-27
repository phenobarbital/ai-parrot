# TASK-1912: escalation_model — stronger model on retry (explicit, no ladder)

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1910
**Assigned-to**: unassigned

---

## Context

Module 3 item 2 (spec §3, G3). Retry today is positional: `_next_worker`
rotates to the next pool index with the same model. This task adds the
opt-in `escalation_model` so retries can run on a stronger tier.
**Decided (spec §8)**: explicit only — no built-in per-backend ladder;
empty string disables escalation.

---

## Scope

- `models.py`: add `escalation_model: str = ""` to `DevAgentSpec`
  (lines 377-393).
- `agent_pool.py`: in `run_wave`'s single-retry path, when the retry
  worker's spec has a non-empty `escalation_model`, dispatch the retry with
  that model instead of `spec.model` (same backend). Only the retry dispatch
  changes; first attempts always use `spec.model`.
- QA-retry redispatch (the TASK-1910/1911 repair loop): when
  `attempt >= 2` and the resolved spec has `escalation_model` set, the
  development node's dispatch uses it.
- Validation: only assert the string is non-empty before use — resolving
  invalid model names stays in the dispatcher's existing failure domain
  (spec §7).
- Unit tests: retry swaps model when set; unset preserves current behavior
  byte-for-byte (assert the dispatched profile's model).

**NOT in scope**: built-in ladders, auto-escalation flags, changing
`_next_worker`'s round-robin selection, `DEV_LOOP_DEV_AGENTS` parsing
changes beyond the new optional key.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | `DevAgentSpec.escalation_model` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py` | MODIFY | retry-path model swap |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | attempt≥2 redispatch model |
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | MODIFY (maybe) | if the dispatcher profile fixes the model at build time, add a rebuild-with-model path |
| `packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py` | MODIFY | escalation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import DevAgentSpec, DevAgentPoolConfig
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:377-393
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend      # Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot"]
    model: str = ""
    count: int = 1              # ge=1

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_pool.py
def _next_worker(self, failed_worker: PoolWorker) -> PoolWorker:   # line 159
async def run_wave(self, tasks: List[TaskRef], *, research: ResearchOutput,
                   run_id: str, cwd_for: Callable[[str], str]) -> WaveResult:  # 237-244
# retry: exactly once, on _next_worker(fw); single-worker pool retries same worker

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
# build_dispatcher (~98-201): materializes DevAgentSpec → fixed dispatcher+profile
# — check whether model is frozen at build time; if so the retry path needs a
#   per-dispatch model override or a rebuilt dispatcher (prefer the smallest change)
```

### Does NOT Exist
- ~~`DevAgentSpec.tier` / `.escalation` / ladder config~~ — only `escalation_model: str = ""` (this task adds it)
- ~~`DEV_LOOP_AUTO_ESCALATE`~~ — rejected in spec §8; do not add
- ~~per-dispatch model parameter on dispatchers~~ — *(unverified — check `DevLoopCodeDispatcher.dispatch` signature before assuming; if absent, rebuild the worker's dispatcher with the escalation model for the retry)*

### Contract resolution (found during implementation, 2026-07-26)
- The model is NOT frozen in the dispatcher at build time — verified by
  reading `agent_builder.py:build_dispatcher` fully: every branch returns
  a `(dispatcher, profile)` pair where the dispatcher is stateless w.r.t.
  model and the profile alone carries it (`profile.model` for
  claude-code/codex/gemini/grok/zai/moonshot, `profile.llm=
  "<backend>:<model>"` for the "nvidia" backend's
  `LLMCodeDispatchProfile`). `ClaudeCodeDispatcher.dispatch()` reads
  `profile.model` fresh on every call
  (`LLMFactory.create(f"claude-agent:{profile.model}")`). So the smallest
  change is a per-dispatch `profile.model_copy(update={...})` swap — no
  `agent_builder.py` change, no dispatcher rebuild.
- `DevLoopCodeDispatcher.dispatch()`'s signature has no `model` kwarg of
  its own (`brief`/`profile`/`output_model`/`run_id`/`node_id`/`cwd`/
  `session_host`) — confirmed via the Protocol + `ClaudeCodeDispatcher`
  concrete signature. The model travels exclusively on `profile`.

---

## Implementation Notes

### Key Constraints
- The merge-conflict resolver in `development.py:342-415` already escalates
  to claude-code for conflicts — leave it untouched; it is a different path.
- Preserve `WaveResult` bookkeeping: escalated retries count as the same
  single retry, just with a different model.
- Log the escalation (`self.logger.info("retrying task %s on escalation model %s", ...)`).

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_agent_pool.py` — existing retry tests to extend
- `sdd/specs/dev-loop-multiple-dev-agents.spec.md` — FEAT-323 pool design

---

## Acceptance Criteria

- [ ] Retry dispatch uses `escalation_model` when set; `""` → identical to current behavior
- [ ] QA-retry redispatch (attempt ≥ 2) honors `escalation_model`
- [ ] First attempts never use the escalation model
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
async def test_retry_uses_escalation_model(pool_with_escalation): ...
async def test_retry_same_model_when_unset(pool_without_escalation): ...
async def test_first_attempt_never_escalates(pool_with_escalation): ...
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — TASK-1910 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- `models.py`: `DevAgentSpec.escalation_model: str = ""`.
- `agent_pool.py`:
  - `DevAgentPool._escalated_profile(worker)` (static): returns
    `worker.profile.model_copy(update=...)` with the model swapped to
    `worker.spec.escalation_model` — handles both profile shapes
    (`model=` direct field, or `llm="<backend>:<model>"` for
    `LLMCodeDispatchProfile`/nvidia); degrades to the unescalated profile
    for any unrecognized shape (never raises).
  - `_dispatch_one` gained `escalate: bool = False`; when `True` and
    `worker.spec.escalation_model` is non-empty, dispatches with the
    escalated profile and logs
    `"retrying task %s on escalation model %s"`.
  - `run_wave`'s within-wave retry call now passes `escalate=True`
    unconditionally (existing per-worker behavior: only fires if THAT
    worker's spec actually has an `escalation_model` set — the retry may
    land on a different worker via round-robin, verified by a dedicated
    test using two specs with different escalation configs).
  - `run_wave` gained its own `escalate: bool = False` parameter, threaded
    into the FIRST-attempt dispatch gather too (previously only the
    retry gather could escalate) — this is what item 2 (QA-retry
    redispatch) below actually flips.
- `nodes/development.py`: `_execute_pool` computes
  `escalate = shared.get("qa_attempt", 1) >= 2` (the counter TASK-1911's
  `_with_repair_feedback` already bumps) and passes it to
  `pool.run_wave(..., escalate=escalate)` — so a QA-repair-loop
  redispatch (attempt ≥ 2) uses every worker's `escalation_model` on its
  FIRST dispatch of the new wave, not just an internal retry.
  **Scoping decision**: the single-agent path (`_execute_single`) has no
  `DevAgentSpec` at all (`self._dispatch_profile` is a fixed
  construction-time value, or a plain default `ClaudeCodeDispatchProfile`
  with no spec/escalation concept) — there is no lever to escalate, so it
  is intentionally left untouched. This matches the spec's own framing
  ("resolved spec") — escalation only applies where a spec exists.
- `agent_builder.py`: untouched — confirmed unnecessary (see Codebase
  Contract resolution above).
- `test_agent_pool.py`: extended `FakeDispatcher` to record the `profile`
  actually used per call (4th tuple element — verified no existing test
  does whole-tuple equality that this would break). New
  `TestEscalationModel` class: `test_retry_uses_escalation_model`,
  `test_retry_same_model_when_unset` (byte-identical behavior when
  `escalation_model=""`), `test_first_attempt_never_escalates`,
  `test_escalation_on_different_retry_worker_uses_that_workers_spec`
  (retry lands on a different worker via round-robin — the ESCALATED
  worker's own spec is used, not the originally-failed worker's), and
  `test_escalated_profile_handles_llm_field_profile` (the nvidia/
  `LLMCodeDispatchProfile` shape).
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 669 passed, 1 skipped,
  same one pre-existing unrelated failure noted in every prior task.
- `ruff check` clean on all touched files.

**Deviations from spec**: none — both Codebase Contract items resolved
without needing the "maybe" `agent_builder.py` change, and the
single-agent-path scoping decision follows directly from "the resolved
spec" (there is none on that path).
