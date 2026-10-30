"""FEAT-753 M2 — MermaidDiagram registration, schema, lowering golden and validation gate."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registration
from parrot.outputs.a2ui.catalog import (
    DEFAULT_CATALOG_ID,
    ProducerOrigin,
    catalog_instructions,
    get_component,
    validate_envelope,
)
from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_SOURCE_TOO_LARGE,
    MERMAID_UNSAFE_DIRECTIVE,
    MERMAID_UNSAFE_INTERACTION,
    CatalogValidationError,
)
from parrot.outputs.a2ui.catalog.export import export_catalog_definition
from parrot.outputs.a2ui.catalog.parrot.mermaiddiagram import (
    MERMAIDDIAGRAM_INSTRUCTIONS,
    MERMAIDDIAGRAM_SCHEMA,
    MermaidDiagramComponent,
)
from parrot.outputs.a2ui.models import Component, CreateSurface, UpdateComponents

GOLDEN = Path(__file__).parent / "golden" / "mermaiddiagram_lowered.json"
SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
BASIC_PRIMITIVES = {"Card", "Column", "Text"}


def _mermaid_component(**overrides) -> Component:
    props = {
        "source": SEQUENCE_SRC,
        "diagramType": "sequence",
        "title": "Login flow",
        "caption": "Happy path",
        "theme": "neutral",
        "accessibleDescription": "Alice greets Bob",
    }
    props.update(overrides)
    return Component(id="root", component="MermaidDiagram", **props)


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _create(component: Component) -> CreateSurface:
    return CreateSurface(surfaceId="s1", catalogId=DEFAULT_CATALOG_ID, components=[component])


def _update(component: Component) -> UpdateComponents:
    return UpdateComponents(surfaceId="s1", components=[component])


def _validate(envelope, origin=ProducerOrigin.TOOL) -> None:
    # UpdateComponents carries no catalog id of its own — supply the surface default
    validate_envelope(envelope, origin=origin, surface_catalog_id=DEFAULT_CATALOG_ID)


def _issue_codes(envelope, origin) -> set[str]:
    with pytest.raises(CatalogValidationError) as exc:
        _validate(envelope, origin)
    return {i["code"] for i in exc.value.issues}


def test_registration_flags() -> None:
    entry = get_component("MermaidDiagram")
    assert entry.definition.tool_only is False
    assert entry.definition.requires_actions is False
    assert entry.definition.allowed_parents == ["root", "Column"]
    assert "MermaidDiagram" in {c["name"] if isinstance(c, dict) else c for c in _exported_names()}


def _exported_names():
    doc = export_catalog_definition()
    comps = doc.get("components", {})
    return list(comps.keys()) if isinstance(comps, dict) else comps


def test_schema_shape() -> None:
    props = MERMAIDDIAGRAM_SCHEMA["properties"]
    assert MERMAIDDIAGRAM_SCHEMA["required"] == ["source"]
    assert props["source"]["minLength"] == 1
    assert props["source"]["maxLength"] == 32_768
    assert "sequence" in props["diagramType"]["enum"] and "unknown" in props["diagramType"]["enum"]
    assert props["theme"]["enum"] == ["default", "neutral", "dark", "forest", "base"]
    jsonschema.Draft202012Validator.check_schema(MERMAIDDIAGRAM_SCHEMA)
    jsonschema.validate({"source": SEQUENCE_SRC, "diagramType": "sequence"}, MERMAIDDIAGRAM_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"source": ""}, MERMAIDDIAGRAM_SCHEMA)


def test_lowering_golden() -> None:
    comp = _mermaid_component()
    one = _dump(MermaidDiagramComponent().lower(comp, {}))
    two = _dump(MermaidDiagramComponent().lower(comp, {}))
    assert one == two == GOLDEN.read_bytes()


def test_lowering_roles_and_extensions() -> None:
    tree = MermaidDiagramComponent().lower(_mermaid_component(), {})
    assert tree.component == "Card" and tree.id == "root"
    assert tree.metadata.extensions.root["parrot_variant"] == "mermaid-diagram"
    kids = tree.child.children
    roles = [k.metadata.extensions.root["parrot_role"] for k in kids]
    assert roles == ["description", "title", "caption", "mermaid-source"]
    assert kids[0].text == "Alice greets Bob"
    assert kids[-1].text == SEQUENCE_SRC
    ext = kids[-1].metadata.extensions.root
    assert ext["parrot_diagram_type"] == "sequence" and ext["parrot_mermaid_theme"] == "neutral"

    bare = MermaidDiagramComponent().lower(Component(id="root", component="MermaidDiagram", source=SEQUENCE_SRC), {})
    kids = bare.child.children
    assert [k.metadata.extensions.root["parrot_role"] for k in kids] == ["description", "mermaid-source"]
    assert kids[0].text == "Mermaid sequence diagram"
    assert "parrot_mermaid_theme" not in kids[-1].metadata.extensions.root


def test_lowering_emits_only_basic_primitives() -> None:
    tree = MermaidDiagramComponent().lower(_mermaid_component(), {})
    seen = {tree.component, tree.child.component} | {k.component for k in tree.child.children}
    assert seen <= BASIC_PRIMITIVES


@pytest.mark.parametrize("make", [_create, _update])
def test_validate_envelope_llm_origin_accepts_clean_source(make) -> None:
    _validate(make(_mermaid_component()), ProducerOrigin.LLM)
    _validate(make(_mermaid_component()), ProducerOrigin.TOOL)


@pytest.mark.parametrize("origin", [ProducerOrigin.LLM, ProducerOrigin.TOOL])
@pytest.mark.parametrize("make", [_create, _update])
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"source": '%%{init: {"theme": "dark"}}%%\nsequenceDiagram\n A->>B: x\n'}, MERMAID_UNSAFE_DIRECTIVE),
        (
            {"source": 'flowchart TD\n a-->b\n click a href "x"\n', "diagramType": "flowchart"},
            MERMAID_UNSAFE_INTERACTION,
        ),
        ({"source": "x" * 40_000}, MERMAID_SOURCE_TOO_LARGE),
        ({"diagramType": "flowchart"}, MERMAID_DIAGRAM_TYPE_MISMATCH),
    ],
)
def test_validate_envelope_rejects_unsafe_for_both_origins(origin, make, overrides, code) -> None:
    assert code in _issue_codes(make(_mermaid_component(**overrides)), origin)


def test_validate_mermaid_create_and_update_path_is_component_id() -> None:
    bad = _mermaid_component(source="flowchart TD\n click a x\n", diagramType="flowchart")
    for make in (_create, _update):
        with pytest.raises(CatalogValidationError) as exc:
            _validate(make(bad))
        issue = next(i for i in exc.value.issues if i["code"] == MERMAID_UNSAFE_INTERACTION)
        assert issue["path"] == "root"


def test_missing_source_reports_empty() -> None:
    comp = Component(id="root", component="MermaidDiagram")
    assert MERMAID_SOURCE_TOO_LARGE in _issue_codes(_create(comp), ProducerOrigin.TOOL)


def test_instructions_in_catalog_instructions() -> None:
    assert MERMAIDDIAGRAM_INSTRUCTIONS in catalog_instructions()
    assert "NEVER write" in MERMAIDDIAGRAM_INSTRUCTIONS
