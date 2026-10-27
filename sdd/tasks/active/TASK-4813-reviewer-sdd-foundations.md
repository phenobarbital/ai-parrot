# TASK-4813: Add reviewer SDD settings and base-ref payloads

**Feature**: FEAT-759 — GitHubReviewer SDD Spec Acceptance Criteria
**Spec**: `sdd/specs/github-reviewer-sdd-spec-acceptance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec M1 and M5 together with the additive review-result field from §2.

## Scope

Implement spec M1 and M5 together with the additive review-result field from §2.
- Add keyword-only sdd_feature_prefix="FEAT", enable_sdd_spec_fallback=True, max_spec_scan_files=500.
- Store these values; require a positive integer scan cap (reject booleans, non-integers and values <= 0 with ValueError).
- Add the escaped feature-prefix regex and extraction helper with the same first-text/first-match behavior as Jira extraction.
- Add conf-backed constants alongside GITHUB_REVIEW_JIRA_PROJECT, mirroring its environment/default pattern for configured subclasses.
  Retain the explicit constructor defaults in the approved skeleton, just as jira_project retains its literal NAV default.
- Add PRReviewResult.requirement_source with Literal["jira", "sdd_spec"] and default "jira".
- Add base_ref/base_sha from the already-fetched PR response; missing base fields become empty strings.
- Extend the lightweight test reviewer with the new state and helper bindings, without altering existing test assertions.
- Do not activate fallback in either review entry point yet; integration is a separate deliverable.

**NOT in scope**: Jira toolkit changes, `_extract_ticket_key` or `_fetch_ticket` behavior changes,
`_ask_llm_for_review` changes, external review submission during tests, dependency updates, and unrelated refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Constructor, extraction, result field and manual payload |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Environment-backed SDD setting constants |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Foundation regressions and minimal reviewer state |

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

`from navconfig import config` exists in `packages/ai-parrot/src/parrot/conf.py:6`; `from parrot import conf` exists in `packages/ai-parrot/tests/bots/test_github_reviewer.py:23`.
### Existing Signatures to Use
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:738`: GitHubReviewer.__init__(self, repository: str, *, jira_project: str = "NAV", ..., **kwargs: Any) -> None; preserve every existing parameter.
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1514`: _extract_ticket_key(self, *texts: str) -> Optional[str].
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:2299`: async _fetch_pr_payload(self, repo: str, pr_number: int) -> Optional[Dict[str, Any]].
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:261`: PRReviewResult(BaseModel), with jira_key/discrepancies/summary/approve.
- `packages/ai-parrot/tests/bots/test_github_reviewer.py:52`: _MinimalReviewer skips the Agent initializer; its real payload helper is bound at line 187.
- `packages/ai-parrot/src/parrot/conf.py:804`: GITHUB_REVIEW_JIRA_PROJECT uses config.get with a literal fallback.
### Does NOT Exist
- _extract_feature_id, _feature_id_regex and the three new settings are absent before this task.
- PRReviewResult.feature_id does not exist and must not be introduced.
- base_ref/base_sha are absent from the current manual reviewer payload.


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
      "path": "packages/ai-parrot/src/parrot/conf.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_github_reviewer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._extract_ticket_key",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_pr_payload",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#PRReviewResult",
    "sym:packages/ai-parrot/tests/bots/test_github_reviewer.py#_MinimalReviewer"
  ]
}
```

## Implementation Notes

No dependencies: modifies reviewer.py, conf.py and the reviewer test fixture; consumes no new toolkit symbol. Runs alongside TASK-4814, which owns separate toolkit files.

Use strict type hints, Google-style docstrings, existing logging, and black (120 columns).
Keep all network and LLM traffic mocked in tests. Do not add dependencies or new HTTP client imports.
Blueprint FILL IN markers describe planning gaps; remove every marker from completed implementation code.
This task has no Delegation Contract: edge-case implementation and test bodies require the normal executor.

## Implementation Blueprint

### Steps (in order)
1. Add constructor fields and conf constants — because later helpers need explicit, bounded settings.
2. Add extraction and payload metadata — because spec lookup must use the PR base branch.
3. Add the defaulted source field and fixture state — because old model construction and tests must keep working.
4. Add isolated configuration/extraction/payload regressions before committing — because no integration dependency is needed.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:742`; occurrences: 1 (verified against `ddaf44b05`).
```python
        jira_project: str = "NAV",
