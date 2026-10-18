# Design Research Triage — tests-optimization-sdd-flow (FEAT-699)

Model: gpt-5.6-luna (codex-cli 0.162.1, reasoning high). 12 suggestions, all paths
verified repo-contained and existing; key evidence claims spot-checked:
- S2: background.py:728 `_plan_selection` calls plan_tests WITHOUT `declared` — confirmed.
- S9: sdd-done.md:296 final re-run passes only `--no-ledger` — confirmed.
- S4: planner.py:42 unconditionally appends `-m policy.marker_expression` — confirmed.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Contract presence = explicit selector mode (architecture) | CONFIRM | Matches decided replacement semantics; makes the mode testable | §2 Overview, M3 |
| S2 | Route contract through every validation entry point (architecture) | CONFIRM | Verified gap: ValidationSupervisor plans with no declarations today | §2 Integration, M6 |
| S3 | Versioned structured index payload, fail closed (api) | CONFIRM | Independently found the `validation_contract: "required"` collision; new `test_contract` object with schema+digest | §2 Data Models, M2 |
| S4 | Per-invocation marker composition override (api) | CONFIRM | planner.py:42 would silently deselect declared integration tests; user decided override-except-real_llm | §2, M3 |
| S5 | Node-level junit evidence for cache/baseline (risk) | CONFIRM | parse_junit keeps only aggregates today; cache/baseline misclassify without node statuses; fail closed | M4/M5, §7 |
| S6 | Cache invalidation beyond imports (risk) | CONFIRM | Execution manifest + collection fingerprint; unknown ⇒ miss | M4, §7 |
| S7 | Feature-scoped, lock-protected cache namespace (architecture) | CONFIRM | Unlocked RMW loses entries under parallel validations; reuse report.py lock pattern | M4 |
| S8 | Baseline runner as explicit new subsystem (risk) | CONFIRM | Verified: no .so-copy mechanism exists in worktree lifecycle code; prep contract + fail-closed unknown | M5 |
| S9 | Feature closeout fresh by default (alternative) | CONFIRM | --no-ledger does not bypass a green cache; closeout table must be a real run; resolves §8 Q2 (cache reuse via explicit --use-cache only) | M6/M7, §8 |
| S10 | Brief-flow scope mismatch (risk) | CONFIRM | Adopted the exclusion branch: /sdd-brief keeps the fallback path in v1 (HOTFIX-* ids unsupported by ValidationSupervisor); resolves §8 Q7 | §1 Non-Goals, §7 |
| S11 | E2E acceptance tests before narrowing (testing) | CONFIRM | Folded as §4 integration-test rows | §4 |
| S12 | Nightly = explicit package-suite matrix, no repo mutation from CI (alternative) | CONFIRM | Per-dist extras + junit artifacts; kills the "ledger from CI" branch of §8 Q5 (notification mechanism stays open) | M8, §8 |

Summary: 12 confirmed · 0 rejected · 0 escalated.
