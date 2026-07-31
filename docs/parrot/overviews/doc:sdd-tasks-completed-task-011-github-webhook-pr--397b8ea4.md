---
type: Wiki Overview
title: 'TASK-011: GitHub webhook — emit `pr_comment` / `pr_review` events'
id: doc:sdd-tasks-completed-task-011-github-webhook-pr-comment-events-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the webhook half of Module 9. `GitHubWebhookHook` today only
relates_to:
- concept: mod:parrot.core.hooks.github_webhook
  rel: mentions
---

# TASK-011: GitHub webhook — emit `pr_comment` / `pr_review` events

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the webhook half of Module 9. `GitHubWebhookHook` today only
classifies `pull_request` opened/reopened/synchronize. The revision loop
(TASK-012) needs the hook to also surface reviewer **comments** and **reviews**.

---

## Scope

- Extend `GitHubWebhookHook._classify_event` to recognise:
  - `issue_comment` with `action == "created"` on a PR → `pr_comment`
  - `pull_request_review` with `action == "submitted"` → `pr_review`
- Parse and emit a payload carrying: `pr_number`, `body` (comment / review
  body), `head_sha`, `author` (login), `branch` (head ref), `repository`
  (`owner/name`), and `review_state` (for reviews: approved /
  changes_requested / commented).
- Emit `github.pr_comment` / `github.pr_review` events (mirror the existing
  `github.pr_*` emission shape).
- Keep existing `pull_request` handling unchanged.
- Unit tests with fixture payloads.

**NOT in scope**: the revision trigger/run (TASK-012); dev-loop `webhook.py`
(TASK-012).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/github_webhook.py` | MODIFY | Classify + parse `issue_comment` / `pull_request_review` |
| `packages/ai-parrot/tests/core/hooks/test_github_webhook_comments.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.hooks.github_webhook import GitHubWebhookHook   # github_webhook.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/hooks/github_webhook.py
class GitHubWebhookHook(BaseHook):                               # :12
    # handled today: pull_request actions {"opened","reopened","synchronize"}  (:26)
    def _classify_event(self, github_event, payload) -> Optional[str]   # :72
    # emits events tagged f"github.{event_type}"  (:104) with a parsed dict (:61-113):
    #   pr_number, pr_title, pr_body, head_ref, base_ref, draft, author, timestamps

# Reference consumer (already reacts to github.pr_* events):
# packages/ai-parrot/src/parrot/bots/github_reviewer.py  (handle_hook_event, head_sha dedup)
```

### Does NOT Exist
- ~~`issue_comment` / `pull_request_review` handling~~ — added here.
- ~~`github.pr_comment` / `github.pr_review` events~~ — created here.

---

## Implementation Notes

### Key Constraints
- `issue_comment` fires for both issues and PRs — only emit when
  `payload["issue"].get("pull_request")` is present (it IS a PR).
- For `issue_comment`, the head SHA is not in the payload; carry the PR number
  and let the consumer fetch head SHA (or include it from
  `pull_request_review.pull_request.head.sha` for reviews). Document which path
  carries `head_sha`.
- Preserve HMAC validation and existing classification for `pull_request`.

### References in Codebase
- `github_webhook.py:61-113` — existing PR payload parsing to mirror.
- `bots/github_reviewer.py` — head-sha dedup the consumer will reuse.

---

## Acceptance Criteria

- [ ] An `issue_comment.created` on a PR emits `github.pr_comment` with `pr_number`, `body`, `author`, `repository`.
- [ ] A `pull_request_review.submitted` emits `github.pr_review` with `review_state` + `head_sha`.
- [ ] An `issue_comment` on a non-PR issue is ignored.
- [ ] Existing `pull_request` classification unchanged.
- [ ] `pytest packages/ai-parrot/tests/core/hooks/test_github_webhook_comments.py -v` passes.

---

## Test Specification
```python
def test_issue_comment_on_pr_emits_pr_comment(hook):
    event_type = hook._classify_event("issue_comment",
        {"action":"created","issue":{"number":42,"pull_request":{}},"comment":{"body":"please fix"}})
    assert event_type == "pr_comment"

def test_issue_comment_on_plain_issue_ignored(hook):
    assert hook._classify_event("issue_comment",
        {"action":"created","issue":{"number":7},"comment":{"body":"x"}}) is None
```

---

## Agent Instructions
Standard SDD lifecycle. Confirm `_classify_event` shape before editing.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`core/hooks/github_webhook.py`)
- `_classify_event` now also recognises `issue_comment`/`created` **on a PR**
  (`issue.pull_request` present) → `pr_comment`, and
  `pull_request_review`/`submitted` → `pr_review`. Existing `pull_request`
  opened/reopened/synchronize handling is unchanged.
- Extracted `_build_event_payload(github_event, event_type, payload,
  delivery_id)` that parses three payload shapes: PR events (from
  `pull_request`), `pr_comment` (from `issue`+`comment`; `head_sha`/`branch`
  are `None` — not in the payload, consumer fetches via `pr_number`), and
  `pr_review` (from `pull_request`+`review`; carries `head_sha`, `branch`,
  `review_state`). Emits the documented keys plus a `body` alias.
- HMAC verification + the `github.<event_type>` emission shape preserved.

**Verification**
- `pytest test_github_webhook_comments.py` → 10 passed.
- Backward compat: existing `test_github_webhook.py` → 8 passed (18 total).
- `ruff check` clean on both files.
