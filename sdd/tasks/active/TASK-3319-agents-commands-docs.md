# TASK-3319: Agents, commands and docs use the tiered `select_tests` CLI

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3310, TASK-3317
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11, AC1 and AC14. The deterministic kernel and its CLI
(`python -m scripts.sdd.select_tests`, TASK-3310) exist, but the markdown lanes still run tests by
prose or run the **full suite**: `qa-runner` step 3b (`pytest -q --tb=line`), `sdd-autopilot`
step 3b (`pytest --tb=short` "full-suite sanity"), `sdd-coder` ("Run THIS task's
acceptance-criteria tests"), `sdd-worker` (merge consolidation and fallback lane), `/sdd-done`
(touched-module tests during lint fixes). This task rewrites those instructions to the tier CLI
and documents tiers, guard, core escalation, ledger and codex operator-config inheritance in the
orchestrator doc.

G9: cost proportional to blast radius — leaf changes pay the mirror of directories, core changes
pay the suites of importing distributions once (ledger); full suite and e2e only in CI.

---

## Scope

- `qa-runner.md`: remove the full-suite sanity pass (step 3b) and the "full-suite sanity pass is welcome"
  guideline; step 3 becomes `python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --run`.
  Adjust the example report text that mentions "full-suite failures".
- `sdd-autopilot.md`: delete step 3b (`pytest --tb=short` quick full-suite sanity check); step 3a becomes the
  feature-tier CLI.
- `sdd-coder.md`: validation step says run the commands under the task's `## Validation Commands`; a broad
  pytest is rewritten (or blocked when nothing is scoped) by the harness; codex seats get a deny carrying the
  scoped command.
- `sdd-worker.md`: after each `merged` outcome run `--tier merge --run` in the feature worktree; fallback lane
  "Run acceptance-criteria tests." → the task's `## Validation Commands`, then `--tier merge --run`.
- `/sdd-done` (both copies): the touched-module test instruction uses `--tier feature --run`.
- `docs/dev_loop/sdd-coder-orchestrator.md`: new section "Scoped test selection (FEAT-563)".

**NOT in scope**: the CLI itself (TASK-3310); guard code (TASK-3309/3312/3313/3314); `/sdd-task` docs (TASK-3315);
`.codex/agents/sdd-worker.toml` (no test prose). The `.agent/agents/` mirrors ARE in scope (Files table) —
leaving the full-suite line in `.agent/agents/sdd-autopilot/agent.md:575` would defeat AC1.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/qa-runner.md` | MODIFY | feature-tier CLI; drop full-suite pass and guideline |
| `.claude/agents/sdd-autopilot.md` | MODIFY | drop full-suite sanity step; feature-tier CLI |
| `.claude/agents/sdd-coder.md` | MODIFY | Validation Commands + guard behaviour |
| `.claude/agents/sdd-worker.md` | MODIFY | merge-tier CLI after `merged`; fallback lane |
| `.claude/commands/sdd-done.md` | MODIFY | touched-module tests → feature tier |
| `.agent/workflows/sdd-done.md` | MODIFY | same as the `.claude` copy |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | new "Scoped test selection (FEAT-563)" section |
| `.agent/agents/sdd-autopilot/agent.md` | MODIFY | mirror of the `.claude` sdd-autopilot edit (full-suite line L575) |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | mirror of the `.claude` sdd-worker edit ("Run acceptance-criteria tests." L232) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — markdown only.

### Existing Signatures to Use (verified anchors, 1 occurrence each unless stated)
```text
.claude/agents/qa-runner.md:43   - **Stay in scope.** Validate the feature's new/modified files. A full-suite
.claude/agents/qa-runner.md:44     sanity pass is welcome, but a pre-existing unrelated failure must be
.claude/agents/qa-runner.md:45     reported as such — do not blame it on this feature.
.claude/agents/qa-runner.md:61   3. **Run the test suite** (capture exit codes — they decide the verdict):
.claude/agents/qa-runner.md:63-67   # a) Targeted … pytest <feature-test-paths> -q --tb=short … # b) Sanity … pytest -q --tb=line 2>&1 | tail -30
.claude/agents/qa-runner.md:69      Use `pytest-asyncio` conventions already in the repo for async tests.
.claude/agents/qa-runner.md:112  Two full-suite failures (tests/loaders/test_pdf.py) predate this feature
.claude/agents/sdd-autopilot.md:566  3. Run the test suite:
.claude/agents/sdd-autopilot.md:567     a. `pytest` for the specific test files related to the feature
.claude/agents/sdd-autopilot.md:568     b. `pytest --tb=short` for a quick full-suite sanity check
.claude/agents/sdd-coder.md:164  - Run THIS task's acceptance-criteria tests.
.claude/agents/sdd-worker.md:284    - `merged` → run THAT task's acceptance criteria in this worktree (integration with sibling merges can break them);
.claude/agents/sdd-worker.md:285      green → step (g) of the Fallback loop for this task, with a Completion Note that ends with
.claude/agents/sdd-worker.md:431 - Run acceptance-criteria tests.
.claude/commands/sdd-done.md:142   `except Exception`), run the tests of the touched module before committing.
.agent/workflows/sdd-done.md:141   `except Exception`), run the tests of the touched module before committing.
docs/dev_loop/sdd-coder-orchestrator.md:497 ## Related
```

### Created by dependency tasks (TASK-3310 — verify it landed before starting)
```bash
python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev] \
    [--task-file sdd/tasks/active/TASK-NNN-x.md] [--worktree <path>] [--run] [--json]
