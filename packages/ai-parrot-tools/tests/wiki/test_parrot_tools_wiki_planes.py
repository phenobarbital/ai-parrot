"""Plane wrappers moved to parrot_tools.wiki (FEAT-540 M3)."""

import importlib

import pytest

_OLD = {
    "parrot.knowledge.wiki.structural.tools": ["create_structural_tools", "WikiSymbolLookupTool", "SymbolLookupInput"],
    "parrot.knowledge.wiki.structural.toolkit": ["CodeStructuralToolkit"],
    "parrot.knowledge.wiki.decisions.tools": ["create_decision_tools", "WikiDecisionWhyTool", "DecisionService"],
    "parrot.knowledge.wiki.decisions.toolkit": ["DecisionToolkit"],
    "parrot.knowledge.wiki.schema.tools": ["create_schema_tools", "WikiSchemaLookupTool", "_SchemaTool"],
    "parrot.knowledge.wiki.schema.toolkit": ["SchemaPlaneToolkit"],
}


@pytest.mark.parametrize(
    "name",
    [
        "CodeStructuralToolkit",
        "DecisionToolkit",
        "SchemaPlaneToolkit",
        "create_structural_tools",
        "create_decision_tools",
        "create_schema_tools",
    ],
)
def test_exported(name: str) -> None:
    import parrot_tools.wiki as w

    assert getattr(w, name)


@pytest.mark.parametrize("old,names", list(_OLD.items()))
def test_old_path_identity(old: str, names: list[str]) -> None:
    shim = importlib.import_module(old)
    new = importlib.import_module("parrot_tools.wiki." + old.split(".")[-2])
    for name in names:
        assert getattr(shim, name) is getattr(new, name)


@pytest.mark.parametrize("old", list(_OLD))
def test_old_path_unknown_attribute(old: str) -> None:
    shim = importlib.import_module(old)
    with pytest.raises(AttributeError):
        shim.definitely_not_here  # noqa: B018


def test_shim_import_is_lazy() -> None:
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    code = (
        "import sys\n"
        f"sys.path[:0] = [{str(root / 'packages/ai-parrot/src')!r}, {str(root / 'packages/ai-parrot-tools/src')!r}]\n"
        "import parrot.knowledge.wiki.schema.tools, parrot.knowledge.wiki.schema.toolkit\n"
        "import parrot.knowledge.wiki.decisions.toolkit, parrot.knowledge.wiki.structural.tools\n"
        "print('parrot_tools.wiki.schema' in sys.modules)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
