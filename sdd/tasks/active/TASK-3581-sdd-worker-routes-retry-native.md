# TASK-3581: `sdd-worker` routes the `retry_native` handoff

**Feature**: FEAT-588 — Make the sdd-coder retry ladder reachable for complex/unknown tasks
**Spec**: `sdd/specs/fixgroup-47eb801095a6.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:569e81756247` (ledger, severity major)

---

## Context

Implements the orchestrator half of spec §3 **Module 1**, and closes spec
**R4**: *"`sdd-worker` must actually route the new handoff; an unrouted field is
a silent no-op that looks fixed in tests."*

TASK-3580 makes the engine return `TaskResult(outcome="retry_native",
native_retry=<NativePrep>)` when a complex/unknown task's only remaining
eligible strong seat is native. The engine has no dispatcher for a native seat —
`sdd-worker` runs it itself with the `Agent` tool, exactly as it already does
for a *planned* native attempt 1 after `coder_prepare_native`. Without a
routing rule in the prompt, the orchestrator will hit an outcome its
"Consolidate each task by outcome" list does not mention and stall or guess.

Per spec §8 **Q1 (resolved: distinct)**, `retry_native` is deliberately a
*separate* outcome from the planned-native path so telemetry can tell "planned
native" from "retried onto native" — the prompt must preserve that distinction
when attributing the attempt.

---

## Scope

- Add a `retry_native` bullet to the orchestrator loop's outcome list, in the
  same style as its siblings, instructing the worker to:
  - dispatch `Agent(subagent_type="sdd-coder", model=<native_retry.model>, ...)`
    against `native_retry.worktree_path` / `native_retry.branch`, reusing the
    existing native-Agent call shape (including `coder_feedback`,
    `assessment_id` and the "never call `Agent` twice for the same task" rule);
  - treat the result like any other native coder completion — `coder_merge(task_id)`
    on its notification;
  - attribute the attempt with `native_retry.attempt_uid` and backend `native`,
    and record it as a **retry**, not a planned native attempt.
- Apply the edit to **both** twins byte-identically.
- Add a prompt-contract test asserting the routing rule is present.

**NOT in scope**:
- Any engine or model change — TASK-3580 owns `engine.py` and `models.py`.
- Changing the planned-native attempt-1 instructions (step 2 of the loop).
- `docs/dev_loop/sdd-coder-orchestrator.md` — operator docs are not part of
  this feature's scope.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Add the `retry_native` outcome rule |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Byte-identical twin of the above |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Prompt-contract test for the new rule |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `b366bd774` on 2026-09-21.

### Verified facts

```text
# The two prompt copies are byte-identical TODAY and must stay so:
#   md5 eb92d6e8fa7aa11f642b26106973ea13  .claude/agents/sdd-worker.md
#   md5 eb92d6e8fa7aa11f642b26106973ea13  packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
# Enforced by: packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
# (full-body parity sweep, FEAT-377 Module 1 / TASK-1906).
# Editing only one copy FAILS that test. Edit both, or copy one over the other.
```

### Existing outcome rules to match in style (`.claude/agents/sdd-worker.md:361-372`)
```text
   - `merge_conflict` → `git merge <branch>` in this worktree, resolve, commit, then `coder_merge(task_id)` again.
   - `fidelity_violation` → treat as `failed` (a coder touched `sdd/` or unlisted files, OR its diff adds a banned import …).
   - `plan_stale` → replan the task with the current pool generation; do not consume an attempt.
   - `not_dispatched` → keep the task pending; do not treat it as completed.
```

### The native-Agent call shape already in the prompt (step 2, `:315-324`)
```text
Agent(subagent_type="sdd-coder", model=<prepared.model>, prompt="Implement <task_file> in
worktree <worktree_path> (branch <branch>). Work only there. Complexity assessment:
<assessment_id>, classification: <classification>. Previous delivery feedback:
<prepared.coder_feedback>")
…
`Agent` returns immediately with an id: the native coder runs in the **background** and its
result reaches you later as a task **notification**.
**Never call `Agent` again for the same task**.
```

### `NativePrep` fields available on `TaskResult.native_retry` (models.py:360)
```python
task_id, task_file, branch, worktree_path, seat_label, model,
attempt_uid, coder_feedback, assessment_id, execution_id, bg_handle
```

### Does NOT Exist
- ~~a `retry_native` rule anywhere in either prompt today~~ — `grep -n retry_native .claude/agents/sdd-worker.md` returns nothing. You are adding the first one.
- ~~`coder_retry_native` / `coder_prepare_retry` MCP tools~~ — no such tools. The reservation arrives inside `TaskResult.native_retry`; there is no extra call to make.
- ~~a second `coder_prepare_native` call for the retry~~ — the engine already reserved the worktree; calling it again is wrong and would raise `task_not_in_plan` (`engine.py:1762-1764`).
- ~~`.claude/agents/sdd-coder.md` needs changing~~ — the coder sub-agent is unchanged; only the orchestrator learns the new outcome.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#TaskResult"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Both twins, byte-identical.** `test_subagent_parity.py` compares full bodies.
  The safest sequence is: edit `.claude/agents/sdd-worker.md`, then
  `cp` it over `_subagent_data/sdd-worker.md`, then confirm with `md5sum`.
