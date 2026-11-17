# TASK-5736: Stage browser identities until Telegram code confirmation

**Feature**: FEAT-906 — Telegram browser login confirmation
**Spec**: `sdd/specs/telegram-browser-login-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:21146a531a96`

## Context

The owner approved browser-only code confirmation to prevent forwarded login links from authenticating the initiating Telegram chat as a different browser user. Implements FEAT-906.

## Scope

Implement spec M1/M2 and the OAuth2 part of M3. Verify into an isolated candidate; return a browser-only confirmation code. Only a scoped Telegram redemption may publish the candidate. Preserve existing webview behavior. Cover forwarded links, owner binding, expiry, replay, cancellation, concurrent requests and post-auth deferral.

**NOT in scope**: distributed persistence, provider rewrites, unrelated authentication flows or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py` | MODIFY | Security implementation/test |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login_confirmation.py` | CREATE | Security implementation/test |

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
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login_confirmation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py#BrowserLoginRegistry",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py#_browser_oauth2_callback"
  ]
}
```

## Implementation Blueprint

### Steps (in order)

1. Reverify the listed anchors and read the approved spec — preserve its security boundary.
2. Implement only the declared files and the scope above — keep the change reviewable.
3. Run the explicit validation commands against worktree sources — shared editable installs otherwise test the main checkout.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/src/parrot/integrations/telegram/browser_login.py:58
class BrowserLoginRegistry:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py:152
async def _browser_oauth2_callback(request: web.Request, state: str) -> web.Response:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:2570
    async def handle_login(self, message: Message) -> None:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py:177
async def test_browser_complete_handler_success(browser_client) -> None:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py:339
async def test_browser_identity_uses_verified_claims() -> None:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py` (MODIFY)
```text
# occurrences: 1; verified packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py:504
class TestOAuth2BrowserBranch:
```
FILL IN: implement this file’s scoped changes using the spec interfaces and AC1-AC7. Preserve adjacent behavior. Why: this verified anchor identifies the current flow under test.
### `packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login_confirmation.py` (CREATE)
```python
"""FEAT-906: browser authentication stays pending until Telegram confirmation."""
import pytest

# FILL IN: fixtures and regression cases bounded by spec AC1-AC5.
```
Why: exercise real registry/wrapper behavior with fake provider I/O, not a mocked completion result.

### FILL IN checklist

- [ ] Scoped behavior and regression assertions satisfy the relevant AC1-AC7.
- [ ] No provider token or confirmation code is logged or sent to Telegram before redemption.

## Acceptance Criteria

- [ ] Scope above implemented without changing webview authentication behavior.
- [ ] Validation commands pass against worktree source paths.
- [ ] New/changed Python passes configured Ruff and Black checks.
- [ ] Spec AC1-AC7 relevant to this task hold.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_identity_verification.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_browser_login_confirmation.py -q`

## Test Specification

Use the spec §4 regression matrix. New tests must distinguish candidate verification from active session publication. Documentation also runs `parrot sdd techwiki check --spec sdd/specs/telegram-browser-login-fixes.spec.md --root .` during closeout.

## Agent Instructions

Work only in the FEAT-906 worktree. Preserve other edits. Commit this task's files, then use `parrot sdd task finalize` with real TaskCompletionEvidence at the implementation HEAD. Do not manually move task files or fabricate verification.

## Completion Note

Recorded by task finalization after implementation and validation.
