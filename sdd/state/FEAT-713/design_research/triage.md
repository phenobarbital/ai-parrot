# Design research triage — accounting-metrics-layer (FEAT-713)

Model: gpt-5.6-luna · codex-cli 0.163.0 · run 20261021T002356Z-254899
Path checks: all 12 `affected_paths` passed containment (`spec_tools check-path`) and `test -e`.
Evidence spot-checks: `DatasetManager.add_dataframe` pandas-only (`tool.py:1091`); `AuditLedger.append` storage
failure only logged (`audit_ledger.py:385-431`); `validate_query` FROM/JOIN names only (`sql.py:520`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Immutable, versioned chart of accounts (architecture) | CONFIRM | snapshot hashed into `model_hash` | §2 Data Models, M4 |
| S2 | One canonical IR, per-target renderings (alternative) | CONFIRM | one AST, `sql_hash` per dialect | §1, §2, M5 |
| S3 | SQLToolkit validation is not a semantic allowlist (risk) | CONFIRM | compiler self-check pass | M5, AC12 |
| S4 | Sign contract as data-shape semantics (api) | CONFIRM | `amount_convention` with four normalisations | §2, M2/M4, AC3/AC9 |
| S5 | Effective-dated completeness per interval (architecture) | CONFIRM | membership partition | M4, AC4 |
| S6 | Numeric / empty-result semantics before golden tests (testing) | CONFIRM | COALESCE, NULLIF, Decimal, tolerance | M5, §4, AC8/AC9 |
| S7 | Keep accounting out of the DatasetManager catalog contract (architecture) | CONFIRM | own `ModelCatalog`, injected `frame_provider` | §2, M8 |
| S8 | No shared DatasetManager caches (risk) | CONFIRM | no result cache in v1 | Non-Goals, AC13 |
| S9 | Separate durable accounting audit contract (architecture) | CONFIRM | fail-closed `FINANCE_AUDIT_MODE` | M7, AC11 |
| S10 | Structural vs live assertion validation (testing) | CONFIRM | `AssertionResult`, `on_failure` | M4, M9, AC15 |
| S11 | Resolve `parrot.semantic` satellite ownership first (architecture) | CONFIRM + ESCALATE | mirror FEAT-704 M1 files; FEAT-704 spec amendment is a human call | M1, §7, §8 Q10 |

Summary: 11 confirmed · 0 rejected · 1 escalated.