- Match the surrounding bullet style exactly: three-space indent, a backticked
  outcome name, ` → `, imperative text. Do not restructure the list.
- The prompt is instructions for a model, not code — keep it terse and
  unambiguous. State the retry attribution explicitly, since Q1 chose a distinct
  outcome precisely so telemetry can separate the two cases.

### References in Codebase
- `.claude/agents/sdd-worker.md:315-324` — the native `Agent` call shape to reuse.
- `.claude/agents/sdd-worker.md:401-402` — how native attempts are attributed
  (backend `native`, `attempt_uid` from the prep).
- `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:93`
  `test_orchestrator_loop_describes_background_native_agents` — the closest
  existing prompt-contract test to model the new one on.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `retry_native` bullet to `.claude/agents/sdd-worker.md` — *why*: the
   orchestrator's outcome list is the only place it learns how to act on an
   outcome, and an unlisted one stalls the loop.
2. Copy the file over its `_subagent_data/` twin — *why*: `test_subagent_parity.py`
   fails on any byte difference, and dev-loop dispatches the packaged copy.
3. Add the prompt-contract test — *why*: prompts have no type checker, so the
   test is the only thing that keeps the rule from being silently dropped.

### `.claude/agents/sdd-worker.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -c -F '   - `not_dispatched` → keep the task pending; do not treat it as completed.' .claude/agents/sdd-worker.md)
# AFTER — insert below `   - ``not_dispatched`` → keep the task pending; do not treat it as completed.` (verified: .claude/agents/sdd-worker.md:372)
   - `retry_native` → the task's attempt 2 was reserved on a NATIVE seat because no MCP strong seat was
     left (FEAT-588). The reservation is in `native_retry`; do NOT call `coder_prepare_native` again.
     Dispatch it exactly like a planned native coder — `Agent(subagent_type="sdd-coder",
     model=<native_retry.model>, prompt="Implement <native_retry.task_file> in worktree
     <native_retry.worktree_path> (branch <native_retry.branch>). Work only there. Complexity
     assessment: <native_retry.assessment_id>. Previous delivery feedback:
     <native_retry.coder_feedback>")` — then `coder_merge(task_id)` on its notification, same as any
     native coder, and never call `Agent` twice for the same task. Attribute it with backend `native`
     and `native_retry.attempt_uid`, and record it as a RETRY (attempt 2), never as a planned native
     attempt — the distinct outcome exists so the two stay separable.
```
**Why**: it reuses the native dispatch mechanics the worker already performs, so
the only genuinely new instructions are *where the reservation comes from*
(`native_retry`, not a `coder_prepare_native` call) and *how to attribute it*.
Both are the exact things a model would otherwise guess wrong.

### `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (MODIFY)
```bash
# Not a separate edit — reproduce the twin byte-for-byte and prove it:
cp .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
md5sum .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md
# the two digests MUST match
```
**Why**: hand-editing both invites a one-character drift that fails
`test_subagent_parity.py` with a full-body diff that is painful to read.

### `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'def test_orchestrator_loop_describes_background_native_agents' packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py)
# AFTER — add a new module-level test below `def test_orchestrator_loop_describes_background_native_agents():` and its body
def test_worker_prompt_routes_retry_native_handoff():
    """FEAT-588 R4: the orchestrator must know what to do with `retry_native`."""
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    # FILL IN: assert the rule exists and pins the three things a model would
    # otherwise guess — that the reservation comes from `native_retry` (not a
    # second `coder_prepare_native` call), that it is dispatched via `Agent`,
    # and that it is attributed as a retry — bounded by AC-1 of this task.
    raise NotImplementedError
```
**Why**: assert on the *substance* (no second prepare call, Agent dispatch,
retry attribution), not on one exact sentence — a brittle full-string match
would break on any harmless rewording of the bullet.

### FILL IN checklist
- [ ] the prompt-contract test's assertions

---

## Acceptance Criteria

- [ ] AC-1 — both prompts document how to route `retry_native`: reservation from `native_retry`, `Agent` dispatch, `coder_merge` on notification, retry attribution with `attempt_uid` + backend `native`.
- [ ] AC-2 — the prompt explicitly forbids a second `coder_prepare_native` call for a `retry_native` task.
- [ ] AC-3 — `.claude/agents/sdd-worker.md` and `_subagent_data/sdd-worker.md` are byte-identical (`md5sum` match).
- [ ] AC-4 — `test_subagent_parity.py` passes.
- [ ] AC-5 — the new prompt-contract test passes and fails if the rule is removed.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`

---

## Output

### Completion Note
(Agent fills this in when done)
