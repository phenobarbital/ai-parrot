"""Stage 2 — structured-input / structured-output identification (full image or Set-of-Marks strips)."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type, Union

import cv2
import numpy as np
from pydantic import BaseModel, Field, create_model

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import Descriptors
from parrot_pipelines.planogram.contracts import (
    AddedShape,
    CycleContext,
    Identification,
    IdentificationResponse,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.grid.merger import _compute_iou
from parrot_pipelines.planogram.identification.references import select_references
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes
from parrot_pipelines.planogram.perception.slots import from_strip_norm, strip_box, to_strip_norm

logger = logging.getLogger(__name__)

IDENTIFY_PROMPT_VERSION: str = "identify-v2-ocr"
IDENTIFY_STAGE: str = "identify"
DUPLICATE_IOU: float = 0.5
SLOT_CROP_PAD: float = 0.08
PixelBox = Tuple[int, int, int, int]
Target = Union[Slot, Shape]
_CallResult = Tuple[List[Identification], List[Shape], List[str]]

_MARK_COLOUR = (0, 255, 0)
_LABEL_BG = (0, 0, 0)
_LABEL_FG = (255, 255, 255)
#: Mark label height as a fraction of the labelled box height, clamped to [min, max] pixels.
_MARK_LABEL_RATIO = 0.12
_MARK_MIN_LABEL_PX = 11  # the pre-scaling size (font scale 0.5)
_MARK_MAX_LABEL_PX = 64
_HERSHEY_CAP_HEIGHT_PX = 22  # cv2.FONT_HERSHEY_SIMPLEX digit height at font scale 1.0
_EMPTY_IDENTITY_TOKENS = frozenset({"", "none", "null", "unknown", "n/a", "na", "empty", "empty slot"})


def _target_id(target: Target) -> str:
    """Id the LLM must echo back: ``slot_id`` for slots, ``shape_id`` for shapes."""
    return target.slot_id if isinstance(target, Slot) else target.shape_id


def _order_key(target: Target) -> Tuple[int, int, int, str]:
    """Deterministic order: row, slot index, x, id."""
    row = target.row_index if target.row_index is not None else 1_000_000
    index = target.slot_index if target.slot_index is not None else 1_000_000
    return row, index, target.box.x1, _target_id(target)


def _targets(perception: PerceptionResult, *, include_zones: bool = False) -> List[Target]:
    """Slots or usable shapes, with profile-cycle zones appended once when requested."""
    targets: List[Target] = list(perception.slots) if perception.slots else list(usable_shapes(perception.shapes))
    if include_zones:
        if not perception.slots:
            targets = [target for target in targets if target.kind != ShapeKind.ZONE]
        target_ids = {_target_id(target) for target in targets}
        targets.extend(zone for zone in perception.zones if zone.shape_id not in target_ids)
    return sorted(targets, key=_order_key)


def _include_zones(ctx: CycleContext) -> bool:
    """Whether the profile-driven cycle makes zones identification targets."""
    return ctx.layout is not None


def _plan_chunks(targets: Sequence[Any], substrip_max_slots: int) -> List[List[Any]]:
    """Group targets by row_index (top→bottom); split rows above the cap into balanced contiguous chunks.

    Args:
        targets: Slots or shapes.
        substrip_max_slots: Maximum targets per call.

    Returns:
        Calls in row order, each a contiguous, left→right chunk.
    """
    if not targets:
        return []
    cap = max(1, substrip_max_slots)
    rows: Dict[int, List[Any]] = {}
    for target in targets:
        row = target.row_index if target.row_index is not None else -1
        rows.setdefault(row, []).append(target)
    chunks: List[List[Any]] = []
    for row in sorted(rows):
        members = sorted(rows[row], key=_order_key)
        n_chunks = math.ceil(len(members) / cap)
        size = math.ceil(len(members) / n_chunks)
        chunks.extend(members[i : i + size] for i in range(0, len(members), size))
    return chunks


def _mark_style(box_height: int) -> Tuple[float, int, int]:
    """Scale the mark label with the box it labels so it survives the provider's downscaling.

    A fixed 0.5 font scale (about 10 px on a 1400-px strip) was illegible to Nova 2 Lite, which then
    permuted answers across neighbouring areas. The label is sized to a fraction of the box height,
    clamped so small boxes keep the old size and huge boxes do not get billboards.

    Args:
        box_height: Height of the marked box, in strip pixels.

    Returns:
        ``(font_scale, text_thickness, outline_thickness)``.
    """
    target = max(_MARK_MIN_LABEL_PX, min(_MARK_MAX_LABEL_PX, round(box_height * _MARK_LABEL_RATIO)))
    font_scale = target / _HERSHEY_CAP_HEIGHT_PX
    text_thickness = max(1, round(font_scale * 2))
    outline_thickness = max(2, round(font_scale * 2))
    return font_scale, text_thickness, outline_thickness


def render_marked_strip(image: np.ndarray, strip: PixelBox, marks: List[Tuple[int, PixelBox]]) -> bytes:
    """Crop ``strip`` and draw a numbered outline per mark; PNG bytes. Picklable — runs in the CPU executor.

    An empty ``marks`` list yields the plain crop. Labels are drawn at the BOTTOM edge of each box so the
    product face is never covered, and are sized relative to the box (see ``_mark_style``) so they stay
    legible after the vision provider downscales the strip.

    Args:
        image: Full-resolution BGR image.
        strip: ``(x1, y1, x2, y2)`` crop in source pixels.
        marks: ``(number, (x1, y1, x2, y2))`` in source pixels.

    Returns:
        PNG bytes of the (marked) crop.
    """
    x1, y1, x2, y2 = strip
    crop = image[y1:y2, x1:x2].copy()
    height = crop.shape[0]
    for number, (bx1, by1, bx2, by2) in marks:
        cx1, cy1, cx2, cy2 = bx1 - x1, by1 - y1, bx2 - x1, by2 - y1
        font_scale, text_thickness, outline = _mark_style(cy2 - cy1)
        cv2.rectangle(crop, (cx1, cy1), (cx2, cy2), _MARK_COLOUR, outline)
        text = str(number)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
        pad = max(2, th // 4)
        tx = cx1 + max(0, (cx2 - cx1 - tw) // 2)
        ty = min(max(cy2 - outline - pad, th + pad), height - pad - 1)
        cv2.rectangle(crop, (tx - pad, ty - th - pad), (tx + tw + pad, ty + pad), _LABEL_BG, -1)
        cv2.rectangle(crop, (tx - pad, ty - th - pad), (tx + tw + pad, ty + pad), _MARK_COLOUR, max(1, outline // 2))
        cv2.putText(crop, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, _LABEL_FG, text_thickness, cv2.LINE_AA)
    return encode_png(crop)


def _without_reference_id() -> Type[BaseModel]:
    """``IdentificationResponse`` whose area entries have no ``reference_id`` field.

    A model fills every field its response schema offers, so a call that attaches no reference image must
    not offer the field at all.
    """
    fields: Dict[str, Any] = {
        name: (field.annotation, field) for name, field in Identification.model_fields.items() if name != "reference_id"
    }
    entry = create_model("UnreferencedIdentification", **fields)
    return create_model(
        "UnreferencedIdentificationResponse",
        existing_identifications=(List[entry], Field(default_factory=list)),  # type: ignore[valid-type]
        added_shapes=(List[AddedShape], Field(default_factory=list)),
    )


#: Response schema of a call without reference images.
UNREFERENCED_RESPONSE: Type[BaseModel] = _without_reference_id()


async def _ask_identify(
    ctx: CycleContext, prompt: str, images: Sequence[bytes], referenced: bool
) -> IdentificationResponse:
    """One identify call; ``reference_id`` is part of the schema only when the call carries references."""
    schema = IdentificationResponse if referenced else UNREFERENCED_RESPONSE
    answer = await ctx.vision.ask(prompt, images, schema, stage=IDENTIFY_STAGE, prompt_version=IDENTIFY_PROMPT_VERSION)
    if isinstance(answer, IdentificationResponse):
        return answer
    return IdentificationResponse.model_validate(answer.model_dump())


def build_identify_prompt(
    targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str], *, reference_labels: Sequence[str] = ()
) -> str:
    """Build provider-neutral identify-v2-ocr instructions and own-area OCR/confidence.

    Args:
        targets: ``{"id", "mark", "box_2d", "ocr_text"[, "ocr_confidence", "tag_text"]}`` per area.
        vocabulary: Descriptor field names to report (names only, never values).
        reference_labels: Opaque labels of reference images attached after the main image.

    Returns:
        Prompt text that never names placement expectations or catalogue keys.
    """
    areas = json.dumps(list(targets), separators=(",", ":"), ensure_ascii=False)
    fields = ", ".join(vocabulary) if vocabulary else "(none)"
    prompt = (
        "You are analysing a retail shelf image. Below is a list of numbered AREAS in this image; each has an "
        "id, an optional mark (the number drawn on its outline), a box_2d as [ymin, xmin, ymax, xmax] "
        "normalised to 0-1000 relative to the image you receive, and ocr_text: the text a local OCR read inside "
        "that area (may be empty, partial or slightly wrong), with ocr_confidence when available.\n\n"
        "INSTRUCTIONS:\n"
        "- Judge each area independently and ONLY from what is visible inside its own box. Adjacent areas often "
        "differ. Never copy an answer from one area to another and never describe something outside an area "
        "under that area's id.\n"
        "- Return exactly one entry per area in existing_identifications, with shape_id equal to the area id.\n"
        "- occupancy is 'occupied' when a package or product body is visible, including a box seen from its "
        "side, tilted, dark, or with glare. Only shelf backing, a hook, divider, price tag or fixture parts is "
        "'empty'. Use 'unknown' only when the box itself is unreadable.\n"
        "- ocr_text is NOT evidence of emptiness. Read the printed product code into text and product, correcting "
        "ocr_text when needed. Brand comes from the visible logo.\n"
        "- For each area report these descriptor fields inside descriptors: "
        f"{fields}.\n"
        "- raw_confidence 0..1 applies to empty areas too. evidence: one short sentence saying what you saw.\n"
        "- Use null when something is not legible — do not guess.\n"
        "- If you see a product that no area covers, report it ONLY under added_shapes with box_norm "
        "[ymin, xmin, ymax, xmax] in 0-1000 relative to the image you receive, plus product, brand, text, "
        "descriptors, raw_confidence and evidence.\n\n"
    )
    if reference_labels:
        labels = ", ".join(reference_labels)
        prompt += (
            f"The attached reference images, in order, have opaque labels: {labels}. They only show what some "
            "catalogue items look like, not what belongs in any area. Set reference_id to a matching label or "
            "null; printed text wins over a reference.\n\n"
        )
    return f"{prompt}AREAS: {areas}"


def _uncertain(target_id: str, image_id: str, source: ObservationSource, reason: str) -> Identification:
    """Placeholder identification for a target the model did not (usably) assess."""
    return Identification(
        shape_id=target_id,
        image_id=image_id,
        product=None,
        raw_confidence=0.0,
        evidence=[reason],
        source=source,
        uncertain=True,
    )


def _source_for(perception: PerceptionResult) -> ObservationSource:
    """Identification source: llm when perception itself came from the LLM detector, else cv."""
    return ObservationSource.LLM if perception.detection_source == "llm" else ObservationSource.CV


def _inside(box: DetectionBox, strip: DetectionBox) -> bool:
    """True when the box centre lies inside the strip."""
    cx, cy = (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2
    return strip.x1 <= cx <= strip.x2 and strip.y1 <= cy <= strip.y2


def _has_identity_evidence(identification: Identification) -> bool:
    """Whether structured identity fields prove that a product is present.

    Free-form evidence is deliberately excluded: only explicit product, brand, text, or descriptor values
    may resolve an omitted/defaulted occupancy value.
    """

    def meaningful(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().casefold() not in _EMPTY_IDENTITY_TOKENS
        if isinstance(value, dict):
            return any(meaningful(item) for item in value.values())
        if isinstance(value, (list, tuple, set, frozenset)):
            return any(meaningful(item) for item in value)
        return bool(value)

    values = (identification.product, identification.brand, identification.text, identification.descriptors)
    return any(meaningful(value) for value in values)


def _normalise_occupancy(identification: Identification) -> Identification:
    """Treat explicit identity fields as occupied when the model left occupancy at its default."""

    if identification.occupancy == "unknown" and _has_identity_evidence(identification):
        return identification.model_copy(update={"occupancy": "occupied"})
    return identification


def _validate(
    response: IdentificationResponse,
    perception: PerceptionResult,
    candidates: Sequence[Target],
    *,
    strip: Optional[DetectionBox],
    next_shape_id: Callable[[], str],
) -> Tuple[List[Identification], List[Shape], List[str]]:
    """Validate a response against an explicit candidate list."""
    width, height = perception.image_size
    frame = strip or DetectionBox(x1=0, y1=0, x2=width, y2=height, confidence=1.0)
    targets = [target for target in candidates if strip is None or _inside(target.box, strip)]
    known = {_target_id(t): t for t in targets}
    source = _source_for(perception)
    errors: List[str] = []

    by_id: Dict[str, Identification] = {}
    for item in response.existing_identifications:
        if item.shape_id not in known:
            errors.append(f"unknown id {item.shape_id}")
            continue
        if item.shape_id in by_id:
            errors.append(f"duplicate id {item.shape_id} (first occurrence kept)")
            continue
        normalised = _normalise_occupancy(item)
        by_id[item.shape_id] = normalised.model_copy(update={"image_id": perception.image_id, "source": source})
    identifications: List[Identification] = []
    for target_id in known:
        identifications.append(
            by_id.get(target_id) or _uncertain(target_id, perception.image_id, source, "missing_in_response")
        )

    accepted: List[Shape] = []
    taken = [t.box for t in targets]
    for index, added in enumerate(response.added_shapes):
        try:
            box = from_strip_norm(added.box_norm, frame)
        except ValueError as exc:
            errors.append(f"added shape #{index} rejected: {exc}")
            continue
        if not (0 <= box.x1 < box.x2 <= width and 0 <= box.y1 < box.y2 <= height):
            errors.append(f"added shape #{index} rejected: outside the image")
            continue
        box = box.model_copy(update={"confidence": added.raw_confidence})
        if any(_compute_iou(box, other) > DUPLICATE_IOU for other in taken):
            errors.append(f"added shape #{index} rejected: duplicates an existing area")
            continue
        shape_id = next_shape_id()
        shape = Shape(
            shape_id=shape_id,
            image_id=perception.image_id,
            kind=added.kind,
            box=box,
            profile="llm_added",
            ocr_text=added.text,
            source=ObservationSource.LLM_ADDED,
        )
        accepted.append(shape)
        taken.append(box)
        identifications.append(
            Identification(
                shape_id=shape_id,
                image_id=perception.image_id,
                product=added.product,
                brand=added.brand,
                text=added.text,
                descriptors=dict(added.descriptors),
                occupancy="occupied",
                raw_confidence=added.raw_confidence,
                evidence=list(added.evidence),
                source=ObservationSource.LLM_ADDED,
            )
        )
    return identifications, accepted, errors


def validate_response(
    response: IdentificationResponse,
    perception: PerceptionResult,
    *,
    strip: Optional[DetectionBox],
    next_shape_id: Callable[[], str],
) -> Tuple[List[Identification], List[Shape], List[str]]:
    """Validate a response using legacy targets and preserve the public API."""
    return _validate(response, perception, _targets(perception), strip=strip, next_shape_id=next_shape_id)


def _area(target: Target, strip: DetectionBox, mark: Optional[int], perception: PerceptionResult) -> Dict[str, Any]:
    """Structured-input entry of one target; own-box OCR wins when available."""
    if perception.ocr_readings:
        own = perception.ocr_readings.get(_target_id(target))
        area: Dict[str, Any] = {
            "id": _target_id(target),
            "mark": mark,
            "box_2d": to_strip_norm(target.box, strip),
            "ocr_text": (own.text or None) if own else None,
            "ocr_confidence": own.confidence if own and own.text else None,
        }
        if isinstance(target, Slot) and target.anchor_shape_id:
            anchor_reading = perception.ocr_readings.get(target.anchor_shape_id)
            anchor = next((shape for shape in perception.shapes if shape.shape_id == target.anchor_shape_id), None)
            area["tag_text"] = (
                (anchor_reading.text or None) if anchor_reading else (anchor.ocr_text if anchor else None)
            )
        return area
    ocr_text = None
    if isinstance(target, Shape):
        ocr_text = target.ocr_text
    elif target.anchor_shape_id:
        anchor = next((s for s in perception.shapes if s.shape_id == target.anchor_shape_id), None)
        ocr_text = anchor.ocr_text if anchor is not None else None
    return {"id": _target_id(target), "mark": mark, "box_2d": to_strip_norm(target.box, strip), "ocr_text": ocr_text}


def _as_tuple(box: DetectionBox) -> PixelBox:
    """``DetectionBox`` → picklable pixel tuple."""
    return box.x1, box.y1, box.x2, box.y2


async def _run_call(
    image: np.ndarray,
    targets: Sequence[Any],
    strip: DetectionBox,
    perception: PerceptionResult,
    ctx: CycleContext,
    *,
    vocabulary: Sequence[str],
    marks: bool,
    next_shape_id: Callable[[], str],
    full_image: bool = False,
    include_zones: bool = False,
) -> _CallResult:
    """One LLM call for targets plus selected references, isolating vision failures."""
    mark_list = [(n, _as_tuple(t.box)) for n, t in enumerate(targets, start=1)] if marks else []
    areas = [_area(t, strip, n if marks else None, perception) for n, t in enumerate(targets, start=1)]
    target_ids = {_target_id(target) for target in targets}
    call_readings = {key: value for key, value in perception.ocr_readings.items() if key in target_ids}
    policy = ctx.layout.references if ctx.layout is not None else None
    references, diagnostics = select_references(ctx.reference_bank, call_readings, policy) if policy else ([], [])
    labels = [reference.label for reference in references]
    prompt = build_identify_prompt(areas, vocabulary, reference_labels=labels)
    errors = []
    for diagnostic in diagnostics:
        if diagnostic.startswith("references: selected"):
            logger.info("%s: %s", perception.image_id, diagnostic)
        else:
            errors.append(f"{perception.image_id}: {diagnostic}")
    retry_error: Optional[str] = None
    try:
        png = await ctx.executor.run(render_marked_strip, image, _as_tuple(strip), mark_list)
        images = [png, *(reference.image for reference in references)]
        answer = await _ask_identify(ctx, prompt, images, bool(labels))
    except VisionError as exc:
        source = _source_for(perception)
        message = f"identify_failed: {exc}"
        uncertain = [_uncertain(_target_id(t), perception.image_id, source, message) for t in targets]
        return uncertain, [], [*errors, f"{perception.image_id}: {message}"]
    requested_ids = target_ids
    returned_ids = {item.shape_id for item in answer.existing_identifications}
    missing_ids = sorted(requested_ids - returned_ids)
    if missing_ids:
        repair_prompt = (
            f"{prompt}\n\nCORRECTION: Your previous response omitted these required area ids: "
            f"{json.dumps(missing_ids)}. Return a complete replacement response with exactly one "
            "existing_identifications entry for every requested area."
        )
        try:
            answer = await _ask_identify(ctx, repair_prompt, images, bool(labels))
        except VisionError as exc:
            retry_error = f"{perception.image_id}: identify_incomplete_retry_failed: {exc}"
    invalid_references = [
        item
        for item in answer.existing_identifications
        if item.reference_id is not None and item.reference_id not in labels
    ]
    if invalid_references:
        answer = answer.model_copy(
            update={
                "existing_identifications": [
                    item.model_copy(update={"reference_id": None}) if item in invalid_references else item
                    for item in answer.existing_identifications
                ]
            }
        )
        errors.extend(
            f"{perception.image_id}: unknown reference_id {item.reference_id} for {item.shape_id}"
            for item in invalid_references
        )
    idents, added, validation_errors = _validate(
        answer,
        perception,
        _targets(perception, include_zones=include_zones),
        strip=None if full_image else strip,
        next_shape_id=next_shape_id,
    )
    errors.extend(validation_errors)
    if retry_error is not None:
        errors.append(retry_error)
    final_ids = {item.shape_id for item in answer.existing_identifications}
    final_missing_ids = sorted(requested_ids - final_ids)
    if final_missing_ids:
        errors.append(f"{perception.image_id}: identify_incomplete: missing {json.dumps(final_missing_ids)}")
    # A padded strip may contain a neighbouring chunk's target: keep only this call's targets (+ additions).
    own = {_target_id(t) for t in targets} | {s.shape_id for s in added}
    return [i for i in idents if i.shape_id in own], added, errors


def _id_allocator(perception: PerceptionResult) -> Callable[[], str]:
    """Pipeline-owned ids for accepted additions: ``<image_id>:added:<n>``."""
    counter = {"n": 0}

    def allocate() -> str:
        counter["n"] += 1
        return f"{perception.image_id}:added:{counter['n']}"

    return allocate


def _finalise(
    perception: PerceptionResult, ctx: CycleContext, results: Sequence[_CallResult], *, include_zones: bool = False
) -> IdentificationResult:
    """Concatenate call results, revalidate membership of additions, order deterministically, record errors."""
    identifications: List[Identification] = []
    added: List[Shape] = []
    errors: List[str] = []
    for idents, shapes, errs in results:
        identifications.extend(idents)
        added.extend(shapes)
        errors.extend(errs)
    if added:
        relabelled = assign_membership([*perception.shapes, *added], perception.zones, perception.image_size)
        membership = {s.shape_id: s for s in relabelled}
        added = [
            s.model_copy(
                update={
                    "membership": membership[s.shape_id].membership,
                    "membership_evidence": membership[s.shape_id].membership_evidence,
                }
            )
            for s in added
        ]
    order = {_target_id(t): n for n, t in enumerate(_targets(perception, include_zones=include_zones))}
    added_order = {s.shape_id: n for n, s in enumerate(added)}

    def sort_key(item: Identification) -> Tuple[int, int, str]:
        if item.shape_id in order:
            return 0, order[item.shape_id], ""
        if item.shape_id in added_order:
            return 1, added_order[item.shape_id], ""
        return 2, 0, item.shape_id

    identifications.sort(key=sort_key)
    ctx.errors.extend(errors)
    return IdentificationResult(
        image_id=perception.image_id, identifications=identifications, added=added, errors=errors
    )


def _check_vocabulary(vocabulary: Sequence[str], extra: Sequence[str] = ()) -> None:
    """ValueError when a name is not built in or profile-declared."""
    unknown = [name for name in vocabulary if name not in set(Descriptors.model_fields) | set(extra)]
    if unknown:
        raise ValueError(f"unknown descriptor fields in vocabulary: {unknown}")


async def identify_full_image(
    image: np.ndarray, perception: PerceptionResult, ctx: CycleContext, *, vocabulary: Sequence[str]
) -> IdentificationResult:
    """One call: whole image + stage-1 JSON. Boxes are normalised against the full image.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image.
        ctx: Per-run services (vision adapter, CPU executor, error sink).
        vocabulary: Descriptor fields to report.

    Returns:
        The validated identification result.
    """
    extra = ctx.layout.descriptor_fields if ctx.layout is not None else ()
    _check_vocabulary(vocabulary, extra)
    zones = _include_zones(ctx)
    width, height = perception.image_size
    frame = DetectionBox(x1=0, y1=0, x2=width, y2=height, confidence=1.0)
    targets = _targets(perception, include_zones=zones)
    result = await _run_call(
        image,
        targets,
        frame,
        perception,
        ctx,
        vocabulary=vocabulary,
        marks=False,
        next_shape_id=_id_allocator(perception),
        full_image=True,
        include_zones=zones,
    )
    return _finalise(perception, ctx, [result], include_zones=zones)


async def identify_strips(
    image: np.ndarray,
    perception: PerceptionResult,
    ctx: CycleContext,
    *,
    vocabulary: Sequence[str],
    marks: bool = True,
    substrip_max_slots: int = 8,
) -> IdentificationResult:
    """One call per row (sub-strips above the cap), concurrently; a failed strip is isolated.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image.
        ctx: Per-run services (vision adapter, CPU executor, error sink).
        vocabulary: Descriptor fields to report.
        marks: Draw numbered Set-of-Marks outlines on each strip.
        substrip_max_slots: Maximum targets per call.

    Returns:
        The validated identification result.
    """
    extra = ctx.layout.descriptor_fields if ctx.layout is not None else ()
    _check_vocabulary(vocabulary, extra)
    zones = _include_zones(ctx)
    allocate = _id_allocator(perception)
    chunks = _plan_chunks(_targets(perception, include_zones=zones), substrip_max_slots)
    results = await asyncio.gather(
        *(
            _run_call(
                image,
                chunk,
                strip_box(chunk, perception.image_size),
                perception,
                ctx,
                vocabulary=vocabulary,
                marks=marks,
                next_shape_id=allocate,
                include_zones=zones,
            )
            for chunk in chunks
        )
    )
    return _finalise(perception, ctx, results, include_zones=zones)


async def identify_slots(
    image: np.ndarray,
    perception: PerceptionResult,
    ctx: CycleContext,
    *,
    vocabulary: Sequence[str],
    marks: bool = True,
) -> IdentificationResult:
    """Identify each target in its own padded crop with source-coordinate validation.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image.
        ctx: Per-run services, profile and reference bank.
        vocabulary: Descriptor fields to report.
        marks: Draw the numbered outline on each crop.

    Returns:
        Validated identifications with isolated per-target errors.
    """
    _check_vocabulary(vocabulary, ctx.layout.descriptor_fields if ctx.layout is not None else ())
    zones = _include_zones(ctx)
    allocate = _id_allocator(perception)
    targets = _targets(perception, include_zones=zones)
    results = await asyncio.gather(
        *(
            _run_call(
                image,
                [target],
                strip_box([target], perception.image_size, pad=SLOT_CROP_PAD),
                perception,
                ctx,
                vocabulary=vocabulary,
                marks=marks,
                next_shape_id=allocate,
                include_zones=zones,
            )
            for target in targets
        )
    )
    return _finalise(perception, ctx, results, include_zones=zones)
