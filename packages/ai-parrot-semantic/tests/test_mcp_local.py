"""Regression contract: Local MCP configuration and semantic-layer documentation (M11b).

Every configuration and model example is extracted from the documentation's own
fenced blocks, so the doc cannot drift from what these tests exercise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_server import create_toolkit_mcp_server
from parrot.semantic.errors import SemanticAccessError
from parrot.semantic.loader import SemanticModelLoader
from parrot.semantic.models import SemanticQuery

from . import _guard_factory
from ._models import models_dir  # noqa: F401

_DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "tools" / "semantic-layer.md"
_FENCE = re.compile(r"^```(?P<lang>[a-z]+)\n(?P<body>.*?)^```$", re.MULTILINE | re.DOTALL)
_FACTORY_MODULE = "semantic_mcp_local_guard_factory"
_QUERY = SemanticQuery(model="orders", metrics=["revenue"], dimensions=["region"])


def _doc_blocks(lang: str) -> list[str]:
    """Return every fenced block of ``lang`` from the semantic-layer documentation."""
    text = _DOC_PATH.read_text(encoding="utf-8")
    return [match["body"] for match in _FENCE.finditer(text) if match["lang"] == lang]


def _doc_yaml(first_line: str | None = None, *, key: str | None = None) -> str:
    """Return the single YAML block starting with ``first_line`` or declaring top-level ``key``."""
    matches = [
        body
        for body in _doc_blocks("yaml")
        if (first_line is not None and body.startswith(first_line + "\n"))
        or (key is not None and key in (yaml.safe_load(body) or {}))
    ]
    assert len(matches) == 1, f"expected exactly one documented YAML block for {first_line or key}"
    return matches[0]


@pytest.fixture
def guard_factory_module(monkeypatch: pytest.MonkeyPatch) -> str:
    """Register the fixture guard factory module for this test only."""
    monkeypatch.setitem(sys.modules, _FACTORY_MODULE, _guard_factory)
    return _FACTORY_MODULE


def _write_policy(path: Path, *, allow: bool) -> Path:
    """Write one deterministic allow or deny decision for the fixture guard."""
    path.mkdir()
    (path / "decisions.json").write_text(json.dumps({"allow": allow}), encoding="utf-8")
    return path


def _doc_config(path: Path, models: Path, policy_dir: Path, factory_module: str) -> Path:
    """Write the documented toolkit YAML with only its placeholders substituted."""
    text = _doc_yaml(key="toolkits")
    for placeholder, value in (
        ("/path/to/models", str(models)),
        ("/path/to/policies", str(policy_dir)),
        ("myapp.semantic_auth.build_guard", f"{factory_module}.build_guard"),
    ):
        assert placeholder in text
        text = text.replace(placeholder, value)
    path.write_text(text, encoding="utf-8")
    return path


def test_documented_yaml_and_json_parse(tmp_path: Path) -> None:
    """The documented toolkit YAML and .mcp.json blocks parse into the required contract."""
    config_path = tmp_path / "toolkits.yaml"
    config_path.write_text(_doc_yaml(key="toolkits"), encoding="utf-8")
    section = load_toolkits_config(tmp_path, config_path=config_path).toolkits["semantic-layer"]
    assert section.class_path == "parrot.semantic.bootstrap.LocalSemanticLayerToolkit"
    assert section.kwargs["agent_id"] == "local-semantic"
    assert section.kwargs["static_subject"]["user_id"] == "operator"
    assert section.kwargs["guard_factory"] == "myapp.semantic_auth.build_guard"

    json_blocks = [json.loads(body) for body in _doc_blocks("json")]
    servers = [block["mcpServers"]["parrot-semantic-layer"] for block in json_blocks if "mcpServers" in block]
    assert servers == [{"command": "parrot", "args": ["mcp-local", "semantic-layer"]}]


def test_documented_model_loads_through_real_loader(tmp_path: Path) -> None:
    """The documented model and policy blocks load through SemanticModelLoader unchanged."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "orders.yml").write_text(_doc_yaml("# orders.yml"), encoding="utf-8")
    (models / "orders.policy.yaml").write_text(_doc_yaml("# orders.policy.yaml"), encoding="utf-8")

    loaded = SemanticModelLoader(models, driver="duckdb").load()["orders"]

    assert loaded.policy.governed is True
    assert {member.name for member in loaded.members} >= {"region", "ordered_at", "revenue", "orders"}
    assert set(loaded.schema.tables) == {"sales.orders"}


@pytest.mark.asyncio
async def test_actual_mcp_factory_governed_startup(tmp_path: Path, models_dir: Path, guard_factory_module: str) -> None:
    """Start the actual MCP factory from the documented YAML with a governed fixture."""
    config_path = _doc_config(
        tmp_path / "toolkits.yaml", models_dir, _write_policy(tmp_path / "allow", allow=True), guard_factory_module
    )

    server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=config_path)
    toolkit = server._owned_toolkit
    tool = toolkit.get_tool("sl_compile_query")
    assert tool is not None
    result = await tool._execute(query=_QUERY)

    assert "SELECT" in result["sql"]
    assert toolkit._ledger.entries[-1].channel == "mcp-local"
    assert toolkit._ledger.entries[-1].static_subject is True


@pytest.mark.asyncio
async def test_explicit_allow_and_deny_calls(tmp_path: Path, models_dir: Path, guard_factory_module: str) -> None:
    """Verify explicit fixture decisions govern tool calls rather than config parsing alone."""
    allow_config = _doc_config(
        tmp_path / "allow.yaml", models_dir, _write_policy(tmp_path / "allow", allow=True), guard_factory_module
    )
    allow_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=allow_config)
    allow_tool = allow_server._owned_toolkit.get_tool("sl_compile_query")
    assert allow_tool is not None
    assert "SELECT" in (await allow_tool._execute(query=_QUERY))["sql"]

    deny_config = _doc_config(
        tmp_path / "deny.yaml", models_dir, _write_policy(tmp_path / "deny", allow=False), guard_factory_module
    )
    deny_server = create_toolkit_mcp_server("semantic-layer", root=tmp_path, config_path=deny_config)
    deny_tool = deny_server._owned_toolkit.get_tool("sl_compile_query")
    assert deny_tool is not None
    with pytest.raises(SemanticAccessError, match="PBAC denied"):
        await deny_tool._execute(query=_QUERY)
