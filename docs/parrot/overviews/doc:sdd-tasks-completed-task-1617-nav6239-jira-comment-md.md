---
type: Wiki Overview
title: 'TASK-1617: Jira Comment — NAV-6239 Fix Confirmed'
id: doc:sdd-tasks-completed-task-1617-nav6239-jira-comment-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-1616 adds and passes the regression tests confirming that
relates_to:
- concept: mod:parrot.tools
  rel: mentions
---

# TASK-1617: Jira Comment — NAV-6239 Fix Confirmed

**Feature**: FEAT-254 — BotManager Hot Registration — NAV-6239 Confirmation
**Spec**: `sdd/specs/botmanager-hot-registration-nav6239.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1616
**Assigned-to**: unassigned

---

## Context

After TASK-1616 adds and passes the regression tests confirming that
`ChatbotHandler._put_database` immediately registers new bots in `BotManager`
without restart, this task posts an audit comment on Jira ticket **NAV-6239**
("Service Restart Required to Train and Use New Bot") so the ticket can be
resolved and stakeholders are informed.

Implements **Spec §3 Module 2**.

---

## Scope

Post a single comment on Jira ticket **NAV-6239** that contains:

1. **Triage summary**: explain which code path already implements hot registration.
2. **Evidence**: cite the test file and test function names added in TASK-1616.
3. **Conclusion**: the bug is confirmed fixed; no server restart is required when
   a bot is created via `PUT /api/v1/bots`.
4. **Recommendation**: resolve/close the ticket.

**NOT in scope**:
- Changing any production code.
- Transitioning the Jira ticket status (leave that for the assignee to do
  manually unless the Jira toolkit exposes a transition endpoint).
- Editing or closing other Jira tickets.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| *(none)* | — | This task performs a one-shot Jira API call; no repo file is created |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# JiraToolkit — parrot/tools/jira/toolkit.py (or parrot.tools.jira)
# Uses environment variables:
#   JIRA_INSTANCE   — e.g. https://trocglobal.atlassian.net
#   JIRA_USERNAME   — e.g. jesuslarag@gmail.com
#   JIRA_API_TOKEN  — Atlassian API token
#   JIRA_PROJECT    — e.g. NAV
# Auth: basic_auth with (JIRA_USERNAME, JIRA_API_TOKEN)
```

### Jira REST endpoint for adding a comment

```
POST {JIRA_INSTANCE}/rest/api/3/issue/{issueIdOrKey}/comment
Content-Type: application/json
Authorization: Basic <base64(email:token)>

{
  "body": {
    "type": "doc",
    "version": 1,
    "content": [
      {
        "type": "paragraph",
        "content": [{ "type": "text", "text": "<comment text>" }]
      }
    ]
  }
}
```

### Does NOT Exist

- ~~`JiraToolkit.add_comment()`~~ — verify the exact method name via `grep`
  before calling; it may be `post_comment`, `comment`, or a direct HTTP call.
- ~~`JiraToolkit.close_ticket()`~~ — no such method; status transitions require
  a separate workflow call (out of scope).

---

## Implementation Notes

### Comment text to post

Use this exact text (or a minor localisation) as the Jira comment body:

---

**NAV-6239 — Fix Confirmed (FEAT-254)**

**Triage finding:**
Code review of `packages/ai-parrot-server/src/parrot/handlers/bots.py`
confirms that `ChatbotHandler._put_database` (line 863) already calls
`_register_bot_into_manager → manager.add_bot(bot)` (line 892 / 599)
immediately after persisting the bot to the database.  The bot is available
in `BotManager._bots` before the HTTP 201 response is returned —
**no server restart is required**.

The same pattern applies for updates (`_post_database` removes the old
instance and re-registers) and deletes (`delete` calls `manager.remove_bot`).

**Evidence:**
Regression tests added in FEAT-254 (commit on branch
`feat-254-botmanager-hot-registration-nav6239`):
- `test_put_database_registers_bot_immediately`
- `test_post_database_reregisters_updated_bot`
- `test_delete_database_removes_bot_from_manager`

File: `packages/ai-parrot/tests/test_chatbot_handler.py`

All three tests pass on `pytest packages/ai-parrot/tests/test_chatbot_handler.py -v`.

**Recommendation:** Resolve / close NAV-6239 — the fix was already in place.

---

### How to post the comment

**Option A — via JiraToolkit (preferred if available):**

```python
import asyncio
from parrot.tools.jira.toolkit import JiraToolkit  # verify path first

async def post():
    jira = JiraToolkit()
    await jira.add_comment("NAV-6239", "<comment text above>")

asyncio.run(post())
```

**Option B — via curl (fallback):**

```bash
source .venv/bin/activate
python - <<'EOF'
import os, json, base64, urllib.request

instance = os.environ["JIRA_INSTANCE"]
user = os.environ["JIRA_USERNAME"]
token = os.environ["JIRA_API_TOKEN"]

comment_body = {
    "body": {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "NAV-6239 — Fix Confirmed (FEAT-254)\n\n<paste full comment text>"}
                ]
            }
        ]
    }
}

url = f"{instance}/rest/api/3/issue/NAV-6239/comment"
creds = base64.b64encode(f"{user}:{token}".encode()).decode()
req = urllib.request.Request(
    url,
    data=json.dumps(comment_body).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Basic {creds}"},
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    print(resp.status, resp.read().decode())
EOF
```

**Option C — via `gh` CLI Jira extension (if installed):**
Check if `gh jira comment NAV-6239` is available.

### Key Constraints

- Do NOT commit any code file for this task.
- Confirm TASK-1616 tests pass before posting the comment.
- If all three options fail (no credentials, no network), output the comment
  text to stdout so the assignee can paste it manually, then mark this task
  complete with a deviation note.

---

## Acceptance Criteria

- [ ] Comment posted on https://trocglobal.atlassian.net/browse/NAV-6239.
- [ ] Comment references the test file path and all three test function names.
- [ ] Comment concludes that the fix is confirmed and restart is not required.
- [ ] TASK-1616 tests pass before this comment is posted (dependency enforced).

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1616 is in `sdd/tasks/completed/` and its tests pass.
2. Check available tools:
   - Try `from parrot.tools.jira.toolkit import JiraToolkit` — if importable, use Option A.
   - Else use Option B (pure Python stdlib, no extra deps).
3. Verify env vars `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN` are set.
4. Post the comment using the exact text from "Comment text to post" above.
5. Confirm the HTTP 200/201 response.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude (sdd-worker / /sdd-start)
**Date**: 2026-06-26
**Notes**: Used Option B (pure Python stdlib via `urllib.request`), loading credentials
from `env/.env`. Comment posted successfully — HTTP 201 received.

  - Comment ID : 59477
  - Author     : Jesus Lara (jesuslarag@gmail.com)
  - Created    : 2026-06-26T09:14:34.545-0400
  - URL        : https://trocglobal.atlassian.net/browse/NAV-6239?focusedCommentId=59477

Comment body includes: triage finding, code path references (bots.py:863/892/599),
all three test function names, file path (`TestHotRegistrationRegression` class),
and recommendation to close.

**Deviations from spec**: none — comment text matches the spec template exactly.
