"""Unit tests for owner-scoped Agent Studio tooling persistence."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ConfigDict

from parrot.handlers.studio import tooling_store as store_module
from parrot.handlers.studio.tooling_store import AgentToolingStore
from parrot.tools.spec import SECRET_MASK


class _JiraConfig(BaseModel):
    """Minimal strict schema used to verify the store's validation path."""

    model_config = ConfigDict(extra="forbid")
    server_url: str | None = None
    token: str | None = None


class _JiraToolkit:
    """Test-only toolkit contract."""

    config_model = _JiraConfig


@pytest.fixture
def vault(monkeypatch):
    """In-memory async vault implementation."""
    data = {}

    async def _store(user_id, name, secrets):
        data[(user_id, name)] = dict(secrets)

    async def _retrieve(user_id, name):
        return dict(data[(user_id, name)])

    monkeypatch.setattr(store_module, "store_vault_credential", _store)
    monkeypatch.setattr(store_module, "retrieve_vault_credential", _retrieve)
    monkeypatch.setattr(store_module, "delete_vault_credential", AsyncMock())
    return data


@pytest.fixture
def db_store(monkeypatch):
    """Store backed by a fake database-origin agent."""
    row = SimpleNamespace(name="a1", created_by=42, toolkit_config={}, mcp_servers=[], set=MagicMock(), update=AsyncMock())
    handler = SimpleNamespace(_get_db_agent=AsyncMock(return_value=row), _registry=lambda: None, request=SimpleNamespace(app={}))
    store = AgentToolingStore(handler)
    schema = {
        "type": "object",
        "properties": {
            "server_url": {"type": "string"},
            "token": {"type": "string", "x-secret": True},
            "internal": {"x-server-managed": True},
        },
    }
    monkeypatch.setattr(store, "schema_for", lambda _slug: (_JiraToolkit, schema))
    monkeypatch.setattr(store, "_persist", AsyncMock())
    return store, row


@pytest.mark.asyncio
async def test_put_jira_vaults_token_under_owner(vault, db_store):
    """Toolkit secrets are stored under the agent owner, not the caller."""
    store, _ = db_store
    spec = await store.put_toolkit("a1", "jira", {"server_url": "https://x", "token": "t0k"}, ["token"])

    assert vault[("42", "toolkit_jira_a1")] == {"token": "t0k"}
    assert "token" not in spec.params
    assert spec.secret_refs == {"token": "toolkit_jira_a1"}


@pytest.mark.asyncio
async def test_mask_keeps_existing_secret_without_vault_write(vault, db_store):
    """The secret mask preserves its existing reference and vault content."""
    store, _ = db_store
    initial = await store.put_toolkit("a1", "jira", {"token": "t0k"}, [])
    state = await store.load("a1")
    state.tooling.toolkits = [initial]
    store.load = AsyncMock(return_value=state)

    spec = await store.put_toolkit("a1", "jira", {"token": SECRET_MASK}, [])

    assert vault[("42", "toolkit_jira_a1")] == {"token": "t0k"}
    assert spec.secret_refs == {"token": "toolkit_jira_a1"}


@pytest.mark.asyncio
async def test_rejects_unknown_and_server_managed_params(vault, db_store):
    """Validation blocks strict-model extras and server-owned parameters."""
    store, _ = db_store
    with pytest.raises(ValueError, match="Invalid toolkit parameters"):
        await store.put_toolkit("a1", "jira", {"unknown": "no"}, [])
    with pytest.raises(ValueError, match="Server-managed parameters"):
        await store.put_toolkit("a1", "jira", {"internal": "no"}, [])


@pytest.mark.asyncio
async def test_mcp_secrets_never_remain_in_params(vault, db_store):
    """MCP secret fields are replaced with owner-scoped vault references."""
    store, _ = db_store
    specs = await store.put_mcp_servers("a1", [{"name": "remote", "url": "https://mcp", "headers": {"X-Key": "x"}}])

    assert vault[("42", "mcp_agent_remote_a1")] == {"headers": {"X-Key": "x"}}
    assert "headers" not in specs[0].params
    assert specs[0].secret_refs == {"headers": "mcp_agent_remote_a1"}


@pytest.mark.asyncio
async def test_registry_python_agent_is_read_only(tmp_path, monkeypatch):
    """A registry agent from Python is never editable by the tooling store."""
    meta = SimpleNamespace(bot_config=SimpleNamespace(toolkits=[], mcp_servers=[], config={"created_by": "7"}), file_path=tmp_path / "a1.py")
    registry = SimpleNamespace(get_metadata=lambda _name: meta)
    handler = SimpleNamespace(_get_db_agent=AsyncMock(return_value=None), _registry=lambda: registry,
                              _registry_agent_owner=lambda _meta: "7")
    store = AgentToolingStore(handler)

    state = await store.load("a1")

    assert not state.editable
    with pytest.raises(PermissionError):
        await store.put_mcp_servers("a1", [])
