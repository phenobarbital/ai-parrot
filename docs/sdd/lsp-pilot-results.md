# FEAT-580 LSP Pilot — Live Evaluation Results

**Status: RUN EXECUTED, decision computed, `no_go` — pending required human
acceptance review before this can be treated as the certified result.**

A real 180-attempt run executed against real Bedrock-Mantle seats on
2026-09-20, spending ≈$0.75 of the approved $15.00 ceiling. This is real
evidence — real token counts, real per-attempt costs, real varying
wall-times, real recorded traces for all 180 attempts — not offline
fixture data. Every number below is independently re-derivable from the
committed
[`lsp-pilot-live-run-summary.json`](./lsp-pilot-live-run-summary.json) — a
trimmed copy of the actual `PilotReport` this run produced — and pinned by
four tests in
`packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py`
(`test_real_live_run_*`) that load that exact file and recompute the gate
from it.

**One important disambiguation up front**, because the pilot's own data
model overloads a word that could otherwise mislead a skim-reader: every
`PilotReport` this codebase can produce — including this real one — sets
a field literally named `PilotReport.synthetic`. That field name does
**not** mean "this run didn't really happen." It means "no human has yet
certified this report as the audited result," and
`benchmarks.sdd_lsp.runner.run_pilot()` sets it `True` on *every* report
it ever returns, live or not, by explicit design (see its docstring):
flipping it to `False` is deliberately left to a human caller, never the
runner itself. This run's committed `synthetic` field is still `True`
today — not because the run is fake, but because that human
certification step (below) has not happened yet.

**What is NOT yet done: certification.** Per spec §3 Module Breakdown's
verbatim M6 requirement — "Requires provisioned CLI seats, actual
usage/pricing, and human acceptance review; results cannot be
manufactured" — this is explicitly not something an agent can self-certify.
This document presents the run's real, verified evidence and the gate's
real, verified `no_go` output, but the formal sign-off step has not
happened. See "Certification status" below.

## Adoption gate decision: `no_go`

| Field | Value |
|---|---|
| Decision | **`no_go`** |
| Cost change (`lsp_combined` vs `wiki_ast`) | **−30.34%** (i.e. `lsp_combined` costs 30.34% *more* per accepted task, not less) |
| Median wall-time change (`lsp_combined` vs `wiki_ast`) | **+13.60%** (i.e. `lsp_combined` is slower) |
| Acceptance regressed | False |
| Correctness regressed | False |
| Gate thresholds | Adoption requires ≥10% cost reduction AND ≤10% wall-time regression; neither was met |

