---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [github-reviewer, tests, ledger-fix]
---

# Feature Specification: GitHubReviewer SDD-fallback test matrix completion

**Feature ID**: FEAT-817
**Date**: 2026-11-05
**Author**: Claude (sdd-fix)
**Status**: approved
**Target version**: next
**Discovered-from**: `issue:9e74a96838c7` (spec:FEAT-759)

## 1. Motivation & Business Requirements

### Problem Statement
FEAT-759 (`sdd/specs/github-reviewer-sdd-spec-acceptance.spec.md`) §4 lists a test
matrix for the GitHubReviewer SDD-spec requirement fallback. Production code matches
the spec, but `packages/ai-parrot/tests/bots/test_github_reviewer.py` on `origin/dev`
does not cover several §4 rows. This feature closes that test gap only.

### Missing §4 rows (diffed against origin/dev d0e6d526fd)
| §4 row | Gap on origin/dev |
|---|---|
| `test_fetch_spec_requirement_rejects_placeholder_ac` | no direct `_filter_spec_acceptance_criteria` tests: untouched template, generic subsets, comment-only, placeholder, checked/whitespace variants |
| `test_fetch_spec_requirement_accepts_substantive_ac` | only one mixed case inside the shape test |
| `test_locate_spec_file_fast_path_code_search_hit` | no assertion that a validated hit skips the directory listing |
| `test_locate_spec_file_rejects_invalid_search_candidate` | prefix-id (FEAT-81 vs FEAT-811), fenced header, incidental mention, wrong path/extension, missing/error/truncated not covered |
| `test_locate_spec_file_falls_back_on_rate_limited_search` | only the raised-exception variant exists, not `error="rate_limited"` |
| `test_review_pull_request_no_source_unchanged` | no-FEAT and unresolvable-spec in both entry points |
| `test_extract_feature_id_does_not_shadow_jira` (flag part) | `enable_sdd_spec_fallback=False` disabling lookup in both entry points |
| `test_review_outcomes_expose_requirement_source` | Jira source, strict deferred/blocked/submission-error outcomes |
| `test_review_pull_request_end_to_end_spec_sourced` | full flow with fake GitToolkit (search miss → listing → read) and fake LLM |

### Goals
- Add the missing tests using FEAT-759's fixtures. Fix production code only if a test exposes a real bug.

### Non-Goals
- No behaviour change to `github_reviewer.py` or `gittoolkit.py`.

## 2. Architectural Design
Tests only; they reuse the existing `_MinimalReviewer`, `_wire_reviewer`, `_wire_strict`
stand-ins in the test module.

## 3. Module Breakdown
### Module 1: Test additions
- **Path**: `packages/ai-parrot/tests/bots/test_github_reviewer.py`
- **Responsibility**: add the rows listed in §1.

## 4. Test Specification
Each row in the §1 table becomes at least one test in the module above.

### Validation Contract

tests:
- packages/ai-parrot/tests/bots/test_github_reviewer.py
markers: none

## 5. Acceptance Criteria
- [ ] Every §1 gap row has a passing test in `test_github_reviewer.py`.
- [ ] `ruff check` clean on the test file.
- [ ] No production behaviour change unless a test reveals a bug (documented in the task Completion Note).

## 6. Codebase Contract
### Verified Imports
- `GitHubReviewer._filter_spec_acceptance_criteria`, `_locate_spec_file`, `_fetch_spec_requirement`, `_resolve_requirement`, `review_pull_request`, `strict_review_pull_request`, `_ask_llm_for_review` (`packages/ai-parrot/src/parrot/bots/github_reviewer.py`).
- `SearchCodeResult`, `RepoDirectoryListing`, `RepoDirectoryEntry`, `FileContentResult` (`parrot_tools.gittoolkit`), already imported by the test module.

### Does NOT Exist
- No new fixtures module; fixtures live inline in the test file.

## 7. Implementation Notes & Constraints
Run with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.

## 8. Open Questions
None.

## Worktree Strategy
Single task, single worktree `feat-FEAT-817-github-reviewer-test-matrix`.

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-05 | Claude | Initial, from ledger `issue:9e74a96838c7` |