# exit 0 = all invocations passed / plan printed; 1 = an invocation failed; 2 = usage error or empty task-tier plan
# --run records green escalated invocations in the per-worktree ledger
```
Other facts to document (spec §2, §7): tiers table; guard active only inside sdd-coder attempts
(`parrot-test-scope.json` in the per-worktree git admin dir); rewrite (MCP/native) vs deny (codex);
core escalation (transitive source fan-in ≥ 50 or `CORE_PATHS`) across importing distributions,
merge+feature only, deduped by `parrot-test-scope-escalations.json`; agent marker expression
`not e2e and not real_llm and not integration`; xdist allowlist; R3b — codex development dispatches
no longer pass `--ignore-user-config`, so `~/.codex/config.toml` applies (model/sandbox/approval stay pinned).

### Does NOT Exist
- ~~a `--tier ci`~~ — CI is unchanged; the CLI tiers are task, merge, feature only
- ~~`pytest -q` full-suite pass in any SDD agent after this task~~
- ~~`.agent/agents/qa-runner`~~ — no mirrored qa-runner copy exists (only `.agent/agents/sdd-*`)
- ~~`.codex/agents/sdd-worker.toml` test prose~~ — verified: no matching test instructions there

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/agents/qa-runner.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-autopilot.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": "docs/dev_loop/sdd-coder-orchestrator.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-autopilot/agent.md", "action": "MODIFY"},
    {"path": ".agent/agents/sdd-worker/agent.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Existing imperative agent prose (short numbered steps, fenced bash). Keep frontmatter untouched.

### Key Constraints
- Do not change agent frontmatter (hooks, tools, model).
- `qa-runner` verdict logic (step 6) stays: exit codes decide; the CLI's exit code replaces the targeted pytest exit code.
- Every replacement names the tier and the reason in one clause (executors follow reasons).
- `/sdd-done` copies must receive byte-identical replacement text.

### References in Codebase
- spec §2 "Tiers" table and "User-facing behaviour"; §7 R3b, R13, R14

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `scripts/sdd/select_tests.py` exists and `--help` lists `--tier/--base/--run` — *why*: prose must match the real CLI.
2. Edit qa-runner and sdd-autopilot (remove full-suite passes) — *why*: AC1, biggest wall-clock sink.
3. Edit sdd-coder and sdd-worker — *why*: task tier via Validation Commands, merge tier after each merge.
4. Edit both sdd-done copies identically — *why*: feature tier at close.
5. Add the docs section above `## Related` — *why*: AC14.

