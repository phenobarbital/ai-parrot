---
kind: brief
slug: feat-699-red-tests
key: PR-1727
base_branch: dev
source:
  type: github-issue
  ref: phenobarbital/ai-parrot#1727
  url: https://github.com/phenobarbital/ai-parrot/pull/1727
jira_issue_key: null
ledger_issue: issue:1e684c2b1d72
created: "2026-10-18T22:53:43+00:00"
---

# Brief: PR #1727 (FEAT-699) — rewrite the 8 legacy tests red on the feature branch

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/feat-699-red-tests/tasks/. -->

## Problem

PR #1727 (`feat-FEAT-699-tests-optimization-sdd-flow` → `dev`, state OPEN) reports
"ai-parrot ❌ 442 tests · 434 passed · 6 failed · 2 errors" in its closeout table
and CI job "Test ai-parrot" fails on both Python 3.11 and 3.12 (run 39171782303,
`FAILED tests/sdd_scripts/test_select_tests.py::test_run_records_green_core_escalation`).
The PR body names four "known red" legacy tests and says five
`test_llm_code_dispatcher.py` tests are red on dev already.

Reproduction (2026-10-18, exported `origin/feat-FEAT-699-…` @ d7a20a3c1 and `origin/dev`
@ 79172ca8f into the scratchpad, `pytest packages/ai-parrot/tests/flows/dev_loop` plus
`tests/sdd_scripts/test_select_tests.py` on both):

| Test (PR branch) | dev baseline | Verdict |
|---|---|---|
| `test_qa_default_criteria.py::test_derives_pytest_scoped_to_changed_packages` | pass | **new red** (not in the ledger issue) |
| `test_qa_default_criteria.py::test_derived_criterion_gates_the_run` | pass | **new red** |
| `test_qa_default_criteria.py::test_falls_back_to_git_diff_when_development_published_nothing` | pass | **new red** |
| `test_qa_default_criteria.py::test_tests_created_by_development_are_unioned_with_the_diff` | pass | **new red** |
| `test_scope/test_qanode_feature_tier.py::test_feature_tier_equals_mirror_selection` | pass | new red (issue:1e684c2b1d72) |
| `sdd_coder/test_supervisor_ledger.py::test_second_merge_validation_skips_unchanged_suites` | pass | new red (issue:1e684c2b1d72) |
| `sdd_coder/test_supervisor_ledger.py::test_red_first_run_forces_full_second_run` | pass | new red (issue:1e684c2b1d72) |
| root `tests/sdd_scripts/test_select_tests.py::test_run_records_green_core_escalation` | pass | new red (issue:1e684c2b1d72, the CI failure) |
| `test_pr_enrichment.py` (11 tests, `nova` has no `NovaClient`) | **fail** | baseline red / environment — out of scope |
| `test_recovery_lifecycle.py` (3 tests, Redis `nav-api.dev.local:6379` refused) | **fail** | baseline red / environment — out of scope |
| `test_llm_code_dispatcher.py` | pass | pass on both here; not reproduced |

Eight tests are new red on the feature branch and are the scope of this brief. The
"6 failed + 2 errors" in the PR table is the 442-test subset that `/sdd-done` planned;
the whole dev_loop tree shows the same eight once baseline reds are removed.

## Root cause

FEAT-699 changed two things the legacy tests still assert:

1. **Mirror is file-level.** `plan_tests()` now builds mirror targets with
   `pytest_file_targets()` (`packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:144`),
   defined at `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py:84`: a changed
   `foo.py` maps to an existing `test_foo.py` walking up the mirrored test tree, never to a
   directory. `QANode._default_criteria` goes through `plan_tests`
   (`packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:597`), so the fixtures of
   `test_qa_default_criteria.py` — which create test *directories* only — now yield an
   empty plan and no derived criterion (`:81`, `:94`, `:144`, `:280`). Meanwhile
   `QANode._pytest_targets` still delegates to the dir-level walk-up
   (`qa.py:645` → `_scope_mirror.pytest_targets`), so
   `test_qanode_feature_tier.py:38` compares a file-level plan against a dir-level
   helper and gets `set() != {'packages/ai-parrot/tests/flows/dev_loop'}`. The spec
   says "Mirror resolution becomes file-level everywhere" (spec §Design, line 110) and
   lists `pytest_target_for()` as "modifies → file-level resolution" (line 174), but the
   PR added `pytest_file_target_for` beside the old function and left QANode on the old one.

