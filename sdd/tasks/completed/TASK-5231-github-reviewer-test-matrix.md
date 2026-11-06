# TASK-5231: Complete FEAT-759 §4 test matrix for GitHubReviewer SDD fallback

**Feature**: FEAT-817 — github-reviewer-test-matrix
**Spec**: `sdd/specs/github-reviewer-test-matrix.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:9e74a96838c7`

## Context
Ledger `issue:9e74a96838c7`: FEAT-759 spec §4 rows are missing from
`packages/ai-parrot/tests/bots/test_github_reviewer.py`. See spec §1 gap table.

## Scope
Add tests for every gap row in spec §1.

**NOT in scope**: production refactors; gittoolkit tests.

## Files to Create / Modify
- `packages/ai-parrot/tests/bots/test_github_reviewer.py` — MODIFY

## Codebase Contract
See spec §6. Use `_wire_reviewer`, `_wire_strict`, `_PAYLOAD`, `_checks`,
`TestSDDSpecRequirements._content` patterns already in the module.

## Acceptance Criteria
- [ ] Each spec §1 gap row covered by a passing test.
- [ ] `ruff check packages/ai-parrot/tests/bots/test_github_reviewer.py` clean.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q
```

## Completion Note
Added 4 test classes (32 tests) to `test_github_reviewer.py` covering every spec §1 gap row:
AC filter placeholder/substantive (incl. checked/whitespace/comment/full-template variants), locate fast-path hit
(no listing), 10 invalid-candidate fallbacks (FEAT-81 vs FEAT-811, fenced header, incidental mention, wrong
ext/path, missing/error/truncated/raising read), rate_limited search fallback, ordered scan, no-source /
unresolvable-spec / fallback-disabled in both entry points, Jira source reported over LLM-claimed source,
strict deferred/blocked/submission-error exposing `sdd_spec`, and an end-to-end spec-sourced review with fake
GitToolkit + fake LLM through the real `_ask_llm_for_review`. No production bug found; no production code changed.
Full module: 353 passed. ruff clean.