```
Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:826`; occurrences: 1 (verified against `ddaf44b05`).
```python
        self._ticket_key_regex = re.compile(rf"\b{re.escape(self.jira_project)}-\d+\b")
```
Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:261`; occurrences: 1 (verified against `ddaf44b05`).
```python
class PRReviewResult(BaseModel):
```
Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:2326`; occurrences: 1 (verified against `ddaf44b05`).
```python
            "head_sha": ((pr.get("head") or {}).get("sha")) or "",
```
Apply these scoped insertions; retain all surrounding code:
```python
# Add these keyword-only parameters immediately after jira_project:
sdd_feature_prefix: str = "FEAT",
enable_sdd_spec_fallback: bool = True,
max_spec_scan_files: int = 500,
# In __init__, before compiling the feature regex:
self.sdd_feature_prefix = sdd_feature_prefix
self.enable_sdd_spec_fallback = enable_sdd_spec_fallback
# FILL IN: reject invalid max_spec_scan_files as specified in Scope.
self.max_spec_scan_files = max_spec_scan_files
self._feature_id_regex = re.compile(rf"\b{re.escape(self.sdd_feature_prefix)}-\d+\b")
# Add a sibling of _extract_ticket_key in GitHubReviewer:
def _extract_feature_id(self, *texts: str) -> Optional[str]:
    """Return the first configured SDD feature identifier in the supplied texts."""
    # FILL IN: mirror _extract_ticket_key's empty-text and first-match rules.
# Add inside PRReviewResult without changing any existing field:
requirement_source: Literal["jira", "sdd_spec"] = "jira"
# Add to _fetch_pr_payload's returned dict immediately after head_sha:
"base_ref": ((pr.get("base") or {}).get("ref")) or "",
"base_sha": ((pr.get("base") or {}).get("sha")) or "",
```

**Why**: The constructor remains backward compatible; base metadata requires no additional API calls. Keep base_sha as metadata only.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)

Anchor at `packages/ai-parrot/src/parrot/conf.py:804`; occurrences: 1 (verified against `ddaf44b05`).
```python
GITHUB_REVIEW_JIRA_PROJECT: str = config.get("GITHUB_REVIEW_JIRA_PROJECT", fallback="NAV")
```
Apply these scoped insertions; retain all surrounding code:
```python
GITHUB_REVIEW_SDD_FEATURE_PREFIX: str = config.get("GITHUB_REVIEW_SDD_FEATURE_PREFIX", fallback="FEAT")
GITHUB_REVIEW_ENABLE_SDD_SPEC_FALLBACK: bool = config.getboolean("GITHUB_REVIEW_ENABLE_SDD_SPEC_FALLBACK", fallback=True)
GITHUB_REVIEW_MAX_SPEC_SCAN_FILES: int = config.getint("GITHUB_REVIEW_MAX_SPEC_SCAN_FILES", fallback=500)
```

**Why**: These constants expose the same deployment configuration pattern as the Jira prefix; callers can pass them explicitly as constructor kwargs.

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/tests/bots/test_github_reviewer.py:52`; occurrences: 1 (verified against `ddaf44b05`).
```python
class _MinimalReviewer:
```
Apply these scoped insertions; retain all surrounding code:
```python
# Extend _MinimalReviewer.__init__ with matching optional kwargs and state.
# Bind within _MinimalReviewer:
_extract_feature_id = GitHubReviewer._extract_feature_id
# Append tests; retain existing assertions.
class TestSDDReviewerFoundations:
    def test_extract_feature_id_matches_feat_prefix(self) -> None:
        """Recognize the configured prefix, respecting word boundaries and text order."""
        # FILL IN: FEAT-811, no match, custom escaped prefix, empty text, multiple IDs.
    def test_source_defaults_and_scan_limit(self) -> None:
        """Default to Jira on results and enabled bounded SDD lookup on reviewers."""
        # FILL IN: real constructor defaults, explicit False, invalid scan caps.
    @pytest.mark.asyncio
    async def test_fetch_pr_payload_includes_base_ref(self) -> None:
        """Copy the base branch and SHA without an additional GitHub request."""
        # FILL IN: normal base, missing/null base and missing keys; one API call.
```

**Why**: Fixture changes prepare later entry-point tests while existing behavior is still unchanged.

### FILL IN checklist
- [ ] Validate the real constructor and add configuration documentation; do not test only the stand-in.
- [ ] Implement first-match extraction and tests for escaped custom prefixes.
- [ ] Cover result defaults and manual payload missing/null base handling.


## Acceptance Criteria

- [ ] Default fallback is True; explicit False remains False. Prefix defaults to FEAT and cap to 500.
- [ ] Invalid scan caps fail deterministically; positive integer caps are stored unchanged.
- [ ] Feature extraction respects configured prefix, boundaries and ordered inputs.
- [ ] Manual payload contains base_ref/base_sha with empty-string defaults and makes no extra GitHub call.
- [ ] Existing result constructors default to jira and accept only the two declared source values.
- [ ] Existing test assertions remain unchanged and all foundation tests pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

The task-owned regression cases are listed in the blueprint and acceptance criteria.
Extend existing fixtures only as required; preserve existing regression assertions.
Use fake GitHub responses and AsyncMock for asynchronous boundaries. Assert actual
call arguments/counts and public outcomes, not just private implementation details.

## Agent Instructions

1. Run `$sdd-start TASK-4813` to provision the feature worktree; never implement on dev.
2. Read the spec and verify all dependencies are done in `sdd/tasks/index/github-reviewer-sdd-spec-acceptance.json`.
3. Recheck the contract and anchors after dependency changes, then implement only declared files.
4. Run the Validation Commands; save logs under `artifacts/logs/`.
5. Commit scoped code and use `scripts.sdd.finalize_task` with real TaskCompletionEvidence
   and the implementation HEAD to finalize task state. Never manually move this file or use close_task.sh.

## Completion Note

Pending implementation; finalization owns this section.
