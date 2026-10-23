# TASK-4665: End-to-end integration tests for the MS Teams auth lane

**Feature**: FEAT-729 — MS Teams user authentication lane
**Spec**: `sdd/specs/msteams-user-auth-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4659, TASK-4660, TASK-4661, TASK-4662, TASK-4664
**Assigned-to**: unassigned

---

## Context

Implements the **integration half of spec §3 Module 7 / §4**. Each previous task
ships its own unit tests; this one proves the pieces work *together* over a full
Teams turn.

The fixtures reuse the proof of concept's data verbatim, because it is already
proven to drive the real code: `sdd/state/FEAT-729/poc/poc_teams_identity.py`
exercised the actual `_get_user_id` and `resolve_email`, and
`exchange_run.transcript.md` holds the real `HTTP 200` body shape.

**No live Azure credential is required.** The exchange is stubbed at the
`aiohttp` boundary; the one real end-to-end run is recorded evidence under
`sdd/state/FEAT-729/poc/`, not a test.

---

## Scope

- Create `test_msteams_auth_lane.py` with the three integration tests of spec §4.
- Provide the three shared fixtures (`teams_activity`, `fake_adapter`,
  `exchange_response_200`) with signatures matching the real `BotFrameworkAdapter`.
- Assert the identity equality that is the feature's whole point:
  `provider_user_id` from the exchange equals `aad_object_id` from the activity.

> **Not dependent on TASK-4663.** This suite assembles the lane by hand
> (strategy + `register_auth_commands`) and never constructs
> `MSTeamsAgentWrapper`; the wrapper's auth gate is covered by TASK-4663's
> own `test_msteams_auth_gate.py`. `check_task_graph` flagged the edge as
> unjustified and it was removed rather than rationalised.

**NOT in scope**: unit tests for individual modules (they ship with their own
tasks); any `real_llm` test; a live Azure or Navigator call.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py` | CREATE | Three integration tests + shared fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.schema import Activity, ChannelAccount                  # installed
from parrot.integrations.msteams.auth import (                          # TASK-4659/4661
    MSTeamsAuthStrategy, MSTeamsSessionStore, MSTeamsUserSession, user_key,
)
from parrot.auth.token_exchange import TokenExchangeClient               # TASK-4660
from parrot.integrations.msteams.commands.auth_commands import register_auth_commands  # TASK-4662
```

### Existing Signatures to Use
```python
# The adapter methods the fake MUST mirror exactly (installed signatures):
async def get_user_token(self, context, connection_name: str, magic_code: str = None,
                         oauth_app_credentials=None) -> TokenResponse
async def exchange_token(self, turn_context, connection_name: str, user_id: str,
                         exchange_request) -> TokenResponse

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py:173 — the callback under regression test
async def handle_msteams_jira_callback(request)   # verified: line 173

# The PoC's real 200 body shape (sdd/state/FEAT-729/poc/exchange_run.transcript.md):
#   user_id=35  username=jlara@trocglobal.com  email=jlara@trocglobal.com
#   auth_method=basic  auth_origin=azure
#   provider_user_id=4e2aa0ea-56b8-49fe-85cf-05e97d479ba6   <- the Entra oid
```

### Does NOT Exist
- ~~a shared `conftest.py` fixture for Teams activities~~ — check
  `packages/ai-parrot-integrations/tests/integrations/msteams/` before adding one; if a local `conftest.py` exists, extend it rather
  than redefining fixtures in this file.
- ~~a live Azure token in CI~~ — never write a test that needs one.
- ~~`TokenResponse` from `botbuilder.schema`~~ — it is in
  `botframework.connector.token_api.models`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py#MSTeamsAuthStrategy",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py#handle_msteams_jira_callback"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The fake adapter's signatures must match the real ones. A fake that drifts
  passes a suite against a shape the real adapter does not have — the spec calls
  this out explicitly in §4.
- Reuse the PoC's constants so the fixtures and the recorded evidence agree.

---

## Implementation Blueprint

### Steps (in order)
1. Write the fixtures first — *why*: all three tests share them, and the
   `fake_adapter` signature fidelity is the main risk in this task.
2. Assert the `provider_user_id == aad_object_id` equality explicitly — *why*:
   it is the feature's core claim, and a test that only checks "authenticated"
   would pass even if the wrong identity were bound.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py` (CREATE)
