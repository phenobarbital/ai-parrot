"""TASK-3337: core models are strict; fixtures honour their contract."""
from __future__ import annotations

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from plancheck.models import Catalog, PlanogramRef, PriceReading, Slot, SlotReading


def test_models_forbid_extra() -> None:
    """Unknown fields are rejected on every StrictModel."""
    with pytest.raises(ValidationError):
        PriceReading(raw="$1.00", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Slot(
            slot_id="img_r00_s00",
            image_id="img",
            row=0,
            index=0,
            box=(0, 0, 10, 10),
            origin="tag_anchored",
            bogus=1,  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        SlotReading(
            slot_id="img_r00_s00",
            occupancy="occupied",
            visibility="full",
            bogus=1,  # type: ignore[call-arg]
        )


def test_shelf_orders_by_slot_not_position(mini_planogram: PlanogramRef) -> None:
    """Shelf 1 positions are 1,2,5,3,4,6 but ``shelf(1)`` returns slots 1..6."""
    shelf_1 = mini_planogram.shelf(1)
    assert [f.slot for f in shelf_1] == [1, 2, 3, 4, 5, 6]
    assert [f.position for f in shelf_1] == [1, 2, 5, 3, 4, 6]


def test_mini_planogram_has_19_facings_and_closeout(mini_planogram: PlanogramRef) -> None:
    assert len(mini_planogram.facings) == 19
    unresolved = [f for f in mini_planogram.facings if not f.identity_required]
    assert len(unresolved) == 2
    assert all(f.sku == "CLOSEOUT" for f in unresolved)
    assert {f.facing_id[-2:] for f in unresolved} == {"f1", "f2"}


def test_mini_catalog_covers_identity_skus(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    identity_skus = {f.sku for f in mini_planogram.facings if f.identity_required}
    for sku in identity_skus:
        assert mini_catalog.by_sku(sku) is not None
    assert mini_catalog.by_sku("nope") is None
    assert len(mini_catalog.items) == 17


def test_shelf_image_tags_pass_detector_filters(shelf_image: np.ndarray) -> None:
    """Numerically re-check the detector's filters on one tag crop (no detector import)."""
    assert shelf_image.shape == (1200, 1600, 3)

    x, top, bw, bh = 150, 300, 70, 30
    gray = cv2.cvtColor(shelf_image, cv2.COLOR_BGR2GRAY)
    crop = gray[top:top + bh, x:x + bw]
    assert crop.std() >= 25
    assert crop.mean() > 150

    aspect = bw / bh
    assert 1.65 < aspect < 4.4
    assert 0.025 * 1600 < bw < 0.09 * 1600
    assert 0.014 * 1200 < bh < 0.06 * 1200


@pytest.mark.asyncio
async def test_fake_backend_pops_raises_and_calls(fake_backend) -> None:
    sentinel_result = {"choice": "AC-11"}
    sentinel_error = RuntimeError("boom")

    def sentinel_callable(prompt: str, images: list) -> str:
        return f"{prompt}:{len(images)}"

    fake_backend.queue["identify"] = [sentinel_result, sentinel_error, sentinel_callable]

    result = await fake_backend.ask("p1", ["img1"], dict, stage="identify", prompt_version="v1")
    assert result is sentinel_result

    with pytest.raises(RuntimeError, match="boom"):
        await fake_backend.ask("p2", ["img1", "img2"], dict, stage="identify", prompt_version="v1")

    result = await fake_backend.ask("p3", ["img1"], dict, stage="identify", prompt_version="v1")
    assert result == "p3:1"

    assert len(fake_backend.calls) == 3
    assert [c["stage"] for c in fake_backend.calls] == ["identify", "identify", "identify"]
    assert fake_backend.calls[1]["n_images"] == 2

    with pytest.raises(AssertionError):
        await fake_backend.ask("p4", [], dict, stage="identify", prompt_version="v1")
