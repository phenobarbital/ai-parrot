"""Report artefacts for the planogram compliance check (FEAT-565, spec §3 Module 11).

Synchronous, cv2-only. The pipeline calls :func:`write_report` through ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .models import Box, ComplianceReport, PositionResult, Settings, SlotObservation

logger = logging.getLogger(__name__)

# BGR. One entry per PositionStatus literal + "unregistered" (slot with no planogram facing).
STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "match": (0, 170, 0),
    "misplaced": (0, 200, 255),
    "variant_unresolved": (0, 140, 255),
    "mismatch": (0, 0, 220),
    "empty": (200, 0, 200),
    "inferred_present": (220, 160, 0),
    "occupied_unassigned": (160, 160, 0),
    "conflict": (0, 0, 120),
    "not_assessed": (128, 128, 128),
    "not_visible": (80, 80, 80),
    "unregistered": (200, 200, 200),
}


def _sha256_file(path: Path) -> str:
    """Return the hex sha256 of a file read in binary mode."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip(box: Box, width: int, height: int) -> Box | None:
    """Clip ``box`` to the image; return ``None`` when nothing is left."""
    x1, y1, x2, y2 = box
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def annotate(image: np.ndarray, observations: list[SlotObservation], positions: list[PositionResult]) -> np.ndarray:
    """Draw slot/tag boxes coloured by position status on a COPY of ``image``.

    Args:
        image: BGR image in original resolution.
        observations: Observations of THIS image only (caller filters by ``slot.image_id``).
        positions: All position results (looked up by ``facing.facing_id``).

    Returns:
        A new annotated BGR array with the same shape as ``image``.
    """
    overlay = image.copy()
    height, width = overlay.shape[:2]
    thickness = max(2, round(width / 800))  # idiom verified: detect_price_labels.py:159
    font_scale = width / 3000  # idiom verified: detect_price_labels.py:161
    by_facing = {p.facing.facing_id: p for p in positions}
    for obs in observations:
        position = by_facing.get(obs.facing_id) if obs.facing_id else None
        status = position.status if position else "unregistered"
        color = STATUS_COLORS[status]
        slot_box = _clip(obs.slot.box, width, height)
        if slot_box is None:
            continue
        x1, y1, x2, y2 = slot_box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness)
        label = f"{position.facing.shelf}:{position.facing.slot} {status}" if position else "unregistered"
        cv2.putText(
            overlay,
            label,
            (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            max(1, round(width / 1000)),
        )
        if obs.slot.tag_box is not None:
            tag_box = _clip(obs.slot.tag_box, width, height)
            if tag_box is not None:
                tx1, ty1, tx2, ty2 = tag_box
                cv2.rectangle(overlay, (tx1, ty1), (tx2, ty2), color, max(1, thickness - 1))
    return overlay


def _write_image(path: Path, image: np.ndarray) -> None:
    """``cv2.imwrite`` with its boolean result checked (it does not raise on failure)."""
    if not cv2.imwrite(str(path), image):
        raise OSError(f"Cannot write image: {path}")


def _snapshot(report: ComplianceReport, settings: Settings, prompt_versions: dict[str, str]) -> dict[str, Any]:
    """Build the ``run.snapshot.json`` payload (settings, models, prompt versions, input hashes)."""
    return {
        "settings": settings.model_dump(mode="json"),
        "prompt_versions": prompt_versions,
        "llm": report.run.llm,
        "ocr_llm": report.run.ocr_llm,
        "inputs": {
            "images": {info.image_id: info.sha256 for info in report.images},
            "planogram": _sha256_file(Path(settings.planogram)),
            "catalog": _sha256_file(Path(settings.catalog)),
            "prices": _sha256_file(Path(settings.prices)) if settings.prices else None,
        },
    }


def write_report(
    report: ComplianceReport,
    images: dict[str, np.ndarray],
    settings: Settings,
    prompt_versions: dict[str, str],
) -> Path:
    """Write every artefact of one run into a NEW directory.

    Args:
        report: The finished report.
        images: ``image_id`` → decoded BGR image (original resolution).
        settings: Run settings; ``settings.output`` is the directory to create.
        prompt_versions: Stage name → prompt version string, recorded in the snapshot.

    Returns:
        Path of the written ``compliance.json``.

    Raises:
        FileExistsError: ``settings.output`` already exists (nothing is written).
        OSError: An image could not be encoded/written.
    """
    output = Path(settings.output)
    output.mkdir(parents=True, exist_ok=False)  # FileExistsError BEFORE any write — spec §5
    (output / "slots").mkdir()
    (output / "tags").mkdir()
    compliance_path = output / "compliance.json"
    compliance_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    for image_id, image in images.items():
        own = [obs for obs in report.slots if obs.slot.image_id == image_id]
        _write_image(output / f"annotated_{image_id}.jpg", annotate(image, own, report.positions))
        height, width = image.shape[:2]
        for obs in own:
            slot_box = _clip(obs.slot.box, width, height)
            if slot_box is None:
                logger.debug("Slot %s box clips to nothing in image %s; skipping crop", obs.slot.slot_id, image_id)
                continue
            sx1, sy1, sx2, sy2 = slot_box
            _write_image(output / "slots" / f"{obs.slot.slot_id}.png", image[sy1:sy2, sx1:sx2])
            if obs.slot.tag_box is not None and obs.slot.tag_id is not None:
                tag_box = _clip(obs.slot.tag_box, width, height)
                if tag_box is None:
                    logger.debug("Tag %s box clips to nothing in image %s; skipping crop", obs.slot.tag_id, image_id)
                    continue
                tx1, ty1, tx2, ty2 = tag_box
                _write_image(output / "tags" / f"{obs.slot.tag_id}.png", image[ty1:ty2, tx1:tx2])
    (output / "run.snapshot.json").write_text(
        json.dumps(_snapshot(report, settings, prompt_versions), indent=2), encoding="utf-8"
    )
    logger.info("Report written to %s", output)
    return compliance_path
