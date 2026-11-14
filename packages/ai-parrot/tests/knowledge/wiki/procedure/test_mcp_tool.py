"""Tests for the ``wiki_procedure_next`` MCP tool on both transports (FEAT-891)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parrot.knowledge.wiki.mcp_server import close_bundle, create_wiki_mcp_server
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProbeCheck, ProcedureSpec
from parrot.knowledge.wiki.procedure.operations import (
    PROCEDURE_NEXT_DESCRIPTION,
    ProcedureNextInput,
    op_procedure_next,
    procedure_plane_available,
)
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.transport import build_operation_descriptors


def _project(root: Path, *, with_plane: bool) -> None:
    """Create a git-backed wiki project and optionally build a minimal procedure plane."""
    (root / ".git").mkdir()
    config = WikiProjectConfig(wiki_name="procedure-mcp")
    save_project_config(root, config)
    if not with_plane:
        return

    source = root / "sdd" / "procedures" / "x.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("graph: sdd\n", encoding="utf-8")
    spec = ProcedureSpec(
        id="sdd:start",
        title="Start task",
        kind="command",
        command="parrot sdd task start <TASK>",
        preconditions=[ProbeCheck(probe="index.exists")],
    )
    asyncio.run(
        ProcedurePlane(root / PLANE_DIR).build(
            [spec],
            [source],
            root=root,
            probe_costs={"index.exists": "local"},
        )
    )


def test_no_plane_no_tool(tmp_path: Path) -> None:
    """Without a built plane neither transport lists the tool."""
    _project(tmp_path, with_plane=False)
    assert procedure_plane_available(tmp_path) is False

    framework = create_wiki_mcp_server(tmp_path, transport="framework")
    sdk = create_wiki_mcp_server(tmp_path, transport="sdk")
    try:
        assert "wiki_procedure_next" not in framework.tools
        assert "wiki_procedure_next" not in {d.name for d in build_operation_descriptors(sdk.wiki_bundle)}
    finally:
        asyncio.run(close_bundle(framework.wiki_bundle))
        asyncio.run(close_bundle(sdk.wiki_bundle))


def test_mcp_tool_both_transports(tmp_path: Path) -> None:
    """With a plane, both transports list the tool with the same description and schema, and it answers."""
    _project(tmp_path, with_plane=True)
    framework = create_wiki_mcp_server(tmp_path, transport="framework")
    sdk = create_wiki_mcp_server(tmp_path, transport="sdk")
    try:
        framework_tool = framework.tools["wiki_procedure_next"].tool
        assert framework_tool.description == PROCEDURE_NEXT_DESCRIPTION
        assert framework_tool.args_schema is ProcedureNextInput

        descriptor = next(
            item for item in build_operation_descriptors(sdk.wiki_bundle) if item.name == "wiki_procedure_next"
        )
        assert descriptor.description == PROCEDURE_NEXT_DESCRIPTION
        assert descriptor.input_model is ProcedureNextInput
        assert descriptor.mount == "procedure"
        result = asyncio.run(descriptor.invoke(ProcedureNextInput()))
        assert not result.is_error
        assert result.data is not None
        assert "next" in result.data and "mandatory" in result.data
        framework_result = asyncio.run(framework.tools["wiki_procedure_next"].execute({}))
        assert framework_result["isError"] is False
    finally:
        asyncio.run(close_bundle(framework.wiki_bundle))
        asyncio.run(close_bundle(sdk.wiki_bundle))


@pytest.mark.asyncio
async def test_operation_without_plane_is_not_an_error(tmp_path: Path) -> None:
    """op_procedure_next answers with a one-line message when no plane exists."""
    result = await op_procedure_next(None, ProcedureNextInput(), root=tmp_path)
    assert not result.is_error and "parrot sdd procedure build" in result.text
