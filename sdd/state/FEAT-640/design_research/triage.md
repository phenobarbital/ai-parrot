# Design research triage — FEAT-640 formdesigner-venue-tables

Source: suggestions.json (gpt-5.6-luna, codex-cli 0.160.0). Path checks: 10/10 contained + existing.

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning
> high, 89 s) · Status: completed · Transcript: `sdd/state/FEAT-640/design_research/`
> All 10 cited paths verified inside the repository and existing.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make schema convergence atomic and serialized (architecture) | CONFIRM | DDL is transactional in Postgres; a failed ADD must not leave the drops applied, and two app workers can race the catalog guard. `initialize()` now runs inside one transaction after `pg_advisory_xact_lock`. | §2 Overview ¶1, M1 skeleton, §7 Patterns, AC7 |
| S2 | Define remediation for invalid legacy rows (risk) | REJECT | Tables are empty everywhere (brainstorm resolution), so no legacy rows can block an ADD; with S1 a failure rolls back to v1 instead of half-migrating. A preflight/remediation lane is unnecessary cost. | §7 Known Risks (recorded) |
| S3a | Scope catalog checks to the target relation (architecture) | CONFIRM | `pg_constraint.conname` is per-relation, not unique; a name-only guard can be masked. Guard now filters `conrelid = '<table>'::regclass`. | §2 Overview ¶1, M1 `_add_constraint_if_missing`, AC7 |
| S3b | Verify the final constraint set after initialization (architecture) | REJECT | With S1 the run is all-or-nothing; AC8's manual evidence checks the catalog once. A runtime audit adds `fetch` calls to a method that is deliberately plain `execute`. | §7 Known Risks |
| S4 | Guard site creation against an unauthorized store (architecture) | CONFIRM | Already decided with the user before this run (brainstorm resolution); M3's `_INSERT_SITE_SQL` carries the store predicate and `StoreNotFoundError`. | M3, AC4 |
| S5 | Decide and enforce the location-to-client invariant (api) | CONFIRM | Real gap: `(site_id, org_id)` alone lets client B attach a location under client A's site in the same org. Site predicate and composite FK now include `client_id`. | §2 Overview ¶3 + Data Models, M1, M3, AC3, §8 |
| S6 | Narrow or strengthen the raw-write security claim (risk) | CONFIRM | The brainstorm's "impossible by any path" was only true for org-consistency of locations; membership/store predicates are service-level. Wording corrected and the limit stated. | §2 Overview (scope paragraph) |
| S7 | Return one indistinguishable 404 response (risk) | REJECT | The parent-first probe only reveals facts about the caller's own org (is this site mine, is this client mine); cross-org probes always read "Site … not found". No cross-tenant oracle is created by distinct bodies. | §7 Known Risks |
| S8 | Use strict JSON type validation for geofence inputs (api) | CONFIRM | `validate_geofence` already rejects bool/str/float-radius/NaN/inf; added the missing "body must be a JSON object" check (a list body is an `AttributeError` → 500 today) and the enumerated handler cases. | §2 Overview ¶4, M4, §4 tests, AC9 |
| S9 | Preserve stable graph result keys with SQL aliases (api) | CONFIRM | Verified: `_attach_store_substructure()` reads `s["store_id"]`, `s["store_name"]`, `s["market_id"]` (`org_graph.py:416-424`); a physical rename without `AS` would break the graph. M5 now mandates aliases + a key test. | M5, §4 tests |
| S10 | Add real-Postgres migration evidence (testing) | ESCALATE | No Postgres fixture exists; whether to add a CI service/container fixture versus the manual transcript is the user's call. | §8 Q4 |
| S11 | Make the membership grant a startup-checked contract (risk) | ESCALATE | Grant is documented (M6); a readiness probe touches app wiring outside this repo's control. | §8 Q1 |

Summary: **7** confirmed (S1, S3a, S4, S5, S6, S8, S9) · **3** rejected (S2, S3b, S7) · **2** escalated (S10, S11).
