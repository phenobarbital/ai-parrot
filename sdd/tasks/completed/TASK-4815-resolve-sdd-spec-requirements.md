# TASK-4815: Resolve and parse bounded SDD spec requirements

**Feature**: FEAT-759 — GitHubReviewer SDD Spec Acceptance Criteria
**Spec**: `sdd/specs/github-reviewer-sdd-spec-acceptance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4813, TASK-4814
**Assigned-to**: unassigned

## Context

Implement spec M3: resolve a feature ID at the supplied base ref and build a Jira-shaped requirements envelope.

## Scope

Implement spec M3: resolve a feature ID at the supplied base ref and build a Jira-shaped requirements envelope.
- Add _locate_spec_file, _parse_spec_sections and _fetch_spec_requirement with the exact skeleton signatures.
- Empty ref or absent toolkit returns None without any GitHub request.
- Search once with the quoted feature ID query. A single hit with no error is only a candidate: enforce direct sdd/specs/*.spec.md path and exact unfenced Feature ID metadata.
- Validate exists/content/error/truncated/encoding before accepting text at the requested ref. Reject binary/base64 results.
- On search errors, multiple/zero hits or invalid candidates, list sdd/specs at ref; inspect file entries in lexicographic path order.
- Bound unique candidate reads across both phases by max_spec_scan_files. Cache reads within the lookup, including rejections; first validated match wins.
- Fetch the resolved file at the same ref once more, revalidate feature identity/content, then parse. This final read adds at most one content call beyond the cap.
- Parse level-two Markdown sections outside fences, lower-case keys, strip leading N. numbering, preserve subsection contents.
- Filter AC boilerplate per spec §3 exactly, including checkbox/whitespace variants, comments and unresolved placeholders; retain original text of substantive criteria.
- Return exactly {"fields": {"summary": H1 title, "description": motivation section, self._ac_field_id: filtered AC}} or None.
- Log expected toolkit failures and return None; never let an unavailable spec abort the review. No review-entry wiring yet.

**NOT in scope**: Jira toolkit changes, `_extract_ticket_key` or `_fetch_ticket` behavior changes,
`_ask_llm_for_review` changes, external review submission during tests, dependency updates, and unrelated refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Ref-specific lookup, Markdown parsing and requirements envelope |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Lookup, validation, parser and AC-filter regression cases |

## Codebase Contract (Anti-Hallucination)

Verified at `ddaf44b059ebc2f2699f6750cadbc4141370000f`. Recheck these references after dependencies land; source line numbers
have moved since the spec, but the quoted attachment anchors are still present.

```python
from typing import Any, Dict, List, Literal, Optional
import re
from pydantic import BaseModel, Field
from parrot.bots.github_reviewer import GitHubReviewer, PRReviewResult
from unittest.mock import AsyncMock, MagicMock
import pytest
```
Reviewer imports verified at github_reviewer.py:40-60; test imports at
 test_github_reviewer.py:10-49. Standard library plus existing pyproject dependencies.

Additional imports from parrot_tools.gittoolkit: FileContentResult (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:493`), SearchCodeResult (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:545`),
GitToolkitError (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:46`); RepoDirectoryListing and RepoDirectoryEntry are created by TASK-4814, not present at planning time.
### Existing Signatures to Use
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2734`: async search_repo_code(self, query: str, repository: Optional[str] = None, max_results: int = 20) -> SearchCodeResult.
- `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:2518`: async get_file_content_at_ref(self, path: str, ref: str, repository: Optional[str] = None, start_line: Optional[int] = None, end_line: Optional[int] = None) -> FileContentResult.
- FileContentResult exposes exists, content, encoding, error, truncated, repository/path/ref; SearchCodeResult exposes total_count/items/error.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1880`: async _fetch_ticket(self, ticket_key: str, *, fields: Optional[str] = None) -> Optional[Dict[str, Any]]; returns envelope.data, consumed via fields.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:805`: self._ac_field_id is configured as JIRA_ACCEPTANCE_CRITERIA_FIELD, default customfield_10100.
- TASK-4813 provides self.max_spec_scan_files and the fixture's feature configuration.
- TASK-4814 provides async list_repo_directory(self, path: str, ref: str, repository: Optional[str] = None) -> RepoDirectoryListing.
### Does NOT Exist
- _locate_spec_file/_parse_spec_sections/_fetch_spec_requirement are absent before this task.
- There is no existing branch-aware code-search API; never invent a ref argument for search_repo_code.
- There is no feature-ID-to-path registry or Jira mapping required for spec resolution.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/github_reviewer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#FileContentResult",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#SearchCodeResult",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkitError",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.search_repo_code",
    "sym:packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py#GitToolkit.get_file_content_at_ref",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_ticket"
  ]
}
```

