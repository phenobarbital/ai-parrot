# FEAT-636 design research triage (model gpt-5.6-luna, 12 suggestions)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Put one-source execution behind LinkedSurfaceService (architecture) | CONFIRM | guard/auth/error mapping stays in the service | §2, §3 M4/M5 |
| S2 | Accept parameter overrides, not client conditions (api) | CONFIRM | raw conditions would bypass locked/caps | §2, §3 M5, AC7 |
| S3 | Explicit viewer-vs-owner identity + share propagation (risk) | CONFIRM | pins proposal U1/U4 concretely | §2, §3 M5/M7, AC8 |
| S4 | Specify non-persisted-surface behavior (architecture) | CONFIRM | snapshot-only; never silent QS fallback | §2, §3 M7, AC10 |
| S5 | Align input_alias with manifest contract (api) | CONFIRM | gate checks alias against requires_columns | §3 M2, AC9 |
| S6 | Define result-to-rows contract (api) | CONFIRM | shared select_output_frame, deterministic rejects | §2, §3 M2, AC4 |
| S7 | Separate transform-stage from data-stage failures (risk) | CONFIRM | 3 stable 422 codes vs data_stage 502 | §3 M3, AC5 |
| S8 | Shared linked-transform validation gate (architecture) | CONFIRM | one gate for toolkit/persist/runtime | §3 M2/M4/M6, AC9 |
| S9 | Enforce post-transform row/serialization limits (risk) | CONFIRM | max_fetch_rows cap in apply_python_transform | §3 M2, AC6 |
| S10 | Regenerate schema chain + UI types (api) | CONFIRM | both schema artifacts + pnpm generate + drift test | §3 M1/M7, AC3 |
| S11 | E2E matrix: auth, parity, lane routing (testing) | CONFIRM | adopted as §4 integration matrix | §4 |
| S12 | Persisted/server-refresh-only first phase (alternative) | REJECT | dynamic fetch for persisted surfaces IS the user-decided scope (U1/U4); S4 already bounds the surface | — |

Summary: 11 CONFIRM / 1 REJECT / 0 ESCALATE. All affected_paths passed containment + existence checks.
