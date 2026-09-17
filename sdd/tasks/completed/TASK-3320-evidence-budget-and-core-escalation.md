# TASK-3320: Evidence — task-tier budget (< 60 s) and real core-escalation plans

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3310, TASK-3318
**Assigned-to**: unassigned

---

## Context

Spec §5 AC12 (budget) and AC9b (core escalation on the real tree). Unit tests prove the kernel on
fixture repos; these two criteria must be shown on **this** monorepo:

- **AC12** — on a representative 1–4 file change in `packages/ai-parrot`, task-tier validation
  wall-clock is **< 60 s** (goal G3), log `artifacts/logs/feat-563-task-tier-budget.log`.
- **AC9b** — a change to `packages/ai-parrot/src/parrot/bots/abstract.py` and one to
  `packages/ai-parrot/src/parrot/clients/base.py` escalate, at merge and feature tiers, to the suites
  of every distribution whose source imports them, and the task tier does **not** escalate; plans saved
  as `artifacts/logs/feat-563-core-escalation.json`.

This task only measures and records. If a number misses its bound, the task records the miss and
fails its acceptance criterion — it does not change kernel code.

---

## Scope

- Create a **scratch, detached** checkout of the feature branch outside the repo
  (`git worktree add --detach "$TMPDIR/feat563-evidence" <feature-branch>`), used read-only for
  measurement and removed at the end (`git worktree remove`), never pushed.
- **AC12**: in the scratch checkout, reset to the commit that implemented TASK-3309 (2 files:
  `test_scope/guard.py` + its test), then time
  `python -m scripts.sdd.select_tests --tier task --base <that-commit>^ --task-file <TASK-3309 file> --worktree <scratch> --run`.
  Run it 3 times; record each wall-clock, the plan (`--json`, without `--run`), and pass/fail vs 60 s (use the median).
- **AC9b**: in the scratch checkout (back at the feature tip), make one throwaway commit appending a comment
  line to `bots/abstract.py`; produce `--json` plans (no `--run`) for tiers `task`, `merge`, `feature` with
  `--base HEAD~1`. Reset, repeat for `clients/base.py`. Collect all six plans into one JSON document.
- Write both artifacts into the **feature worktree** (not the scratch checkout).

**NOT in scope**: running the escalated suites (cost; AC9c ledger behaviour is covered by unit tests);
tuning thresholds; changing any source or test file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/logs/feat-563-task-tier-budget.log` | CREATE | AC12 timings, plan, verdict |
| `artifacts/logs/feat-563-core-escalation.json` | CREATE | AC9b plans for `bots/abstract.py` and `clients/base.py` × 3 tiers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None in committed code. JSON assembly uses stdlib `json` inline.

### Existing Signatures to Use
- Verified paths: `packages/ai-parrot/src/parrot/bots/abstract.py`, `packages/ai-parrot/src/parrot/clients/base.py`.
- Grep baseline (spec §6): `parrot.clients.base` 182 source importers, `parrot.bots.abstract` 146 — both ≫ 50.
- Worktree rule (`.claude/rules/worktree-management.md` §4): pytest from a checkout other than the main one needs
  `PYTHONPATH=packages/ai-parrot/src` (the shared `.venv` is editable against the main checkout); apply it to `--run`.

### Created by dependency tasks (verify they landed before starting)
```bash
# TASK-3310 — scripts/sdd/select_tests.py
python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base REF] [--task-file PATH] [--worktree PATH] [--run] [--json]
# --json prints ScopePlanModel: tier, invocations[{distribution, argv, targets[{path, distribution, reason}]}],
#        escalated[], core_hits[{path, module, fanin, forced, distributions}], skipped_escalations[], notes[]
```
- TASK-3318 — `test_scope/policy.py::CORE_PATHS` measured list (both files expected in it).
- TASK-3309 — its implementation commit (find with `git log --oneline --grep "TASK-3309"` on the feature branch).

### Does NOT Exist
- ~~a `--tier ci`~~ — tiers are task, merge, feature
- ~~a CLI flag to inject changed files~~ — changed files come from `git diff <base>...HEAD`; hence the scratch commits
- ~~`artifacts/logs/feat-563-*.json` schema validator~~ — shape is `ScopePlanModel` per plan

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/logs/feat-563-task-tier-budget.log", "action": "CREATE"},
    {"path": "artifacts/logs/feat-563-core-escalation.json", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Evidence logs under `artifacts/logs/`: exact commands, raw outputs, explicit verdict line.

### Key Constraints
- The scratch checkout lives under `$TMPDIR` (outside `.claude/worktrees/`), is `--detach`ed, and is removed before the
  task ends; its throwaway commits are never pushed or merged. It exists only because changed files are git-derived.
- Never `uv sync` anywhere; use the shared `.venv` with `PYTHONPATH` per the worktree rule.
- `--run` only for AC12; AC9b plans are `--json` without `--run`.
- If the median exceeds 60 s: keep the log, mark AC12 FAILED in it and in the Completion Note with the per-invocation
  breakdown — do not change kernel code here.

### References in Codebase
- spec §5 AC9b, AC12; §2 Tiers table; G3, G7b

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3310/3318 landed and `CORE_PATHS` contains both core files — *why*: AC9b expects `forced` or threshold hits.
2. Create the scratch detached checkout at the feature tip — *why*: throwaway commits must not touch the feature branch.
3. AC12: checkout TASK-3309's commit, run the timed task-tier command 3×, capture `--json` plan — *why*: a real 2-file ai-parrot change.
4. AC9b: back to tip; for each core file make a throwaway commit and capture task/merge/feature `--json` — *why*: proves escalation on the real import graph and that task tier never escalates.
5. Write both artifacts in the feature worktree; remove the scratch checkout — *why*: evidence committed, scratch gone.

### Driver (inline shell, not committed)
```bash
set -euo pipefail
FEAT_WT="$(git rev-parse --show-toplevel)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SCRATCH="${TMPDIR:-/tmp}/feat563-evidence"
git worktree add --detach "$SCRATCH" "$BRANCH"
export PYTHONPATH="$SCRATCH/packages/ai-parrot/src"

