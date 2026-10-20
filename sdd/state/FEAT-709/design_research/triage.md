# Design research triage — language-agnostic-validation-runners (FEAT-709)

Model: gpt-5.6-luna · codex-cli 0.162.1 · Status: completed · 12 suggestions
Every `affected_paths` entry passed containment (`spec_tools check-path`) and `test -e`.
Factual claims spot-checked 2026-10-20 @ 7dd48d3c2: `scripts/sdd/select_tests.py` has no shebang (line 1 is the docstring);
`LLMCodeDispatchProfile.allowed_commands` default (models/llm.py:51-55) lists `pytest` but not `pnpm`/`cargo`/`parrot`;
`report.nodeid_from_testcase` (report.py:111-114) returns None unless `file` ends in `.py`; `green_cache._is_cacheable`
(green_cache.py:49-51) accepts only `.py`; `SubWorktreeManager.create` (worktree_manager.py:143-165) always forks
`self.feature_branch`; `ExecutionEvidenceStore.put_artifact` (evidence.py:170) exists.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make verdict execution a first-class supervisor receipt (architecture) | CONFIRM | One supervisor-owned run-and-verdict path serves the seat tool and the engine gate; the verdict is persisted through `ExecutionEvidenceStore.put_artifact` before it is returned, so no caller can see a verdict that is not evidence. | §2 Overview, M6 |
| S2 | Validate the immutable attempt tree before acquiring the merge lock (architecture) | CONFIRM | The gate runs in `_consolidate` after extraction + lint autofix (the last engine mutations) and before `_acquire_merge_lock`, diffing against the fork SHA from `_consolidate_diff_base`, not the moving feature-branch name. | M7, §7 Gotchas |
| S3 | Match normalized command chains, not only argv[0] (api) | CONFIRM | `pnpm test`, `pnpm run test`, `pnpm exec vitest`, `npx vitest`, `uv run`, `python -m` are launcher chains; `RunnerAdapter.matches` receives a normalized argv from a shared launcher-stripping step and ambiguous chains are rejected, never guessed. | M1, M3, M4 |
| S4 | Resolve the guard bypass and verdict-command mismatch (risk) | CONFIRM | `allowed_commands` gains the configured runners' binaries from the registry; the native rewrite invokes `python scripts/sdd/select_tests.py … --verdict` (no shebang exists); rewritten commands return parsed verdict data only; unsupported compounds stay allowed by the guard but are covered by the engine gate (stated explicitly). | M8, §7 Gotchas |
| S5 | Make cache and baseline behavior explicitly runner-scoped (architecture) | CONFIRM | `filter_cached`/`record_green`/`classify_failures` operate only on `runner == "pytest"` targets; other runners are never cached and their failures are `unknown`, which gates. | M3, M5, AC |
| S6 | Centralize runner validation in the kernel checker (api) | CONFIRM | `check_task_graph._check_test_contract` and `cache_test_contract.py` consume the registry + `contract_from_index_header` (schema-1 lift included); the duplicated `_pytest_operands` in the checker is removed. | M9 |
| S7 | Inject a capability into the dispatcher instead of importing the engine (api) | CONFIRM | `LLMCodeDispatcher.set_validation_runner(...)` mirrors `set_event_registry_resolver`; the capability is bound per attempt to that task only and delegates to the supervisor path behind `coder_run_validation`; absent capability ⇒ hard tool error. | M8 |
| S8 | Add an explicit validation-retry state machine (architecture) | CONFIRM | `TaskOutcome` gains `validation_failed`; `TaskResult.validation` carries the verdict; the same-seat repair attempt is seeded from the failed attempt branch (`SubWorktreeManager.create(..., base=branch)`), counts as an attempt, emits its own outcome, and is classified apart from model suspension. | M7 |
| S9 | Separate per-runner deadlines from the plan deadline (risk) | CONFIRM | Per-invocation timeout from the runner settings plus an overall cap; unfinished invocations are `timed_out`, finished evidence is kept, and a partial run never records green cache. | M6, §8 Q4 (budget values still open) |
| S10 | Add runner-specific evidence fixtures before changing the parser spine (testing) | CONFIRM | `parse_junit` must accept non-`.py` `file` attributes and retain failure text; fixtures for TS junit, nested suites, missing `file`, libtest text, `e2e-verdict.json`, missing report, non-zero exit and excerpt truncation land in the first kernel task. | M4, §4 |
| S11 | Enforce runner tier eligibility at admission (api) | CONFIRM | A runner block whose `tiers` includes a tier its adapter does not allow is a contract validation error with a diagnostic, never an empty green plan; `parrot-e2e` rejects `task`. | M2, M9, AC |
| S12 | Constrain TOML adapter loading to the stdlib kernel contract (risk) | CONFIRM | Extension adapters are imported by the registry under the kernel's own import rules, checked against the `RunnerAdapter` protocol at load, and the lint verifies them under isolated system Python; failure names the config path and fails closed. | M1, M9 |

Summary: **12** confirmed · **0** rejected · **0** escalated.
