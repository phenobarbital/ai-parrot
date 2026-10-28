# TASK-4816: Integrate SDD fallback into both review entry points

**Feature**: FEAT-759 — GitHubReviewer SDD Spec Acceptance Criteria
**Spec**: `sdd/specs/github-reviewer-sdd-spec-acceptance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4815
**Assigned-to**: unassigned

## Context

Implement spec M4 and the integration regressions in §4.

## Scope

Implement spec M4 and the integration regressions in §4.
- Before either no_ticket branch, attempt spec resolution only when no Jira key is present and fallback is enabled.
- If a spec resolves, use its FEAT ID as ticket_key and source sdd_spec; otherwise retain the existing no-ticket response and notification byte-for-byte.
- Jira-key presence always selects Jira. Preserve the existing fetch arguments, ticket_not_found outcomes and wiki-refresh lifecycle, even on Jira failure.
- Never pass a synthetic FEAT key to _fetch_ticket or overwrite an already resolved spec envelope with a Jira fetch.
- Preserve _ask_llm_for_review and its call signature, CI/check policy, submission rules, drafting and notification behavior.
- Explicitly stamp result.requirement_source after LLM return and add the same source to both reviewed outcome dictionaries.
- Retain source metadata for strict approved/deferred/blocked and review-submission errors; do not add fields to early no-review returns.
- Cover both source selection and real submit_pr_review calls using fakes, including webhook payload construction for opened/reopened/synchronize.
- Keep existing test assertions unchanged; only add cases and necessary fixture bindings.

**NOT in scope**: Jira toolkit changes, `_extract_ticket_key` or `_fetch_ticket` behavior changes,
`_ask_llm_for_review` changes, external review submission during tests, dependency updates, and unrelated refactors.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Webhook and strict source selection plus outcome metadata |
| `packages/ai-parrot/tests/bots/test_github_reviewer.py` | MODIFY | Paired flow and webhook integration regressions |

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

Additional verified import: `from parrot.core.hooks.github_webhook import GitHubWebhookHook` (`packages/ai-parrot/src/parrot/core/hooks/github_webhook.py:108`).
Toolkit result models used by fakes are verified in TASK-4815; reuse those imports and fixture setup.
### Existing Signatures to Use
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1523`: async review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any].
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:2767`: async strict_review_pull_request(self, payload: Dict[str, Any]) -> Dict[str, Any].
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1880`: async _fetch_ticket(self, ticket_key: str, *, fields: Optional[str] = None) -> Optional[Dict[str, Any]].
- `packages/ai-parrot/src/parrot/bots/github_reviewer.py:2029`: async _ask_llm_for_review(self, *, payload: Dict[str, Any], ticket_key: str, ticket: Dict[str, Any], diff_text: str, diff_truncated: bool, diff_available: bool, use_wiki: bool = True) -> PRReviewResult; unchanged.
- `packages/ai-parrot/src/parrot/core/hooks/github_webhook.py:108`: classmethod _build_event_payload(cls, github_event: str, event_type: str, payload: Dict[str, Any], delivery_id: str) -> Dict[str, Any]; pull-request branch has base_ref at line 205.
- TASK-4813 supplies config/extraction/source field/manual base_ref; TASK-4815 supplies _fetch_spec_requirement(repo, feature_id, ref).
### Does NOT Exist
- No source metadata exists on current public outcome dictionaries; add only after a review result exists.
- PRReviewResult.feature_id does not exist; reuse jira_key as the display key.
- No new webhook producer or SDD-to-Jira mapping is needed.


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
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.review_pull_request",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer.strict_review_pull_request",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._fetch_ticket",
    "sym:packages/ai-parrot/src/parrot/bots/github_reviewer.py#GitHubReviewer._ask_llm_for_review",
    "sym:packages/ai-parrot/src/parrot/core/hooks/github_webhook.py#GitHubWebhookHook._build_event_payload"
  ]
}
```

## Implementation Notes

Depends on TASK-4815 for _fetch_spec_requirement and serialized writes to github_reviewer.py/test_github_reviewer.py; TASK-4813 settings, result field and base_ref payload arrive transitively through TASK-4815.

Use strict type hints, Google-style docstrings, existing logging, and black (120 columns).
Keep all network and LLM traffic mocked in tests. Do not add dependencies or new HTTP client imports.
Blueprint FILL IN markers describe planning gaps; remove every marker from completed implementation code.
This task has no Delegation Contract: edge-case implementation and test bodies require the normal executor.

## Implementation Blueprint

### Steps (in order)
1. Insert fallback before each no-ticket branch — because source selection is controlled by Jira-key presence, not fetch success.
2. Guard the existing Jira fetch when a spec envelope already exists — because a FEAT key is not a Jira ticket.
3. Preserve each entry point's wiki-refresh start/await locations for the Jira path — because webhook and strict lifecycles differ.
4. Stamp selected source after the LLM result and in both outcome builders — because an LLM-provided source is untrusted metadata.
5. Add paired flow regressions and webhook payload coverage — because both entry paths must use the supplied base branch.

### `packages/ai-parrot/src/parrot/bots/github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:1559`; occurrences: 1 (verified against `ddaf44b05`).
```python
        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")
        if not ticket_key:
            self.logger.info(
```
Anchor at `packages/ai-parrot/src/parrot/bots/github_reviewer.py:2802`; occurrences: 1 (verified against `ddaf44b05`).
```python
        ticket_key = self._extract_ticket_key(payload.get("pr_body") or "", payload.get("pr_title") or "")
        if not ticket_key:
            outcome: Dict[str, Any] = {"status": "no_ticket", "repository": repo, "pr_number": pr_number}
```
Apply these scoped insertions; retain all surrounding code:
```python
# Insert immediately after ticket_key extraction in BOTH entry points:
requirement_source = "jira"
ticket = None
if not ticket_key and self.enable_sdd_spec_fallback:
    feature_id = self._extract_feature_id(payload.get("pr_body") or "", payload.get("pr_title") or "")
    if feature_id:
        ticket = await self._fetch_spec_requirement(repo, feature_id, str(payload.get("base_ref") or ""))
        if ticket is not None:
            ticket_key = feature_id
            requirement_source = "sdd_spec"
# Keep each existing `if not ticket_key:` branch unchanged.
# At the existing Jira fetch site after _start_wiki_refresh, guard the fetch:
if requirement_source == "jira":
    # Webhook entry point:
    ticket = await self._fetch_ticket(ticket_key)
    # Strict entry point instead uses its original fields argument:
    # ticket = await self._fetch_ticket(ticket_key, fields=self._jira_strict_fields)
# Retain the existing ticket-is-None branch and its return/notification behavior.
# Immediately after the LLM returns (outside the unchanged call):
result.requirement_source = requirement_source
# Add this entry to EACH post-review outcome dict (not early returns):
"requirement_source": requirement_source,
```

**Why**: This preserves Jira failure behavior and only enables fallback for absent Jira keys. The two quoted anchors disambiguate otherwise identical extraction statements; each full context occurs once.

### `packages/ai-parrot/tests/bots/test_github_reviewer.py` (MODIFY)

Anchor at `packages/ai-parrot/tests/bots/test_github_reviewer.py:52`; occurrences: 1 (verified against `ddaf44b05`).
```python
class _MinimalReviewer:
```
Apply these scoped insertions; retain all surrounding code:
```python
# Add this verified import for webhook integration regression:
from parrot.core.hooks.github_webhook import GitHubWebhookHook

class TestSDDReviewIntegration:
    @pytest.mark.asyncio
    async def test_jira_fetch_failure_never_uses_spec(self) -> None:
        """A found Jira key wins even when its issue cannot be fetched."""
        # FILL IN: both entry points; no toolkit/error/missing issue; both IDs present.
    @pytest.mark.asyncio
    async def test_review_outcomes_expose_requirement_source(self) -> None:
        """Stamp selected source on model and outcomes regardless of LLM output."""
        # FILL IN: Jira/spec; approve/block/defer/submission-error and explicit disabled fallback.
    @pytest.mark.asyncio
    async def test_review_pull_request_end_to_end_spec_sourced(self) -> None:
        """A search miss can become an actual review vote using a base-branch spec."""
        # FILL IN: real helper chain, fake toolkit/LLM, assert review event/body and source.
    @pytest.mark.asyncio
    async def test_webhook_spec_review_uses_base_ref(self) -> None:
        """Webhook payloads forward the branch used for every spec read."""
        # FILL IN: call GitHubWebhookHook._build_event_payload with PR events.
```

**Why**: Use the real payload builder and requirements helpers with fake I/O; direct mutation of expected source values would not test integration. Existing fixture bindings are provided by predecessors.

### FILL IN checklist
- [ ] Parameterize both entry points for Jira-only, both IDs, spec-only, disabled fallback and no usable source.
- [ ] Assert identical early no-ticket/ticket-not-found outcomes, comment-only behavior and zero review votes on unusable AC.
- [ ] Assert real submit_pr_review arguments for APPROVE, REQUEST_CHANGES and strict deferred COMMENT.
- [ ] Assert wiki-refresh start/await behavior remains unchanged for Jira success/failure.
- [ ] Assert source persists on submission failure and cannot be overridden by LLM output.
- [ ] Build webhook events through the existing classmethod; use a base ref different from the default branch.


## Acceptance Criteria

- [ ] Both entry points use spec fallback only when Jira extraction returns no key and fallback is enabled.
- [ ] Jira fetch failures never invoke spec lookup or submit a review; original failure outcomes and lifecycle remain unchanged.
- [ ] Resolvable substantive specs produce real review votes with sdd_spec metadata; no-source and placeholder specs remain comment-only.
- [ ] Selected source overrides LLM source and is exposed on model and all reviewed outcome variants including submission errors.
- [ ] Existing CI, draft, notification and review-submission decisions remain unchanged; _ask_llm_for_review is untouched.
- [ ] Manual payload and opened/reopened/synchronize webhook payloads resolve at the supplied base_ref.
- [ ] All pre-existing reviewer tests pass without weakening assertions.

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_github_reviewer.py -q`

## Test Specification

The task-owned regression cases are listed in the blueprint and acceptance criteria.
Extend existing fixtures only as required; preserve existing regression assertions.
Use fake GitHub responses and AsyncMock for asynchronous boundaries. Assert actual
call arguments/counts and public outcomes, not just private implementation details.

## Agent Instructions

1. Run `$sdd-start TASK-4816` to provision the feature worktree; never implement on dev.
2. Read the spec and verify all dependencies are done in `sdd/tasks/index/github-reviewer-sdd-spec-acceptance.json`.
3. Recheck the contract and anchors after dependency changes, then implement only declared files.
4. Run the Validation Commands; save logs under `artifacts/logs/`.
5. Commit scoped code and use `scripts.sdd.finalize_task` with real TaskCompletionEvidence
   and the implementation HEAD to finalize task state. Never manually move this file or use close_task.sh.

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 97s. Merged by engine; 350 tests pass across reviewer + gittoolkit suites.