# --- AC12 ---
GUARD_SHA="$(git log --format=%H --grep 'TASK-3309' -n 1 "$BRANCH")"
git -C "$SCRATCH" checkout --detach "$GUARD_SHA"
TASK_FILE="sdd/tasks/completed/TASK-3309-kernel-guard.md"   # FILL IN: fall back to sdd/tasks/active/ if not moved yet
python -m scripts.sdd.select_tests --tier task --base "$GUARD_SHA^" --task-file "$TASK_FILE" --worktree "$SCRATCH" --json \
  > "$SCRATCH/../feat563-task-plan.json"
for i in 1 2 3; do
  /usr/bin/time -f "run $i wall=%e s exit=%x" \
    python -m scripts.sdd.select_tests --tier task --base "$GUARD_SHA^" --task-file "$TASK_FILE" --worktree "$SCRATCH" --run
done 2>&1 | tee "$SCRATCH/../feat563-budget-raw.txt"
# FILL IN: write $FEAT_WT/artifacts/logs/feat-563-task-tier-budget.log = commands + plan JSON + three wall times
#          + "median=<s> bound=60 verdict=PASS|FAILED" — bounded by AC12

# --- AC9b ---
git -C "$SCRATCH" checkout --detach "$BRANCH"
for CORE in packages/ai-parrot/src/parrot/bots/abstract.py packages/ai-parrot/src/parrot/clients/base.py; do
  printf '\n# FEAT-563 evidence probe\n' >> "$SCRATCH/$CORE"
  git -C "$SCRATCH" -c user.name=evidence -c user.email=evidence@local commit -qam "probe $CORE"
  for TIER in task merge feature; do
    python -m scripts.sdd.select_tests --tier "$TIER" --base HEAD~1 --worktree "$SCRATCH" --json \
      > "$SCRATCH/../feat563-$(basename "$CORE" .py)-$TIER.json"
  done
  git -C "$SCRATCH" reset -q --hard HEAD~1
done
# FILL IN: assemble {"bots/abstract.py": {"task": …, "merge": …, "feature": …}, "clients/base.py": {…},
#          "generated_at": "<ISO>", "feature_commit": "<sha>"} into $FEAT_WT/artifacts/logs/feat-563-core-escalation.json — bounded by AC9b

