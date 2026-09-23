"""Closed-set strip orchestration for Nova (FEAT-592)."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    Identification,
    IdentificationResponse,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    Shape,
    Slot,
)
from parrot_pipelines.planogram.identification.identify import render_marked_strip, validate_response
from parrot_pipelines.planogram.identification.vision import VisionAdapter, VisionError
from parrot_pipelines.planogram.perception.executor import CpuExecutor
from parrot_pipelines.planogram.perception.slots import strip_box, to_strip_norm

from prompt import NOVA_PROMPT_VERSION, NOVA_STAGE, PlanogramVocabulary, build_nova_identify_prompt

logger = logging.getLogger(__name__)

PixelBox = Tuple[int, int, int, int]
Target = Union[Slot, Shape]
SUBSTRIP_MAX_SLOTS: int = 8


class FlatDetection(BaseModel):
    """One row of detections.json. ``bbox`` is always source-image pixels."""

    shape_id: str
    bbox: List[int]
    occupancy: str = "unknown"
    brand: Optional[str] = None
    product: Optional[str] = None
    text: Optional[str] = None
    confidence: float = 0.0
    evidence: Optional[str] = None
    source: str = "cv"
    inferred: bool = False
    uncertain: bool = False


class RunStats(BaseModel):
    """Provider-call accounting — one strip can cost up to three calls."""

    strips: int = 0
    failed_strips: int = 0
    calls: int = 0
    cache_hits: int = 0
    incomplete_retries: int = 0
    image_bytes_sent: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0


def _target_id(target: Target) -> str:
    """Return the provider-facing id for a slot or shape."""
    return target.slot_id if isinstance(target, Slot) else target.shape_id


def _target_order(target: Target) -> Tuple[int, int, int, str]:
    """Return a stable row-major ordering key."""
    row = target.row_index if target.row_index is not None else 1_000_000
    index = target.slot_index if target.slot_index is not None else 1_000_000
    return row, index, target.box.x1, _target_id(target)


def _targets(perception: PerceptionResult) -> List[Target]:
    """Return slots when present, otherwise shapes, in row-major order."""
    targets: List[Target] = list(perception.slots) if perception.slots else list(perception.shapes)
    return sorted(targets, key=_target_order)


def _plan_chunks(targets: Sequence[Target], substrip_max_slots: int) -> List[List[Target]]:
    """Split each row into balanced contiguous chunks in row-major order."""
    cap = max(1, substrip_max_slots)
    rows: Dict[int, List[Target]] = {}
    for target in targets:
        row = target.row_index if target.row_index is not None else -1
        rows.setdefault(row, []).append(target)

    chunks: List[List[Target]] = []
    for row in sorted(rows):
        members = sorted(rows[row], key=_target_order)
        chunk_count = math.ceil(len(members) / cap)
        chunk_size = math.ceil(len(members) / chunk_count)
        chunks.extend(members[index : index + chunk_size] for index in range(0, len(members), chunk_size))
    return chunks


def _as_tuple(box: DetectionBox) -> PixelBox:
    """Convert a detection box to the picklable pixel tuple renderer expects."""
    return box.x1, box.y1, box.x2, box.y2


def _source_for(perception: PerceptionResult) -> ObservationSource:
    """Return the pipeline-owned source for provider identifications."""
    return ObservationSource.LLM if perception.detection_source == "llm" else ObservationSource.CV


def _uncertain(target: Target, perception: PerceptionResult, reason: str) -> Identification:
    """Build a placeholder when the provider cannot assess one target."""
    return Identification(
        shape_id=_target_id(target),
        image_id=perception.image_id,
        raw_confidence=0.0,
        evidence=[reason],
        source=_source_for(perception),
        uncertain=True,
    )


def _target_ocr_text(target: Target) -> str:
    """Return a target's direct OCR text, or an empty string when unavailable."""
    return target.ocr_text or "" if isinstance(target, Shape) else ""


