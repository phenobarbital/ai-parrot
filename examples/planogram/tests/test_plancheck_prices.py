"""Unit tests for plancheck.prices (FEAT-565, TASK-3343). No network, no real OCR models."""

from __future__ import annotations

import sys
from decimal import Decimal

import cv2
import numpy as np
import pytest

from plancheck.models import PriceReading, RowPriceReading, Slot, TagPriceReading
from plancheck.prices import PRICE_STAGE, TagOcr, contact_sheet, parse_price, read_prices

# Mirror of the geometry constants in examples/planogram/tests/conftest.py (TASK-3337). Do NOT
# `from conftest import ...`: the repo root also has a conftest.py, so the bare module name is ambiguous.
TAG_W, TAG_H, TAG_X0, TAG_DX, TAG_ROWS_Y, TAGS_PER_ROW = 70, 30, 150, 220, (300, 650, 1000), 6


class StubOcr:
    """Duck-typed TagOcr: returns queued texts in call order."""

    def __init__(self, texts: list[str], available: bool = True) -> None:
        self.texts, self.available, self.reads = list(texts), available, 0

    def read(self, crop: np.ndarray) -> str:
        self.reads += 1
        return self.texts.pop(0)


def _row_slots(row: int, *, untagged_last: bool = False) -> list[Slot]:
    """Six tag-anchored slots of conftest row `row` (0-based), built from the shared constants."""
    top = TAG_ROWS_Y[row]
    slots: list[Slot] = []
    for i in range(TAGS_PER_ROW):
        x = TAG_X0 + TAG_DX * i
        cx = x + TAG_W // 2
        box = (cx - 80, top - 10 - 200, cx + 80, top - 10)
        slot_id = f"img_r{row + 1:02d}_s{i + 1:02d}"
        if untagged_last and i == TAGS_PER_ROW - 1:
            slots.append(
                Slot(
                    slot_id=slot_id,
                    image_id="img",
                    row=row,
                    index=i,
                    box=box,
                    tag_id=None,
                    tag_box=None,
                    origin="gap_filled",
                )
            )
        else:
            tag_box = (x, top, x + TAG_W, top + TAG_H)
            slots.append(
                Slot(
                    slot_id=slot_id,
                    image_id="img",
                    row=row,
                    index=i,
                    box=box,
                    tag_id=f"tag_{slot_id}",
                    tag_box=tag_box,
                    origin="tag_anchored",
                )
            )
    return slots


def _dummy_crop(w: int = 70, h: int = 30) -> np.ndarray:
    return np.full((h, w, 3), 200, dtype=np.uint8)


@pytest.mark.parametrize(
    "text,status,amount",
    [
        ("$45.99", "read", Decimal("45.99")),
        ("45 99", "read", Decimal("45.99")),
        ("45⁹⁹", "read", Decimal("45.99")),
        ("'59\"", "partial", None),
        ("45%", "partial", None),
        ("口", "unreadable", None),
        ("4599", "partial", None),
        ("45 | 99", "partial", None),
        ("", "unreadable", None),
    ],
)
def test_parse_price_cases(text: str, status: str, amount: Decimal | None) -> None:
    reading = parse_price(text)
    assert reading.status == status
    assert reading.amount == amount
    assert reading.source == "none"
    if text:
        assert reading.raw == text
    else:
        assert reading.raw is None
    if text == "$45.99":
        assert reading.currency == "USD"
    else:
        assert reading.currency is None


def test_tag_ocr_unavailable_without_rapidocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    ocr = TagOcr()
    assert ocr.available is False
    assert ocr.read(_dummy_crop()) == ""