git worktree remove --force "$SCRATCH"   # scratch only: detached, throwaway commits, nothing to keep
```
**Why this shape**: changed files are git-derived, so real diffs are the only faithful input; the detached scratch
isolates throwaway commits from the feature branch, and `--force` removal is safe because nothing there is kept.

### `artifacts/logs/feat-563-task-tier-budget.log` (CREATE)
```text
FEAT-563 AC12 — task-tier budget
change: <GUARD_SHA> (TASK-3309, files: <list>)
command: python -m scripts.sdd.select_tests --tier task --base <GUARD_SHA>^ --task-file <path> --worktree <scratch> --run
plan: <json>
run 1 wall=<s> exit=<n>
run 2 wall=<s> exit=<n>
run 3 wall=<s> exit=<n>
median=<s> bound=60 verdict=<PASS|FAILED>
```

### `artifacts/logs/feat-563-core-escalation.json` (CREATE)
```json
{
  "generated_at": "FILL IN",
  "feature_commit": "FILL IN",
  "bots/abstract.py": {"task": {}, "merge": {}, "feature": {}},
  "clients/base.py": {"task": {}, "merge": {}, "feature": {}}
}
```

### FILL IN checklist
- [ ] task file path fallback (completed vs active); bounded by AC12 input
- [ ] budget log with median verdict; bounded by AC12
- [ ] escalation JSON assembly; bounded by AC9b
- [ ] scratch checkout removed (`git worktree list` has no `feat563-evidence`)

---

## Acceptance Criteria

- [ ] AC12 — `artifacts/logs/feat-563-task-tier-budget.log` shows three runs and `median < 60` with `verdict=PASS` (a FAILED verdict is recorded honestly and leaves this criterion unmet)
- [ ] AC9b — in `artifacts/logs/feat-563-core-escalation.json`, for both files: `merge` and `feature` plans have non-empty `core_hits` naming the file and `escalated` ⊇ `core_hits[*].distributions` (including `ai-parrot`); `task` plans have empty `escalated` and `core_hits`
- [ ] Both JSON plans parse and every plan has the `ScopePlanModel` keys
- [ ] No source/test file changed on the feature branch; scratch checkout removed

## Validation Commands
- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Test Specification

```bash
grep -Eq 'median=[0-9.]+ bound=60 verdict=PASS' artifacts/logs/feat-563-task-tier-budget.log
python - <<'PY'
import json
from pathlib import Path
doc = json.loads(Path("artifacts/logs/feat-563-core-escalation.json").read_text())
for core in ("bots/abstract.py", "clients/base.py"):
    plans = doc[core]
    assert not plans["task"]["escalated"] and not plans["task"]["core_hits"], core
    for tier in ("merge", "feature"):
        hits = plans[tier]["core_hits"]
        assert any(h["path"].endswith(core) for h in hits), (core, tier)
        dists = {d for h in hits for d in h["distributions"]}
        assert "ai-parrot" in plans[tier]["escalated"] and dists <= set(plans[tier]["escalated"]), (core, tier)
