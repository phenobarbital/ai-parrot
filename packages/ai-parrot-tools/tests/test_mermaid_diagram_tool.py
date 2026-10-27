"""FEAT-753 M4 — MermaidDiagramTool."""

from __future__ import annotations

import importlib

from parrot.tools.mermaid_diagram import MermaidDiagramArgs, MermaidDiagramTool
from parrot_tools import TOOL_REGISTRY

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
CLICK_SRC = 'flowchart TD\n    a --> b\n    click a href "https://example.org"\n'


def test_tool_schema_and_docstring() -> None:
    tool = MermaidDiagramTool()
    assert tool.name == "render_mermaid_diagram"
    assert tool.args_schema is MermaidDiagramArgs
    assert "infographic" in (MermaidDiagramTool.__doc__ or "")
    props = tool.get_schema()["parameters"]["properties"]
    for field in ("source", "title", "caption", "theme", "accessible_description"):
        assert field in props


async def test_tool_execute_returns_lift_shape() -> None:
    result = await MermaidDiagramTool()._execute(source=SEQUENCE_SRC, title="Greeting")
    assert "version" not in result["a2ui_envelope"]
    assert result["a2ui_envelope"]["components"][0]["component"] == "MermaidDiagram"
    artifact = result["artifacts"][0]
    assert artifact["type"] == "a2ui_surface"
    assert artifact["component"] == "MermaidDiagram"
    assert artifact["surface_id"] == result["a2ui_envelope"]["surfaceId"]
    assert result["diagram_type"] == artifact["diagram_type"] == "sequence"
    assert result["source"] == SEQUENCE_SRC


async def test_tool_propagates_validation_error() -> None:
    result = await MermaidDiagramTool().execute(source=CLICK_SRC)
    assert result.status != "success"
    assert "MERMAID_UNSAFE_INTERACTION" in str(result.error or result.result)


def test_tool_registered_in_mapping() -> None:
    dotted = TOOL_REGISTRY["mermaid_diagram"]
    module_path, _, cls_name = dotted.rpartition(".")
    assert getattr(importlib.import_module(module_path), cls_name) is MermaidDiagramTool
