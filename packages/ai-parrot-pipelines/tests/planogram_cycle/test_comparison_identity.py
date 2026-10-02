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


def _models():
    """Catalogue whose facings carry only a model number, like a migrated shelf row."""
    facings = [
        {
            "facing_id": f"m{i}",
            "shelf_id": "s1",
            "slot": i,
            "product": product,
            "brand": "Acme",
            "descriptors": {"display_name": product},
        }
        for i, product in enumerate(("ET-2980", "ET-3950", "ET-2980 Pro"), start=1)
    ]
    return load_slots_definition({"shelves": [{"shelf_id": "s1", "shelf_number": 1, "facings": facings}]})


def test_a_catalogue_name_contained_in_the_read_name_resolves():
    assert resolve_identity(_ident(brand="Acme", product="EcoTank ET-3950"), _models(), required_fields=()) == (
        "ET-3950",
        ["ET-3950"],
    )
    assert resolve_identity(_ident(text="Acme EcoTank et-3950 printer"), _models(), required_fields=())[0] == "ET-3950"


def test_containment_needs_whole_tokens():
    assert resolve_identity(_ident(product="EcoTank ET-39500"), _models(), required_fields=()) == (None, [])
    assert resolve_identity(_ident(product="XET-3950"), _models(), required_fields=()) == (None, [])


def test_containment_prefers_the_longest_catalogue_name():
    assert resolve_identity(_ident(product="EcoTank ET-2980 Pro"), _models(), required_fields=())[0] == "ET-2980 Pro"
    assert resolve_identity(_ident(product="EcoTank ET-2980"), _models(), required_fields=())[0] == "ET-2980"


def test_a_longer_name_only_absorbs_the_names_nested_in_it():
    assert resolve_identity(_ident(text="ET-2980 Pro | ET-3950"), _models(), required_fields=()) == (
        None,
        ["ET-3950", "ET-2980 Pro"],
    )


def test_two_contained_names_stay_unresolved():
    assert resolve_identity(_ident(text="ET-2980 | ET-3950"), _models(), required_fields=()) == (
        None,
        ["ET-2980", "ET-3950"],
    )


def test_containment_ignores_free_form_evidence_and_other_brands():
    assert resolve_identity(_ident(evidence=["next to the ET-3950 box"]), _models(), required_fields=()) == (None, [])
    assert resolve_identity(_ident(brand="Other", product="EcoTank ET-3950"), _models(), required_fields=()) == (
        None,
        [],
    )


def _referenced_ctx() -> CycleContext:
    from parrot_pipelines.planogram.contracts import ReferenceImage

    bank = [
        ReferenceImage(label="ref-0001", image=b"png", catalog_key="ET-2980 Printer"),
        ReferenceImage(label="ref-0002", image=b"png", catalog_key="ET-3950 Printer"),
        ReferenceImage(label="ref-0003", image=b"png", catalog_key="Unlisted model"),
    ]
    return CycleContext(reference_bank=bank)


def test_a_matched_reference_names_an_unread_product():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    read = _ident(brand="Acme", occupancy="occupied", evidence=["white printer"], reference_id="ref-0002")
    result = canonicalise(read, _models(), _referenced_ctx())
    assert result.product == "ET-3950"
    assert result.evidence == ["white printer", "reference | ref-0002 | ET-3950 Printer"]


def test_printed_text_wins_over_a_reference():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    read = _ident(text="EcoTank ET-2980", reference_id="ref-0002")
    assert canonicalise(read, _models(), _referenced_ctx()).product == "ET-2980"
    two = _ident(text="ET-2980 Pro | ET-3950", reference_id="ref-0001")
    assert canonicalise(two, _models(), _referenced_ctx()).product is None


def test_a_reference_picks_one_of_the_text_candidates():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    two = _ident(text="ET-2980 | ET-3950", evidence=["two labels"], reference_id="ref-0002")
    assert canonicalise(two, _models(), _referenced_ctx()).product == "ET-3950"


