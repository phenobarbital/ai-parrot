"""hydrate_mcp hardening (FEAT-622 M7)."""
import pytest

import parrot.tools.spec as spec_module
from parrot.tools.spec import AgentMCPServerSpec, hydrate_mcp


@pytest.mark.asyncio
async def test_hydrate_mcp_vault_fills_only_secret_fields(monkeypatch):
    """A secret_refs key outside MCP_SECRET_FIELDS raises before any vault read."""
    reads: list[tuple] = []

    async def _vault(owner, name):
        reads.append((owner, name))
        return {"command": "sh", "headers": {"a": "b"}}

    monkeypatch.setattr(spec_module, "retrieve_vault_credential", _vault)
    bad = AgentMCPServerSpec(name="s", url="https://x/", secret_refs={"command": "v"}, vault_owner="u")
    with pytest.raises(ValueError):
        await hydrate_mcp(bad)
    assert reads == []
    ok = AgentMCPServerSpec(name="s", url="https://x/", secret_refs={"headers": "v"}, vault_owner="u")
    assert (await hydrate_mcp(ok))["headers"] == {"a": "b"}