def test_contact_sheet_is_png_with_cells() -> None:
    sheet3 = contact_sheet([_dummy_crop() for _ in range(3)])
    decoded3 = cv2.imdecode(np.frombuffer(sheet3, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded3 is not None

    sheet7 = contact_sheet([_dummy_crop() for _ in range(7)])
    decoded7 = cv2.imdecode(np.frombuffer(sheet7, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded7 is not None
    assert decoded7.shape[0] > decoded3.shape[0]

    with pytest.raises(ValueError):
        contact_sheet([])


@pytest.mark.asyncio
async def test_read_prices_llm_only_for_unread(shelf_image, fake_backend) -> None:
    slots = _row_slots(0)
    ocr = StubOcr(["$10.99", "$10.99", "$10.99", "$10.99", "12%", "口"])
    fake_backend.queue["prices"].append(
        RowPriceReading(
            tags=[TagPriceReading(cell=1, price_text="$12.99"), TagPriceReading(cell=2, price_text="$13.50")]
        )
    )

    result = await read_prices(shelf_image, slots, ocr, fake_backend)

    assert len(fake_backend.calls) == 1
    call = fake_backend.calls[0]
    assert call["stage"] == PRICE_STAGE
    assert call["n_images"] == 1

    for slot in slots[:4]:
        reading = result[slot.slot_id]
        assert reading.status == "read"
        assert reading.source == "ocr"
        assert reading.amount == Decimal("10.99")

    llm_reading_1 = result[slots[4].slot_id]
    assert llm_reading_1.status == "read"
    assert llm_reading_1.source == "llm"
    assert llm_reading_1.amount == Decimal("12.99")

    llm_reading_2 = result[slots[5].slot_id]
    assert llm_reading_2.status == "read"
    assert llm_reading_2.source == "llm"
    assert llm_reading_2.amount == Decimal("13.50")


@pytest.mark.asyncio
async def test_read_prices_without_rapidocr(shelf_image, fake_backend) -> None:
    slots = _row_slots(0)
    ocr = StubOcr([], available=False)
    fake_backend.queue["prices"].append(RowPriceReading(tags=[]))

    result = await read_prices(shelf_image, slots, ocr, fake_backend)

    assert ocr.reads == 0
    assert len(fake_backend.calls) == 1
    assert fake_backend.calls[0]["n_images"] == 1
    assert "6" in fake_backend.calls[0]["prompt"]
    for slot in slots:
        assert result[slot.slot_id].status == "unreadable"


@pytest.mark.asyncio
async def test_read_prices_untagged_slot_not_assessed(shelf_image, fake_backend) -> None:
    slots = _row_slots(0, untagged_last=True)
    ocr = StubOcr(["$1.00"] * 5)

    result = await read_prices(shelf_image, slots, ocr, fake_backend)

    untagged = slots[-1]
    assert untagged.tag_box is None
    assert result[untagged.slot_id] == PriceReading()
    assert fake_backend.calls == []


@pytest.mark.asyncio
async def test_read_prices_llm_failure_keeps_ocr(shelf_image, fake_backend) -> None:
    slots = _row_slots(0)
    ocr = StubOcr(["$1.00"] * 5 + ["12%"])
    fake_backend.queue["prices"].append(RuntimeError("boom"))
    errors: list[str] = []

    result = await read_prices(shelf_image, slots, ocr, fake_backend, errors=errors)

    reading = result[slots[5].slot_id]
    assert reading.status == "partial"
    assert reading.source == "ocr"
    assert reading.raw == "12%"
    assert len(errors) == 1


@pytest.mark.asyncio
async def test_read_prices_llm_partial_answer_does_not_overwrite(shelf_image, fake_backend) -> None:
    slots = _row_slots(0)
    ocr = StubOcr(["$1.00"] * 4 + ["12%", "口"])
    fake_backend.queue["prices"].append(
        RowPriceReading(tags=[TagPriceReading(cell=1, price_text="45"), TagPriceReading(cell=2, price_text=None)])
    )

    result = await read_prices(shelf_image, slots, ocr, fake_backend)

    partial_reading = result[slots[4].slot_id]
    assert partial_reading.status == "partial"
    assert partial_reading.source == "ocr"

    unreadable_reading = result[slots[5].slot_id]
    assert unreadable_reading.status == "unreadable"
    assert unreadable_reading.source == "ocr"


@pytest.mark.asyncio
async def test_read_prices_no_backend(shelf_image) -> None:
    slots = _row_slots(0)
    ocr = StubOcr(["$5.00"] * 6)

    result = await read_prices(shelf_image, slots, ocr, None)

    for slot in slots:
        reading = result[slot.slot_id]
        assert reading.status == "read"
        assert reading.source == "ocr"
        assert reading.amount == Decimal("5.00")