def test_a_reference_settles_nothing_when_uncertain_unknown_or_uncatalogued():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    ctx = _referenced_ctx()
    for read in (
        _ident(uncertain=True, reference_id="ref-0002"),
        _ident(reference_id="ref-0009"),
        _ident(reference_id="ref-0003"),
    ):
        result = canonicalise(read, _models(), ctx)
        assert result.product is None and not result.evidence


def test_printed_text_naming_the_product_is_evidence():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    read = canonicalise(_ident(product="EcoTank ET-3950", text="ACME EcoTank ET-3950"), _models(), CycleContext())
    assert read.product == "ET-3950" and read.evidence == ["text | ACME EcoTank ET-3950"]
    bare = canonicalise(_ident(product="EcoTank ET-3950", text="ACME"), _models(), CycleContext())
    assert bare.product == "ET-3950" and bare.evidence == []


def test_an_agreeing_reference_is_evidence_for_a_product_named_without_any():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    named = canonicalise(_ident(product="ET-3950", reference_id="ref-0002"), _models(), _referenced_ctx())
    assert named.evidence == ["reference | ref-0002 | ET-3950 Printer"]
    other = canonicalise(_ident(product="ET-3950", reference_id="ref-0001"), _models(), _referenced_ctx())
    assert other.product == "ET-3950" and other.evidence == []


def test_a_reference_does_not_rename_a_product_read_as_something_else():
    from parrot_pipelines.planogram.stages.compare import canonicalise

    read = _ident(product="Duet", text='Portable 80" projection screen DUET', evidence=["box"], reference_id="ref-0002")
    result = canonicalise(read, _models(), _referenced_ctx())
    assert result.product is None and result.evidence == ["box"]


def test_a_facing_without_a_brand_resolves_whatever_brand_the_model_reports():
    facings = [
        {"facing_id": "m1", "shelf_id": "s1", "slot": 1, "product": "ET-2980", "brand": "Acme"},
        {"facing_id": "m2", "shelf_id": "s1", "slot": 2, "product": "Duet"},
    ]
    for facing in facings:
        facing["descriptors"] = {"display_name": facing["product"]}
    definition = load_slots_definition({"shelves": [{"shelf_id": "s1", "shelf_number": 1, "facings": facings}]})
    for brand in ("Acme", "Duet", None):
        read = _ident(brand=brand, product='Portable 80" projection screen Duet')
        assert resolve_identity(read, definition, required_fields=()) == ("Duet", ["Duet"])
    assert resolve_identity(_ident(brand="Other", product="EcoTank ET-2980"), definition, required_fields=()) == (
        None,
        [],
    )


def test_a_product_read_once_too_often_is_withdrawn_not_reported_as_a_mismatch():
    from parrot_pipelines.planogram.comparison.registration import ImageRegistration
    from parrot_pipelines.planogram.stages.compare import SURPLUS_EVIDENCE, _demote_surplus_identities

    definition = _models()  # m1 ET-2980, m2 ET-3950, m3 ET-2980 Pro
    idents = [
        _ident(shape_id="a", product="ET-2980"),
        _ident(shape_id="b", product="ET-2980"),
        _ident(shape_id="c", product="ET-2980 Pro"),
    ]
    registration = ImageRegistration(image_id="img0", assignments={"a": "m1", "b": "m2", "c": "m3"})
    kept, demoted, other = _demote_surplus_identities(idents, registration, definition)
    assert kept.product == "ET-2980" and other.product == "ET-2980 Pro"
    assert demoted.product is None and demoted.descriptors["candidates"] == ["ET-2980"]
    assert demoted.evidence == [SURPLUS_EVIDENCE]
    # With its own facing unmatched the same claim stands: the product may really be misplaced.
    moved = ImageRegistration(image_id="img0", assignments={"b": "m2", "c": "m3"})
    assert _demote_surplus_identities(idents, moved, definition)[1].product == "ET-2980"
