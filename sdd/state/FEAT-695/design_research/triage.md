## 9. Design Research Cross-Check
Model: gpt-5.6-luna · Status: completed · transcript `sdd/state/FEAT-695/design_research/`

| # | Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Typed, versioned result model in `TaskCompletionEvidence` | REJECT | Results are tmp-only by user decision. A typed stdlib `SuiteResult`/`TaskTestRecord` with explicit statuses covers the zero/unknown/failed distinction. | §2 Data Models |
| S2 | Per-invocation junit paths, not one shared path | CONFIRM | Verified: `select_tests.py:108` runs one subprocess per distribution. | §3 M1 `junit_path_for` |
| S3 | Pass every task file to the closeout feature run | CONFIRM | Verified: declared targets come only from `--task-file` (`select_tests.py` main). | §3 M5, AC12 |
| S4 | Bind reports to head_sha/base_ref/argv | CONFIRM | Needed for stale marking. | §2 Data Models, AC13 |
| S5 | Persist via `ExecutionEvidenceStore` durably | REJECT | Contradicts the resolved decision: results are a temporary artifact under tmp. | — |
| S6 | Closeout run must not mutate the escalation ledger | CONFIRM | Verified: `select_tests.py:115`/`:123`. | §3 M2 `--no-ledger`, AC12 |
| S7 | Explicit timeout/parse/selection states; process timeout | CONFIRM | `--timeout` is per-test only. | §2 statuses, §3 M5 `timeout -k` |
| S8 | Retry/overlap semantics before totals | CONFIRM | Latest per task+suite, `attempts`, labelled totals. | AC13, §7 |
| S9 | Adversarial parser/closeout tests | CONFIRM | — | §4 |
| S10 | Use selector cost signals instead of a 10-task cutoff | REJECT | The user explicitly chose a deterministic task-count rule. Its "say not_run with reason" part was already in AC3. | — |
| S11 | Cover the third mirror `.agent/workflows/sdd-done.md`; fallback prints the real body | CONFIRM | Verified: the file exists, with a note at `:124`. | §3 M5, AC10 |
