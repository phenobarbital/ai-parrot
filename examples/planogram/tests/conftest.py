"""Shared fixtures for the plancheck tests (FEAT-565). Synthetic data only — the repo is public."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # → ``import plancheck``

from plancheck.models import Catalog, CatalogItem, PlanogramFacing, PlanogramRef  # noqa: E402

IMG_H, IMG_W = 1200, 1600
TAG_W, TAG_H, TAG_X0, TAG_DX = 70, 30, 150, 220
TAG_ROWS_Y = (300, 650, 1000)
TAGS_PER_ROW = 6
PRODUCT_W, PRODUCT_H, PRODUCT_GAP = 160, 200, 10
SHELF1_POSITIONS = (1, 2, 5, 3, 4, 6)  # deliberately NON-monotone vs slots 1..6


@pytest.fixture
def shelf_image() -> np.ndarray:
    """Dark canvas with 3 rows x 6 white tags (inner dark bar) and a coloured product block above each."""
    image = np.full((IMG_H, IMG_W, 3), 30, dtype=np.uint8)
    for r, top in enumerate(TAG_ROWS_Y):
        for i in range(TAGS_PER_ROW):
            x = TAG_X0 + TAG_DX * i
            cv2.rectangle(image, (x, top), (x + TAG_W - 1, top + TAG_H - 1), (245, 245, 245), -1)
            cv2.rectangle(image, (x + 15, top + 10), (x + 54, top + 19), (40, 40, 40), -1)
            cx = x + TAG_W // 2
            colour = (40 + 35 * i, 200 - 50 * r, 90 + 25 * ((i + r) % 4))
            cv2.rectangle(
                image,
                (cx - PRODUCT_W // 2, top - PRODUCT_GAP - PRODUCT_H),
                (cx + PRODUCT_W // 2 - 1, top - PRODUCT_GAP - 1),
                colour,
                -1,
            )
    return image


def _sku(shelf: int, slot: int) -> tuple[str, str | None]:
    """Return (sku, brand) of the synthetic planogram."""
    if shelf == 3 and slot == 6:
        return "CLOSEOUT", None
    return (f"AC-{shelf}{slot}", "Acme") if slot <= 3 else (f"BO-{shelf}{slot}", "Bolt")


def _position(shelf: int, slot: int) -> int:
    return SHELF1_POSITIONS[slot - 1] if shelf == 1 else (shelf - 1) * 6 + slot


@pytest.fixture
def mini_planogram_data() -> dict[str, Any]:
    """Raw source-schema planogram dict (same keys as the real file, synthetic values)."""
    shelves = []
    for shelf in (1, 2, 3):
        products = {}
        for slot in range(1, 7):
            sku, brand = _sku(shelf, slot)
            products[f"pos {shelf}:{slot}"] = {
                "position": _position(shelf, slot), "segment": "left" if slot <= 3 else "right",
                "segment_number": 1 if slot <= 3 else 2, "slot": slot,
                "segment_slot": slot if slot <= 3 else slot - 3, "product": sku, "brand": brand,
                "shelf": shelf, "facings": 2 if sku == "CLOSEOUT" else 1, "confidence": "high",
                "read_method": "inferred" if shelf == 2 else "direct", "notes": None,
            }
        shelves.append({"shelf": f"Shelf {shelf}", "shelf_number": shelf, "product_count": 6,
                        "facing_count": 7 if shelf == 3 else 6, "products": products})
    meta = {"product_count": 18, "physical_facing_count": 19, "source": "synthetic fixture", "shelves": 3,
            "segments": 2, "planogram": "Mini", "fixture": "test", "option": "A"}
    return {"planogram": meta, "shelves": shelves}


@pytest.fixture
def mini_planogram(mini_planogram_data: dict[str, Any]) -> PlanogramRef:
    """The same planogram built directly from models (19 facings) — no loader involved."""
    facings = []
    for shelf in mini_planogram_data["shelves"]:
        for product in sorted(shelf["products"].values(), key=lambda p: p["slot"]):
            for k in range(1, product["facings"] + 1):
                facings.append(PlanogramFacing(
                    facing_id=f"p{product['position']:03d}_f{k}", position=product["position"],
                    shelf=product["shelf"], segment=product["segment"], slot=product["slot"],
                    segment_slot=product["segment_slot"], facing=k, sku=product["product"],
                    brand=product["brand"], identity_required=product["product"] != "CLOSEOUT",
                    source_confidence=product["confidence"], reference_read_method=product["read_method"],
                ))
    return PlanogramRef(planogram_id="mini", source="synthetic fixture", shelf_count=3, facings=facings)


@pytest.fixture
def mini_catalog() -> Catalog:
    """One item per identity-required SKU; slot 1/4 std black, 2/5 XL black, 3/6 std tri-color."""
    items = []
    for shelf in (1, 2, 3):
        for slot in range(1, 7):
            sku, brand = _sku(shelf, slot)
            if brand is None:
                continue
            family = f"{shelf}{0 if brand == 'Acme' else 1}"
            variant = (slot - 1) % 3
            xl, colors = variant == 1, (["tri-color"] if variant == 2 else ["black"])
            name = f"{brand} {family}{'XL' if xl else ''} {'Tri-color' if variant == 2 else 'Black'}"
            items.append(CatalogItem(sku=sku, brand=brand, display_name=name, family=family, xl=xl,
                                     colors=colors, identifiers=[sku], aliases=[name], provenance="fixture"))
    return Catalog(items=items)


class FakeBackend:
    """Stand-in for ``plancheck.vision.VisionBackend``: canned responses per stage."""

    def __init__(self, *, is_local: bool = False) -> None:
        self.is_local = is_local
        self.calls: list[dict[str, Any]] = []
        self.queue: dict[str, list[Any]] = {"identify": [], "verify": [], "prices": []}

    async def ask(self, prompt: str, images: Any, schema: type, *, stage: str, prompt_version: str) -> Any:
        """Pop the next canned item for ``stage``: raise it, call it, or return it."""
        self.calls.append({"stage": stage, "prompt": prompt, "n_images": len(images), "schema": schema})
        assert self.queue.get(stage), f"FakeBackend: no canned response left for stage {stage!r}"
        item = self.queue[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return item(prompt, images) if callable(item) else item


@pytest.fixture
def fake_backend() -> FakeBackend:
    """A fresh cloud-like fake backend."""
    return FakeBackend()
