"""FEAT-473 TASK-2566 — STRUCTURED_TABLE end-to-end A2UI conformance.

NOTE: named ``..._e2e_a2ui.py`` (not ``..._e2e.py``) to avoid colliding with
the pre-existing FEAT-218 ``test_structured_table_e2e.py`` in this same
directory — the task's own file table named the latter, unaware it was
already taken; see this task's Completion Note.

PandasAgent-style table response → the satellite hook's dual-emit produces a
v1.0 envelope; ``bake_envelope`` expands the ``DataTable`` ``ChildTemplate``
row into exactly one row node per data-model row, and the static
``PDFRenderer`` (satellite A2UI renderer) renders it successfully.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("jsonpointer")
pytest.importorskip("weasyprint")


def _lower_to_basic_components(envelope):
    """Lower every non-primitive top-level component to Basic form.

    Mirrors ``tests/outputs/a2ui/conformance/test_all_emitters.py``'s own
    helper — built from the public catalog API only.
    """
    from parrot.outputs.a2ui.catalog import get_component
    from parrot.outputs.a2ui.catalog.base import to_components

    lowered = []
    for comp in envelope.components:
        entry = get_component(comp.component)
        if entry.definition.is_primitive:
            lowered.append(comp)
        else:
            tree = entry.component_cls().lower(comp, envelope.data_model)
            lowered.extend(to_components(tree, id_prefix=f"{comp.id}-lc"))
    return lowered


@pytest.mark.asyncio
async def test_structured_table_e2e_a2ui():
    from parrot.models.outputs import OutputMode
    from parrot.outputs.a2ui.baking import bake_envelope
    from parrot.outputs.a2ui.models import A2UIAgentMessage
    from parrot.outputs.a2ui_renderers.pdf import PDFRenderer
    from parrot.outputs.formats import get_renderer

    df = pd.DataFrame({"id": [1, 2, 3], "amount": [10.5, 20.0, 30.75]})
    resp = SimpleNamespace(
        data=df, response="Order amounts.", code=None, output=None, a2ui_envelope=None, artifact_id=None
    )

    renderer = get_renderer(OutputMode.STRUCTURED_TABLE)()
    out, _explanation = await renderer.render(resp)

    assert out is not None
    assert "data" not in out

    envelope = resp.a2ui_envelope
    assert envelope is not None
    surface = A2UIAgentMessage.model_validate(envelope).create_surface
    root = next(c for c in surface.components if c.id == "root")
    assert root.component == "DataTable"

    lowered = _lower_to_basic_components(surface)
    lowered_surface = surface.model_copy(update={"components": lowered})
    baked = bake_envelope(lowered_surface)

    row_nodes = [c for c in baked if c.get("metadata", {}).get("extensions", {}).get("parrot_role") == "row"]
    data_model_rows = surface.data_model["rows"]
    assert len(row_nodes) == len(data_model_rows) == 3

    # PDFRenderer (static satellite renderer) renders it successfully.
    artifact = await PDFRenderer().render(surface)
    assert artifact.mime_type == "application/pdf"
