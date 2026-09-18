"""Pipeline orchestration for the planogram compliance check (FEAT-565, spec §2 stages 1→8)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .detection import detect_tags
from .grid import build_slots, row_pitch
from .identify import IDENTIFY_PROMPT_VERSION, identify_rows
from .models import Catalog, ComplianceReport, ImageInfo, PlanogramRef, PriceReading, RunInfo, Settings, SlotObservation
from .prices import PRICE_PROMPT_VERSION, TagOcr, read_prices
from .reference import load_catalog, load_planogram, load_prices
from .registration import apply_registration, register_image
from .report import write_report
from .scoring import brand_shares, merge_positions, shelf_scores, summarize
from .verify import VERIFY_PROMPT_VERSION, verify_rows
from .vision import VisionBackend

logger = logging.getLogger(__name__)

STANDING_NOTES: tuple[str, ...] = (
    "All planogram mappings are automatic (registration_method=auto_alignment); none was human-reviewed.",
    "Metrics describe model observations; they are not calibrated accuracy estimates.",
    "verified_by_expectation and inferred results count only in the lenient score.",
)


def resolve_verify_pass(setting: bool | None, is_local: bool) -> bool:
    """``None`` → auto (on for cloud, off for local backends); an explicit value always wins."""
    return (not is_local) if setting is None else setting


def effective_concurrency(requested: int, is_local: bool) -> int:
    """Local servers are driven one call at a time (spec §2 CLI: '1 when the provider is a local server')."""
    return 1 if is_local else requested


def absolutize(settings: Settings) -> Settings:
    """Return a copy of ``settings`` whose path fields are absolute.

    MUST run before the first backend is constructed: that is the first ``parrot`` import and
    navconfig ``chdir``s to the repository root (spec §7).
    """
    update: dict[str, Any] = {
        "images": [str(Path(p).expanduser().resolve()) for p in settings.images],
        "planogram": str(Path(settings.planogram).expanduser().resolve()),
        "catalog": str(Path(settings.catalog).expanduser().resolve()),
        "output": str(Path(settings.output).expanduser().resolve()),
        "cache_dir": str(Path(settings.cache_dir).expanduser().resolve()),
    }
    if settings.prices is not None:
        update["prices"] = str(Path(settings.prices).expanduser().resolve())
    return settings.model_copy(update=update)


def _default_backend_factory(llm: str, *, cache_dir: Path, base_url: str | None) -> VisionBackend:
    """Build the real backend (this call performs the first ``parrot`` import)."""
    return VisionBackend(llm, cache_dir=cache_dir, base_url=base_url)


def _read_image(path: Path) -> tuple[np.ndarray, str]:
    """Synchronous: read bytes, hash them, decode to BGR. Raises ``ValueError`` when undecodable."""
    data = path.read_bytes()
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image, hashlib.sha256(data).hexdigest()


async def _process_image(
    image_id: str,
    path: Path,
    *,
    settings: Settings,
    planogram: PlanogramRef,
    catalog: Catalog,
    backend: Any,
    ocr_backend: Any,
    ocr: TagOcr,
    semaphore: asyncio.Semaphore,
    verify_pass: bool,
) -> tuple[ImageInfo, np.ndarray, list[SlotObservation], list[str], list[str]]:
    """Stages 1–7 for one photo.

    Returns:
        (image info, decoded image, observations, errors, notes).
    """
    errors: list[str] = []
    notes: list[str] = []
    image, sha256 = await asyncio.to_thread(_read_image, path)
    height, width = image.shape[:2]
    rows, _unassigned = await asyncio.to_thread(
        detect_tags, image, image_id, work_width=settings.work_width, roi=settings.roi
    )
    info = ImageInfo(
        image_id=image_id,
        path=str(path),
        sha256=sha256,
        width=width,
        height=height,
        tag_rows=len(rows),
        tags=sum(len(r.tags) for r in rows),
        slots=0,
    )
    if not rows:
        logger.warning("%s: no tag rows detected — photo reported unregistered", image_id)
        notes.append(f"{image_id}: no price-tag rows detected; photo is unregistered.")
        return info, image, [], errors, notes
    slots = build_slots(rows, (width, height))
    info.slots = len(slots)

    async def _prices() -> dict[str, PriceReading]:
        try:
            return await read_prices(image, slots, ocr, ocr_backend, semaphore=semaphore, errors=errors)
        except Exception as exc:  # noqa: BLE001 — a failed price pass must not abort the photo
            errors.append(f"{image_id}: price reading failed: {exc}")
            return {}

    prices, (observations, identify_errors) = await asyncio.gather(
        _prices(), identify_rows(image, slots, backend, catalog, semaphore, marks=settings.marks)
    )
    errors.extend(identify_errors)
    for obs in observations:
        obs.price = prices.get(obs.slot.slot_id, PriceReading())

    # Build pitches: {row.row: row_pitch(row)}
    # Any observation row missing from it (synthesized untagged row) inherits the LAST tag row's pitch
    pitches: dict[int, float] = {}
    for row in rows:
        pitches[row.row] = row_pitch(row)

    # For observations in rows not in pitches (untagged synthesized rows), use last tag row's pitch
    if rows:
        last_tag_row_pitch = pitches.get(rows[-1].row, 0.0)
        for obs in observations:
            if obs.slot.row not in pitches:
                pitches[obs.slot.row] = last_tag_row_pitch

    registration = register_image(image_id, observations, planogram, catalog, pitches)
    apply_registration(observations, registration)
    info.registration = registration

    if verify_pass:
        verify_errors = await verify_rows(image, observations, planogram, catalog, backend, semaphore)
        errors.extend(verify_errors)

    return info, image, observations, errors, notes


async def run_check(settings: Settings, *, backend_factory: Callable[..., Any] | None = None) -> ComplianceReport:
    """Run the whole compliance check and write the report.

    Args:
        settings: Run settings (paths may be relative; they are absolutized first).
        backend_factory: Test seam. ``factory(llm, *, cache_dir, base_url)`` → backend exposing
            ``ask(...)`` and ``is_local``. ``None`` uses :class:`VisionBackend`.

    Returns:
        The report that was written to ``settings.output``.

    Raises:
        FileExistsError: ``settings.output`` already exists (checked before any work).
        FileNotFoundError / ValueError: Invalid inputs (planogram, catalog, prices, images).
    """
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings = absolutize(settings)  # BEFORE any backend construction (first parrot import)

    # Check output doesn't exist (blocking I/O)
    def _check_output_exists(path: Path) -> bool:
        return path.exists()

    if await asyncio.to_thread(_check_output_exists, Path(settings.output)):
        raise FileExistsError(f"Output directory already exists: {settings.output}")
    planogram = load_planogram(Path(settings.planogram))
    catalog, missing = load_catalog(Path(settings.catalog), planogram)
    expected_prices = load_prices(Path(settings.prices)) if settings.prices else None
    factory = backend_factory or _default_backend_factory
    ocr = TagOcr()

    all_observations: list[SlotObservation] = []
    all_errors: list[str] = []
    all_notes: list[str] = []
    images_by_id: dict[str, np.ndarray] = {}
    image_infos: list[ImageInfo] = []

    async with contextlib.AsyncExitStack() as stack:
        # Build backend
        backend = factory(settings.llm, cache_dir=Path(settings.cache_dir), base_url=settings.base_url)
        # Enter backend through stack only when it has __aenter__ (FakeBackend has none)
        if hasattr(backend, "__aenter__"):
            backend = await stack.enter_async_context(backend)

        # Build ocr_backend: same object unless settings.ocr_llm is set AND differs
        ocr_backend: Any = None
        if settings.ocr_llm is not None and settings.ocr_llm != settings.llm:
            ocr_backend = factory(settings.ocr_llm, cache_dir=Path(settings.cache_dir), base_url=settings.base_url)
            if hasattr(ocr_backend, "__aenter__"):
                ocr_backend = await stack.enter_async_context(ocr_backend)
        else:
            ocr_backend = backend

        verify_pass = resolve_verify_pass(settings.verify_pass, backend.is_local)
        semaphore = asyncio.Semaphore(effective_concurrency(settings.concurrency, backend.is_local))

        # Process each image
        async def _process_one(
            n: int, path_str: str
        ) -> tuple[ImageInfo, np.ndarray, list[SlotObservation], list[str], list[str]]:
            image_id = f"image_{n:02d}"
            path = Path(path_str)
            return await _process_image(
                image_id,
                path,
                settings=settings,
                planogram=planogram,
                catalog=catalog,
                backend=backend,
                ocr_backend=ocr_backend,
                ocr=ocr,
                semaphore=semaphore,
                verify_pass=verify_pass,
            )

        # Run all images concurrently, capturing per-image failures
        results = await asyncio.gather(
            *[_process_one(n, path) for n, path in enumerate(settings.images, start=1)],
            return_exceptions=True,
        )

        for n, result in enumerate(results, start=1):
            image_id = f"image_{n:02d}"
            if isinstance(result, FileNotFoundError):
                raise result
            if isinstance(result, ValueError):
                raise result
            if isinstance(result, Exception):
                all_errors.append(f"{image_id}: {result}")
                logger.error("%s: processing failed: %s", image_id, result)
                continue
            info, image, observations, errors, notes = result
            image_infos.append(info)
            images_by_id[image_id] = image
            all_observations.extend(observations)
            all_errors.extend(errors)
            all_notes.extend(notes)

    # After the stack closes: merge/score/report
    positions = merge_positions(planogram, all_observations, catalog, settings.weights, expected_prices)

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reference_provisional = any(f.reference_read_method != "direct" for f in planogram.facings)

    run_info = RunInfo(
        visit_id=settings.visit_id,
        planogram_id=planogram.planogram_id,
        llm=settings.llm,
        ocr_llm=settings.ocr_llm or settings.llm,
        verify_pass=verify_pass,
        started_at=started,
        finished_at=finished,
        errors=all_errors,
        catalog_missing_skus=missing,
        reference_provisional=reference_provisional,
        local_ocr_available=ocr.available,
    )

    report = ComplianceReport(
        run=run_info,
        images=image_infos,
        slots=all_observations,
        positions=positions,
        shelves=shelf_scores(positions),
        brands=brand_shares(positions, catalog),
        compliance=summarize(positions, shelf_scores(positions), catalog, expected_prices),
        notes=list(STANDING_NOTES)
        + all_notes
        + (["Reference positions are provisional (inferred from planogram)."] if reference_provisional else []),
    )

    await asyncio.to_thread(
        write_report,
        report,
        images_by_id,
        settings,
        {
            "identify": IDENTIFY_PROMPT_VERSION,
            "verify": VERIFY_PROMPT_VERSION,
            "prices": PRICE_PROMPT_VERSION,
        },
    )

    return report
