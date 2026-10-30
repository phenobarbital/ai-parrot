"""FEAT-753 M3 — build_mermaid_diagram."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui import builders
from parrot.outputs.a2ui.builders import build_mermaid_diagram
from parrot.outputs.a2ui.catalog import ProducerOrigin
from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_UNSAFE_INTERACTION,
    CatalogValidationError,
)

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
DIRECTIVE_SRC = '%%{init: {"theme": "dark", "flowchart": {"htmlLabels": true}}}%%\nflowchart TD\n    a --> b\n'


def _props(envelope) -> dict:
    comp = envelope.components[0]
    assert comp.component == "MermaidDiagram"
    return comp.model_extra


def test_build_mermaid_diagram_in_all() -> None:
    assert "build_mermaid_diagram" in builders.__all__


def test_build_mermaid_diagram_normalizes_and_detects() -> None:
    env = build_mermaid_diagram(source=DIRECTIVE_SRC)
    props = _props(env)
    assert "%%{" not in props["source"]
    assert props["theme"] == "dark"
    assert props["diagramType"] == "flowchart"
    assert env.model_dump_json() == build_mermaid_diagram(source=DIRECTIVE_SRC).model_dump_json()
    # explicit theme wins over the lifted one
    assert _props(build_mermaid_diagram(source=DIRECTIVE_SRC, theme="forest"))["theme"] == "forest"


def test_build_mermaid_diagram_optional_props_only_when_set() -> None:
    bare = _props(build_mermaid_diagram(source=SEQUENCE_SRC))
    assert set(bare) == {"source", "diagramType"}
    full = _props(
        build_mermaid_diagram(
            source=SEQUENCE_SRC, title="T", caption="C", theme="neutral", accessible_description="Alice greets Bob"
        )
    )
    assert full["title"] == "T" and full["caption"] == "C"
    assert full["theme"] == "neutral" and full["accessibleDescription"] == "Alice greets Bob"


def test_build_mermaid_diagram_rejects_declared_mismatch() -> None:
    with pytest.raises(CatalogValidationError) as exc:
        build_mermaid_diagram(source=SEQUENCE_SRC, diagram_type="flowchart")
    assert MERMAID_DIAGRAM_TYPE_MISMATCH in {i["code"] for i in exc.value.issues}


def test_build_mermaid_diagram_rejects_unsafe_source() -> None:
    with pytest.raises(CatalogValidationError) as exc:
        build_mermaid_diagram(source='flowchart TD\n a-->b\n click a href "x"\n')
    assert MERMAID_UNSAFE_INTERACTION in {i["code"] for i in exc.value.issues}


def test_build_mermaid_diagram_llm_origin_passes() -> None:
    env = build_mermaid_diagram(source=SEQUENCE_SRC, origin=ProducerOrigin.LLM)
    assert _props(env)["diagramType"] == "sequence"
