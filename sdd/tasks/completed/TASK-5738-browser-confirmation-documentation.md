# TASK-5738: Documentation — Telegram browser login confirmation

**Feature**: FEAT-906 — Telegram browser login confirmation
**Spec**: `sdd/specs/telegram-browser-login-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5736, TASK-5737
**Assigned-to**: unassigned
**Discovered-from**: `issue:21146a531a96`

## Context

The owner approved browser-only code confirmation to prevent forwarded login links from authenticating the initiating Telegram chat as a different browser user. Implements FEAT-906.

## Scope

Update operator flow, public API, HTTP statuses, expiry/cancellation and security limitations. Document that browser authentication is pending until /login CODE reaches the initiating bot/user/chat; update both Mermaid and OAuth2 prose.

**NOT in scope**: distributed persistence, provider rewrites, unrelated authentication flows or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/integrations/telegram-auth-open-mode.md` | MODIFY | Confirmation flow |

## Codebase Contract

### Verified Imports

```python
from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field
from parrot.integrations.telegram.browser_login import BrowserLoginEntry, BrowserLoginRegistry
from parrot.integrations.telegram.auth import TelegramUserSession
```

The existing source uses aiohttp/Pydantic and the two Telegram types. Standard-library secrets, hashlib, time, asyncio and typing require no new dependencies. Never runtime-import auth.py or wrapper.py from browser_login.py (auth imports browser_login).

### Existing Signatures to Use

`BrowserLoginRegistry.register(entry)`, `.consume(state)`, `.peek(state)`; `TelegramAgentWrapper.handle_login(message)`, `.handle_logout(message)`, `._new_login_candidate(session)`, `._complete_auth_payload(data, *, telegram_id, chat_id, notify=True, browser_entry=None, run_post_success=True)` and `._authenticate_browser_identity(data, method, target, browser_entry)`. New signatures are fixed by spec §3 Interface skeletons. The HTML pages use `completeLogin(payload, legacySend)` and `showBrowserResult(ok, message, redirectUrl)`.

### Does NOT Exist

No existing confirmation code registry or redemption endpoint. No runtime-safe auth.py import from browser_login.py. No proof of Telegram sender ownership in browser state alone.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/integrations/telegram-auth-open-mode.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)

1. Reverify the listed anchors and read the approved spec — preserve its security boundary.
2. Implement only the declared files and the scope above — keep the change reviewable.
3. Run the explicit validation commands against worktree sources — shared editable installs otherwise test the main checkout.

### `wiki/integrations/telegram-auth-open-mode.md` (MODIFY)
```text
# occurrences: 1; verified wiki/integrations/telegram-auth-open-mode.md:6
# Telegram Auth Open Mode (webview | browser)
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.

### FILL IN checklist

- [ ] Scoped behavior and regression assertions satisfy the relevant AC1-AC7.
- [ ] No provider token or confirmation code is logged or sent to Telegram before redemption.

## Acceptance Criteria

- [ ] Scope above implemented without changing webview authentication behavior.
- [ ] Validation commands pass against worktree source paths.
- [ ] New/changed Python passes configured Ruff and Black checks.
- [ ] Spec AC1-AC7 relevant to this task hold.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py::test_wiki_page_documents_browser_mode -q`

## Test Specification

Use the spec §4 regression matrix. New tests must distinguish candidate verification from active session publication. Documentation also runs `parrot sdd techwiki check --spec sdd/specs/telegram-browser-login-fixes.spec.md --root .` during closeout.

## Agent Instructions

Work only in the FEAT-906 worktree. Preserve other edits. Commit this task's files, then use `parrot sdd task finalize` with real TaskCompletionEvidence at the implementation HEAD. Do not manually move task files or fabricate verification.

## Completion Note


- Task: TASK-5738
- Feature: telegram-browser-login-fixes
- Implementation SHA: 7a6c9f01253481e696b1fd7b0452aebd94754906
- Closed at (UTC): 2026-11-17T14:38:26+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 3 |
| fix_commits | 0 |
| checkpoint | unsupported_host: native manual implementation has no engine settlement |
| compaction | unsupported_host: no verified Codex adapter |
| review | Independent review and primary evidence cross-check recorded |
| validation | See immutable validation_refs |
