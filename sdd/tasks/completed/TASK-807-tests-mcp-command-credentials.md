# TASK-807: Tests for MCP Command Credentials

**Feature**: FEAT-113 — Vault-Backed Credentials for Telegram /add_mcp
**Spec**: `sdd/specs/mcp-command-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-803, TASK-804, TASK-805, TASK-806
**Assigned-to**: unassigned

---

## Context

This task creates the full unit + integration test suite for FEAT-113. The
tests cover: the `_split_secret_and_public` helper, `TelegramMCPPersistenceService`
CRUD, the rewritten command handlers (add/list/remove) and rehydration, and
regression guards ensuring the Redis key is never written.

Implements **Module 5** of the spec (§3) and verifies all items in §4.

---

## Scope

- Create `packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py`.
- Implement all unit tests from spec §4 (table: 16 tests).
- Implement integration tests: `test_end_to_end_add_list_remove` and
  `test_wrapper_rehydration_on_login`.
- Use `pytest` + `pytest-asyncio`.
- Mock `DocumentDb`, `store_vault_credential`, `retrieve_vault_credential`,
  `delete_vault_credential`, `ToolManager.add_mcp_server / remove_mcp_server`.

**NOT in scope**: Implementation code (that is TASK-803 through TASK-806).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py` | CREATE | Full test suite for FEAT-113 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test subject imports:
from parrot.integrations.telegram.mcp_persistence import (
    TelegramMCPPublicParams,
    UserTelegramMCPConfig,
    TelegramMCPPersistenceService,
)
from parrot.integrations.telegram.mcp_commands import (
    _split_secret_and_public,     # private, tested directly
    register_mcp_commands,
    rehydrate_user_mcp_servers,
    add_mcp_handler,
    list_mcp_handler,
    remove_mcp_handler,
)

# Vault utils to mock:
# parrot.handlers.vault_utils.store_vault_credential
# parrot.handlers.vault_utils.retrieve_vault_credential
# parrot.handlers.vault_utils.delete_vault_credential

# DocumentDb to mock:
# parrot.interfaces.documentdb.DocumentDb
```

### Existing Signatures to Use

```python
# mcp_commands.py — new handler signatures after TASK-805:
async def add_mcp_handler(message: Message, tool_manager_resolver: ToolManagerResolver) -> None: ...
async def list_mcp_handler(message: Message) -> None: ...
async def remove_mcp_handler(message: Message, tool_manager_resolver: ToolManagerResolver) -> None: ...
async def rehydrate_user_mcp_servers(tool_manager: "ToolManager", user_id: str) -> int: ...

# _split_secret_and_public returns:
# tuple[TelegramMCPPublicParams, dict[str, Any]]

# vault_utils.py:116 — retrieve raises KeyError if not found (not returns None):
async def retrieve_vault_credential(user_id: str, vault_name: str) -> Dict[str, Any]: ...
```

### Does NOT Exist

- ~~`rehydrate_user_mcp_servers(redis_client, tool_manager, user_id)`~~ — old 3-arg signature is gone after TASK-805.
- ~~`add_mcp_handler(..., redis_client=...)`~~ — `redis_client` removed from all handlers.
- ~~`retrieve_vault_credential` returning `None`~~ — raises `KeyError` on miss; test with `side_effect=KeyError`.
- ~~`TelegramMCPPublicParams.token`~~ — no token field on the public model.
- ~~`redis_client.hset / hmget`~~ — Redis is no longer used in these modules.

---

## Implementation Notes

### Fixture Strategy

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat

@pytest.fixture
def bearer_payload() -> dict:
    return {
        "name": "fireflies",
        "url": "https://api.fireflies.ai/mcp",
        "auth_scheme": "bearer",
        "token": "sk-test-0123456789",
    }

@pytest.fixture
def api_key_payload() -> dict:
    return {
        "name": "brave",
        "url": "https://api.brave.com/mcp",
        "auth_scheme": "api_key",
        "api_key": "bsa-...-redacted",
        "api_key_header": "X-Brave-Key",
    }

@pytest.fixture
def basic_payload() -> dict:
    return {
        "name": "internal",
        "url": "https://internal.example/mcp",
        "auth_scheme": "basic",
        "username": "svc",
        "password": "p@ss!word",
    }

def _make_message(text: str, chat_type: str = "private", user_id: int = 12345) -> MagicMock:
    """Build a minimal aiogram Message mock."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.chat = MagicMock(spec=Chat)
    msg.chat.type = chat_type
    msg.reply = AsyncMock()
    msg.delete = AsyncMock()
    return msg
```

### Test Structure