```python
"""Integration tests for the MS Teams authentication lane (FEAT-729)."""
from __future__ import annotations

import pytest

from botbuilder.schema import Activity, ChannelAccount

# Reused verbatim from sdd/state/FEAT-729/poc/ — already proven to drive the
# real _get_user_id and resolve_email.
TEAMS_OID = "7c8f1d2e-3b4a-5c6d-7e8f-9a0b1c2d3e4f"
TENANT_ID = "11112222-3333-4444-5555-666677778888"


@pytest.fixture
def teams_activity() -> Activity:
    """Activity with aad_object_id, tenant and a Teams-scoped from id."""
    # FILL IN: build the Activity with channel_data={"tenant": {"id": TENANT_ID}}
    # and from_property=ChannelAccount(id="29:...", aad_object_id=TEAMS_OID)


@pytest.fixture
def fake_adapter():
    """Stubs get_user_token / exchange_token / get_oauth_sign_in_link.

    Signatures must match BotFrameworkAdapter exactly (Codebase Contract).
    """
    # FILL IN


@pytest.fixture
def exchange_response_200() -> dict:
    """The PoC's real 200 body, redacted."""
    # FILL IN: user_id 35, auth_origin azure, provider_user_id == TEAMS_OID


class TestLoginEndToEnd:
    async def test_login_command_end_to_end(self, teams_activity, fake_adapter,
                                            exchange_response_200):
        """/login -> token -> exchange -> session -> /whoami reports the nav id."""
        # FILL IN: drive the registered /login then /whoami handlers; assert the
        # reply names the Navigator id and that provider_user_id == TEAMS_OID


class TestSsoInvoke:
    async def test_signin_token_exchange_invoke(self, teams_activity, fake_adapter):
        """A signin/tokenExchange invoke routes to exchange_token and completes."""
        # FILL IN


class TestJiraCallbackRegression:
    async def test_jira_callback_persists_identity(self):
        """handle_msteams_jira_callback leaves a real row (42P10 regression)."""
        # FILL IN: depends on TASK-4664; assert the row reads back
```
**Why this shape**: the three classes map one-to-one onto spec §4's integration
table. The identity-equality assertion is inside the first test rather than its
own case because it is only meaningful on a completed exchange.

### FILL IN checklist
- [ ] `teams_activity` — PoC-faithful activity; bounded by AC-1
- [ ] `fake_adapter` — signature-faithful stubs; bounded by AC-4
- [ ] `exchange_response_200` — the recorded 200 body; bounded by AC-1
- [ ] the three tests; bounded by AC-1..AC-3

---

## Acceptance Criteria

- [ ] AC-1 `/login` → `/whoami` completes and the reported id is the Navigator
      id, with `provider_user_id == aad_object_id` asserted explicitly
- [ ] AC-2 a `signin/tokenExchange` invoke reaches `adapter.exchange_token` and
      ends with an authenticated session
- [ ] AC-3 `handle_msteams_jira_callback` leaves a row that reads back
- [ ] AC-4 every fake adapter method's signature matches the installed
      `BotFrameworkAdapter`
- [ ] No test requires a live Azure or Navigator endpoint
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_auth_lane.py -q`

---

## Test Specification

> This task *is* the test specification; the blueprint above is the scaffold.
> Every `FILL IN` body must become a real assertion — a test that only checks
> `authenticated is True` does not satisfy AC-1.

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
   `scripts/sdd/close_task.sh TASK-4665 msteams-user-auth-lane verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

> Filled in by the implementing agent when the task is closed.

**Completed**:
**Deviations from scope**:
**Ambiguities found in the spec**:
**Follow-up needed**:
