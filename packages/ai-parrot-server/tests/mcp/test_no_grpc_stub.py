"""FEAT-746 M0b — the dead gRPC MCP stub and its config fields are gone (AC17)."""

from __future__ import annotations

import dataclasses
import importlib.util
import pathlib

from parrot.mcp.config import MCPServerConfig

TRANSPORTS = pathlib.Path(__file__).resolve().parents[2] / "src" / "parrot" / "mcp" / "transports"


def test_stub_files_removed():
    """Ensure the unsupported gRPC MCP transport files cannot be discovered."""
    assert not (TRANSPORTS / "grpc_session.py").exists()
    assert not (TRANSPORTS / "mcp.proto").exists()
    assert importlib.util.find_spec("parrot.mcp.transports.grpc_session") is None


def test_config_has_no_grpc_fields():
    """Ensure MCP server configuration cannot retain retired gRPC settings."""
    names = {field.name for field in dataclasses.fields(MCPServerConfig)}
    assert not {name for name in names if name.startswith("grpc_")}
