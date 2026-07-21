---
type: Wiki Overview
title: 'TASK-1658: Tests — FEAT-261 unit and integration tests'
id: doc:sdd-tasks-completed-task-1658-msagentsdk-auth-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **9**. All unit tests for FEAT-261 modules 1-8.
relates_to:
- concept: mod:parrot.auth.audit
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.agent
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.auth
  rel: mentions
- concept: mod:parrot.integrations.msagentsdk.models
  rel: mentions
---

# TASK-1658: Tests — FEAT-261 unit and integration tests

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1657
**Assigned-to**: unassigned

---

## Context

Implements spec Module **9**. All unit tests for FEAT-261 modules 1-8.
Tests must cover the 17 unit test cases listed in the spec, plus 3
integration scenarios.

## Scope

Create test files for all FEAT-261 modules.

## Files to Create/Modify

- `tests/integrations/test_msagentsdk/test_auth_config.py` — CREATE
- `tests/integrations/test_msagentsdk/test_identity.py` — CREATE
- `tests/integrations/test_msagentsdk/test_invoke_routing.py` — CREATE
- `tests/integrations/test_msagentsdk/test_credential_bridge.py` — CREATE
- `tests/integrations/test_msagentsdk/test_audit_ledger.py` — CREATE
- `tests/integrations/test_msagentsdk/test_resolver.py` — CREATE
- `tests/integrations/test_msagentsdk/test_wrapper_wiring.py` — CREATE
- `tests/integrations/test_msagentsdk/test_signin_integration.py` — CREATE

## Implementation Notes

### Check existing test directory:
```bash
ls tests/integrations/test_msagentsdk/ 2>/dev/null || echo "no dir"
```

If it doesn't exist, create it with an `__init__.py`.

### Key fixtures (conftest.py or per-file):

```python
import pytest
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

@pytest.fixture
def oauth_config():
    return MSAgentSDKConfig(
        name="TestBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
        oauth_connections={"o365": "graph_sso", "jira": "jira_oauth"},
        obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
    )

class MockFromProperty:
    def __init__(self, id: str, aad_object_id: str = None):
        self.id = id
        self.aad_object_id = aad_object_id

class MockConversation:
    def __init__(self, id: str):
        self.id = id

class MockActivity:
    def __init__(self, type="message", text=None, from_id="user-123",
                 aad_id=None, conv_id="conv-456", name=None, value=None):
        self.type = type
        self.text = text
        self.from_property = MockFromProperty(from_id, aad_id)
        self.conversation = MockConversation(conv_id)
        self.name = name
        self.value = value
        self.members_added = []
        self.recipient = MockFromProperty("bot-id")
        self.channel_id = "msteams"

class MockContext:
    def __init__(self, activity):
        self.activity = activity
        self.sent_activities = []

    async def send_activity(self, activity):
        self.sent_activities.append(activity)
```

### Test: test_auth_config.py

```python
def test_config_oauth_connections(oauth_config):
    assert oauth_config.oauth_connections == {"o365": "graph_sso", "jira": "jira_oauth"}
    assert oauth_config.obo_scopes == {"o365": ["https://graph.microsoft.com/.default"]}

def test_config_oauth_connections_empty():
    cfg = MSAgentSDKConfig(name="Bot", chatbot_id="bot", anonymous_auth=True)
    assert cfg.oauth_connections == {}
    assert cfg.obo_scopes == {}

def test_config_from_dict_with_oauth():
    data = {
        "chatbot_id": "agent",
        "anonymous_auth": True,
        "oauth_connections": {"o365": "graph_sso"},
        "obo_scopes": {"o365": ["https://graph.microsoft.com/.default"]},
    }
    cfg = MSAgentSDKConfig.from_dict("TestBot", data)
    assert cfg.oauth_connections == {"o365": "graph_sso"}
```

### Test: test_identity.py

```python
from parrot.integrations.msagentsdk.agent import ParrotM365Agent

def test_identity_aad_object_id():
    agent = ParrotM365Agent(parrot_agent=MockBot())
    activity = MockActivity(aad_id="00000000-0000-0000-0000-000000000001")
    uid = agent._extract_user_id(activity)
    assert uid == "00000000-0000-0000-0000-000000000001"

def test_identity_fallback_channel_id():
    agent = ParrotM365Agent(parrot_agent=MockBot())
    activity = MockActivity(from_id="user-999")
    # No aad_object_id set
    uid = agent._extract_user_id(activity)
    assert uid == "user-999"
```

### Test: test_invoke_routing.py

