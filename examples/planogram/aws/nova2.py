"""Identify planogram slot contents with Amazon Nova 2 Lite (FEAT-592).

Feeds real Stage-1 OpenCV boxes to Nova through the existing planogram VisionAdapter
and writes flat {bbox, brand, product, occupancy} JSON plus an annotated image.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.contracts import (
    IdentificationResponse,
    ObservationSource,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.identification.vision import VisionAdapter
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, propose_shapes
from parrot_pipelines.planogram.perception.executor import CpuExecutor
from parrot_pipelines.planogram.perception.membership import assign_membership
from parrot_pipelines.planogram.perception.ocr import OcrReader, read_crop
from parrot_pipelines.planogram.perception.rows import group_rows
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots, candidate_shape_id

from identify import FlatDetection, RunStats, flatten, identify_strips_closed_set
from nova_vision import NovaVisionClient
from prompt import NOVA_PROMPT_VERSION, load_planogram_vocabulary

logger = logging.getLogger("nova2")

DEFAULT_MODEL = "nova-2-lite"
DEFAULT_REGION_PREFIX = "us"


async def perceive(image_bgr: np.ndarray, image_id: str, executor: CpuExecutor) -> PerceptionResult:
    """Stage-1 perception, mirroring types/ink_wall.py:181-214 (spec §9 S4)."""
    height, width = image_bgr.shape[:2]
    size = (width, height)
    candidates = await executor.run(propose_shapes, image_bgr, [PRICE_TAG_PROFILE])
    rows = group_rows(candidates, width)
    slots = build_slots(
        rows,
        size,
        image_id=image_id,
        rule=AnchorRule.TAG_BELOW_PRODUCT,
        fill_gaps=True,
        untagged_bottom_row=True,
    )
    position = {
        slot.anchor_shape_id: (slot.row_index, slot.slot_index) for slot in slots if slot.anchor_shape_id is not None
    }
    shapes: List[Shape] = []
    for candidate in candidates:
        shape_id = candidate_shape_id(image_id, candidate)
        row_index, slot_index = position.get(shape_id, (None, None))
        shapes.append(
            Shape(
                shape_id=shape_id,
                image_id=image_id,
                kind=ShapeKind.PRICE_TAG,
                box=DetectionBox(
                    x1=candidate.x1,
                    y1=candidate.y1,
                    x2=candidate.x2,
                    y2=candidate.y2,
                    confidence=max(0.0, min(1.0, candidate.score)),
                ),
                profile=candidate.profile,
                row_index=row_index,
                slot_index=slot_index,
                source=ObservationSource.CV,
            )
        )

    ocr_available = OcrReader().available
    if ocr_available and shapes:
        crops = [image_bgr[shape.box.y1 : shape.box.y2, shape.box.x1 : shape.box.x2] for shape in shapes]
        ocr_results = await asyncio.gather(*(executor.run(read_crop, crop) for crop in crops))
        shapes = [
            shape.model_copy(update={"ocr_text": text or None, "ocr_confidence": confidence if text else None})
            for shape, (text, confidence) in zip(shapes, ocr_results, strict=True)
        ]

    shapes = assign_membership(shapes, [], size)
    return PerceptionResult(
        image_id=image_id,
        image_size=size,
        shapes=shapes,
        slots=slots,
        zones=[],
        row_count=len(rows),
        detection_source=ObservationSource.CV.value,
        ocr_available=ocr_available,
        errors=[],
    )


def load_perception(path: Path, image_bgr: np.ndarray) -> PerceptionResult:
    """Deserialize a --boxes override and fail fast when it does not match the image.

    Raises:
        ValueError: image_size differs from the decoded image's (width, height), or a
            box falls outside the image, or a slot's anchor_shape_id names no shape.
    """
    perception = PerceptionResult.model_validate_json(Path(path).read_text(encoding="utf-8"))
    height, width = image_bgr.shape[:2]
    if tuple(perception.image_size) != (width, height):
        raise ValueError(
            f"{path}: image_size {tuple(perception.image_size)} does not match the "
            f"image ({width}, {height}) - the override is stale"
        )

    def validate_box(owner: str, box: DetectionBox) -> None:
        if not (0 <= box.x1 < box.x2 <= width and 0 <= box.y1 < box.y2 <= height):
            raise ValueError(
                f"{path}: {owner} box ({box.x1}, {box.y1}, {box.x2}, {box.y2}) is outside ({width}, {height})"
            )

    shape_ids = {shape.shape_id for shape in perception.shapes}
    for shape in [*perception.shapes, *perception.zones]:
        validate_box(shape.shape_id, shape.box)
    for slot in perception.slots:
        validate_box(slot.slot_id, slot.box)
        if slot.anchor_shape_id is not None and slot.anchor_shape_id not in shape_ids:
            raise ValueError(f"{path}: {slot.slot_id} anchor_shape_id {slot.anchor_shape_id!r} names no shape")
    return perception


def annotate(image_bgr: np.ndarray, detections: Sequence[FlatDetection]) -> np.ndarray:
    """Draw each box labelled ``brand / product``; empty slots in a distinct colour.

    Picklable and synchronous — runs in the CpuExecutor, never on the event loop.
    """
    canvas = image_bgr.copy()
    colours = {"occupied": (0, 180, 0), "empty": (0, 0, 220), "unknown": (0, 180, 220)}
    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        colour = colours.get(detection.occupancy, colours["unknown"])
        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 2)
        label = " / ".join(value for value in (detection.brand, detection.product) if value)
        if not label:
            label = detection.occupancy
        label_y = min(canvas.shape[0] - 4, y2 + 16)
        cv2.putText(canvas, label, (x1, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1, cv2.LINE_AA)
    return canvas


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for spec §3 Module 5."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path, help="Source planogram image")
    parser.add_argument("--boxes", type=Path, help="Validated PerceptionResult JSON override")
    parser.add_argument("--planogram", required=True, type=Path, help="Planogram JSON for closed-set vocabulary")
    parser.add_argument("--output", required=True, type=Path, help="Directory for generated outputs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Nova model alias")
    parser.add_argument("--region", help="AWS region")
    parser.add_argument("--aws-id", help="AWS credential profile id")
    parser.add_argument("--concurrency", type=int, default=4, help="Maximum concurrent Nova calls")
    parser.add_argument("--no-marks", action="store_true", help="Do not draw Set-of-Marks labels on strips")
    parser.add_argument("--cache-dir", type=Path, help="Vision response cache directory")
    return parser


async def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse flags, run the cycle, write outputs.

    Returns:
        0 success, 1 invalid input, 2 completed with errors.
    """
    args = _build_parser().parse_args(argv)
    if args.concurrency < 1:
        logger.error("--concurrency must be >= 1")
        return 1
    try:
        client = await NovaVisionClient.create(
            aws_id=args.aws_id,
            region=args.region,
            model=args.model,
            region_prefix=DEFAULT_REGION_PREFIX,
        )
    except Exception as exc:  # Credential resolution must precede image decoding.
        logger.error("Unable to initialize Nova credentials: %s", exc)
        return 1

    try:
        async with CpuExecutor(max_workers=args.concurrency) as executor:
            image = await executor.run(cv2.imread, str(args.image))
            if image is None:
                logger.error("Unable to decode image: %s", args.image)
                return 1
            try:
                perception = (
                    load_perception(args.boxes, image) if args.boxes else await perceive(image, "img0", executor)
                )
                vocabulary = load_planogram_vocabulary(args.planogram)
            except (OSError, ValueError) as exc:
                logger.error("Invalid input: %s", exc)
                return 1
            if not perception.slots and not perception.shapes:
                logger.error("No perception targets found in %s", args.image)
                return 1

            vision = VisionAdapter(
                client,
                ResolvedBackend(provider="nova", model=client.resolved_model_id, origin="constructor"),
                semaphore=asyncio.Semaphore(args.concurrency),
                cache_dir=args.cache_dir,
            )
            started = time.monotonic()
            result, stats = await identify_strips_closed_set(
                image,
                perception,
                vision,
                vocabulary,
                executor=executor,
                schema_instruction=NovaVisionClient._schema_instruction(IdentificationResponse),
                marks=not args.no_marks,
            )
            stats.wall_seconds = time.monotonic() - started
            rows = flatten(result, perception)
            args.output.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                (args.output / "detections.json").write_text,
                json.dumps([row.model_dump(mode="json") for row in rows], indent=2, sort_keys=True),
                encoding="utf-8",
            )
            annotated = await executor.run(annotate, image, rows)
            await executor.run(cv2.imwrite, str(args.output / "annotated.jpg"), annotated)
            run_payload = {
                "model": client.resolved_model_id,
                "region": client.resolved_region,
                "prompt_version": NOVA_PROMPT_VERSION,
                "target_count": len(perception.slots) or len(perception.shapes),
                **stats.model_dump(),
            }
            await asyncio.to_thread(
                (args.output / "run.json").write_text,
                json.dumps(run_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return 2 if result.errors else 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
