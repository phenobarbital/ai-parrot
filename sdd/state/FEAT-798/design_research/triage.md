# Triage — FEAT-798 design research (codex gpt-5.6-luna)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Verify voice replacements against the live API before deleting the old ids (risk) | CONFIRM | `gemini-3.8-live` / `gemini-3.8-flash-tts` were in no checked-in catalogue; both resolved live on 2026-11-04 (F029), and the check is now a blocking gate per id | §5 AC-12, M4 tests |
| S2 | Treat Argon cache loss as an explicit product contract (risk) | CONFIRM | existing fail-open tests use a 2.5 string; an Argon-specific test proves the new default cannot drop `system_instruction` | M2 tests, §4, §7 |
| S3 | Resolve the `gemini-flash-latest` vs `gemini-3.8-flash` fallback policy (architecture) | CONFIRM | one rule: method defaults and fallback chains name `GEMINI_3_8_FLASH`; `_default_model` stays (FEAT-688 U4) | §2 Overview "Fallback policy" |
| S4 | Keep string routing for the 2.5 computer-use id while removing catalogue publication (risk) | REJECT | Google shut `gemini-2.5-computer-use-preview-10-2025` down on 2026-07-28 (F028); routing an unreachable id contradicts the FEAT-688 dead-prefix rule. The behavioural flip is made deliberate by updating `test_google_computer_use.py` and `test_computer_use_vocabulary.py` in M2 | — |
| S5 | Exact pricing coverage for Argon with `cost_usd` + `revision_for` tests (risk) | CONFIRM | `calculator.py:301` is exact-key; row + test added | M7, §4, AC-8 |
| S6 | Make the public enum deletion policy explicit with negative tests and a documented breaking contract (api) | CONFIRM | negative tests already in M5; a migration doc now states the breaking contract | M3 docs (`docs/migration/gemini-2-5-retirement.md`), AC-15 |
| S7 | Make the retirement guard token-aware and consistent with non-goals (testing) | CONFIRM | whole-id matching already specified; `clients/base.py` comment mentions added as a reviewed exclusion so the non-goal and the guard agree | M5 skeleton, AC-1 |
| S8 | Validate hand-maintained UI lists against the backend catalogue (api) | CONFIRM (partial) | `google:gemini-3-pro-preview` is not a catalogue value → fixed in M7; a cross-language consistency test is rejected as out of scope (no vitest for this file, UI gate is `pnpm build`) | M7 skeleton |
| S9 | Operational migration contract for explicit overrides (risk) | CONFIRM | overrides are preserved by design; documented + `test_explicit_override_preserves_retired_id` | M3 docs/tests, §4 |
| S10 | Keep the SDK floor bump independently gate-verifiable (testing) | CONFIRM | M6 is its own exclusive task with the TASK-4371 gate | M6 |
| S11 | Resolve the pre-existing `google:gemini-3-flash` drift explicitly (alternative) | ESCALATE | outside the 2.5 scope; the operator decides whether to fold it into M3 | §8 Q2 |

Summary: 9 confirmed (S8 partial) · 1 rejected (S4) · 1 escalated (S11).
All 51 cited paths passed containment (`parrot sdd spec check-path`) and `test -e`.
