# FEAT-604 — merge-tier cost, before/after (AC8)

Baseline (spec §1, 2026-09-25, pre-#1494): 27 invocations, 26 full package suites,
ledger-skipped escalations: 0 (FEAT-601 worktree, `select_tests --tier merge`).

## Worktree used

- Path: `.claude/worktrees/feat-FEAT-601-training-agent`
- Branch: `feat-FEAT-601-training-agent`
- HEAD: `45cd932a087333e3a779ee7cd3f26eb4702bb2fd`
  (`fix(training-agent): FEAT-601 review fixes — export tips + WhatsApp media_urls`)
- Working tree: clean (`git status --porcelain` empty), verified before and after
  both measurement runs.
- Diff breadth vs `origin/dev`: `git diff --name-only --diff-filter=d origin/dev...HEAD`
  → **128 changed files**. This is the same worktree the spec's own §1 baseline was
  measured against (still present at measurement time — no stand-in needed).

## Commands used

Both runs executed with M1/M2 (TASK-3797/3798/3800) landed on the FEAT-604 feature
branch (this task's own worktree, `feat-FEAT-604-merge-tier-validation-cost--TASK-3802-a2-...`,
HEAD `0f408a58e`), targeting the FEAT-601 worktree via `--worktree`:

```bash
python3 -m scripts.sdd.select_tests --tier merge \
  --worktree /home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-FEAT-601-training-agent \
  --json
```

Run 1 used a **cold** escalation ledger (no `parrot-test-scope-escalations.json` yet
in the FEAT-601 worktree's per-worktree git dir). Between run 1 and run 2, the ledger
was seeded honestly via the public `record_green_escalation` API, called once per
escalated distribution with **that same run's own plan attribution** (`core_hits`
paths for the distribution as `core_files`, `cap_hits[dist]` as `impact_files`,
`cap_impacted[dist]` as the impacted hash) — i.e. exactly the inputs
`select_tests.py --run` itself would have passed after a green suite run (see
`scripts/sdd/select_tests.py` lines 99-107). The 26 escalated distributions' full
suites were **not actually executed** — running 26 monorepo package suites end to
end was not feasible in this session, and the spec explicitly allows seeding via the
API with the plan's own values instead of a literal `--run` (Implementation Notes:
"Do NOT actually execute the escalated suites to seed greens if wall time is
prohibitive — the API-seeding path above exists precisely because AC8 measures the
SELECTION, not suite runtime.").

No content changed between run 1 and run 2 (`git status --porcelain` on the FEAT-601
worktree was empty throughout; only the ledger file inside its per-worktree git dir
was written, which is exactly the mechanism under test).

## Results

| run | invocations | escalated (list length) | skipped_escalations (list length) |
|---|---|---|---|
| 1 (cold ledger) | **27** | 26 (`ai-parrot`, `ai-parrot-advisors`, 17× `ai-parrot-client-*`, `ai-parrot-embeddings`, `ai-parrot-integrations`, `ai-parrot-loaders`, `ai-parrot-pipelines`, `ai-parrot-server`, `ai-parrot-tools`, `ai-parrot-visualizations`, `parrot-formdesigner`) | 0 |
| 2 (unchanged content, green ledger) | **11** | 1 (`ai-parrot` — cap trigger re-detected, then ledger-skipped, see note below) | 26 (`ai-parrot` + the 25 other run-1-escalated distributions) |

Run 2's 11 invocations were the distributions whose selection came from `declared`/
`mirror`/`import` targets (real changed test/source files in those packages), not
from escalation: `ai-parrot-client-amazon`, `ai-parrot-client-google`,
`ai-parrot-client-grok`, `ai-parrot-client-openai`, `ai-parrot-integrations`,
`ai-parrot-loaders`, `ai-parrot-pipelines`, `ai-parrot-server`, `ai-parrot-tools`,
`ai-parrot-visualizations`, `root`.

**Note on `ai-parrot` appearing in both `escalated` and `skipped_escalations` in run
2**: `select.py`'s cap-detection step appends a distribution to `escalated` as soon
as its impacted-test count exceeds the cap (`impact_cap`), *before* consulting the
ledger — this is what makes an over-the-cap trigger visible even when the ledger
later skips it. `ai-parrot`'s cap trigger (379 impacted tests > cap 150) was
re-detected in run 2 exactly as in run 1, but its ledger entry's core blobs, impact
blobs and impacted hash all matched (verified directly: `pending_escalations`
returned `to_run=[]`, `skipped=[...26 distributions including ai-parrot...]`), so no
invocation was added for it — confirmed against the actual `invocations` list above,
which excludes `ai-parrot`. This was traced by instrumenting `context
.pending_escalations` in place and re-running `plan_tests` twice reproducibly; it is
not a defect.

**AC8 verdict: YES — run 2 plans strictly fewer invocations: 11 < 27.**
Skipped distributions (26) appear in run 2's `skipped_escalations`, as required.

**Seeding method**: `record_green_escalation` with the plan's own `core_hits`/
`cap_hits`/`cap_impacted` attribution (not `--run`, to avoid executing 26 full
monorepo package suites end to end).

## Validation

- `PYTHONPATH=packages/ai-parrot/src python3 -m pytest tests/sdd_scripts/test_select_tests.py -q` → 8 passed
- `PYTHONPATH=packages/ai-parrot/src python3 -m pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q` → 8 passed

(Both required the worktree-local gitignored `.so` build artifacts for
`parrot.utils.types` and `parrot.utils.parsers.toml` to be copied in from the main
checkout's `packages/ai-parrot/src/parrot/utils/` — cpython-3.12 builds, matching
the active interpreter — since this bare git worktree does not build Cython
extensions on its own; this is read-only test-environment setup, not a deliverable.)
