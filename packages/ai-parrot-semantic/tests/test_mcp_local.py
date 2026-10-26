"""Regression contract: Local MCP configuration and semantic-layer documentation (M11b)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.models import SemanticQuery

from . import _guard_factory
from ._models import models_dir  # noqa: F401

sys.modules.setdefault("semantic_mcp_local_guard_factory", _guard_factory)


def _write_policy(path: Path, *, allow: bool) -> Path:
    """Write one deterministic allow or deny decision for the fixture guard."""
    path.mkdir()
    (path / "decisions.json").write_text(json.dumps({"allow": allow}), encoding="utf-8")
    return path


def _config(models_dir: Path, policy_dir: Path) -> str:
    """Return the documented local toolkit shape with isolated fixture paths."""
    kwargs = {
        "models_dir": str(models_dir),
        "dialect": "duckdb",
        "agent_id": "local-semantic",
        "static_subject": {"user_id": "operator", "tenant_id": "local", "roles": ["admin"]},
        "guard_factory": "semantic_mcp_local_guard_factory.build_guard",
        "guard_factory_kwargs": {"policy_dir": str(policy_dir)},
    }
    return (
        "toolkits:\n  semantic-layer:\n    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit\n    kwargs: "
        + json.dumps(kwargs)
        + "\n    env: {}\n"
    )


def test_yaml_and_json_example_contract(tmp_path: Path) -> None:
    """Verify the documented copyable YAML and MCP JSON have the required contract."""
    documentation = (Path(__file__).resolve().parents[3] / "docs" / "tools" / "semantic-layer.md").read_text(
        encoding="utf-8"
    )
    for text in (
        "class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit",
        "agent_id: local-semantic",
        "static_subject: {user_id: operator, tenant_id: local, roles: [admin]}",
        "guard_factory: myapp.semantic_auth.build_guard",
        '"parrot-semantic-layer"',
        '"args": ["mcp-local", "semantic-layer"]',
    ):
        assert text in documentation

    config_path = tmp_path / "toolkits.yaml"
    config_path.write_text(
        "toolkits:\n  semantic-layer:\n    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit\n    kwargs:\n      models_dir: /path/to/models\n      dialect: duckdb\n      agent_id: local-semantic\n      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}\n      guard_factory: myapp.semantic_auth.build_guard\n      guard_factory_kwargs: {policy_dir: /path/to/policies}\n    env: {}\n",
        encoding="utf-8",
    )
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(
        '{"parrot-semantic-layer": {"command": "parrot", "args": ["mcp-local", "semantic-layer"]}}', encoding="utf-8"
    )

    section = load_toolkits_config(tmp_path, config_path=config_path).toolkits["semantic-layer"]
    assert section.class_path == "parrot.semantic.bootstrap.LocalSemanticLayerToolkit"
    assert section.kwargs["agent_id"] == "local-semantic"
    assert section.kwargs["static_subject"]["user_id"] == "operator"
    assert json.loads(mcp_path.read_text(encoding="utf-8"))["parrot-semantic-layer"]["args"] == [
        "mcp-local",
        "semantic-layer",
    ]


@pytest.mark.asyncio
async def test_actual_mcp_factory_governed_startup(tmp_path: Path, models_dir: Path) -> None:
    """Start the actual MCP factory with a configured governed fixture."""
    policy_dir = _write_policy(tmp_path / "allow", allow=True)
    config_path = tmp_path / "toolkits.yaml"
    config_path.write_text(_config(models_dir, policy_dir), encoding="utf-8")

    server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=config_path)
    toolkit = server._owned_toolkit
    tool = toolkit.get_tool("sl_compile_query")
    assert tool is not None
    result = await tool._execute(query=SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"]))

    assert "SELECT" in result["sql"]
    assert toolkit._ledger.entries[-1].channel == "mcp-local"
    assert toolkit._ledger.entries[-1].static_subject is True


@pytest.mark.asyncio
async def test_explicit_allow_and_deny_calls(tmp_path: Path, models_dir: Path) -> None:
    """Verify explicit fixture decisions govern tool calls rather than config parsing alone."""
    query = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])
    allow_config = tmp_path / "allow.yaml"
    allow_config.write_text(_config(models_dir, _write_policy(tmp_path / "allow", allow=True)), encoding="utf-8")
    allow_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=allow_config)
    allow_tool = allow_server._owned_toolkit.get_tool("sl_compile_query")
    assert allow_tool is not None
    assert "SELECT" in (await allow_tool._execute(query=query))["sql"]

    deny_config = tmp_path / "deny.yaml"
    deny_config.write_text(_config(models_dir, _write_policy(tmp_path / "deny", allow=False)), encoding="utf-8")
    deny_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=deny_config)
    deny_tool = deny_server._owned_toolkit.get_tool("sl_compile_query")
    assert deny_tool is not None
    with pytest.raises(SemanticAccessError, match="PBAC denied"):
        await deny_tool._execute(query=query)
