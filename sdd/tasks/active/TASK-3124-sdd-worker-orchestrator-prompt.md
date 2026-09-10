# TASK-3124: `sdd-worker.md` — Orchestrator Loop replaces the sequential Execution Loop (+ twin sync)

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3122, TASK-3123
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 and §2 Overview steps 1–6. `sdd-worker` keeps its Cardinal Rules,
Startup Sequence, Task-Scoped Mode (still used by the dev-loop pool), Structured Output
Contract and STOP conditions, but its "## Execution Loop" becomes an orchestrator loop
over the `parrot-sdd-coder` MCP tools plus the native Haiku `Agent` call; step b2
(`writer_generate`) disappears (spec C3); the Completion summary gains a per-model table
(G9). The legacy sequential loop survives as an explicit fallback for when the MCP server
is missing. `tools:` must list the seven `mcp__parrot-sdd-coder__*` names or the agent
cannot call the server (spec §7; precedent `sdd-ideation.md:44`). Byte-parity with the
packaged twin is mandatory (FEAT-547).

---

## Scope

- Rewrite `.claude/agents/sdd-worker.md`: `tools:` line; delete "### b2)" and its checklist line; replace "## Execution Loop" … up to "## Completion" with "## Orchestrator Loop (FEAT-549)" + "## Fallback: Sequential Loop" (the old a–h steps minus b2); extend "## Completion" with the per-model table; update the description paragraph.
- `cp` to `_subagent_data/sdd-worker.md`.
- Tests: orchestrator markers present, `writer_generate` absent, `tools:` lists the seven names, parity green.

