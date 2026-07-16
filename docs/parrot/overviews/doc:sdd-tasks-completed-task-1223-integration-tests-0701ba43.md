---
type: Wiki Overview
title: 'TASK-1223: Integration tests + documentation'
id: doc:sdd-tasks-completed-task-1223-integration-tests-and-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Final task. Implements spec §3 Module 7 (integration tests) and
relates_to:
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-1223: Integration tests + documentation

**Feature**: FEAT-182 — GitToolkit On-Demand Code Retrieval for GithubReviewer
**Spec**: `sdd/specs/gittoolkit-pr-context-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1222
**Assigned-to**: unassigned

---

## Context

Final task. Implements spec §3 Module 7 (integration tests) and
Module 8 (configuration & docs). Closes the feature.

---

## Scope

- Add the two integration tests listed in spec §4 to
  `packages/ai-parrot/tests/bots/test_github_reviewer.py`:
  - `test_full_review_with_real_diff_fixture` — end-to-end review with
    a fixture PR + Jira ticket + mocked tool calls produces the expected
    `PRReviewResult` discrepancies.
  - `test_full_review_falls_back_when_tools_disabled` — setting
    `max_review_tool_calls=0` reverts to today's one-shot behavior
    (no tool calls attempted).
- Update `docs/github-reviewer.md` with a new **Tool-Assisted Review**
  section documenting:
  - The 3 new tools and their schemas.
  - The `max_review_tool_calls` kwarg (default 5) and the
    `GITHUB_REVIEWER_MAX_TOOL_CALLS` env var.
  - The `GITHUB_REVIEWER_BLOB_CACHE_TTL` env var (default 604800).
  - How to interpret the cap-hit `WARNING` log line.
- Add docstrings to the three new public tool methods on `GitToolkit`
  if they were left thin in TASKs 1219-1221 (they SHOULD already have
  thorough docstrings; this is a cleanup pass).
- Update `.env.example` (if it exists in the relevant package) with the
  new env-var names + comments.

**NOT in scope**:
- New tests for the tools themselves (already in TASKs 1219-1221).
- Code changes to the toolkit or reviewer beyond docstring polish.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Add 2 integration tests |
| `docs/github-reviewer.md` | MODIFY | New "Tool-Assisted Review" section |
| `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py` | MODIFY (docstrings only) | Polish docstrings on the 3 new tools |
| `.env.example` (if present) | MODIFY | Add the 2 new env vars |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports. Tests reuse fixtures from TASK-1222's reviewer test
suite and from the existing
`packages/ai-parrot-tools/tests/test_gittoolkit_pr_context.py`
fixtures (HTTP mocks via `responses`).

### Existing Signatures to Use

After TASKs 1217-1222 land, the following are stable in the codebase:

```python
from parrot_tools.gittoolkit import (
    GitToolkit,
    GetFileContentInput, ComparePRVersionsInput, SearchRepoCodeInput,
    FileContentResult, CompareVersionsResult, SearchCodeResult,
)
from parrot.bots.github_reviewer import GitHubReviewer, PRReviewResult

# New env vars (navconfig.get with fallback):
config.get("GITHUB_REVIEWER_MAX_TOOL_CALLS", fallback=5)
config.get("GITHUB_REVIEWER_BLOB_CACHE_TTL", fallback=604800)
```

### Does NOT Exist

- ~~`docs/api/gittoolkit.md`~~ — no per-class API doc exists; the
  reviewer doc is the canonical user-facing doc.
- ~~A top-level `.env.example` in this repo~~ — verify before editing.
  Each package may have its own; if there is no `.env.example`,
  document the env vars in `docs/github-reviewer.md` instead.

---

## Implementation Notes

### `docs/github-reviewer.md` — new section template

```markdown
## Tool-Assisted Review

`GithubReviewer` exposes three on-demand code-retrieval tools to the LLM
so it can pull additional repository context during a PR review when
the diff alone is insufficient.

### Tools

- **`get_file_content_at_ref(path, ref, start_line?, end_line?)`** —
  full file body at a given commit, branch, or tag. Supports line
  slicing for large files.
- **`compare_pr_versions(pr_number, path)`** — base + head versions of
  a single file in the PR, both as full content.
- **`search_repo_code(query)`** — GitHub Code Search restricted to the
  PR's own repository on its default branch.

### Configuration

| Env var | Default | Purpose |
|---|---|---|
| `GITHUB_REVIEWER_MAX_TOOL_CALLS` | `5` | Hard cap on tool calls per review |
| `GITHUB_REVIEWER_BLOB_CACHE_TTL` | `604800` | SHA-keyed blob cache TTL in seconds |
| `REDIS_URL` | unset | Optional shared blob cache backend |

The `max_review_tool_calls` constructor kwarg overrides the env var.

### Cap-hit telemetry

When the LLM exhausts its tool-call budget the reviewer emits a single
`WARNING` log:

```
GitHubReviewer: PR <repo>#<pr_number> hit tool-call cap (count=<N>, tools=<names>)
```

Use this signal to tune the cap if it fires frequently in production.
```

### Integration test sketch

```python
@pytest.mark.asyncio
async def test_full_review_with_real_diff_fixture(reviewer, mock_github):
    """End-to-end review pulls a file via tool then produces expected discrepancies."""
    # Fixture: PR diff that touches a function whose full body is needed.
    # Mock tools to return the canned file content.
    # Run review_pull_request.
    # Assert outcome.discrepancies contains the expected entries.
    ...

@pytest.mark.asyncio
async def test_full_review_falls_back_when_tools_disabled(reviewer):
    """max_review_tool_calls=0 reverts to today's one-shot review."""
    reviewer.max_review_tool_calls = 0
    # Patch self.ask to record whether tools were offered.
    # Assert it was called WITHOUT tools (or with max_iterations=1).
    ...
```

---

## Acceptance Criteria

- [ ] Both integration tests pass:
  `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py::test_full_review_with_real_diff_fixture -v`
  and
  `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py::test_full_review_falls_back_when_tools_disabled -v`.
- [ ] `docs/github-reviewer.md` includes a "Tool-Assisted Review"
  section covering tools, env vars, and the cap-hit log.
- [ ] The three new tool methods on `GitToolkit` have thorough
  docstrings (≥ 5 lines including a usage example).
- [ ] `ruff check packages/ai-parrot/ packages/ai-parrot-tools/` passes.
- [ ] `pytest packages/ai-parrot/ packages/ai-parrot-tools/` runs clean
  (full suite, not just new tests).

---

## Test Specification

See Integration test sketch above. Fixtures come from TASK-1222's
reviewer test suite — reuse `reviewer`, `fixture_payload`, and the
HTTP mock setup.

---

## Agent Instructions

1. Verify TASK-1222 completed.
2. Write integration tests; reuse fixtures.
3. Update `docs/github-reviewer.md`.
4. Polish tool docstrings if needed.
5. Run full test suite + ruff.
6. Update per-spec index status to `done`. Mark the feature
   `completed_at` in the index header to today's date.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**:
- Added 2 integration tests in `TestIntegrationToolAssistedReview` — both pass.
- Updated `docs/github-reviewer.md` with "Tool-Assisted Review" section covering
  tools, configuration table (env vars + constructor kwarg), and cap-hit telemetry.
- Tool docstrings on the 3 new `GitToolkit` methods were already thorough — no
  changes needed.
- No `.env.example` files exist in the repo; env vars documented in the markdown.
- Updated per-spec index `completed_at` for TASK-1223 and `completed_at` in
  the feature header.

**Deviations from spec**: none
