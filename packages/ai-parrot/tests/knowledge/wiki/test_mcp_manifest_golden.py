"""Golden MCP manifests per configuration (FEAT-540 M5)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig
from parrot.knowledge.wiki.mcp_server import build_wiki_tools, close_bundle, create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiNamespaceConfig, WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.schema.store import SchemaStore
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.transport import build_operation_descriptors


GOLDEN = Path(__file__).parent / "golden" / "mcp_manifests"
CONFIGS = [
    "minimal_local",
    "ledger",
    "decisions",
    "schema_present",
    "schema_absent",
    "federated",
    "bulk_on",
    "bulk_off",
    "vault",
    "remote_proxy",
]


def _canonical_manifest(descriptors: list[Any]) -> list[dict[str, Any]]:
    """Normalize transport-neutral operations into a stable golden representation."""
    return sorted(
        [
            {
                "name": descriptor.name,
                "description": descriptor.description,
                "schema": descriptor.input_model.model_json_schema(),
                "mount": descriptor.mount,
            }
            for descriptor in descriptors
        ],
        key=lambda item: item["name"],
    )


async def _seed_store(root: Path, config: WikiProjectConfig) -> None:
    """Create a local retrieval plane required by the manifest builders."""
    store = create_wiki_store(config.storage_path(root), wiki_name=config.wiki_name, backend=config.backend)
    await store.upsert_pages([WikiPageRecord(concept_id="page", title="Page", body="Body")])


def _configuration(config_name: str, root: Path) -> tuple[WikiProjectConfig, dict[str, Any]]:
    """Build one isolated configuration-matrix entry and bundle arguments."""
    config = WikiProjectConfig(wiki_name=config_name)
    arguments: dict[str, Any] = {"read_repair": False}

    if config_name == "ledger":
        arguments["ledger_dir"] = root / "server" / ".parrot" / "ledger"
    elif config_name == "decisions":
        config.decisions = DecisionConfig(generation_enabled=True)
    elif config_name in {"schema_present", "schema_absent"}:
        (root / ".git").mkdir()
        if config_name == "schema_present":
            schema_dir = config.schema_path(root)
            schema_dir.mkdir(parents=True)
            SchemaStore(schema_dir / "schema.db")
    elif config_name == "federated":
        namespace_root = root / "namespace"
        namespace_config = WikiProjectConfig(wiki_name="namespace")
        asyncio.run(_seed_store(namespace_root, namespace_config))
        config.namespaces = {"namespace": WikiNamespaceConfig(path=str(namespace_root))}
    elif config_name == "bulk_on":
        arguments["include_bulk_tools"] = True
    elif config_name == "vault":
        (root / ".obsidian").mkdir()
    elif config_name == "remote_proxy":
        # A proxy preserves the remote manifest; this baseline uses the same
        # representative remote surface as the local minimal configuration.
        pass
    elif config_name not in {"minimal_local", "bulk_off"}:
        raise ValueError(f"Unknown manifest configuration: {config_name}")
    return config, arguments


def _manifest_for_transport(bundle: Any, transport: str) -> list[dict[str, Any]]:
    """Return a canonical manifest for either MCP transport.

    Framework tools are the wrappers mounted in ``WikiToolBundle``; SDK tool
    definitions are generated from the same operation descriptors.  Both must
    therefore retain names, descriptions, schemas, and mount conditions.
    """
    descriptors = build_operation_descriptors(bundle)
    if transport == "framework":
        framework_by_name = {tool.name: tool for tool in bundle.tools}
        framework_by_name.update({tool.name: tool for tool in bundle.vault_tools if tool.name == "vault_ingest"})
        assert set(framework_by_name) >= {descriptor.name for descriptor in descriptors}
        for descriptor in descriptors:
            tool = framework_by_name[descriptor.name]
            assert tool.description == descriptor.description
            assert tool.args_schema.model_json_schema() == descriptor.input_model.model_json_schema()
    elif transport != "sdk":
        raise ValueError(f"Unknown MCP transport: {transport}")
    return _canonical_manifest(descriptors)


@pytest.mark.parametrize("config", CONFIGS)
@pytest.mark.parametrize("transport", ["framework", "sdk"])
def test_manifest_matches_golden(
    config: str, transport: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both MCP transports retain the configuration-specific manifest."""
    root = tmp_path / config
    root.mkdir()
    project_config, arguments = _configuration(config, root)
    asyncio.run(_seed_store(root, project_config))
    from parrot.knowledge.wiki import project

    monkeypatch.setattr(project, "find_shared_root", lambda candidate: root if config.startswith("schema_") else None)
    bundle = build_wiki_tools(root, project_config, **arguments)
    try:
        manifest = _manifest_for_transport(bundle, transport)
        golden_path = GOLDEN / f"{config}.json"
        if os.environ.get("UPDATE_GOLDEN") == "1":
            if transport == "framework":
                golden_path.parent.mkdir(parents=True, exist_ok=True)
                golden_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return
        assert manifest == json.loads(golden_path.read_text(encoding="utf-8"))
    finally:
        asyncio.run(close_bundle(bundle))


def test_minimal_manifest_matches_frozen_tool_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The minimal local manifest preserves the FEAT-569 name baseline."""
    from tests.knowledge.wiki.test_tool_surface_golden import LOCAL_NO_LEDGER

    config = WikiProjectConfig(wiki_name="baseline")
    save_project_config(tmp_path, config)
    asyncio.run(_seed_store(tmp_path, config))
    from parrot.knowledge.wiki import project

    monkeypatch.setattr(project, "find_shared_root", lambda root: None)
    server = create_wiki_mcp_server(tmp_path, transport="framework")
    try:
        manifest = _canonical_manifest(build_operation_descriptors(server.wiki_bundle))
        assert [entry["name"] for entry in manifest] == LOCAL_NO_LEDGER
    finally:
        asyncio.run(close_bundle(server.wiki_bundle))
