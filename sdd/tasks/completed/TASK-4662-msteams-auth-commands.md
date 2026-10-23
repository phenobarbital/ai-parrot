# TASK-4662: /login, /logout and /whoami commands for MS Teams

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4661
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 4**. User-facing control over the lane built by
TASK-4661, registered on the router that already exists.

`/whoami` is the proof of concept's `whoami` probe surfaced in Teams: the PoC's
`GET /poc/whoami` returned `{"nav_user_id": "35", ...}` for the exchanged
session, and this command reports the same thing to the user.

The reply text must distinguish `user_not_found` — *"you are not provisioned in
Navigator"* — from a bad or missing token. The exchange **never provisions
users** (spec §7), so this is the most likely production failure, and a generic
"login failed" would send people hunting the wrong problem.

---

## Scope

- Create `msteams/commands/auth_commands.py` with
  `register_auth_commands(router, strategy)`.
- `/login` — resolve through the strategy; on "needs auth" send the sign-in
  card; on success confirm with the resolved identity.
- `/logout` — `strategy.sign_out`, then confirm.
- `/whoami` — report Navigator id, email and session expiry, or say plainly that
  the user is not signed in.
- Unit tests for the three handlers, including the `user_not_found` wording.

**NOT in scope**: registering the commands on the router instance — that call
site is in `wrapper.py` and belongs to TASK-4663, which owns every edit to that
file. Do **not** modify `wrapper.py` or `commands/__init__.py` here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py` | CREATE | The three handlers + `register_auth_commands` |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.core import TurnContext                                   # installed
from parrot.integrations.msteams.auth import MSTeamsAuthStrategy, user_key  # TASK-4659/4661
from parrot.auth.token_exchange import REASON_USER_NOT_FOUND, REASON_BACKEND_NOT_LOADED  # TASK-4660
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py — the router this task registers on
class MSTeamsCommandRouter:
    def register(self, command: str, handler: Callable) -> None:   # line 56
    async def try_dispatch(self, text: str, turn_context) -> bool: # line 74

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py — the registration pattern to mirror
def register_jira_commands(router, oauth_manager) -> ...            # line 300
def _connect_jira_card(...)                                         # line 39  (card shape)
def _get_user_id(turn_context: "TurnContext") -> str                # line 116

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/knowledge_upload.py — roster lookup for the email
class TeamsKnowledgeUpload:                                         # line 59
    async def resolve_email(self, turn_context: TurnContext) -> Optional[str]:  # line 115

# From TASK-4661:
class MSTeamsAuthStrategy:
    async def ensure_authenticated(self, turn_context) -> MSTeamsUserSession
    async def send_signin_card(self, turn_context) -> None
    async def sign_out(self, turn_context) -> None
```

### Does NOT Exist
- ~~a `/login` command registered under `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`~~ — 0 hits. The router's
  existing commands are the Jira, agent and knowledge-upload ones.
- ~~`MSTeamsCommandRouter.unregister` / `.commands` / `.list_commands`~~ — the
  API is `register` and `try_dispatch` only.
- ~~`strategy.login()` / `.logout()`~~ — the methods are
  `ensure_authenticated`, `send_signin_card`, `sign_out`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter.register",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsAuthStrategy",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py#register_jira_commands"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Adaptive Cards go through `parrot.outputs.cards`; follow `_connect_jira_card`
  (`jira_commands.py:39`) and use `DEFAULT_ADAPTIVE_CARD_VERSION`.
- **Never echo a token** into a reply or a log.
- `/whoami` on an unauthenticated user is a normal answer, not an error.

### Reason-to-wording map (AC-3)
| `reason` | What the user is told |
|---|---|
| `user_not_found` | not provisioned in Navigator — an administrator must create the account |
| `backend_not_loaded` | the server is not configured for this sign-in method (operator problem) |
| anything else | sign-in failed, try `/login` again |

---

## Implementation Blueprint

### Steps (in order)
1. Write `register_auth_commands` as a thin closure factory over the strategy —
   *why*: it mirrors `register_jira_commands` and keeps the handlers testable
   without a router.
