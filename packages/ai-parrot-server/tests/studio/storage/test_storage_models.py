"""FEAT-621 M2 — DB-free model tests."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from parrot.handlers.studio._base import STUDIO_SLUG_RE
from parrot.handlers.studio.models import CreateAgentRequest
from parrot.handlers.studio.storage import StudioPartition
from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAgentKey,
    StudioAgentRecord,
)
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec


def test_agent_key_qualified_roundtrip() -> None:
    assert StudioAgentKey("acme", "sales").qualified == "studio:acme:sales"
    assert StudioAgentKey(None, "sales").qualified == "studio:-:sales"
    assert StudioAgentKey.parse("studio:-:sales") == StudioAgentKey(None, "sales")
    assert StudioAgentKey.parse("studio:acme:sales") == StudioAgentKey("acme", "sales")
    for bad in ("acme:sales", "studio:acme:a:b", "studio:acme", "studio::x"):
        with pytest.raises(ValueError):
            StudioAgentKey.parse(bad)
    with pytest.raises(ValueError):
        StudioAgentKey("-", "sales")
    with pytest.raises(ValueError):
        StudioAgentKey("acme", "a:b")


def test_partition_from_scope() -> None:
    class _Scope:
        tenant = "acme"

    assert StudioPartition.from_scope(_Scope()) == StudioPartition("acme")
    assert StudioPartition.from_scope(object()) == StudioPartition.GLOBAL
    assert StudioPartition.GLOBAL.tenant is None


def test_definition_from_create_request() -> None:
    req = CreateAgentRequest(
        name="sales", persist=True,
        config={"temperature": 0.3, "max_tokens": 10, "top_k": 4, "top_p": 0.5,
                "system_prompt": "hi", "tools": ["x"], "extra": 1},
    )
    d = StudioAgentDefinition.from_create_request(req)
    assert d.model_params.temperature == 0.3 and d.system_prompt == "hi" and d.tools == ["x"]
    assert (d.model_params.max_tokens, d.model_params.top_k, d.model_params.top_p) == (10, 4, 0.5)
    assert d.config == {"extra": 1}
    assert "persist" not in d.model_dump() and "name" not in d.model_dump()


@pytest.mark.parametrize("key", ["llm", "model", "model_config", "chatbot_id", "name", "mcp_servers",
                                 "toolkits", "vector_store_config", "tools", "temperature"])
def test_definition_rejects_reserved_and_overwritten_keys(key: str) -> None:
    with pytest.raises(ValidationError):
        StudioAgentDefinition(config={key: 1})


@pytest.mark.parametrize("key", ["tenant", "created_by", "visibility", "allowed_groups"])
def test_definition_rejects_feat605_reserved(key: str) -> None:
    with pytest.raises(ValidationError, match="reserved_config_key"):
        StudioAgentDefinition(config={key: "x"})
    with pytest.raises(ValidationError, match="reserved_config_key"):
        StudioAgentDefinition.from_create_request(CreateAgentRequest(name="a", config={key: "x"}))


def test_tooling_ref_scheme() -> None:
    aid = uuid4()
    now = datetime.now(timezone.utc)
    rec = StudioAgentRecord(aid, None, "sales", "u", "private", (), StudioAgentDefinition(), "active", 1, now, now)
    assert rec.tooling_ref == f"studio-agent:{aid}"
    assert rec.key == StudioAgentKey(None, "sales")
    assert not STUDIO_SLUG_RE.match(rec.tooling_ref)


def _bundle(**kw):
    return StudioAgentBundle(name="a", definition=StudioAgentDefinition(), **kw)


def test_bundle_rejects_secret_fields() -> None:
    assert _bundle(toolkits=[ToolkitSpec(slug="jira", params={"url": "x"})]).toolkits
    with pytest.raises(ValidationError):
        _bundle(toolkits=[ToolkitSpec(slug="jira", secret_refs={"token": "v"})])
    with pytest.raises(ValidationError):
        _bundle(toolkits=[ToolkitSpec(slug="jira", vault_owner="u")])
    with pytest.raises(ValidationError):
        _bundle(toolkits=[ToolkitSpec(slug="jira", params={"api_key": "s"})])
    with pytest.raises(ValidationError):
        _bundle(mcp_servers=[AgentMCPServerSpec(name="m", secret_refs={"headers": "v"})])
