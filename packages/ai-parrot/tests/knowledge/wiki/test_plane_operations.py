"""Plane operations parity (FEAT-540 M3)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.operations import DecisionWhyInput, op_decision_why
from parrot.knowledge.wiki.decisions.tools import create_decision_tools
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig
from parrot.knowledge.wiki.schema.operations import SchemaLookupInput, op_schema_lookup
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.tools import create_schema_tools
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.structural.operations import CodeOutlineInput, op_code_outline
from parrot.knowledge.wiki.structural.tools import create_structural_tools
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord


@pytest.fixture
async def seeded(tmp_path):
    """Create one rootless structural-plane symbol fixture."""
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    await store.upsert_symbols(
        [
            SymbolRecord(
                rel_path="pkg/mod.py",
                language="python",
                kind=SymbolKind.FUNCTION,
                name="f",
                qualname="f",
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=10,
                content_hash="h",
            )
        ],
        source_id="file:pkg/mod.py",
    )
    return store


@pytest.mark.parametrize(
    "module",
    [
        "parrot.knowledge.wiki.structural.operations",
        "parrot.knowledge.wiki.decisions.operations",
        "parrot.knowledge.wiki.schema.operations",
    ],
)
def test_operations_framework_free(module: str) -> None:
    """Operation modules do not import the framework tool layer."""
    source_root = Path(__file__).parents[3] / "src"
    code = (
        "import importlib, sys; "
        f"sys.path.insert(0, {str(source_root)!r}); "
        f"importlib.import_module({module!r}); "
        "assert 'parrot.tools.abstract' not in sys.modules"
    )
    completed = subprocess.run([sys.executable, "-I", "-c", code], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


async def test_structural_operation_matches_tool(seeded, tmp_path) -> None:
    """The lifted outline operation preserves the structural tool payload."""
    config = WikiProjectConfig(wiki_name="t")
    tool = create_structural_tools(seeded, tmp_path, config, read_repair=False)[1]
    tool_result = await tool._execute("file:pkg/mod.py")
    operation_result = await op_code_outline(
        seeded,
        CodeOutlineInput(target="file:pkg/mod.py"),
        service_factory=tool._service_factory,
    )
    assert operation_result.is_error is False
    assert operation_result.data == tool_result.result


async def test_decision_operation_matches_tool(adr_store, tmp_path) -> None:
    """The lifted decision operation preserves its rendered ToolResult."""
    tool = next(tool for tool in create_decision_tools(adr_store, tmp_path, WikiProjectConfig()) if tool.name == "wiki_decision_why")
    tool_result = await tool._execute("why")
    operation_result = await op_decision_why(
        adr_store,
        DecisionWhyInput(question="why"),
        service_factory=tool._service_factory,
    )
    assert operation_result.is_error is False
    assert operation_result.text == tool_result.result
    assert operation_result.data == tool_result.metadata


async def test_schema_operation_matches_tool(plane_dir, sales_metadata) -> None:
    """The lifted schema operation preserves the formatted lookup payload."""
    service = SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)
    await service.put_table("bigquery", "bigquery", sales_metadata)
    tool = create_schema_tools(service.store, None, WikiProjectConfig(), service=service)[0]
    tool_result = await tool._execute("bigquery:epson.sales")
    operation_result = await op_schema_lookup(
        service.store,
        SchemaLookupInput(ref="bigquery:epson.sales"),
        service=service,
        annotation_store=service.store,
    )
    assert operation_result.is_error is False
    assert operation_result.data == tool_result.result