PY
! git worktree list | grep -q feat563-evidence
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
7. **Move this file** to `tasks/completed/TASK-3320-evidence-budget-and-core-escalation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5, sequential fallback lane, user-authorized for
`complex_model_unavailable`-blocked tasks)
**Date**: 2026-09-17
**Notes**:

**AC12 (task-tier budget) — PASS.** Blueprint deviation: `git log --format=%H --grep 'TASK-3309'
-n 1` (as literally written) matches the MOST RECENT commit with "TASK-3309" in its message —
the `sdd: complete TASK-3309` state-update commit, not the 2-file
(`test_scope/guard.py` + `test_guard.py`) implementation commit the task's own Context
describes. I used the correct commit (`8ca7092277a9a0997fd53dcaf9ec5b347f40404e`, verified
`git show --stat` = exactly those 2 files). A second, more consequential problem: that commit
predates TASK-3310, so `scripts/sdd/select_tests.py` does not exist in that historical tree —
the literal blueprint (checkout `GUARD_SHA`, run the CLI there) cannot work at all. Adapted the
measurement to preserve AC12's intent (a real, representative 1-4 file `packages/ai-parrot`
change) while keeping the CLI available: in the scratch checkout, at the feature tip, I removed
those same 2 files (commit `b383ca2939a5a37c2406c5ba7be52855a369e46c`, "PRE") then restored them
from the tip's content (commit `e0aa9c0e7202a266b51558ebf416e6ff727b4340`, "POST") — an exact
replay of the real 203-line/2-file diff as a fresh commit pair, with `--base PRE_SHA`. Measured:
plan selects the mirrored `packages/ai-parrot/tests/flows/dev_loop/test_scope` directory (54
tests, correct — the changed files' own test directory); 3 runs = 7.29s / 7.21s / 7.43s;
median 7.29s, bound 60s, **verdict PASS**. Evidence: `artifacts/logs/feat-563-task-tier-budget.log`
(force-added — `artifacts/` is gitignored, same as prior FEAT-563 evidence logs).

**AC9b (core escalation) — confirmed miss on the literal assertion; intended behavior verified
correct by other means.** Probed both `bots/abstract.py` and `clients/base.py` with a throwaway
commit each, capturing `--json` (no `--run`) plans for all three tiers. Results
(`artifacts/logs/feat-563-core-escalation.json`):
- Both files: `task` tier has empty `core_hits`/`escalated` (never escalates) — ✅ matches AC9b.
- Both files: `merge` and `feature` tiers correctly detect the file as core (`fanin=917`,
  `forced=True`) and correctly add a `reason="core"` target for the package-tests suite of
  **every one of its 25 importing distributions** (confirmed: 25-26 invocations per plan, one per
  distribution) — this is the actual, intended escalation behavior, and it is correct.
- **However**, the AC's literal wording — `escalated ⊇ core_hits[*].distributions` (including
  `ai-parrot`) — does NOT hold: I ran the task's own embedded Test Specification script verbatim
  and it fails all 4 combinations (both files × merge/feature) on exactly that assertion.
  Root cause (verified by reading `test_scope/select.py::plan_tests`, TASK-3308, already
  implemented and covered by its own passing test suite): `ScopePlan.escalated` is populated
  **only** by the merge-tier impact-cap path (`if len(paths) > policy.impact_cap: escalated.append(dist)`),
  never by core-hit escalation — core hits are represented exclusively via `core_hits` +
  `reason="core"` targets. TASK-3308's own `test_core_escalates_every_importing_distribution`
  asserts escalation by checking `invocation.targets`, not `.escalated`, confirming this is the
  established, intentional, tested contract — not a regression I introduced. The one place
  `escalated` and core detection coincide is accidental: `bots/abstract.py`'s merge-tier plan
  shows `escalated: ["ai-parrot"]`, but that is the UNRELATED impact-cap trigger firing
  independently (275 impacted tests > cap 150), not the core-hit path; `clients/base.py`'s
  merge tier has no impact-cap trigger and correctly shows `escalated: []` despite also having a
  core hit. Per this task's own scope ("if a number misses its bound, the task records the miss
  and fails its acceptance criterion — it does not change kernel code"), I did not touch
  `select.py`: AC9b as literally written is **not met**, while its underlying intent (escalate
  the package suites of every importing distribution, once, at merge+feature only) **is**
  demonstrably satisfied and evidenced in the committed JSON. This spec/AC-vs-kernel-contract
  mismatch is worth a follow-up (either loosen AC9b's wording to check `core_hits`/targets, or
  extend `select.py` to also populate `.escalated` for core hits) — flagging for the feature's
  final code review / ledger rather than deciding unilaterally here.
- Encountered and recovered from one environment instability: a scratch git worktree
  (`/tmp/feat563-evidence`) became invalid mid-measurement (`fatal: no es un repositorio git`,
  likely a concurrent worktree-admin operation from another session racing my throwaway
  worktree, since `/tmp` is sandbox-local but `.git/worktrees/*` registration is repo-shared) —
  the `clients/base.py` feature-tier probe came back corrupted (empty plan with a "not a git
  repository" note). Detected it via a full sanity pass over all 6 captured plans before
  assembling the final JSON, and re-ran just that one probe cleanly in a fresh scratch worktree
  before finalizing. The other 5 probes were confirmed unaffected and correct.
- Scratch checkout(s) were removed at the end of each probe (`git worktree remove`, without
  `--force` per the dangerous-actions hook); `git worktree list` shows none remaining.

**Deviations from spec**: (1) used the correct 2-file TASK-3309 implementation commit instead of
the blueprint's literal (ambiguous, `-n 1`-picks-the-wrong-commit) grep, and replayed its diff on
top of the feature tip instead of checking it out historically, because the CLI it needs to run
does not exist at that historical commit — both purely measurement-methodology adaptations, no
kernel/source file was changed. (2) AC9b is recorded as a confirmed literal miss for the reason
above; no kernel code was touched to "fix" it, per this task's explicit scope.
