"""Shared deterministic comparison stage for planogram observations."""

from __future__ import annotations

import logging
from typing import List, Sequence

from parrot.models.detections import PlanogramDescription
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition
from parrot_pipelines.planogram.comparison.identity import names_product, resolve_identity
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration, register_image
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    Shape,
    Slot,
)

logger = logging.getLogger(__name__)


REFERENCE_EVIDENCE_PREFIX = "reference | "
TEXT_EVIDENCE_PREFIX = "text | "


def _reference_product(
    identification: Identification, definition: SlotsDefinition, ctx: CycleContext, candidates: Sequence[str]
) -> tuple[str | None, str | None]:
    """Catalogue id of the reference image the model matched, when it settles an unread identity.

    The catalogue key of the matched reference is resolved like a read name. A reference never
    contradicts printed text: with text candidates it may only pick one of them.

    Returns:
        ``(product, catalogue key)``, or ``(None, None)`` when the reference settles nothing.
    """
    if identification.uncertain or not identification.reference_id:
        return None, None
    key = next((ref.catalog_key for ref in ctx.reference_bank if ref.label == identification.reference_id), None)
    if not key:
        return None, None
    product, _ = resolve_identity(
        Identification(shape_id=identification.shape_id, product=key, brand=identification.brand),
        definition,
        required_fields=(),
    )
    if product is None or (candidates and product not in candidates):
        return None, None
    return product, key


def canonicalise(identification: Identification, definition: SlotsDefinition, ctx: CycleContext) -> Identification:
    """Canonicalize a read to one catalogue id, or retain unresolved candidates.

    Printed text decides first; a matched reference image decides only what the text left open.
    """
    if not identification.product and not identification.text and not identification.reference_id:
        return identification
    by_id = {facing.product.casefold().strip(): facing.product for facing in definition.all_facings() if facing.product}
    product = by_id.get((identification.product or "").casefold().strip())
    if product is None:
        layout = ctx.layout
        vocabulary = getattr(layout, "descriptor_fields", ("family", "colors", "pack", "xl"))
        required_fields = getattr(layout, "required_descriptor_fields", ("family", "xl"))
        product, candidates = resolve_identity(
            identification,
            definition,
            vocabulary=vocabulary,
            required_fields=required_fields,
        )
        if product is None:
            product, key = _reference_product(identification, definition, ctx, candidates)
            if product is not None:
                evidence = [
                    *identification.evidence,
                    f"{REFERENCE_EVIDENCE_PREFIX}{identification.reference_id} | {key}",
                ]
                return identification.model_copy(update={"product": product, "evidence": evidence})
            descriptors = dict(identification.descriptors)
            descriptors["candidates"] = candidates
            return identification.model_copy(update={"product": None, "descriptors": descriptors})
    if not identification.evidence and names_product(identification.text, product):
        # Printed text that names the product is crop-tied evidence even when the model listed none.
        return identification.model_copy(
            update={"product": product, "evidence": [f"{TEXT_EVIDENCE_PREFIX}{identification.text}"]}
        )
    if not identification.evidence:
        # So is the reference image the model matched, when it shows that same product.
        matched, key = _reference_product(identification, definition, ctx, [product])
        if matched == product:
            evidence = [f"{REFERENCE_EVIDENCE_PREFIX}{identification.reference_id} | {key}"]
            return identification.model_copy(update={"product": product, "evidence": evidence})
    return identification.model_copy(update={"product": product})


def registrable_slots(
    perception: PerceptionResult, added: Sequence[Shape], idents: Sequence[Identification], ctx: CycleContext
) -> List[Slot]:
    """Return on-fixture slots in rows carrying reliable evidence."""
    slots = list(perception.slots)
    on_shapes = {
        shape.shape_id for shape in [*perception.shapes, *added] if shape.membership == FixtureMembership.ON_FIXTURE
    }
    on_rows = {slot.row_index for slot in slots if slot.anchor_shape_id in on_shapes}
    last_row = max(on_rows) if on_rows else None
    bottom_row = bool(getattr(ctx.layout, "untagged_bottom_row", False))

    def is_on_fixture(slot: Slot) -> bool:
        if slot.anchor_shape_id:
            return slot.anchor_shape_id in on_shapes
        return slot.row_index in on_rows or (bottom_row and last_row is not None and slot.row_index == last_row + 1)

    kept = [slot for slot in slots if is_on_fixture(slot)]
    reliable = {
        identification.shape_id
        for identification in idents
        if identification.image_id == perception.image_id
        and not identification.uncertain
        and (identification.occupancy in ("occupied", "empty") or identification.product or identification.brand)
    }
    evidence_rows = {
        slot.row_index
        for slot in kept
        if slot.slot_id in reliable or (slot.anchor_shape_id is not None and slot.anchor_shape_id in reliable)
    }
    return [slot for slot in kept if slot.row_index in evidence_rows]


def compare_observations(
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    ctx: CycleContext,
    description: PlanogramDescription,
) -> ComparisonResult:
    """Canonicalize, register, merge, evaluate, score, summarize, and project observations."""
    definition = ctx.definition
    if definition is None:
        raise ValueError("compare_observations requires a slots definition")
    by_image = {result.image_id: result for result in identifications}
    canonical: List[Identification] = []
    registrations: List[ImageRegistration] = []
    for perception in perceptions:
        result = by_image.get(perception.image_id)
        raw = [
            identification
            for identification in (result.identifications if result else [])
            if identification.image_id in (None, perception.image_id)
        ]
        image_idents = [
            canonicalise(identification, definition, ctx).model_copy(update={"image_id": perception.image_id})
            for identification in raw
        ]
        slots = registrable_slots(perception, result.added if result else [], image_idents, ctx)
        registrations.append(register_image(perception.image_id, slots, image_idents, definition))
        canonical.extend(image_idents)
    positions = merge_positions(definition, registrations, canonical, ctx.credit_policy)
    outcomes = evaluate_rules(perceptions, identifications, registrations, ctx)
    shelves = score_shelves(positions, definition, ctx.bindings, outcomes, description, ctx.credit_policy)
    comparison = summarize(shelves, positions, definition, ctx.evidence_weights)
    comparison = comparison.model_copy(
        update={"position_results": positions, "shelf_scores": shelves, "errors": list(ctx.errors)}
    )
    return finalize_comparison(comparison, project_compliance(shelves, positions, definition, description))