def _id_allocator(perception: PerceptionResult) -> Callable[[], str]:
    """Allocate pipeline-compatible ids for accepted added shapes."""
    counter = 0

    def allocate() -> str:
        nonlocal counter
        counter += 1
        return f"{perception.image_id}:added:{counter}"

    return allocate


async def _run_strip(
    image: np.ndarray,
    targets: Sequence[Target],
    perception: PerceptionResult,
    vision: VisionAdapter,
    vocabulary: PlanogramVocabulary,
    *,
    executor: CpuExecutor,
    schema_instruction: str,
    marks: bool,
    next_shape_id: Callable[[], str],
    stats: RunStats,
) -> Tuple[List[Identification], List[Shape], List[str]]:
    """Run and validate one strip, isolating provider failures to its targets."""
    strip = strip_box(targets, perception.image_size)
    mark_list = [(number, _as_tuple(target.box)) for number, target in enumerate(targets, start=1)] if marks else []
    areas: List[Dict[str, Any]] = [
        {
            "id": _target_id(target),
            "mark": number if marks else None,
            "box_2d": to_strip_norm(target.box, strip),
            "ocr_text": _target_ocr_text(target),
        }
        for number, target in enumerate(targets, start=1)
    ]
    prompt = build_nova_identify_prompt(areas, vocabulary, schema_instruction)
    png = await executor.run(render_marked_strip, image, _as_tuple(strip), mark_list)
    stats.image_bytes_sent += len(png)

    try:
        stats.calls += 1
        answer = await vision.ask(
            prompt,
            [png],
            IdentificationResponse,
            stage=NOVA_STAGE,
            prompt_version=NOVA_PROMPT_VERSION,
        )
    except VisionError as exc:
        stats.failed_strips += 1
        message = f"identify_failed: {exc}"
        return (
            [_uncertain(target, perception, message) for target in targets],
            [],
            [f"{perception.image_id}: {message}"],
        )

    requested_ids = {_target_id(target) for target in targets}
    missing_ids = sorted(requested_ids - {item.shape_id for item in answer.existing_identifications})
    retry_error: Optional[str] = None
    if missing_ids:
        repair_prompt = (
            f"{prompt}\n\nCORRECTION: Your previous response omitted these required area ids: "
            f"{json.dumps(missing_ids)}. Return a complete replacement response with exactly one "
            "existing_identifications entry for every requested area."
        )
        stats.incomplete_retries += 1
        try:
            stats.calls += 1
            answer = await vision.ask(
                repair_prompt,
                [png],
                IdentificationResponse,
                stage=NOVA_STAGE,
                prompt_version=NOVA_PROMPT_VERSION,
            )
        except VisionError as exc:
            retry_error = f"{perception.image_id}: identify_incomplete_retry_failed: {exc}"

    identifications, added, errors = validate_response(answer, perception, strip=strip, next_shape_id=next_shape_id)
    if retry_error is not None:
        errors.append(retry_error)
    final_missing_ids = sorted(requested_ids - {item.shape_id for item in answer.existing_identifications})
    if final_missing_ids:
        errors.append(f"{perception.image_id}: identify_incomplete: missing {json.dumps(final_missing_ids)}")

    own_ids = requested_ids | {shape.shape_id for shape in added}
    return [item for item in identifications if item.shape_id in own_ids], added, errors


