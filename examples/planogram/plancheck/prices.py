"""Tag price reading for the planogram compliance check (FEAT-565, Module 5).

Local OCR first, vision-LLM contact-sheet fallback. Digits are never inferred.
"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING

import cv2
import numpy as np

from plancheck.models import PriceReading, RowPriceReading, Slot

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

PRICE_PROMPT_VERSION: str = "prices-v1"
PRICE_STAGE: str = "prices"
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_READ = re.compile(r"(\$)?\s*(\d{1,4})\s*[.,\s]\s*(\d{2})(?!\d)")
_DOLLARS = re.compile(r"\d{1,4}")

_SHEET_HEADER_H = 40
_SHEET_GUTTER = 12
_SHEET_PER_ROW = 6
_SHEET_FONT = cv2.FONT_HERSHEY_SIMPLEX


def parse_price(text: str) -> PriceReading:
    """Parse OCR/LLM text into a PriceReading (``source`` is left ``"none"`` for the caller to set).

    ``read`` needs dollars + separator + two cents digits; dollars only -> ``partial`` (amount None);
    otherwise ``unreadable``. Only whitespace and the cents superscript are normalised.

    Args:
        text: Raw OCR or LLM text for one price tag.

    Returns:
        A ``PriceReading`` with ``status``/``amount``/``currency`` set; ``raw`` keeps the original
        ``text`` (``None`` only when ``text`` is empty); ``source`` is always ``"none"``.
    """
    raw = text if text else None

    normalized = text.strip()

    def _superscript_to_decimal(match: re.Match[str]) -> str:
        return "." + match.group(0).translate(_SUPERSCRIPTS)

    normalized = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", _superscript_to_decimal, normalized)
    normalized = re.sub(r"\s+", " ", normalized)

    match = _READ.search(normalized)
    if match:
        dollar_sign, dollars, cents = match.groups()
        amount = Decimal(f"{dollars}.{cents}")
        currency = "USD" if dollar_sign else None
        return PriceReading(raw=raw, amount=amount, currency=currency, source="none", status="read")

    if _DOLLARS.search(normalized):
        return PriceReading(raw=raw, amount=None, currency=None, source="none", status="partial")

    return PriceReading(raw=raw, amount=None, currency=None, source="none", status="unreadable")


class TagOcr:
    """Lazy RapidOCR wrapper. ``available`` is False when ``rapidocr`` cannot be imported."""

    available: bool

    def __init__(self) -> None:
        self._engine: object | None = None
        try:
            import rapidocr  # noqa: F401  (availability probe only)

            self.available = True
        except ImportError:
            self.available = False
            logger.warning("rapidocr is not installed: every price tag goes to the LLM fallback")

    def read(self, crop: np.ndarray) -> str:
        """4x bicubic upscale -> OCR -> texts joined with ' | '. Synchronous and CPU-bound.

        Args:
            crop: BGR tag crop in original-image pixels.

        Returns:
            The OCR texts joined with ``" | "``, or ``""`` when OCR is unavailable or ``crop`` is empty.
        """
        if not self.available or crop is None or crop.size == 0:
            return ""

        if self._engine is None:
            from rapidocr import RapidOCR

            self._engine = RapidOCR()

        upscaled = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        result = self._engine(upscaled)
        texts = result.txts or ()
        return " | ".join(texts)


def contact_sheet(crops: list[np.ndarray], cell_height: int = 240) -> bytes:
    """One PNG with numbered cells (1-based) for the LLM fallback.

    Each crop is resized to ``cell_height`` (aspect preserved) and placed under a white 40-px
    header band carrying its 1-based cell number, never over the tag pixels. Cells are separated
    by 12-px white gutters and wrapped at 6 cells per line.

    Args:
        crops: Tag crops, in the order their cell numbers are assigned.
        cell_height: Target height (pixels) for every resized crop.

    Returns:
        PNG-encoded bytes of the assembled contact sheet.

    Raises:
        ValueError: When ``crops`` is empty, or PNG encoding fails.
    """
    if not crops:
        raise ValueError("contact_sheet requires at least one crop")

    resized: list[np.ndarray] = []
    for crop in crops:
        h, w = crop.shape[:2]
        new_w = max(1, round(w * cell_height / h))
        resized.append(cv2.resize(crop, (new_w, cell_height), interpolation=cv2.INTER_CUBIC))

    cell_width = max(img.shape[1] for img in resized)
    tiles: list[np.ndarray] = []
    for number, img in enumerate(resized, start=1):
        pad_left = (cell_width - img.shape[1]) // 2
        pad_right = cell_width - img.shape[1] - pad_left
        cell = cv2.copyMakeBorder(img, 0, 0, pad_left, pad_right, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        header = np.full((_SHEET_HEADER_H, cell_width, 3), 255, dtype=np.uint8)
        cv2.putText(header, str(number), (8, _SHEET_HEADER_H - 10), _SHEET_FONT, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
        tiles.append(np.vstack([header, cell]))

    tile_h, tile_w = tiles[0].shape[:2]
    n_cols = min(_SHEET_PER_ROW, len(tiles))
    n_rows = -(-len(tiles) // _SHEET_PER_ROW)  # ceil division
    sheet_w = n_cols * tile_w + (n_cols - 1) * _SHEET_GUTTER
    sheet_h = n_rows * tile_h + (n_rows - 1) * _SHEET_GUTTER
    sheet = np.full((sheet_h, sheet_w, 3), 255, dtype=np.uint8)

    for idx, tile in enumerate(tiles):
        row, col = divmod(idx, _SHEET_PER_ROW)
        y = row * (tile_h + _SHEET_GUTTER)
        x = col * (tile_w + _SHEET_GUTTER)
        sheet[y : y + tile_h, x : x + tile_w] = tile

    ok, buf = cv2.imencode(".png", sheet)
    if not ok:
        raise ValueError("failed to encode the contact sheet as PNG")
    return buf.tobytes()


def _tag_crop(image: np.ndarray, tag_box: tuple[int, int, int, int]) -> np.ndarray:
    """Tag pixels padded 12 % horizontally / 18 % vertically (min 2 px), clipped to the image.

    Args:
        image: Full original-resolution BGR image.
        tag_box: ``(x1, y1, x2, y2)`` of the tag in original-image pixels.

    Returns:
        The padded, clipped crop as a view into ``image``.
    """
    x1, y1, x2, y2 = tag_box
    oh, ow = image.shape[:2]
    px, py = max(2, round((x2 - x1) * 0.12)), max(2, round((y2 - y1) * 0.18))
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(ow, x2 + px), min(oh, y2 + py)
    return image[cy1:cy2, cx1:cx2]


def _ocr_all(ocr: TagOcr, crops: dict[str, np.ndarray]) -> dict[str, str]:
    """Sequential OCR of every crop (runs inside ONE worker thread)."""
    return {slot_id: ocr.read(crop) for slot_id, crop in crops.items()}


def _price_prompt(cells: int) -> str:
    """Instructions for the contact-sheet call.

    Args:
        cells: Number of numbered cells in the attached contact sheet.

    Returns:
        The prompt text sent alongside the contact sheet image.
    """
    return (
        f"The attached image shows {cells} numbered shelf price tags, one per cell, with the cell "
        "number printed in a white header band above each tag. For every cell number from 1 to "
        f"{cells}, read the price exactly as printed on the tag, including both the dollar amount "
        'and the cents digits, and include the "$" sign only when it is visible. If a price is not '
        "fully legible for a cell, report null for that cell — never guess or invent digits. Return "
        "exactly one entry per cell number."
    )


async def read_prices(
    image: np.ndarray,
    slots: list[Slot],
    ocr: TagOcr,
    backend: "VisionBackend | None",
    *,
    semaphore: asyncio.Semaphore | None = None,
    errors: list[str] | None = None,
) -> dict[str, PriceReading]:
    """Return slot_id -> PriceReading for every slot.

    OCR runs via ``asyncio.to_thread``; per row, tags that are not ``read`` go to ONE contact-sheet
    LLM call (schema ``RowPriceReading``). Slots without a tag -> ``not_assessed``. An LLM failure
    keeps the OCR result, logs a warning and appends one message to ``errors`` when given.

    Args:
        image: Full original-resolution BGR image the slots were detected on.
        slots: All slots of the image (tagged and untagged).
        ocr: Lazy local OCR wrapper.
        backend: Vision LLM backend for the contact-sheet fallback, or ``None`` to skip it entirely.
        semaphore: Optional shared concurrency limiter acquired around each row's LLM call.
        errors: Optional out-list; one message is appended per failed row LLM call.

    Returns:
        A mapping of ``slot_id`` to its resolved ``PriceReading``.
    """
    result: dict[str, PriceReading] = {}
    tagged_slots: list[Slot] = []
    for slot in slots:
        if slot.tag_box is None:
            result[slot.slot_id] = PriceReading()
        else:
            tagged_slots.append(slot)

    if not tagged_slots:
        return result

    crops = {slot.slot_id: _tag_crop(image, slot.tag_box) for slot in tagged_slots}
    texts = await asyncio.to_thread(_ocr_all, ocr, crops) if ocr.available else {}

    for slot in tagged_slots:
        if ocr.available:
            reading = parse_price(texts.get(slot.slot_id, "")).model_copy(update={"source": "ocr"})
        else:
            reading = PriceReading(status="unreadable")
        result[slot.slot_id] = reading

    if backend is None:
        return result

    rows: dict[int, list[Slot]] = {}
    for slot in tagged_slots:
        rows.setdefault(slot.row, []).append(slot)

    async def _process_row(row: int, row_slots: list[Slot]) -> None:
        row_slots_sorted = sorted(row_slots, key=lambda s: s.index)
        pending = [s for s in row_slots_sorted if result[s.slot_id].status != "read"]
        if not pending:
            return

        crops_list = [crops[s.slot_id] for s in pending]
        sheet = await asyncio.to_thread(contact_sheet, crops_list)
        prompt = _price_prompt(len(pending))

        try:
            if semaphore is not None:
                async with semaphore:
                    answer = await backend.ask(
                        prompt, [sheet], RowPriceReading, stage=PRICE_STAGE, prompt_version=PRICE_PROMPT_VERSION
                    )
            else:
                answer = await backend.ask(
                    prompt, [sheet], RowPriceReading, stage=PRICE_STAGE, prompt_version=PRICE_PROMPT_VERSION
                )
        except Exception as exc:  # noqa: BLE001 - any backend failure keeps the OCR reading
            image_id = row_slots_sorted[0].image_id
            logger.warning("prices %s row %s: LLM fallback failed: %s", image_id, row, exc)
            if errors is not None:
                errors.append(f"prices {image_id} row {row}: {exc}")
            return

        seen_cells: set[int] = set()
        for tag in answer.tags:
            cell = tag.cell
            if not (1 <= cell <= len(pending)) or cell in seen_cells:
                continue
            seen_cells.add(cell)
            if tag.price_text is None:
                continue
            candidate = parse_price(tag.price_text)
            if candidate.status != "read":
                continue
            target = pending[cell - 1]
            result[target.slot_id] = candidate.model_copy(update={"source": "llm"})

    await asyncio.gather(*(_process_row(row, row_slots) for row, row_slots in rows.items()))
    return result