```python
# ─── Module 2: _split_secret_and_public ───────────────────────────────────

class TestSplitSecretAndPublic:
    def test_split_secret_bearer(self, bearer_payload):
        public, secret = _split_secret_and_public(bearer_payload)
        assert secret == {"token": "sk-test-0123456789"}
        assert not hasattr(public, "token")
        assert public.auth_scheme == "bearer"
        assert public.name == "fireflies"

    def test_split_secret_api_key(self, api_key_payload):
        public, secret = _split_secret_and_public(api_key_payload)
        assert secret == {"api_key": "bsa-...-redacted"}
        assert public.api_key_header == "X-Brave-Key"
        assert "api_key" not in public.model_dump()

    def test_split_secret_basic(self, basic_payload):
        public, secret = _split_secret_and_public(basic_payload)
        assert secret == {"username": "svc", "password": "p@ss!word"}
        assert "username" not in public.model_dump()

    def test_split_secret_none(self):
        payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "none"}
        public, secret = _split_secret_and_public(payload)
        assert secret == {}

    def test_split_missing_bearer_token(self):
        payload = {"name": "x", "url": "https://x.com/mcp", "auth_scheme": "bearer"}
        with pytest.raises(ValueError, match="bearer auth requires a 'token' field"):
            _split_secret_and_public(payload)


# ─── Module 1: TelegramMCPPersistenceService ──────────────────────────────

class TestTelegramMCPPersistenceService:
    """Use AsyncMock for DocumentDb context manager."""

    @pytest.mark.asyncio
    async def test_persistence_save_upsert(self):
        # First call writes, second call updates the same doc
        ...

    @pytest.mark.asyncio
    async def test_persistence_list_excludes_inactive(self):
        # active=False docs are not returned
        ...

    @pytest.mark.asyncio
    async def test_persistence_remove_soft_delete(self):
        # remove() sets active=False; subsequent read_one returns None
        ...


# ─── Module 3: Handlers ───────────────────────────────────────────────────

class TestAddMcpHandler:
    @pytest.mark.asyncio
    async def test_add_mcp_happy_path(self, bearer_payload):
        # Verify: ToolManager → persistence → Vault in that order
        ...

    @pytest.mark.asyncio
    async def test_add_mcp_rolls_back_on_vault_failure(self, bearer_payload):
        # Vault raises → persistence.remove called, tool_manager.remove called
        ...

    @pytest.mark.asyncio
    async def test_non_private_chat_rejected(self, bearer_payload):
        # Group chat → reply with security message, no other calls
        ...

class TestListMcpHandler:
    @pytest.mark.asyncio
    async def test_list_mcp_hides_secrets(self, bearer_payload):
        # output contains "fireflies — https://... (bearer)" but NOT "sk-test-0123456789"
        ...

class TestRemoveMcpHandler:
    @pytest.mark.asyncio
    async def test_remove_mcp_clears_vault_and_doc(self, bearer_payload):
        # DELETE removes from ToolManager, DocumentDB, Vault
        # Missing Vault entry does NOT raise
        ...

class TestRehydrate:
    @pytest.mark.asyncio
    async def test_rehydrate_reassembles_config(self, bearer_payload):
        # public + secret → MCPClientConfig equal to original _build_config result
        ...

    @pytest.mark.asyncio
    async def test_rehydrate_skips_missing_secret(self):
        # Vault KeyError → server skipped, others continue, warning logged
        ...

    @pytest.mark.asyncio
    async def test_redis_key_is_never_written(self, bearer_payload):
        # After add_mcp, confirm redis is never called
        ...
```

### Mocking Strategy

```python
# Patch DocumentDb at the persistence module level:
with patch("parrot.integrations.telegram.mcp_persistence.DocumentDb") as MockDb:
    db_instance = AsyncMock()
    MockDb.return_value.__aenter__ = AsyncMock(return_value=db_instance)
    MockDb.return_value.__aexit__ = AsyncMock(return_value=False)
    db_instance.update_one = AsyncMock()
    db_instance.read = AsyncMock(return_value=[...])
    ...

# Patch vault utils at the mcp_commands module level:
with patch("parrot.integrations.telegram.mcp_commands.store_vault_credential") as mock_store, \
     patch("parrot.integrations.telegram.mcp_commands.retrieve_vault_credential") as mock_retrieve, \
     patch("parrot.integrations.telegram.mcp_commands.delete_vault_credential") as mock_delete:
    ...
```

### Key Constraints

- `pytest-asyncio` must be used for all async tests.
- All assertions on call order for `test_add_mcp_happy_path` must use
  `Mock.call_args_list` or `Mock.assert_called_once_with`.
- `test_redis_key_is_never_written` — mock `redis_client.hset` and assert it
  is never called during `add_mcp_handler`.
- `test_list_mcp_hides_secrets` — check that the reply text does NOT contain
  any secret value from the fixture (e.g., `"sk-test-0123456789"` is not a
  substring of the reply).

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py` created.
- [ ] All 16 unit tests from spec §4 are implemented and pass.
- [ ] `test_end_to_end_add_list_remove` integration test passes.
- [ ] `test_wrapper_rehydration_on_login` integration test passes (can use mocks for DocumentDb + Vault).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py`

---

## Test Specification

The test file IS the test specification. See the Implementation Notes above for
the full test structure. Each test listed in spec §4 must appear as a distinct
test method.

Full spec §4 test list for reference:
1. `test_split_secret_bearer`
2. `test_split_secret_api_key`
3. `test_split_secret_basic`
4. `test_split_secret_none`
5. `test_split_missing_bearer_token`
6. `test_persistence_save_upsert`
7. `test_persistence_list_excludes_inactive`
8. `test_persistence_remove_soft_delete`
9. `test_add_mcp_happy_path`
10. `test_add_mcp_rolls_back_on_vault_failure`
11. `test_list_mcp_hides_secrets`
12. `test_remove_mcp_clears_vault_and_doc`
13. `test_rehydrate_reassembles_config`
14. `test_rehydrate_skips_missing_secret`
15. `test_redis_key_is_never_written`
16. `test_non_private_chat_rejected`
17. `test_end_to_end_add_list_remove` (integration)
18. `test_wrapper_rehydration_on_login` (integration)

---

## Agent Instructions

When you pick up this task:

1. **Verify TASK-803 through TASK-806 are completed**.
2. **Read** the spec §4 in full.
3. **Verify the Codebase Contract** — run the smoke imports before writing tests.
4. **Create** the test file and implement all tests.
5. Run `pytest packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py -v` and fix failures.
6. Run `ruff check` and fix linting issues.
7. **Commit**: `git add packages/ai-parrot/tests/integrations/telegram/test_mcp_commands.py`
8. Move this file to `tasks/completed/` and update the index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
