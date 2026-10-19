"""mcp-local configuration and default exposure tests for the semantic layer."""

from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from parrot.mcp.local_cli import mcp_local
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.semantic.toolkit import SemanticLayerToolkit

from ._models import models_dir  # noqa: F401 -- pytest fixture registration


def _write_config(root: Path, models_dir: Path) -> Path:
    """Write an operator-local semantic-layer toolkit configuration."""
    config_dir = root / ".parrot"
    config_dir.mkdir()
    config_path = config_dir / "mcp-toolkits.yaml"
    config_path.write_text(
        "toolkits:\n"
        "  semantic-layer:\n"
        "    class: parrot.semantic.toolkit.SemanticLayerToolkit\n"
        "    kwargs:\n"
        f"      models_dir: {models_dir}\n"
        "      dialect: duckdb\n"
        "      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}\n"
        "    env: {}\n",
        encoding="utf-8",
    )
    return config_path


def test_mcp_toolkits_yaml_section(tmp_path: Path) -> None:
    """The documented YAML section loads with the expected class path."""
    config_dir = tmp_path / ".parrot"
    config_dir.mkdir()
    (config_dir / "mcp-toolkits.yaml").write_text(
        "toolkits:\n"
        "  semantic-layer:\n"
        "    class: parrot.semantic.toolkit.SemanticLayerToolkit\n"
        "    kwargs: {models_dir: /tmp/m, dialect: duckdb}\n",
        encoding="utf-8",
    )

    config = load_toolkits_config(tmp_path)

    assert config.toolkits["semantic-layer"].class_path == "parrot.semantic.toolkit.SemanticLayerToolkit"


def test_e2e_mcp_local_semantic_layer(tmp_path: Path, models_dir: Path, allow_all_guard: MagicMock) -> None:
    """mcp-local resolves the section and the default toolkit exposes only safe tools."""
    config_path = _write_config(tmp_path, models_dir)

    result = CliRunner().invoke(
        mcp_local,
        ["semantic-layer", "--config", str(config_path), "--list"],
    )

    assert result.exit_code == 0, result.output
    assert "semantic-layer\tenabled\tparrot.semantic.toolkit.SemanticLayerToolkit" in result.output

    toolkit = SemanticLayerToolkit(
        models_dir=models_dir,
        dialect="duckdb",
        dataplane_guard=allow_all_guard,
        static_subject={"user_id": "operator", "tenant_id": "local", "roles": ["admin"]},
    )
    tool_names = {tool.name for tool in toolkit.get_tools()}

    assert "sl_query_metrics" in tool_names
    assert "sl_run_sql" not in tool_names
    assert "sl_save_result_as_dataset" not in tool_names