### `.claude/agents/qa-runner.md` (MODIFY)
````markdown
# occurrences: 1 (verified: grep -c '   # b) Sanity: quick full-suite signal' .claude/agents/qa-runner.md)
# REPLACE lines 62-69 (the fenced block containing `# a) Targeted` … `pytest -q --tb=line 2>&1 | tail -30`
# and the following `Use pytest-asyncio conventions` line — verified: .claude/agents/qa-runner.md:62-69) with:
   ```bash
   # Feature tier (FEAT-563): mirror of directories over the feature's changes ∪ every
   # task's `## Validation Commands` ∪ core escalation (paid once, ledger-deduped).
   # Never run the whole suite here — CI owns full-suite and e2e runs.
   python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --run
   ```
   Add `--json` once (without `--run`) to record in the report which tests ran and why
   (`declared` / `mirror` / `core` / `escalated`, plus `skipped_escalations`).
````
Also replace L43-45 guideline with: `- **Stay in scope.** Validate the feature's new/modified files via the feature tier;
a pre-existing unrelated failure inside that selection must be reported as such — do not blame it on this feature.`
(`# occurrences: 1 (verified: grep -c 'A full-suite$' .claude/agents/qa-runner.md)`), and
`# FILL IN: reword the example at L112 ("Two full-suite failures …") to "Two failures in the feature-tier selection …"` — bounded by AC1.
**Why**: AC1 — no full-suite invocation; exit code of the CLI feeds step 6's verdict unchanged.

### `.claude/agents/sdd-autopilot.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'for a quick full-suite sanity check' .claude/agents/sdd-autopilot.md)
# REPLACE lines 567-568 (verified: .claude/agents/sdd-autopilot.md:567-568) with:
   a. `python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --run` — the feature tier
      (mirror of directories ∪ declared Validation Commands ∪ core escalation); never a full-suite run
```
**Why**: AC1; the following `c.`/`d.` lines (ruff, mypy) stay — FILL IN: re-letter them `b.`/`c.`.

### `.claude/agents/sdd-coder.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c "^- Run THIS task's acceptance-criteria tests.$" .claude/agents/sdd-coder.md)
# REPLACE line 164 (verified: .claude/agents/sdd-coder.md:164) with:
- Run exactly the commands listed under your task file's `## Validation Commands`. Do not run
  `pytest` on a directory, `tests/`, `packages/<dist>/tests` or with no path: inside an sdd-coder
  attempt the harness rewrites such a command to your task's scoped tests (MCP and native seats),
  blocks it when nothing is scoped, or denies it with the scoped command to run (codex).
```
**Why**: task tier (< 60 s, never escalates); tells the seat what the guard will do so it does not retry broader.

### `.claude/agents/sdd-worker.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '   - `merged` → run THAT task' .claude/agents/sdd-worker.md)
# REPLACE line 284 (verified: .claude/agents/sdd-worker.md:284) with:
   - `merged` → in this worktree run `python -m scripts.sdd.select_tests --tier merge --base <feature branch merge-base> --run`
     (mirror ∪ import-impact of the merge ∪ core escalation, paid once per content via the ledger — integration with sibling merges can break them);
```
```markdown
# occurrences: 1 (verified: grep -c '^- Run acceptance-criteria tests.$' .claude/agents/sdd-worker.md)
# REPLACE line 431 (verified: .claude/agents/sdd-worker.md:431) with:
- Run the task's `## Validation Commands`, then `python -m scripts.sdd.select_tests --tier merge --base origin/<base_branch> --run`
  (this lane has no attempt context, so no harness guard — never run a directory or full-suite pytest by hand).
```
**Why**: merge tier is where core escalation is paid first; the fallback lane has no guard (spec Non-Goals).
FILL IN: confirm the exact `--base` phrasing matches the CLI's accepted refs (TASK-3310) — bounded by AC14.

### `.claude/commands/sdd-done.md` and `.agent/workflows/sdd-done.md` (MODIFY)
```markdown
# occurrences: 1 each (verified: grep -cF '), run the tests of the touched module before committing.' <file>)
# REPLACE `run the tests of the touched module before committing.` (verified: .claude/commands/sdd-done.md:142,
# .agent/workflows/sdd-done.md:141) with:
run `python -m scripts.sdd.select_tests --tier feature --base origin/<base_branch> --worktree "$WT" --run` before committing.
```
**Why**: feature tier at close; ledger skips core escalations already green on the same content (AC9c).

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
````markdown
# occurrences: 1 (verified: grep -c '^## Related$' docs/dev_loop/sdd-coder-orchestrator.md)
# BEFORE — insert above `## Related` (verified: docs/dev_loop/sdd-coder-orchestrator.md:497)
## Scoped test selection (FEAT-563)