## Implementation Notes

Depends on TASK-4813 for max_spec_scan_files and serialized writes to github_reviewer.py/test_github_reviewer.py; depends on TASK-4814 for GitToolkit.list_repo_directory and RepoDirectoryListing in gittoolkit.py.

Use strict type hints, Google-style docstrings, existing logging, and black (120 columns).
Keep all network and LLM traffic mocked in tests. Do not add dependencies or new HTTP client imports.
Blueprint FILL IN markers describe planning gaps; remove every marker from completed implementation code.
This task has no Delegation Contract: edge-case implementation and test bodies require the normal executor.

## Implementation Blueprint

### Steps (in order)
1. Add typed toolkit imports and internal validation helpers — because search results alone are not trustworthy feature identity.
2. Implement bounded two-phase lookup with a per-call read cache — because branch mismatch and rejected candidates must not exhaust unbounded requests.
3. Implement fenced Markdown parsing and boilerplate filtering — because template-only AC cannot justify a review vote.
4. Revalidate final content and build the fields envelope — because refs may move between reads.
5. Add parameterized offline regressions for each boundary — because these failures must fall through safely.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:79`; occurrences: 1 (verified against `ddaf44b05`).
```python
from parrot_tools.gittoolkit import (
```
Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1880`; occurrences: 1 (verified against `ddaf44b05`).
```python
    async def _fetch_ticket(
```
Apply these scoped insertions; retain all surrounding code:
```python
# Extend the existing parrot_tools.gittoolkit import block with:
# FileContentResult, GitToolkitError, RepoDirectoryListing.
# Insert these methods immediately before _fetch_ticket:
async def _locate_spec_file(self, repo: str, feature_id: str, ref: str) -> Optional[str]:
    """Resolve a validated direct spec path at ref within a bounded read budget."""
    if not ref or self.git_toolkit is None:
        return None
    # FILL IN: read cache and shared budget; single-hit fast path then sorted listing.
    # FILL IN: exact unfenced feature metadata and readable non-truncated text checks.
    # FILL IN: catch/log GitToolkitError at search/list/read boundaries; return None on exhaustion.

@staticmethod
def _parse_spec_sections(markdown: str) -> Dict[str, str]:
    """Split Markdown on unfenced level-two headings with normalized section keys."""
    # FILL IN: fence tracking, optional N. prefix stripping, original content preservation.

async def _fetch_spec_requirement(
    self, repo: str, feature_id: str, ref: str,
) -> Optional[Dict[str, Any]]:
    """Return validated SDD requirements in the existing Jira fields envelope."""
    # FILL IN: locate, final reread and identity validation; toolkit failures return None.
    # FILL IN: derive H1/motivation; filter AC using the fixed template strings in spec §3.
    # FILL IN: return None without substantive AC, else the exact fields-only envelope.
```

**Why**: These helpers isolate all spec handling from the unchanged LLM prompt and public review orchestration. Add small private validators locally if necessary, with typed signatures and matching fixture bindings.

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/tests/bots/test_github_reviewer.py:52`; occurrences: 1 (verified against `ddaf44b05`).
```python
class _MinimalReviewer:
```
Apply these scoped insertions; retain all surrounding code:
```python
# Bind in _MinimalReviewer after the extraction binding created by TASK-4813:
_locate_spec_file = GitHubReviewer._locate_spec_file
_parse_spec_sections = staticmethod(GitHubReviewer._parse_spec_sections)
_fetch_spec_requirement = GitHubReviewer._fetch_spec_requirement
# Add FileContentResult, SearchCodeResult, GitToolkitError, RepoDirectoryListing
# and RepoDirectoryEntry to the existing toolkit imports; fixture models use real shapes.
class TestSDDSpecRequirements:
    @pytest.mark.asyncio
    async def test_locate_spec_file_budget_and_order(self) -> None:
        """Share the read cap across phases and reuse rejected candidate reads."""
        # FILL IN: cap=1, duplicate candidate, lexicographic entries and first match.
    @pytest.mark.asyncio
    async def test_fetch_spec_requirement_revalidates_final_content(self) -> None:
        """Never accept a different or unreadable file after a mutable-ref reread."""
        # FILL IN: final missing/error/truncated/binary content and changed feature ID.
    @pytest.mark.asyncio
    async def test_fetch_spec_requirement_shape_matches_fetch_ticket(self) -> None:
        """Return only the fields envelope using the configured AC field name."""
        # FILL IN: exact keys, H1, motivation and preserved substantive AC text.
```

**Why**: The test double reuses real helpers, with GitHub calls mocked and actual result models preventing accidental truthy MagicMock acceptance.

### FILL IN checklist
- [ ] Single valid search hit skips listing; invalid hit, rate-limit error and zero/multiple hits exercise listing.
- [ ] Reject wrong/nested paths, wrong extension, incidental mentions, prefix IDs and fenced headers.
- [ ] Count content calls across both phases; assert no duplicate read and no call for missing ref.
- [ ] Test exact/unnumbered headings, fenced examples, CRLF and mixed checkbox forms.
- [ ] Reject full template, generic subsets, comments-only/empty/placeholder AC; accept mixed real criteria and preserve real text.
- [ ] Ensure final content reread failures return None and custom AC field ID controls the output key.


## Acceptance Criteria

- [ ] Validated single-hit search and deterministic ref-specific listing both resolve valid specs.
- [ ] All candidates are direct spec files with exact unfenced metadata and readable, untruncated content at ref.
- [ ] Candidate reads never exceed max_spec_scan_files; rejected cached candidates are not reread during location.
- [ ] Final reread adds at most one content call and mismatched identity or unreadable content returns None.
- [ ] Empty ref makes zero GitHub calls and expected toolkit failures are logged and contained.
- [ ] Template-only/generic-subset/placeholder AC yields None; substantive text survives filtering unchanged.
- [ ] Envelope has exactly fields with summary, description and the configured AC key; _ask_llm_for_review remains unchanged.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

The task-owned regression cases are listed in the blueprint and acceptance criteria.
Extend existing fixtures only as required; preserve existing regression assertions.
Use fake GitHub responses and AsyncMock for asynchronous boundaries. Assert actual
call arguments/counts and public outcomes, not just private implementation details.

## Agent Instructions

1. Run `$sdd-start TASK-4815` to provision the feature worktree; never implement on dev.
2. Read the spec and verify all dependencies are done in `sdd/tasks/index/github-reviewer-sdd-spec-acceptance.json`.
3. Recheck the contract and anchors after dependency changes, then implement only declared files.
4. Run the Validation Commands; save logs under `artifacts/logs/`.
5. Commit scoped code and use `scripts.sdd.finalize_task` with real TaskCompletionEvidence
   and the implementation HEAD to finalize task state. Never manually move this file or use close_task.sh.

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 388s. Merged by engine; reviewer + gittoolkit suites pass (347 tests).
