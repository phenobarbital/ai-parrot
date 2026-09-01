"""Unit tests for toolkit MCP server factory.

FEAT-485: Tests for toolkit_server.py factory — class resolution, LLM wiring,
tool filtering, and error handling.
"""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from parrot.mcp.toolkit_server import create_toolkit_mcp_server


@pytest.fixture
def stub_config(tmp_path):
    """Project root with config pointing to stub toolkit."""
    parrot_dir = tmp_path / ".parrot"
    parrot_dir.mkdir()
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n" "  stub:\n" "    class: tests.mcp.stub_toolkit.StubToolkit\n" "    kwargs: {}\n"
    )
    return tmp_path


def mock_import_module(name):
    """Mock importlib.import_module to return a module with StubToolkit."""
    if "stub_toolkit" in name:
        # Import locally to avoid module resolution issues
        from tests.mcp.stub_toolkit import StubToolkit

        class MockModule:
            pass

        mock = MockModule()
        setattr(mock, "StubToolkit", StubToolkit)
        return mock
    return importlib.import_module(name)


def test_serves_stub_toolkit(stub_config, monkeypatch):
    """Stub toolkit served: tools listed, plain tool callable."""
    # Monkeypatch importlib to return StubToolkit
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    server = create_toolkit_mcp_server("stub", stub_config)

    # Check server name
    assert server.config.name == "parrot-stub"

    # Check tools are registered
    assert len(server._tools) >= 2
    tool_names = {t.name for t in server._tools}
    assert "plain" in tool_names
    assert "dangerous" in tool_names
    # needs_llm should NOT be present (no LLM configured)
    assert "needs_llm" not in tool_names


def test_include_wins_over_exclude(stub_config, monkeypatch):
    """Include wins over exclude; both filters work by tool name."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    # Config with both include and exclude
    parrot_dir = stub_config / ".parrot"
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n"
        "  stub:\n"
        "    class: tests.mcp.stub_toolkit.StubToolkit\n"
        "    include: [plain]\n"
        "    exclude: [dangerous]\n"
    )

    server = create_toolkit_mcp_server("stub", stub_config)
    tool_names = {t.name for t in server._tools}

    # Include should win: only plain present
    assert "plain" in tool_names
    assert "dangerous" not in tool_names


def test_exclude_works_alone(stub_config, monkeypatch):
    """Exclude filters when include is not set."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    parrot_dir = stub_config / ".parrot"
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n" "  stub:\n" "    class: tests.mcp.stub_toolkit.StubToolkit\n" "    exclude: [dangerous]\n"
    )

    server = create_toolkit_mcp_server("stub", stub_config)
    tool_names = {t.name for t in server._tools}

    # dangerous should be absent, plain present
    assert "plain" in tool_names
    assert "dangerous" not in tool_names


def test_llm_dependent_dropped_without_llm(stub_config, monkeypatch):
    """No `llm:` → llm-dependent tool absent from exposure."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    server = create_toolkit_mcp_server("stub", stub_config)
    tool_names = {t.name for t in server._tools}

    # needs_llm should be absent (no LLM configured)
    assert "needs_llm" not in tool_names
    assert "plain" in tool_names


def test_llm_wired_when_configured(stub_config, monkeypatch):
    """With `llm:` configured, LLMFactory.create called and client wired."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    parrot_dir = stub_config / ".parrot"
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n" "  stub:\n" "    class: tests.mcp.stub_toolkit.StubToolkit\n" "    llm: 'test:model'\n"
    )

    # Mock LLMFactory.create
    mock_client = MagicMock()
    monkeypatch.setattr("parrot.mcp.toolkit_server.LLMFactory.create", return_value=mock_client)

    server = create_toolkit_mcp_server("stub", stub_config)

    # Check toolkit has the mocked client
    toolkit = server._tools[0].bound_method.__self__
    assert toolkit.llm_client is mock_client

    # Check needs_llm tool is now present (LLM was wired)
    tool_names = {t.name for t in server._tools}
    assert "needs_llm" in tool_names


def test_confirm_flag_in_schema(stub_config, monkeypatch):
    """Confirming tool's MCP schema contains required `confirm` property."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    server = create_toolkit_mcp_server("stub", stub_config)

    # Find the dangerous tool
    dangerous_tool = None
    for tool in server._tools:
        if tool.name == "dangerous":
            dangerous_tool = tool
            break

    assert dangerous_tool is not None

    # Check MCP schema has confirm property
    schema = dangerous_tool.to_mcp_tool_definition()
    assert "inputSchema" in schema
    assert "properties" in schema["inputSchema"]
    assert "confirm" in schema["inputSchema"]["properties"]


def test_unknown_name_lists_names(stub_config, monkeypatch):
    """Unknown name error lists resolvable names."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    with pytest.raises(ValueError, match="Unknown toolkit name") as exc_info:
        create_toolkit_mcp_server("unknown", stub_config)

    error_msg = str(exc_info.value)
    assert "stub" in error_msg  # should list available names


def test_import_error_named(stub_config, monkeypatch):
    """ImportError names the missing module."""
    parrot_dir = stub_config / ".parrot"
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text("toolkits:\n" "  stub:\n" "    class: nonexistent.module.Toolkit\n")

    with pytest.raises(ImportError):
        create_toolkit_mcp_server("stub", stub_config)


def test_stdout_purity(stub_config, monkeypatch, capsys):
    """stdout carries only JSON-RPC: no import noise."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    server = create_toolkit_mcp_server("stub", stub_config)

    # Capture stdout/stderr
    captured = capsys.readouterr()

    # stdout should be empty
    assert captured.out == ""


def test_cli_override_include(stub_config, monkeypatch):
    """CLI override for include parameter."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    server = create_toolkit_mcp_server("stub", stub_config, include=["plain"])
    tool_names = {t.name for t in server._tools}

    # Only plain should be present
    assert "plain" in tool_names
    assert "dangerous" not in tool_names


def test_toolkit_instantiation_error(stub_config, monkeypatch):
    """TypeError during toolkit instantiation raises ValueError."""
    monkeypatch.setattr("parrot.mcp.toolkit_server.importlib.import_module", mock_import_module)

    parrot_dir = stub_config / ".parrot"
    config_file = parrot_dir / "mcp-toolkits.yaml"
    config_file.write_text(
        "toolkits:\n"
        "  stub:\n"
        "    class: tests.mcp.stub_toolkit.StubToolkit\n"
        "    kwargs:\n"
        "      bad_param: value\n"
    )

    with pytest.raises(ValueError, match="Failed to instantiate toolkit"):
        create_toolkit_mcp_server("stub", stub_config)