2. Branch `/login` on `session.metadata["auth_reason"]` — *why*: AC-3 asserts
   the distinct wording, and the strategy puts the verbatim reason there.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py` (CREATE)
```python
"""/login, /logout and /whoami for the MS Teams lane."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from botbuilder.core import TurnContext

from parrot.auth.token_exchange import (
    REASON_BACKEND_NOT_LOADED,
    REASON_USER_NOT_FOUND,
)

if TYPE_CHECKING:  # pragma: no cover
    from parrot.integrations.msteams.auth import MSTeamsAuthStrategy
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter

logger = logging.getLogger(__name__)


def register_auth_commands(router: "MSTeamsCommandRouter",
                           strategy: "MSTeamsAuthStrategy") -> None:
    """Register /login, /logout and /whoami on the router.

    # verified: MSTeamsCommandRouter.register  packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py:56
    # pattern:  register_jira_commands         packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/jira_commands.py:300
    """

    async def cmd_login(turn_context: TurnContext, *_args) -> None:
        """Sign the user in, or send the sign-in card."""
        # FILL IN: session = await strategy.ensure_authenticated(ctx);
        # authenticated -> confirm with session.nav_user_id and email;
        # else branch on session.metadata.get("auth_reason") per the wording
        # table, and call strategy.send_signin_card(ctx) for the
        # no-token/invalid-token case only. Bounded by AC-1, AC-3.
        raise NotImplementedError

    async def cmd_logout(turn_context: TurnContext, *_args) -> None:
        """Drop the Navigator session and the Token Service token."""
        # FILL IN: await strategy.sign_out(ctx) then confirm — bounded by AC-2
        raise NotImplementedError

    async def cmd_whoami(turn_context: TurnContext, *_args) -> None:
        """Report the resolved Navigator identity and session expiry."""
        # FILL IN: read the session WITHOUT triggering a new exchange; report
        # nav_user_id, nav_email and external_expires_at, or say plainly that
        # the user is not signed in. Bounded by AC-4.
        raise NotImplementedError

    router.register("/login", cmd_login)
    router.register("/logout", cmd_logout)
    router.register("/whoami", cmd_whoami)
```
**Why this shape**: the closures capture `strategy`, so the tests construct the
three handlers with a stub strategy and no router at all. `cmd_whoami` must not
trigger an exchange — it is a report, and a user running it repeatedly should
not hammer the Token Service.

### FILL IN checklist
- [ ] `cmd_login` — resolution + the reason branches; bounded by AC-1, AC-3
- [ ] `cmd_logout` — sign-out + confirmation; bounded by AC-2
- [ ] `cmd_whoami` — read-only report; bounded by AC-4

---

## Acceptance Criteria

- [ ] AC-1 `/login` on a user with a usable token ends authenticated and the
      reply names the Navigator id
- [ ] AC-2 `/logout` calls `strategy.sign_out` exactly once and confirms
- [ ] AC-3 `/login` for a user absent from `auth.users` says *not provisioned*
      and does **not** send a sign-in card; `backend_not_loaded` produces the
      operator wording instead
- [ ] AC-4 `/whoami` reports id, email and expiry when signed in, says so
      plainly when not, and triggers **no** exchange in either case
- [ ] No token value appears in a reply or a log record
- [ ] The three commands are registered through `router.register`
- [ ] `wrapper.py` and `commands/__init__.py` are **untouched** by this task
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_commands.py
import pytest

from parrot.integrations.msteams.commands.auth_commands import register_auth_commands


class _Router:
    """Captures registrations; mirrors MSTeamsCommandRouter.register's shape."""
    def __init__(self):
        self.handlers = {}

    def register(self, command, handler):
        self.handlers[command] = handler


class TestRegistration:
    def test_registers_three_commands(self):
        """/login, /logout and /whoami land on the router."""
        # FILL IN


class TestLogin:
    async def test_user_not_found_wording_and_no_card(self):
        """Not provisioned in Navigator is its own message, with no card."""
        # FILL IN

    async def test_whoami_triggers_no_exchange(self):
        """/whoami is a report, not an authentication attempt."""
        # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug msteams-user-auth-lane --feature-id FEAT-729`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/msteams-user-auth-lane.json`
4. **Verify the Codebase Contract** before writing ANY code. Re-grep every
   anchor: this task was written on `dev @ 0eb59926a` and the spec's §6 was
   verified on `37dc1da44`, so two anchors had already drifted once (see
   Context where noted). If anything moved, fix the contract FIRST.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every
   `# FILL IN:` marker, never change a signature or path it fixes
7. **Verify** the Acceptance Criteria — run the Validation Commands with
   `PYTHONPATH` set per changed package (the shared `.venv` is editable-installed
   against the MAIN checkout, so a bare `pytest` in a worktree imports the wrong
   branch)
8. **Commit the code** — stage only the files this task lists (never `git add .`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4662 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed**: Seat: gpt-5.6-terra · codex · Attempts: 1 · Duration: 165s. /login, /logout, /whoami in msteams/commands/auth_commands.py with tests; merge-tier validation green; reviewed against AC-1..4, no corrections.
**Deviations from scope**: none
**Ambiguities found in the spec**: none
**Follow-up needed**: none
