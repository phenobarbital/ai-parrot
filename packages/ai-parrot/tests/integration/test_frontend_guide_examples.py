"""FEAT-473 TASK-2566 — every A2UI v1.0 envelope example in the frontend guide validates.

Extracts fenced ```json a2ui-envelope``` blocks from
``docs/frontend/structured-artifacts-frontend-guide.md`` (Appendix B) and
runs the same two-layer conformance check the rest of this codebase uses
(:func:`~parrot.outputs.a2ui.catalog.validate_envelope` on the raw Parrot
component tree, :func:`~parrot.outputs.a2ui.catalog.validate_message` on its
lowered, Basic-catalog-only form — see
``tests/outputs/a2ui/conformance/test_all_emitters.py``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — ensure Chart/DataTable/Map registration

_REPO_ROOT = Path(__file__).resolve().parents[4]
_GUIDE_PATH = _REPO_ROOT / "docs" / "frontend" / "structured-artifacts-frontend-guide.md"
_FENCE_RE = re.compile(r"```json a2ui-envelope\n(.*?)```", re.DOTALL)


def _extract_a2ui_envelope_examples() -> list[dict]:
    text = _GUIDE_PATH.read_text(encoding="utf-8")
    return [json.loads(block) for block in _FENCE_RE.findall(text)]


def _lower_to_basic_components(envelope):
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


def test_guide_has_a2ui_envelope_examples():
    examples = _extract_a2ui_envelope_examples()
    assert len(examples) == 3, "expected Chart/Table/Map examples in Appendix B"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_frontend_guide_examples_validate(index):
    from parrot.outputs.a2ui.catalog import validate_envelope, validate_message
    from parrot.outputs.a2ui.catalog.base import ProducerOrigin
    from parrot.outputs.a2ui.models import A2UIAgentMessage

    examples = _extract_a2ui_envelope_examples()
    envelope_dict = examples[index]
    assert envelope_dict["version"] == "v1.0"

    message = A2UIAgentMessage.model_validate(envelope_dict)
    surface = message.create_surface
    validate_envelope(surface, origin=ProducerOrigin.TOOL)

    lowered_surface = surface.model_copy(update={"components": _lower_to_basic_components(surface)})
    lowered_message = A2UIAgentMessage(version="v1.0", create_surface=lowered_surface)
    validate_message(lowered_message)