**Reasons** (from the gate's own output, verbatim):
- `cost_reduction_pct=-30.34 below the 10% threshold`
- `median_wall_time_regression_pct=13.60 exceeds the 10% threshold`

**Interpretation**: on this pilot's twelve fixed tasks, giving the coding
agent the full LSP toolset (`lsp_combined`) did **not** pay for itself
against the `wiki_ast` control (index-free AST/`rg`-based navigation,
Option A of the original brainstorm) — it cost more per accepted task and
took longer, for a marginal (one-task) acceptance improvement. **A
negative result is still a valid, useful result**: it means the LSP
toolkit's current tool loadout is not yet a clear win over the cheaper
alternative for this task mix and model, at least for `minimax.minimax-m2.5`.

## Coverage

| | Value |
|---|---|
| Planned attempts | 180 (12 tasks × 3 repetitions × 5 arms) |
| Executed | 180 |
| Not launched | 0 |
| Missing trace | 0 |
| Accepted (pooled) | 174 / 180 (96.7%) |

## Per-arm summary

| Arm | Planned | Launched | Accepted | Acceptance rate | Cost/accepted task (USD) | Median ms | p95 ms |
|---|---|---|---|---|---|---|---|
| `current` | 36 | 36 | 35 | 97.2% | 0.0030631 | 31052 | 47329 |
| `wiki_ast` | 36 | 36 | 33 | 91.7% | 0.0040105 | 31062 | 46052 |
| `lsp_navigation` | 36 | 36 | 35 | 97.2% | 0.0049429 | 35342 | 50474 |
| `lsp_diagnostics` | 36 | 36 | 35 | 97.2% | 0.0042436 | 31480 | 44484 |
| `lsp_combined` | 36 | 36 | 36 | 100.0% | 0.0052273 | 35287 | 43439 |

`lsp_combined` did reach the highest acceptance rate (100%) of any arm —
the only arm to solve `inv-inherited-receiver` (every other arm missed
it) — but at the highest per-accepted-task cost and among the slowest
median wall-times, which is what the gate weighs.

## Per-task paired outcomes

| Task | current | wiki_ast | lsp_navigation | lsp_diagnostics | lsp_combined |
|---|---|---|---|---|---|
| inv-duplicate-names | True | False | True | True | True |
| inv-alias-reexport | True | True | True | True | True |
| inv-namespace-import | True | True | True | True | True |
| inv-inherited-receiver | False | False | False | False | **True** |
| chg-signature-callers | True | True | True | True | True |
| chg-return-type-consumers | True | True | True | True | True |
| chg-decorator-wrapper | True | True | True | True | True |
| chg-registry-dispatch | True | True | True | True | True |
| fix-wrong-import | True | True | True | True | True |
| fix-type-mismatch | True | True | True | True | True |
| fix-stale-saved-dependency | True | True | True | True | True |
| fix-unavailable-server | True | True | True | True | True |

`fix-unavailable-server` (the forced `operator-unconfigured` environment
id condition) passed on every arm, confirming the LSP toolkit's
documented graceful-degradation behavior (`status="unavailable"`, no
crash) held under a real live run, not just in the offline tests.

## Run manifest (what was actually measured)

| Field | Value |
|---|---|
| Model | `minimax.minimax-m2.5` (AWS Bedrock-Mantle, `mantle:` client) |
| Pinned commit | `48e498f93` |
| Environment id | `lexotanil` |
| Repetitions | 3 per task/arm |
| Spending ceiling | $15.00 |
| Per-attempt cost reservation | $0.50 |
| Actual total spend | ≈ $0.75 (≈ $0.0042/attempt average) |
| Price basis | AWS Bedrock console, operator-confirmed 2026-09-20: $0.30/Mtok input, $1.20/Mtok output |
| Seat | `benchmarks/sdd_lsp/seats/bedrock_mantle_seat.py` — one seat script for all five arms, branching on `PARROT_LSP_PILOT_ARM`/`_TOOLS` env vars; `parrot.bots.Agent` tool-calling loop, `LSPToolkit` for the three LSP arms, small index-free AST/`rg` tools (`benchmarks/sdd_lsp/seats/tools.py`) for the `wiki_ast` control |

## Scope and limitations

- **Single model.** This pilot measured one pinned model
  (`minimax.minimax-m2.5`) across all five arms, per spec §2's controlled-
  comparison requirement (the independent variable is tool loadout, not
  model choice). It does not generalize to other models/CLI hosts without
  a separate run.
- **`wiki_ast` here is index-free AST/`rg` tooling, not the repo's live
  wiki graph.** The pilot's fixtures are tiny, freshly materialized
  scratch directories per attempt, never indexed by `wikitoolkit build` —
  the real wiki MCP tools would return nothing useful against them. The
  `wiki_ast` arm instead uses a small index-free `ast`-based definition/
  reference finder plus `rg` text search, matching the brainstorm's
  Option A discipline without requiring a pre-built index. See
  `benchmarks/sdd_lsp/seats/tools.py`'s module docstring.
- **Twelve fixed synthetic tasks.** The gate's statistical power is
  bounded by this pilot's fixed task set (spec §2); a `no_go` here is
  evidence against adoption for *this* task mix and model, not a
  universal verdict on LSP-based navigation tooling.
- **Real infrastructure noise encountered and discarded, not included
  above.** Two earlier live-run attempts on this same day were discarded
  in full before this one: the first stopped after 1/180 attempts (a real
  bug — the seat never populated `ModelUsage.actual_cost_usd`, so the
  runner's budget-discipline loop correctly refused to launch further
  attempts on unknown cost; fixed and regression-tested, see
  `fix(sdd-research-lsp): FEAT-580 TASK-3514 — seat cost reporting +
  missing _launch_cwd.py`). The second was contaminated mid-run by an
  unrelated concurrent process corrupting the shared Python environment
  (`ModuleNotFoundError` storms across ~84% of attempts, evenly spread
  across all arms, each failing in ~300ms — an import-time crash, not a
  real model response); that run's data was discarded outright rather
  than salvaged or blended with clean data. The run documented above is
  the first (and only) run whose data passed integrity checks (100% of
  attempts produced a trace, elapsed times consistent with genuine
  multi-turn tool-calling loops, no crash storms).

## Certification status

| Item | Status |
|---|---|
| Real 180-attempt run executed | ✅ done (2026-09-20) |
| Coverage/trace/manifest-digest integrity verified | ✅ done — `test_real_live_run_has_full_180_attempt_coverage_and_traces` |
| `no_go` decision independently re-derivable from raw evidence | ✅ done — `test_real_live_run_gate_matches_published_no_go_decision` |
| Committed, auditable evidence artifact | ✅ done — `docs/sdd/lsp-pilot-live-run-summary.json` |
| **Human acceptance review of the `no_go` decision** | ❌ **not done** — spec-required, explicitly non-automatable |
| `PilotReport.synthetic` flipped to `False` (formal certification) | ❌ **not done**, and will not be done by an agent — see below |

This document does not mark TASK-3514 `done` and the per-spec index still
carries it `in-progress`, exactly per the task's own instructions ("If
prerequisites or trace coverage are missing, record the external
blocker and leave this task unfinished... A complete `no_go` result is a
valid deliverable"). The remaining blocker is no longer data,
infrastructure, or seats — it is the operator's explicit review and
acceptance of this `no_go` result, which the spec deliberately keeps a
human-only step.

## Reproducing this run

```bash
python -m benchmarks.sdd_lsp \
  --manifest artifacts/lsp-live-run/manifest.json \
  --output-dir <new-output-dir> \
  --prices artifacts/lsp-live-run/prices.json \
  --live
```

(The manifest/prices files used for this run are session-local, gitignored
artifacts, not committed — they contain no secrets, but per spec §3 M6
each live run should use a freshly reviewed manifest rather than reusing
a prior one verbatim. The full 180-attempt raw output directory
`artifacts/lsp-live-run/run/` — including per-attempt trace JSONL files —
is likewise session-local and gitignored, per repo policy on `artifacts/`.)

Full evidence:
- Committed, reviewable: `docs/sdd/lsp-pilot-live-run-summary.json` (this
  run's real manifest + all 180 real `AttemptRecord`s: arm, accepted,
  elapsed_ms, actual cost, trace presence).
- Session-local only (gitignored, not committed): `artifacts/lsp-live-run/run/report.json`,
  `report.md`, `attempts_progress.jsonl`, and `evidence/<attempt_id>/trace.jsonl`
  per attempt — the full raw traces this summary was trimmed from.
