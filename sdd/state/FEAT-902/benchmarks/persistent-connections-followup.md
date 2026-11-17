# Persistent-connection follow-up for FEAT-902

## Disposition
**Defer.** Keep the current connection-per-operation lifecycle. Do not run an isolated reuse spike and do not propose production reuse from this matrix. Evidence is incomplete (the DEBUG-off overhead pass is missing; see `report.md`), and the measured costs do not point to connection setup as the bottleneck.

## Evidence
- Connection setup is small relative to writer wait. Under claim-race contention (resident lifecycle, candidate), `begin_wait` p50 is 34.3 ms (4 processes) and 54.3 ms (8 processes), while `connection_setup` p50 is 5.7 ms and 5.9 ms and `connection_open` p50 is about 1.5 ms. Even removing all setup cost would leave the writer wait untouched.
- In mixed-ledger workloads, `connection_open` p50 is 0.26–0.35 ms and `connection_setup` p50 is 0.78–1.83 ms. The p95 `connection_setup` tail reaches 9.5 ms at 4 processes, so there is some variance, but not a dominant share of operation latency.
- Connection counts fall in claim-race cells (for example 8000 vs 16000 opens per trial at 8 processes). Connection counts alone are not evidence of benefit: latency is mixed. The 4-process ephemeral claim-race p50 improves (17.0 vs 49.6 ms), while the 8-process ephemeral claim-race p50 is worse (17.9 vs 12.6 ms), and p99 is similar (42.4 vs 41.2 ms).
- Most of the measured gain comes from the candidate's sync fast path (TASK-5714: zero BEGIN attempts on idle ledgers, for example 8000 fewer per trial at 8 processes), not from connection reuse.
- `log_fsync` is 1.1–4.3 ms p50 when writes occur and `sync_probe` is 3–5 ms p50 in the resident candidate runs. These are durability costs that reuse would not remove.
- Variation is large: several baseline cells range by more than 2× across trials (for example baseline 4p resident wiki 488–1528 ops/s), so small differences cannot be attributed to any change.
- The DEBUG-off overhead is unmeasured. Any reuse comparison needs that pass first, since phase instrumentation itself adds cost.

## Next scope
Not applicable under defer. If reuse is reconsidered later, the required design work is:
- Per-file/per-process connection ownership, with one writer per database file.
- Bounded whole-transaction admission, so a connection held across operations cannot starve other writers.
- Commit acknowledgments and explicit failed-transaction cleanup (rollback on cancellation).
- Separate read connections, plus shutdown and drain semantics.
- Cross-process limits: reuse is per process, so the 4- and 8-process comparisons must be repeated per process model.

## Reconsideration conditions
Reopen only when a re-measurement, run with the DEBUG-off pass on an exclusive host, shows connection setup as a dominant share of successful-operation latency under the representative workload, and the writer wait is already reduced. Until then, connection reuse would add lifecycle risk without a measured bottleneck.

## Acceptance evidence for the next step
Not applicable under defer. A future reuse proposal would need: a DEBUG-off run of the full matrix; per-cell p50/p95/p99 with trial ranges; BEGIN and connection counts; zero integrity or invariant failures; and a comparison of setup time against writer wait, with no production reuse merged in the same change.