async def identify_strips_closed_set(
    image: np.ndarray,
    perception: PerceptionResult,
    vision: VisionAdapter,
    vocabulary: PlanogramVocabulary,
    *,
    executor: CpuExecutor,
    schema_instruction: str,
    marks: bool = True,
    substrip_max_slots: int = SUBSTRIP_MAX_SLOTS,
) -> Tuple[IdentificationResult, RunStats]:
    """Identify row chunks concurrently with a closed-set Nova prompt.

    Returns:
        The validated result for the whole image and the provider-call accounting.
    """
    chunks = _plan_chunks(_targets(perception), substrip_max_slots)
    stats = RunStats(strips=len(chunks))
    allocate = _id_allocator(perception)
    results = await asyncio.gather(
        *(
            _run_strip(
                image,
                chunk,
                perception,
                vision,
                vocabulary,
                executor=executor,
                schema_instruction=schema_instruction,
                marks=marks,
                next_shape_id=allocate,
                stats=stats,
            )
            for chunk in chunks
        )
    )

    identifications: List[Identification] = []
    added: List[Shape] = []
    errors: List[str] = []
    for chunk_identifications, chunk_added, chunk_errors in results:
        identifications.extend(chunk_identifications)
        added.extend(chunk_added)
        errors.extend(chunk_errors)

    # Reconcile against the transport client's own accounting: VisionAdapter.ask()
    # discards NovaAnswer (it returns only the parsed schema) and its response
    # cache short-circuits BEFORE ever calling ask_to_image, so `stats.calls`
    # collected above during the strip loop only counts *attempted* asks, not
    # calls that actually reached Bedrock. `vision.client` (verified public
    # attribute: VisionAdapter.__init__ sets `self.client = client`) is the
    # NovaVisionClient instance itself and is the only place a cache hit is
    # visible (see nova_vision.py NovaVisionClient.calls_made).
    attempted_asks = stats.calls
    stats.calls = getattr(vision.client, "calls_made", attempted_asks)
    stats.cache_hits = max(0, attempted_asks - stats.calls)
    stats.input_tokens = getattr(vision.client, "total_input_tokens", 0)
    stats.output_tokens = getattr(vision.client, "total_output_tokens", 0)

    target_order = {_target_id(target): index for index, target in enumerate(_targets(perception))}
    added_order = {shape.shape_id: index for index, shape in enumerate(added)}
    identifications.sort(
        key=lambda item: (
            0 if item.shape_id in target_order else 1 if item.shape_id in added_order else 2,
            target_order.get(item.shape_id, added_order.get(item.shape_id, 0)),
            item.shape_id,
        )
    )
    return (
        IdentificationResult(
            image_id=perception.image_id,
            identifications=identifications,
            added=added,
            errors=errors,
        ),
        stats,
    )


def flatten(result: IdentificationResult, perception: PerceptionResult) -> List[FlatDetection]:
    """Join identifications back to source-pixel boxes.

    Returns:
        Rows ordered by row then left-to-right; unmatched ids are skipped and logged.
    """
    slots = {slot.slot_id: slot for slot in perception.slots}
    shapes = {shape.shape_id: shape for shape in perception.shapes}
    added = {shape.shape_id: shape for shape in result.added}
    rows: List[Tuple[Tuple[int, int, int, str], FlatDetection]] = []

    for identification in result.identifications:
        slot = slots.get(identification.shape_id)
        shape = added.get(identification.shape_id) or shapes.get(identification.shape_id)
        if slot is not None:
            box = slot.box
            row_index, slot_index, inferred = slot.row_index, slot.slot_index, slot.inferred
            source = "cv"
        elif shape is not None:
            box = shape.box
            row_index = shape.row_index if shape.row_index is not None else 1_000_000
            slot_index = shape.slot_index if shape.slot_index is not None else 1_000_000
            inferred = False
            source = "llm_added" if identification.shape_id in added else "cv"
        else:
            logger.warning("Skipping unmatched identification id: %s", identification.shape_id)
            continue

        rows.append(
            (
                (row_index, slot_index, box.x1, identification.shape_id),
                FlatDetection(
                    shape_id=identification.shape_id,
                    bbox=[box.x1, box.y1, box.x2, box.y2],
                    occupancy=identification.occupancy,
                    brand=identification.brand,
                    product=identification.product,
                    text=identification.text,
                    confidence=identification.raw_confidence,
                    evidence=" ".join(identification.evidence) or None,
                    source=source,
                    inferred=inferred,
                    uncertain=identification.uncertain,
                ),
            )
        )
    return [row for _, row in sorted(rows, key=lambda item: item[0])]
