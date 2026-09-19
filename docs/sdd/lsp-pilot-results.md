# FEAT-580 LSP Pilot — Live Evaluation Results

**Status: NOT YET RUN.** No live, audited 180-attempt run has been
executed. This file exists so the M6 "Real-seat run and interpretation"
module (spec §3 Module Breakdown) has its designated location, but it
intentionally contains **no** `go`/`no_go`/`inconclusive` claim, **no**
cost/quality/latency numbers, and **no** "observed X% reduction"
language — none of that would be evidence here, it would be fabrication.

## Why this is blocked

Spec §8 "Open Questions" leaves exactly one item unresolved:

> Which concrete CLI/model versions, immutable environment IDs, real task
> commits, price basis, and spending ceiling should the live run manifest
> use? — *Owner: Jesús / experiment operator*

Per spec §3's Module Breakdown table, M6 is explicitly **not**
delegation-eligible:

> Requires provisioned CLI seats, actual usage/pricing, and human
> acceptance review; results cannot be manufactured.

Concretely, running the pilot for real requires, per
`docs/sdd/lsp-pilot.md`'s "Operator run checklist (pre-M6)":

- A reviewed `PilotManifest` JSON with real immutable environment IDs, a
  pinned task commit, actual prices/cache semantics, a spending ceiling,
  and a per-attempt cost reservation.
- Real, provisioned CLI seats for all five arms, with research/coding/
  review tool visibility independently verified through the actual CLI
  host (`docs/sdd/lsp-pilot.md`'s "Seat-specific visibility checks"), or
  the opt-in `PARROT_LSP_LIVE_MANIFEST` live seat-readiness pass
  (`packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py`).
- Human acceptance review of the resulting decision — this cannot be an
  unattended, automated sign-off.
- An approved spending ceiling, since the run executes real, paid CLI
  calls across 180 planned attempts.

None of the above was available in the implementation session that built
this feature. Per TASK-3514's own instructions ("If prerequisites or
trace coverage are missing, record the external blocker and leave this
task unfinished... A complete no-go result is a valid deliverable; retain
opt-in deployment"), **TASK-3514 is intentionally left `in-progress`, not
`done`**, in `sdd/tasks/index/sdd-research-lsp.json` — see its Completion
Note for the full accounting of what was and was not completed.

## What IS implemented and ready

Every prerequisite module (M1–M5) is complete and tested offline:

- The toolkit: `packages/ai-parrot-tools/src/parrot_tools/lsp/`
  (`models.py`, `snapshot.py`, `protocol.py`, `session.py`, `toolkit.py`).
- The benchmark package: `benchmarks/sdd_lsp/` — `models.py` (pilot
  contracts), `accounting.py` (cache-aware cost math), `fixtures/`
  (the twelve pinned tasks), `runner.py` (`run_pilot`), `report.py`
  (`evaluate_gate` + deterministic JSON/Markdown reports), `__main__.py`
  (the offline-default CLI).
- The seat-readiness harness:
  `packages/ai-parrot-tools/tests/lsp/test_seat_visibility.py`.
- The report-integrity checks that this run's eventual summary must
  satisfy: `packages/ai-parrot-tools/tests/lsp/test_live_pilot_report.py`
  (validated here against synthetic fixtures only, per this file's own
  "not yet run" status).

## How to actually run it

Once an operator has filled in every item in `docs/sdd/lsp-pilot.md`'s
"Operator run checklist (pre-M6)":

```bash
python -m benchmarks.sdd_lsp \
  --manifest <reviewed-manifest.json> \
  --output-dir <dir> \
  --prices <prices.json> \
  --live
```

This produces `<dir>/report.json` and `<dir>/report.md` with the real
`go`/`no_go`/`inconclusive` decision, per-arm pooled statistics, and
per-task paired outcomes. **This file should then be updated in place**
with that decision, the task-level and cohort cost/quality/latency
results from the produced report, and any observed limitations —
replacing this placeholder outright, never appending a fabricated
narrative alongside it.

Until that happens, the toolkit remains opt-in and unproven locally, per
`docs/sdd/lsp-pilot.md`'s "Evaluation status" section.