2. **No suite escalation.** `plan_tests()` no longer escalates to a distribution suite
   on impact-cap or core hits; a core hit becomes a note (`select.py:200`,
   `"core change (…) — covered by nightly"`) and `escalated` / `skipped_escalations`
   are always empty. The escalation ledger (`test_scope/context.py`) is therefore never
   consulted by planning, so a green run can no longer make a second plan "strictly
   fewer" (`test_supervisor_ledger.py:375`), a red run cannot "re-arm" anything
   (`:416`), and `payload["skipped_escalations"]` is always `[]`
   (`tests/sdd_scripts/test_select_tests.py:242`). The replacement mechanism is the
   green cache (`test_scope/green_cache.py`: `filter_cached`, `record_green`), which
   `ValidationSupervisor._plan_selection` applies at merge tier when an `index_path`
   is given (`sdd_coder/background.py:788-800`).

## Research findings

- Symbols: `plan_tests` (`select.py:126-215`), `pytest_file_target_for` /
  `pytest_file_targets` (`mirror.py:84-132`), `QANode._default_criteria`
  (`qa.py:547-616`), `QANode._pytest_targets` / `_pytest_target_for` /
  `_deepest_existing_dir` / `_prune_nested` (`qa.py:642-664`; no callers outside qa.py
  and the three test files below), `ValidationSupervisor.start` (`background.py:493`),
  `_plan_selection` (`:753`), `_record_green_cache` (`:1110`),
  `green_cache.cache_namespace` / `filter_cached` / `record_green` / `CACHE_FILENAME`
  (`green_cache.py:38`, `:156`, `:223`, `:31`), `test_report.parse_junit`
  (`report.py:146`, xunit1 `file` attribute → nodeid), `detect_core` (`impact.py:264`).
- Blast radius of switching QANode helpers to file-level: only
  `test_qa_default_criteria.py` (9 dir-level assertions), `test_qanode_feature_tier.py`
  and `test_mirror.py::test_mirror_parity_with_qanode_fixtures` (parity against the
  dir-level `pytest_targets`). No production caller.
- Prior art for the rewrites: `test_background_contract.py` (`_index()` helper writes a
  per-spec index with a contract; `_JUNIT_FAILURE_CHILD` fakes an xunit1 report from a
  `python -c` child; `SDD_TEST_REPORT_DIR` redirects junit output),
  `test_green_cache.py` (`git_repo` fixture with both `pyproject.toml` files the cache
  manifest requires), root `test_merge_run_uses_cache_second_time`.
- Related ledger issues: issue:1e684c2b1d72 (this brief resolves it);
  issue:9b27d46a6bb2 (legacy escalation-ledger *code* still live in
  `select_tests.py:264-285` and `background.py:1147-1176` — NOT touched here, so the
  rewritten tests must not assert ledger state either way); issue:bfb29d4ffe49,
  issue:826e1329a9c6 (unrelated FEAT-699 review findings).
- `BriefSource.type` has no pull-request literal; `github-issue` is used with the PR
  reference (GitHub models PRs as issues).

## Decisions

Q&A round (2026-10-18):

1. **Fix target → onto the PR branch.** Brief metadata bases on `dev` (the only bases
   `brief_meta` accepts), but the fix worktree branch `fix-PR-1727-feat-699-red-tests`
   is reset to `origin/feat-FEAT-699-tests-optimization-sdd-flow` before any edit, and
   the fix PR targets that feature branch so #1727 goes green before it merges. The
   feature branch carries `scripts/sdd/brief_meta.py` and `sdd/briefs/`, so brief
   tooling works there.
2. **QANode scope → full.** `QANode._pytest_targets` / `_pytest_target_for` delegate to
   the file-level mirror; the ~9 dir-level assertions are rewritten to file-level
   semantics; the orphan `_deepest_existing_dir` delegate is removed (zero callers).
   `mirror.pytest_targets` / `pytest_target_for` / `deepest_existing_dir` stay exported
   (legacy API, out of scope).
3. **Supervisor-ledger rows → rewrite to green-cache semantics** (keep the real-selector
   integration rows): a green merge validation makes the next `_plan_selection` drop the
   cached file; a red run leaves no green-cache entry and the next plan is unchanged.
4. **Root select_tests → rewrite:** a core change yields the
   `core change (…) — covered by nightly` note and empty `escalated` /
   `skipped_escalations`; the test no longer asserts ledger state.

## Fix plan

1. **HOTFIX-PR-1727-1** — QANode mirror helpers go file-level; rewrite
   `test_qa_default_criteria.py`, `test_qanode_feature_tier.py`, `test_mirror.py` parity.
2. **HOTFIX-PR-1727-2** — rewrite the two spec §4 integration rows in
   `test_supervisor_ledger.py` against the green cache (junit-producing fake children,
   per-spec index with `index_path`).
3. **HOTFIX-PR-1727-3** — rewrite `test_run_records_green_core_escalation` in root
   `tests/sdd_scripts/test_select_tests.py` as the core-change-is-a-note test.

The three chunks touch disjoint files and may run in parallel.

## Validation commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q`
