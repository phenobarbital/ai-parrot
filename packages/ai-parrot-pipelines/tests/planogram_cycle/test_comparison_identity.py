"""Shared identity resolution and verify-pass evidence gating (FEAT-612, Module 4)."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.comparison.identity import resolve_identity
from parrot_pipelines.planogram.contracts import CycleContext, Identification
from parrot_pipelines.planogram.identification.verify import VerificationAnswer, pick_candidates, verify_unresolved
from parrot_pipelines.planogram.types.ink_wall import resolve_identity as ink_resolve_identity

BOX = DetectionBox(x1=10, y1=10, x2=60, y2=60, confidence=1.0)
IMAGE = np.full((100, 100, 3), 200, np.uint8)


class _InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class _CountingAdapter:
    """Vision stub that records calls and returns queued answers."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(stage)
        return self.answers.pop(0)


def _definition(extra_facings=()):
    """Generic synthetic catalogue with typed and custom descriptor values."""
    facings = [
        {
            "facing_id": "f1",
            "shelf_id": "s1",
            "slot": 1,
            "product": "P-1",
            "brand": "Acme",
            "descriptors": {
                "display_name": "P one",
                "family": "F1",
                "xl": False,
                "identifiers": ["ID-1"],
                "attributes": {"finish": "matte"},
            },
        },
        {
            "facing_id": "f2",
            "shelf_id": "s1",
            "slot": 2,
            "product": "P-2",
            "brand": "Acme",
            "descriptors": {
                "display_name": "P two",
                "family": "F1",
                "xl": True,
                "aliases": ["Acme Mega Bottle"],
                "attributes": {"finish": "gloss"},
            },
        },
        {
            "facing_id": "f3",
            "shelf_id": "s1",
            "slot": 3,
            "product": "P-3",
            "brand": "Acme",
            "descriptors": {"family": "F2"},
        },
        *extra_facings,
    ]
    return load_slots_definition({"shelves": [{"shelf_id": "s1", "shelf_number": 1, "facings": facings}]})


def _ident(**kwargs) -> Identification:
    kwargs.setdefault("shape_id", "s")
    kwargs.setdefault("image_id", "img0")
    return Identification(**kwargs)


PARITY_READS = [
    dict(brand="Acme", text="ID-1"),
    dict(brand="Acme", descriptors={"family": "f1"}),
    dict(brand="Acme", descriptors={"family": "f1", "xl": True}),
    dict(brand="Acme", descriptors={"family": "F2", "xl": False}),
    dict(brand="Acme", text="acme mega bottle 2"),
    dict(brand="Other", text="ID-1"),
    dict(brand="Acme"),
]


@pytest.mark.parametrize("read", PARITY_READS)
def test_default_arguments_match_ink_wall(read):
    definition = _definition()
    assert resolve_identity(_ident(**read), definition) == ink_resolve_identity(_ident(**read), definition)


def test_no_slot_parameter_and_shape_id_independent():
    assert list(inspect.signature(resolve_identity).parameters) == [
        "identification",
        "definition",
        "vocabulary",
        "required_fields",
    ]
    definition = _definition()
    first = resolve_identity(_ident(shape_id="a", brand="Acme", text="ID-1"), definition)
    second = resolve_identity(_ident(shape_id="b", brand="Acme", text="ID-1"), definition)
    assert first == second


def test_required_fields_empty_disables_signature():
    assert resolve_identity(_ident(brand="Acme", descriptors={"family": "F2"}), _definition(), required_fields=()) == (
        None,
        [],
    )


def test_custom_attribute_resolves_and_contradicts():
    kwargs = {"vocabulary": ("family", "finish"), "required_fields": ("family", "finish")}
    assert resolve_identity(
        _ident(brand="Acme", descriptors={"family": "F1", "finish": "matte"}), _definition(), **kwargs
    ) == (
        "P-1",
        ["P-1"],
    )
    assert resolve_identity(
        _ident(brand="Acme", descriptors={"family": "F1", "finish": "satin"}), _definition(), **kwargs
    ) == (
        None,
        [],
    )


def test_expected_empty_facing_never_candidate():
    empty = {
        "facing_id": "f4",
        "shelf_id": "s1",
        "slot": 4,
        "product": None,
        "expected_occupancy": "empty",
        "brand": "Acme",
        "descriptors": {"family": "F2"},
    }
    definition = _definition([empty])
    assert resolve_identity(_ident(brand="Acme", descriptors={"family": "F2", "xl": False}), definition) == (
        "P-3",
        ["P-3"],
    )
    assert all(
        facing.facing_id != "f4" for facing in pick_candidates(_ident(brand="Acme", uncertain=True), definition, 5)
    )


@pytest.mark.asyncio
async def test_verify_skips_observed_empty_slot():
    adapter = _CountingAdapter()
    ctx = CycleContext(vision=adapter, executor=_InlineExecutor())
    ident = _ident(brand="Acme", occupancy="empty", uncertain=True)
    result = await verify_unresolved(IMAGE, [ident], _definition(), ctx, boxes={"s": BOX})
    assert result[0] is ident and adapter.calls == []


@pytest.mark.asyncio
async def test_offered_candidate_without_visible_text_is_not_evidence():
    answer = VerificationAnswer(choice="P-1", visible_text=[], evidence="it is P-1", confidence=0.9)
    adapter = _CountingAdapter(answer)
    original = _ident(brand="Acme", uncertain=True)
    result = await verify_unresolved(
        IMAGE, [original], _definition(), CycleContext(vision=adapter, executor=_InlineExecutor()), boxes={"s": BOX}
    )
    assert len(adapter.calls) == 1
    assert result[0] is original and result[0].uncertain


def test_pick_candidates_attribute_contradiction():
    candidates = pick_candidates(
        _ident(brand="Acme", descriptors={"family": "F1", "finish": "gloss"}), _definition(), 5
    )
    assert "P-2" in [facing.product for facing in candidates]
    assert "P-1" not in [facing.product for facing in candidates]