Cost is proportional to blast radius: a leaf change pays the mirror of directories; a core change
pays the suites of every distribution importing it — once. Full suite and e2e run only in CI.

| Tier | Where | Selection |
|---|---|---|
| `task` | every sdd-coder attempt (guard) | task `## Validation Commands` ∪ mirror; never escalates |
| `merge` | sdd-worker after each merge | mirror ∪ import-impact ∪ core escalation (ledger-deduped) |
| `feature` | qa-runner, QANode, `/sdd-done` | mirror ∪ all Validation Commands ∪ core escalation |

<!-- FILL IN: subsections — CLI usage and exit codes; guard (attempt context file, rewrite vs block vs
codex deny, inactive outside attempts); core detection (transitive source fan-in ≥ 50 or CORE_PATHS,
importing distributions); escalation ledger (blob hashes, re-arm on change/red, malformed = empty);
agent flags & marker expression; xdist allowlist (evidence: artifacts/logs/feat-563-s3-xdist.md);
codex dev dispatches inherit ~/.codex/config.toml (R3b) — bounded by AC14 -->
````
**Why**: AC14 — operators need one place explaining why a run took seconds or minutes.

### `.agent/agents/sdd-autopilot/agent.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '   b. `pytest --tb=short` for a quick full-suite sanity check' .agent/agents/sdd-autopilot/agent.md)
# REPLACE line L575 `   b. `pytest --tb=short` for a quick full-suite sanity check` with the SAME text you wrote in .claude/agents/sdd-autopilot.md
```
**Why**: the `.agent/` tree is the non-Claude mirror of the agents; a leftover full-suite step there reintroduces the cost this feature removes.

### `.agent/agents/sdd-worker/agent.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -- '- Run acceptance-criteria tests.' .agent/agents/sdd-worker/agent.md)
# REPLACE `- Run acceptance-criteria tests.` (verified: .agent/agents/sdd-worker/agent.md:232) with the SAME text you wrote in .claude/agents/sdd-worker.md
```
**Why**: keep both worker prompts behaviourally identical (merge tier after each merge).

### FILL IN checklist
- [ ] qa-runner L112 example wording; bounded by AC1
- [ ] sdd-autopilot re-lettering of remaining steps; bounded by AC1
- [ ] sdd-worker `--base` phrasing matches CLI; bounded by AC14
- [ ] docs subsections; bounded by AC14

---

## Acceptance Criteria

- [ ] AC1 — `grep -n "pytest -q --tb=line\|full-suite sanity" .claude/agents/qa-runner.md .claude/agents/sdd-autopilot.md .agent/agents/sdd-autopilot/agent.md` returns nothing
- [ ] `sdd-coder.md`, `sdd-worker.md`, both `sdd-done` copies reference `scripts.sdd.select_tests` with the right tier (task via Validation Commands / merge / feature)
- [ ] Both `sdd-done` copies received identical replacement text
- [ ] AC14 — `docs/dev_loop/sdd-coder-orchestrator.md` has a "Scoped test selection (FEAT-563)" section covering tiers, guard, CLI, core escalation, ledger, R3b
- [ ] No agent frontmatter changed (`git diff` shows no `---`-block edits)
- [ ] `.agent/agents/sdd-autopilot/agent.md` and `.agent/agents/sdd-worker/agent.md` carry the same replacement text as their `.claude` counterparts

## Validation Commands
- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Test Specification

```bash
! grep -n "pytest -q --tb=line\|full-suite sanity" .claude/agents/qa-runner.md .claude/agents/sdd-autopilot.md
grep -q "select_tests --tier feature" .claude/agents/qa-runner.md
grep -q "select_tests --tier feature" .claude/agents/sdd-autopilot.md
grep -q "## Validation Commands" .claude/agents/sdd-coder.md
test "$(grep -c 'select_tests --tier merge' .claude/agents/sdd-worker.md)" -ge 2
diff <(grep -o 'select_tests --tier feature[^`]*' .claude/commands/sdd-done.md) \
     <(grep -o 'select_tests --tier feature[^`]*' .agent/workflows/sdd-done.md)
grep -q "^## Scoped test selection (FEAT-563)$" docs/dev_loop/sdd-coder-orchestrator.md
python -m scripts.sdd.select_tests --help | grep -q -- "--tier"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3319-agents-commands-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
