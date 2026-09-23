"""Tests for FEAT-593 tooling specification helpers."""

import pytest

from parrot.tools import spec as spec_module
from parrot.tools.spec import (
    AgentMCPServerSpec,
    SECRET_MASK,
    ToolkitSpec,
    hydrate_params,
    mask_spec,
    normalize_tooling,
    tooling_revision,
)


@pytest.fixture
def fake_vault(monkeypatch):
    """Provide a deterministic in-memory vault reader."""
    store = {("42", "toolkit_dataset_manager_a1"): {"datasources.0.dsn": "postgres://secret"}}

    async def _retrieve(user_id, vault_name):
        return store[(user_id, vault_name)]

    monkeypatch.setattr(spec_module, "retrieve_vault_credential", _retrieve)
    return store


def test_normalize_dedupes_slug():
    """A configured toolkit replaces a duplicate bare toolkit name."""
    out = normalize_tooling(["jira", "weather"], [{"slug": "jira", "params": {"default_project": "T"}}])
    assert out.tools == ["weather"]
    assert [spec.slug for spec in out.toolkits] == ["jira"]


def test_normalize_toolkit_config_map_injects_slug():
    """DB toolkit config entries derive their slug from the mapping key."""
    out = normalize_tooling([], toolkit_config={"querysource": {"params": {"programs": ["troc"]}}})
    assert out.toolkits[0].slug == "querysource"


def test_normalize_drops_invalid_entry(caplog):
    """Invalid toolkit specs are dropped rather than registered."""
    out = normalize_tooling([], [{"slug": "x", "bogus": 1}])
    assert out.toolkits == []


def test_revision_stable_and_sensitive():
    """Revisions are stable for equivalent specs and change with config."""
    specs = [ToolkitSpec(slug="jira", params={"p": 1})]
    assert tooling_revision(specs, []) == tooling_revision(specs, [])
    assert tooling_revision(specs, []) != tooling_revision([ToolkitSpec(slug="jira", params={"p": 2})], [])


@pytest.mark.asyncio
async def test_hydrate_dotted_datasource_secret(fake_vault):
    """Dotted secret references expand into nested datasource params."""
    spec = ToolkitSpec(
        slug="dataset_manager",
        params={"datasources": [{"kind": "sql", "name": "d", "sql": "x"}]},
        secret_refs={"datasources.0.dsn": "toolkit_dataset_manager_a1"},
        vault_owner="42",
    )
    params = await hydrate_params(spec)
    assert params["datasources"][0]["dsn"] == "postgres://secret"
    assert "dsn" not in spec.params["datasources"][0]


def test_mask_spec_masks_every_ref():
    """Masked dumps never expose a value referenced by the vault."""
    spec = ToolkitSpec(slug="jira", params={"server_url": "u"}, secret_refs={"token": "v"}, vault_owner="1")
    assert mask_spec(spec)["params"]["token"] == SECRET_MASK
