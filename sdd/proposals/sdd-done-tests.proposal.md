---
id: FEAT-695
id_status: provisional  # ledger next_feature_id=695; /sdd-spec must reserve via reserve_ids.py
title: "/sdd-done reports a test-results table in the PR body"
type: feature
mode: enrichment
status: review
base_branch: dev
source: inline
confidence: medium
research_state: sdd/state/FEAT-695/
projects: [sdd, dev-loop]
tags: [sdd-done, test-reporting, pull-request, sdd-coder, evidence]
---

# /sdd-done reports a test-results table in the PR body

## 0. Origin

Inline request (es): sdd-worker / sdd-coder run tests per task, and sometimes
sdd-worker runs the whole spec's test set, but none of that reaches the PR that
`/sdd-done` opens. Request: `/sdd-done` should show a table of tests run and
passed, so reviewers have a visible metric when approving the spec.

## 1. Synthesis Summary

Test evidence exists today but is lost in three ways: `/sdd-done` deliberately
skips tests (F001). The sdd-coder evidence store keeps only outcome and exit code,
with no counts (F002). Pass counts survive only as free-text "N passed" in about
29% of Completion Notes, and their scope varies (F003). The PR body is just
"<N>/<total> tasks verified". The fix has two parts. First, structured per-task
test counts recorded during execution. Second, an authoritative feature-tier
re-run inside `/sdd-done` against the final HEAD. Both are rendered as a
Markdown table in the PR body.

## 2. Codebase Findings

### 2.1 Localization
| Path | Role | Evidence |
|---|---|---|
| `.claude/commands/sdd-done.md` §4 (L145-147), §9.2 (L516-530) | skips tests; builds PR body | F001 |
| `.agents/skills/sdd-done/SKILL.md` L182-183 | Codex twin, same PR body | F001 |
| `parrot/flows/dev_loop/sdd_coder/background.py` L190-191 | validation record: outcome + exit_code only | F002 |
| `parrot/flows/dev_loop/sdd_coder/optimization_models.py::TaskCompletionEvidence` | per-task evidence, no counts | F002 |
| `parrot/flows/dev_loop/sdd_coder/evidence.py::ExecutionEvidenceStore` | durable store outside the worktree | F002 |
| `parrot/flows/dev_loop/sdd_coder/summary.py` | per-seat roll-up; precedent for a test roll-up | F002 |
| `scripts/sdd/select_tests.py` → `dev_loop/test_scope/select.py` L163 | `--tier feature --run`; no count parsing | F003 |

### 2.2 Constraints
- `/sdd-done` §4 currently says re-running tests "adds latency without new signal". This proposal reverses that, because the final HEAD (after merges and the §4.5 lint pass) was never tested as a whole.
- Never run a full-suite pytest by hand; use `select_tests --tier feature`.
- Both twins (`.claude/commands` + `.agents/skills`) must change together.
- E2E evidence (§4.6) stays a separate gate; don't merge it into this table.

## 3. Scope (single hypothesis)

1. **Structured counts at the source.** `select_tests --run` gains `--junitxml`/`--report-json <path>`. It parses passed/failed/skipped/errors/duration per suite. The sdd-coder validation path (`coder_run_validation`) persists those counts in its evidence record (`TaskCompletionEvidence.completion_facts` or a typed `TestRunSummary`). The sdd-worker fallback lane writes the same JSON next to the task.
2. **Re-run in `/sdd-done`** (new step between §4.5 and §5): `select_tests --tier feature --base origin/<base> --run --report-json`. The result reflects the final HEAD.
3. **PR-body table**: one row per suite (test module or package) plus a **Total** row (run · passed · failed · skipped · duration). Add a collapsible per-task section built from the recorded per-task evidence. Mark rows where the evidence predates the final HEAD.
4. **Report only, never block.** Failures show up in the table (❌), and the PR is opened anyway.

Not in scope: CI changes, coverage %, E2E gate.

## 4. Confidence Map
- ✓ [high] `/sdd-done` produces no test data today (F001).
- ✓ [high] coder evidence has no counts (F002).
- ◐ [medium] `select.py` runs pytest without parsing results; only the subprocess call was seen (F003).
- ◌ [low] how much latency the feature-tier re-run adds on large features (not measured; see memory: merge-tier validation cost).

## 5. Open Questions
- [x] Data source → **both**: per-task recorded evidence plus an authoritative re-run in `/sdd-done`.
- [x] Do failures block the PR? → **No**, report only.
- [x] Table granularity → **per suite plus a total row** (per-task detail goes in a collapsible section).
- [ ] Timeout/budget for the re-run on large features, and what the table says when it times out.
- [ ] Where per-task JSON lives in the fallback lane (git-ignored `artifacts/logs/` vs the evidence store).

## 6. Recommended Next Step
→ `/sdd-spec sdd/proposals/sdd-done-tests.proposal.md`. Localization is high-confidence; the two remaining questions are spec-level details.

## 7. Research Audit
State: `sdd/state/FEAT-695/` (source.md, findings F001–F003). Budget: default, not truncated.