```python
@pytest.mark.asyncio
async def test_invoke_signin_verify_state():
    agent = ParrotM365Agent(parrot_agent=MockBot())
    activity = MockActivity(type="invoke", name="signin/verifyState",
                            value={"state": "magic-code-12345"})
    ctx = MockContext(activity)
    await agent.on_turn(ctx)
    # Should have sent an invoke response
    assert len(ctx.sent_activities) == 1

@pytest.mark.asyncio
async def test_invoke_signin_token_exchange():
    agent = ParrotM365Agent(parrot_agent=MockBot())
    activity = MockActivity(type="invoke", name="signin/tokenExchange",
                            value={"connectionName": "graph_sso"})
    ctx = MockContext(activity)
    await agent.on_turn(ctx)
    assert len(ctx.sent_activities) == 1

@pytest.mark.asyncio
async def test_invoke_unknown_ignored():
    agent = ParrotM365Agent(parrot_agent=MockBot())
    activity = MockActivity(type="invoke", name="composeExtension/query")
    ctx = MockContext(activity)
    await agent.on_turn(ctx)
    assert len(ctx.sent_activities) == 0
```

### Test: test_audit_ledger.py

```python
from parrot.auth.audit import AuditLedger, AuditEntry

def test_audit_ledger_records_entry():
    ledger = AuditLedger()
    entry = AuditEntry(
        timestamp="2026-06-26T00:00:00Z",
        user_id="user-1",
        channel="msagentsdk",
        tool="o365",
        connection="graph_sso",
        key_fingerprint="abc123",
        action="resolve",
    )
    ledger.record(entry)
    assert len(ledger.entries()) == 1
    assert ledger.entries()[0].tool == "o365"

def test_key_fingerprint_computation():
    import hashlib
    token = "my-secret-token"
    raw = token.encode("utf-8")[:8]
    expected = hashlib.sha256(raw).hexdigest()
    assert len(expected) == 64
    assert expected != token  # fingerprint is not the token itself

@pytest.mark.asyncio
async def test_audit_ledger_flush():
    ledger = AuditLedger()
    await ledger.flush()  # should not raise
```

### Test: test_resolver.py

```python
from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver, CredentialRequired
from parrot.auth.audit import AuditLedger

@pytest.mark.asyncio
async def test_resolver_no_connection_returns_none():
    resolver = BFTokenServiceResolver(
        oauth_connections={},
        obo_scopes={},
    )
    result = await resolver.resolve("msagentsdk", "user-1", tool="unknown")
    assert result is None

@pytest.mark.asyncio
async def test_resolver_no_token_raises_credential_required():
    resolver = BFTokenServiceResolver(
        oauth_connections={"o365": "graph_sso"},
        obo_scopes={},
    )
    # Mock turn_context with no token
    mock_ctx = MockTurnContextNoToken()
    with pytest.raises(CredentialRequired) as exc_info:
        await resolver.resolve("msagentsdk", "user-1", tool="o365", turn_context=mock_ctx)
    assert exc_info.value.connection_name == "graph_sso"

@pytest.mark.asyncio
async def test_resolver_returns_token_and_records_audit():
    ledger = AuditLedger()
    resolver = BFTokenServiceResolver(
        oauth_connections={"o365": "graph_sso"},
        obo_scopes={},
        audit_ledger=ledger,
    )
    mock_ctx = MockTurnContextWithToken("fake-token-abc")
    result = await resolver.resolve("msagentsdk", "user-1", tool="o365", turn_context=mock_ctx)
    assert result == "fake-token-abc"
    assert len(ledger.entries()) == 1
    assert ledger.entries()[0].action == "resolve"
```

### Test: test_wrapper_wiring.py

```python
@pytest.mark.asyncio
async def test_wrapper_wires_resolver(oauth_config):
    # When oauth_connections is non-empty, wrapper creates resolver
    ...

def test_wrapper_no_resolver_when_empty():
    cfg = MSAgentSDKConfig(name="Bot", chatbot_id="bot", anonymous_auth=True)
    # oauth_connections is empty — no resolver
    ...
```

### Integration test: test_signin_integration.py

```python
@pytest.mark.asyncio
async def test_message_unchanged_without_oauth():
    # Message flow with no oauth_connections works as before
    ...
```

## Codebase Contract

### Verified Imports
```python
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
from parrot.integrations.msagentsdk.agent import ParrotM365Agent
from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver, CredentialRequired
from parrot.auth.audit import AuditLedger, AuditEntry
```

## Acceptance Criteria

- [ ] All 17 unit tests listed in spec Section 4 are implemented and pass.
- [ ] At least 1 integration scenario (backward compat without OAuth) passes.
- [ ] `pytest tests/integrations/test_msagentsdk/ -v` exits 0.
- [ ] No imports of `microsoft_agents.*` at module level in test files (keep
      lazy).

### Completion Note

Created 8 test files in `tests/integrations/test_msagentsdk/`:
test_auth_config.py (7 tests — Module 1),
test_audit_ledger.py (9 tests — Module 6),
test_identity.py (6 tests — Module 2),
test_invoke_routing.py (4 tests — Module 3),
test_credential_bridge.py (5 tests — Module 4+7),
test_resolver.py (10 tests — Module 5),
test_wrapper_wiring.py (3 tests — Module 8),
test_signin_integration.py (3 tests — integration).
All 47 tests pass. Requires PYTHONPATH override to pick up worktree's
editable packages (see test runner notes).
