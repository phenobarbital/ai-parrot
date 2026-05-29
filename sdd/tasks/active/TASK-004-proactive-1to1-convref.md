# TASK-004: Proactive 1:1 bootstrap + ConversationReference cache

**Feature**: FEAT-205 — TeamsHumanChannel
**Spec**: `sdd/specs/hitl-teams-channel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001, TASK-002
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 — the **net-new core**. The repo has NO proactive messaging
today (no `ConversationReference`, `continue_conversation`, or
`create_conversation` usage anywhere). This task builds the bot-initiated 1:1:
capture/cache a `ConversationReference`, send via warm
`continue_conversation`, and cold-bootstrap via `create_conversation` when no
prior reference exists. This is the riskiest module — verify the exact
CloudAdapter proactive API (OQ-2) against botbuilder v4.17.1 first.

---

## Scope

- `ConversationReferenceStore` (Redis): `hitl:teams:convref:{email}` →
  serialized `ConversationReference`. Long TTL (~30 days) **refreshed on every
  inbound contact** (OQ-4); also refresh `serviceUrl`.
- Capture a `ConversationReference` from any inbound activity
  (`TurnContext.get_conversation_reference(activity)`), cache-on-contact.
- `SentActivityStore` (Redis): `hitl:teams:sent:{interaction_id}` →
  `{conversation_reference, activity_id, recipient}` (for cancel/update + cross-worker).
- Proactive send helper:
  - warm path: `adapter.continue_conversation(ref, callback, bot_app_id)`.
  - cold path: `create_conversation(...)` (members=[manager AAD id], tenantId,
    isGroup=false, serviceUrl) → capture ref → post. **Verify the exact API
    (OQ-2)** for the vendored botbuilder version.
  - `AppCredentials.trust_service_url(serviceUrl)` before sending; refresh from
    latest activity, never pin.
- Return the posted `activity_id` so the channel can store it.
- On cold-create failure (e.g. bot not installed org-wide), propagate a failure
  signal so the channel returns `False` (NO fallback — OQ-COLD).

**NOT in scope**: the `HumanChannel` contract methods / inbound demux
(TASK-005), card content (TASK-003), Graph resolution itself (TASK-002 — this
task consumes its `ResolvedTeamsUser`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/proactive.py` | CREATE | `ProactiveMessenger`, `ConversationReferenceStore`, `SentActivityStore` |
| `packages/ai-parrot-integrations/tests/test_proactive.py` | CREATE | warm/cold/TTL-refresh/cold-fail tests with a stubbed adapter |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From the BotBuilder SDK (v4.17.1, transitive). Verify exact proactive API (OQ-2):
from botbuilder.core import TurnContext            # get_conversation_reference(activity)
from botbuilder.schema import ConversationReference, Activity
# Adapter comes from TASK-001 vendored plumbing (reuse msteams/adapter.py:18 Adapter(CloudAdapter)).
# Consumes ResolvedTeamsUser from TASK-002 (msteams/graph.py).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18
class Adapter(CloudAdapter): ...   # provides continue_conversation / create_conversation (botbuilder)

# TASK-002 output (consume, do not reimplement):
class ResolvedTeamsUser(BaseModel):  # aad_object_id, upn, email, service_url
    ...
```

### Does NOT Exist
- ~~any existing `ConversationReference` / `continue_conversation` / `create_conversation` usage in `parrot.*`~~ — NONE; this is the first. The names are botbuilder SDK symbols, not parrot code.
- ~~`azure_teambots` proactive helper~~ — the upstream package is purely reactive (confirm fork in TASK-001/OQ-VENDOR).
- ~~`MSTeamsHook` proactive send~~ — `MSTeamsHook` (packages/ai-parrot/src/parrot/core/hooks/messaging.py:186) is reactive only.

---

## Implementation Notes

### Key Constraints
- **OQ-2 first**: confirm `create_conversation` parameters vs a `TeamsInfo`-assisted
  flow against the vendored botbuilder version BEFORE coding the cold path.
- async/await; channel must be stateless across workers — all state in Redis.
- Serialize `ConversationReference` deterministically (botbuilder model →
  dict/json) for Redis (decide format; document it).
- `self.logger` at send/cold-create/failure points; never log secrets.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/adapter.py:18` — adapter.
- Spec §2 (Overview steps 2/4), §7 Known Risks (serviceUrl rotation, cold-create).

---

## Acceptance Criteria

- [ ] Warm path uses `continue_conversation` when a convref is cached.
- [ ] Cold path uses `create_conversation`, captures + stores the new ref.
- [ ] convref TTL refreshed + serviceUrl updated on inbound contact (OQ-4).
- [ ] Posted `activity_id` returned and stored in the sent map.
- [ ] Cold-create failure surfaces as a failure (no fallback) so the caller returns `False`.
- [ ] OQ-2 resolution documented in code/Completion Note.
- [ ] No linting errors: `ruff check .../msteams/proactive.py`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/test_proactive.py -v`

---

## Test Specification
```python
# packages/ai-parrot-integrations/tests/test_proactive.py
import pytest

async def test_warm_path_uses_continue_conversation(stub_adapter, redis): ...
async def test_cold_path_creates_and_caches_ref(stub_adapter, redis): ...
async def test_ttl_and_serviceurl_refreshed_on_contact(redis): ...
async def test_cold_create_failure_propagates(stub_adapter, redis): ...
```

---

## Agent Instructions
Standard SDD flow. Confirm OQ-2 against the vendored botbuilder version, verify
the contract, implement, move to `completed/`, update index.

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