**NOT in scope**: any Python; the `sdd-coder` prompt (TASK-3123); `/sdd-start` (keeps `writer_generate`, spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | orchestrator loop, tools, b2 removal, summary table |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | full-file `cp` of the repo twin |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | CREATE | prompt contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors in `.claude/agents/sdd-worker.md` (414 lines; each occurs exactly once — grep -c verified 2026-09-10)
```
:20   `model: sonnet`
:23   `tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, Agent`
:37   `## ⛔ CARDINAL RULES — NEVER VIOLATE THESE`
:77   `## Task-Scoped Mode (FEAT-323)`          ← KEEP (dev-loop pool still dispatches this prompt with task_id)
:108  `## Startup Sequence`  (§0–§5 through :205)  ← KEEP
:207  `## Execution Loop`                          ← REPLACE from here …
:229  `### b2) Delegated implementation (ONLY when a Delegation Contract exists)`  (:229-251) ← DELETE
:268  `□ Delegated patch hunks were all reviewed before writer_apply?`             ← DELETE (inside checklist d)
:312  `### h) Continue`                            … up to here (old loop moves under "## Fallback: Sequential Loop")
:315  `## Completion`                              ← EXTEND (summary block :338-371)
:373  `## Structured Output Contract (dispatched runs)`   ← KEEP
:404  `## STOP Conditions`                         ← KEEP (+ add MCP-related STOPs)
```
Twin: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` (byte-identical today, FEAT-547 TASK-3106).
Parity test: `tests/flows/dev_loop/test_subagent_parity.py:44`. Existing prompt test: `test_subagent_parity.py:81` `test_worker_prompt_has_per_spec_index_instructions` (must keep passing — do not delete §g wording about the per-spec index).

### Tool contract to encode (from TASK-3122 / spec §2 New Public Interfaces)
```
mcp__parrot-sdd-coder__coder_plan(feature, worktree) → CoderResult{data: CoderPlan{chunks[{tasks[{task_id, task_file, seat_label, native, backend, model}]}], roster[{label, available, reason, model_used, fallback_used}], orphan_branches, pending, blocked}}
mcp__parrot-sdd-coder__coder_run_chunk(feature, worktree, task_ids) → CoderResult{data: CoderJob{job_id, state}}        # MCP-seat tasks only; returns immediately
mcp__parrot-sdd-coder__coder_prepare_native(feature, worktree, task_id) → CoderResult{data: NativePrep{worktree_path, branch, task_file}}
mcp__parrot-sdd-coder__coder_merge(feature, worktree, task_id) → CoderResult{data: TaskResult{outcome, conflict_files, unexpected_files, diagnostics, attempts}}
mcp__parrot-sdd-coder__coder_wait(job_id, timeout_seconds ≤ 300) → CoderResult{data: CoderJob{state, tasks[TaskResult]}}
mcp__parrot-sdd-coder__coder_status(job_id) → CoderResult{data: CoderJob}
mcp__parrot-sdd-coder__coder_cleanup(feature, worktree, keep_conflicted=true) → CoderResult{data: CleanupReport}
outcomes: merged | merge_conflict | failed | fidelity_violation ; errors: CoderResult.status=="error", error.code ∈ ERROR_CODES
```

### Does NOT Exist
- ~~`writer_generate` / `writer_apply` / `parrot-targeted-writer` in sdd-worker after this task~~ — removed (spec C3). `/sdd-start` keeps them (out of scope).
- ~~an `mcp__parrot-sdd-coder__*` tool usable without the `tools:` entry~~ — Claude Code agents can only call tools listed in `tools:` (precedent `sdd-ideation.md:44`).
- ~~`coder_status` and `coder_wait` in the same message~~ — the stdio server is sequential (spec §2 step 5); the prompt must say so.
- ~~SDD-state edits by coders~~ — step (g) stays the orchestrator's; the prompt must run it per merged task.

---

## Implementation Notes

### Key Constraints
- Keep every kept section byte-identical except where this task edits; keep the `test_worker_prompt_has_per_spec_index_instructions` wording (§g) alive in the Fallback loop and reference it from the orchestrator loop's step (g).
- Completion Note fields per task (G9/AC-10): `Seat / Backend / Model / Attempts / Duration / Tokens` — taken from `TaskResult.attempts[*]`.
- Summary table columns: `seat · tasks · retries · failures · wall-clock · tokens`.
- New STOP conditions: `coder_plan` error other than `roster_empty`; a `merge_conflict` you cannot resolve; `dependency_cycle`.
- After editing: `cp .claude/agents/sdd-worker.md packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` and `cmp`.
- Stage with `git add -f .claude/agents/sdd-worker.md` (directory is git-ignored, file tracked).

### References in Codebase
- `.claude/agents/sdd-ideation.md:44,120-128` — how MCP tools are listed and documented inside an agent prompt.
- `sdd/specs/sdd-worker-subagents.spec.md` §2 Overview steps 1–6 and §3 M7 skeleton — the loop text to render.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `tools:` — *why*: without the MCP names nothing else in this task can run.
2. Delete b2 + checklist line — *why*: delegation is now total via sdd-coder (spec C3).
3. Insert "## Orchestrator Loop (FEAT-549)" before the old loop and demote the old loop to "## Fallback: Sequential Loop" — *why*: the fallback keeps the agent useful when `parrot-sdd-coder` is not installed (spec §2 Edge Cases "Roster empty").
4. Extend Completion + STOP — *why*: G9 telemetry and explicit failure modes.
5. `cp` twin; tests; `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py test_worker_prompt_orchestrator.py -v`.

### `.claude/agents/sdd-worker.md` (MODIFY — tools line)
```yaml
# occurrences: 1 (verified: grep -c '^tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, Agent$' .claude/agents/sdd-worker.md)
# REPLACE line :23 with (one line):
tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, Agent, mcp__parrot-sdd-coder__coder_plan, mcp__parrot-sdd-coder__coder_run_chunk, mcp__parrot-sdd-coder__coder_prepare_native, mcp__parrot-sdd-coder__coder_merge, mcp__parrot-sdd-coder__coder_wait, mcp__parrot-sdd-coder__coder_status, mcp__parrot-sdd-coder__coder_cleanup
```

### `.claude/agents/sdd-worker.md` (MODIFY — new section inserted BEFORE `## Execution Loop`, which is renamed)
```markdown
# occurrences: 1 (verified: grep -c '^## Execution Loop$' .claude/agents/sdd-worker.md) — rename that heading to `## Fallback: Sequential Loop (no parrot-sdd-coder server)` and insert the block below ABOVE it.
## Orchestrator Loop (FEAT-549)

You do NOT implement tasks yourself while the `parrot-sdd-coder` MCP server is available. You plan, dispatch,
consolidate, and own SDD state. Coders (`sdd-coder`) run one task each in their own sub-worktree.

0. **Probe the server.** Call `coder_plan(feature=<FEAT-ID>, worktree=<absolute path of this worktree>)`. If the tool is
   unavailable, or the result is `status: error` with `error.code: roster_empty`, print
   `⚠️ parrot-sdd-coder unavailable (<reason>) — falling back to the sequential loop` and run "## Fallback: Sequential Loop".
   Any other `error.code` is a STOP condition.
1. **Print the plan.** Roster line (`available N/M`, each dropped seat with its `reason`), one line per chunk
   (`TASK → seat_label (backend:model | native)`), `blocked` ids, and every `orphan_branches` entry
   (`TASK-NNN branch=… commits=N` — you decide: `coder_merge` to adopt, or `coder_cleanup` to drop; never both blindly).
2. **Dispatch the FIRST chunk in ONE message**: `coder_run_chunk(task_ids=<the chunk's non-native ids>)` AND, for each task
   with `native: true`, `coder_prepare_native(task_id)` followed in the same message by
   `Agent(subagent_type="sdd-coder", model="haiku", prompt="Implement <task_file> in worktree <worktree_path> (branch <branch>). Work only there.")`.
   The chunk only runs in parallel if all of these are issued together.
3. **Wait.** Loop `coder_wait(job_id, timeout_seconds=120)` until `data.state != "running"`. Never call `coder_status` or
   any other tool in the same message as `coder_wait` — the server handles requests one at a time. When a native
   `Agent` returns, call `coder_merge(task_id)` for it.
4. **Consolidate each task by outcome** (`data.tasks[*].outcome`, or the `coder_merge` result):
   - `merged` → run THAT task's acceptance criteria in this worktree (integration with sibling merges can break them);
     green → step (g) of the Fallback loop for this task, with a Completion Note that ends with
     `Seat: <seat_label> · Backend: <backend> · Model: <model> · Attempts: <n> · Duration: <sum duration_s> · Tokens: <usage>`
     taken from `attempts[*]`; red → treat as `failed`.
   - `merge_conflict` → `git merge <branch>` in this worktree, resolve, commit, then `coder_merge(task_id)` again.
   - `fidelity_violation` → treat as `failed` (a coder touched `sdd/` or unlisted files; never merge it by hand).
   - `failed` → attempt 3 is yours: implement the task in THIS worktree with steps c)–f) of the Fallback loop, then (g).
5. `coder_cleanup(keep_conflicted=true)`, then go to 1. Stop when `chunks` is empty AND `pending` is empty.
6. Continue with "## Completion" (code review, push, summary with the per-model table).
```
**Why this shape**: it is spec §2 steps 1–6 verbatim in imperative form; step 2's "ONE message" is the only way the native seat runs concurrently; step 3's sequential-server rule prevents a blocked `coder_wait` from starving other calls (design research S4).

### `.claude/agents/sdd-worker.md` (MODIFY — deletions and Completion extension)
```markdown
# DELETE :229-251 (`### b2) Delegated implementation …` through its step 6) and :268 (`□ Delegated patch hunks …`).
# occurrences: 1 (verified: grep -c '^## Completion$' .claude/agents/sdd-worker.md) — inside the summary block (after "Code review:" lines) add:
   Seats:
     seat         tasks  retries  failures  wall-clock  tokens(in/out)
     qwen           3      0        0        21m04s      118k/31k
     gemini         2      1        0        14m12s       62k/19k
     codex-spark    2      0        1        17m40s       n/a
     haiku(native)  1      0        0         6m03s       n/a
# In `## STOP Conditions` (:404) append:
- `coder_plan` returned an error other than `roster_empty`, or `dependency_cycle`.
- A `merge_conflict` you cannot resolve without changing files outside the task's list.
```

### FILL IN checklist
- [ ] Description paragraph (frontmatter `description:`) mentions the orchestrator role and the fallback — bounded by spec §3 M7
- [ ] Fallback section header text + removal of b2 wording inside step d) checklist — bounded by AC: `writer_generate` absent
- [ ] Twin `cp` + `cmp`

---

## Acceptance Criteria

- [ ] `grep -c "writer_generate\|writer_apply\|parrot-targeted-writer" .claude/agents/sdd-worker.md` == 0.
- [ ] The `tools:` line lists all seven `mcp__parrot-sdd-coder__*` names and keeps `Agent` (AC-3).
- [ ] Body contains `## Orchestrator Loop (FEAT-549)`, `## Fallback: Sequential Loop`, the per-model `Seats:` table, and the Completion Note field line `Seat: … Tokens:` (AC-10).
- [ ] `cmp` repo vs packaged twin succeeds; `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -v` passes incl. `test_worker_prompt_has_per_spec_index_instructions` (AC-11).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -v` passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py
from pathlib import Path
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from tests.flows.dev_loop.test_subagent_parity import _repo_agents_dir   # FILL IN: import path per the tests package layout

TOOLS = [f"mcp__parrot-sdd-coder__coder_{n}" for n in ("plan", "run_chunk", "prepare_native", "merge", "wait", "status", "cleanup")]

def test_worker_prompt_has_orchestrator_loop():
    body = load_subagent_definition("sdd-worker")
    assert "## Orchestrator Loop (FEAT-549)" in body and "## Fallback: Sequential Loop" in body
    assert "writer_generate" not in body and "Seats:" in body and "Seat: " in body

def test_worker_prompt_tools_list_mcp_names():
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    tools_line = next(l for l in text.splitlines() if l.startswith("tools:"))
    assert all(t in tools_line for t in TOOLS) and "Agent" in tools_line
```

---

## Agent Instructions

1. **Read the spec** §2 Overview (steps 1–6, Edge Cases), §3 Module 7, §7 gotchas on the `tools:` whitelist.
2. **Check dependencies** — TASK-3122 and TASK-3123 completed (tool names and agent name are final).
3. **Verify the Codebase Contract** — re-run each `grep -c` anchor on `sdd-worker.md`; read `sdd-ideation.md:44,120-128`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**; `cp` the twin; `git add -f` the repo file.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3124-sdd-worker-orchestrator-prompt.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
