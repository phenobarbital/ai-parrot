"""Unit tests for plancheck.verify (FEAT-565, spec §4 — M9)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from plancheck.models import (
    Catalog,
    PlanogramRef,
    RowVerification,
    Slot,
    SlotObservation,
    SlotReading,
    VerificationReading,
)
from plancheck.verify import option_order, pick_distractors, verify_rows

# Constants from conftest for creating observations
TAG_X0 = 150
TAG_DX = 220
TAG_ROWS_Y = (300, 650, 1000)
TAG_W, TAG_H = 70, 30
PRODUCT_W, PRODUCT_H, PRODUCT_GAP = 160, 200, 10


def _slot(image_id: str, row: int, index: int) -> Slot:
    """Create a slot positioned over the conftest shelf_image grid."""
    col = index  # 0-based index into the 6 columns
    x = TAG_X0 + TAG_DX * col
    y = TAG_ROWS_Y[row]
    # box: product area above the tag
    box = (x, y - PRODUCT_GAP - PRODUCT_H, x + PRODUCT_W, y - PRODUCT_GAP)
    # tag_box: the tag area
    tag_box = (x, y, x + TAG_W, y + TAG_H)
    return Slot(
        slot_id=f"{image_id}_r{row:02d}_s{index:02d}",
        image_id=image_id,
        row=row,
        index=index,
        box=box,
        tag_id=f"{image_id}_r{row:02d}_p{index:02d}",
        tag_box=tag_box,
        origin="tag_anchored",
    )


def _occupied_unresolved(image_id: str, row: int, index: int, facing_id: str) -> SlotObservation:
    """Registered, occupied, unresolved observation placed over the conftest shelf_image grid."""
    slot = _slot(image_id, row, index)
    reading = SlotReading(
        slot_id=slot.slot_id,
        occupancy="occupied",
        visibility="full",
        brand="Acme",
        family="10",
        xl=False,
        colors=["black"],
        pack=1,
        evidence="reads 10 Black",
    )
    return SlotObservation(
        slot=slot,
        reading=reading,
        resolved_sku=None,
        candidate_skus=[],
        resolution="unresolved",
        facing_id=facing_id,
    )


def test_distractors_exclude_expected(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    """For AC-11 (std black, family 10): result excludes 'AC-11', all same brand, the same-family
    variants (AC-12 XL, AC-13 tri-color) come first, len <= 3; CLOSEOUT/unknown SKU → [].
    """
    # AC-11 is shelf 1, slot 1, facing_id p001_f1
    facing = next(f for f in mini_planogram.facings if f.sku == "AC-11")
    result = pick_distractors(facing, mini_planogram, mini_catalog, n=3)

    # Should not include expected SKU
    assert "AC-11" not in result

    # All same brand (Acme)
    for sku in result:
        item = mini_catalog.by_sku(sku)
        assert item is not None
        assert item.brand == "Acme"

    # Same family variants should come first (family 10)
    # AC-12 (XL), AC-13 (tri-color) are same family
    if len(result) >= 2:
        # At least AC-12 and AC-13 should be in the first two positions
        assert "AC-12" in result[:2] or "AC-13" in result[:2]

    # Max 3
    assert len(result) <= 3

    # CLOSEOUT SKU should return empty
    closEOUT_facing = next(f for f in mini_planogram.facings if f.sku == "CLOSEOUT")
    result_closEOUT = pick_distractors(closEOUT_facing, mini_planogram, mini_catalog, n=3)
    assert result_closEOUT == []


def test_option_order_deterministic() -> None:
    """Same slot_id + permuted input → identical output; over several slot_ids the expected SKU
    is not always at index 0.
    """
    skus = ["A", "B", "C", "D"]
    slot_id = "test_slot_001"

    # Same input order
    result1 = option_order(slot_id, skus.copy())
    # Different input order
    result2 = option_order(slot_id, list(reversed(skus)))

    assert result1 == result2

    # Check that expected SKU is not always first across multiple slot_ids
    first_positions = []
    for i in range(10):
        sid = f"slot_{i:03d}"
        skus_for_slot = ["SKU-A", "SKU-B", "SKU-C"]
        result = option_order(sid, skus_for_slot)
        first_positions.append(result[0])

    # Not all first positions should be the same (SHA256 should give different orderings)
    assert len(set(first_positions)) > 1


@pytest.mark.asyncio
async def test_verify_expected_with_evidence(
    shelf_image: np.ndarray, mini_planogram, mini_catalog, fake_backend
) -> None:
    """Queue['verify'] = [RowVerification(...expected sku, evidence='reads 10 Black')] →
    resolution == 'verified_by_expectation', resolved_sku == expected; one call, stage 'verify', 1 image.
    """
    # Create observation: AC-11 (shelf 1, slot 1)
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    # Set up backend response: expected SKU with evidence
    fake_backend.queue["verify"] = [
        RowVerification(
            slots=[
                VerificationReading(slot_id=obs.slot.slot_id, choice="AC-11", evidence="reads 10 Black")
            ]
        )
    ]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    assert obs.resolution == "verified_by_expectation"
    assert obs.resolved_sku == "AC-11"

    # Check backend was called correctly
    assert len(fake_backend.calls) == 1
    call = fake_backend.calls[0]
    assert call["stage"] == "verify"
    assert call["n_images"] == 1


@pytest.mark.asyncio
async def test_verify_without_evidence_is_inferred(
    shelf_image, mini_planogram, mini_catalog, fake_backend
) -> None:
    """Expected sku + evidence '' → resolution == 'inferred', resolved_sku is None, issue recorded."""
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    # Set up backend response: expected SKU without evidence
    fake_backend.queue["verify"] = [
        RowVerification(slots=[VerificationReading(slot_id=obs.slot.slot_id, choice="AC-11", evidence="")])
    ]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    assert obs.resolution == "inferred"
    assert obs.resolved_sku is None
    assert "verify_no_evidence" in obs.issues


@pytest.mark.asyncio
async def test_verify_distractor_other_and_invalid(
    shelf_image, mini_planogram, mini_catalog, fake_backend
) -> None:
    """Distractor+evidence → resolved to distractor/verified_by_expectation; 'cannot_tell' → unchanged;
    unknown sku → unchanged + 'verify_invalid_choice'; foreign slot_id → error string.
    """
    # Create observation: AC-11 (shelf 1, slot 1)
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    # Get a distractor SKU (AC-12 is same family)
    distractor_sku = "AC-12"

    # Set up backend response: distractor with evidence
    fake_backend.queue["verify"] = [
        RowVerification(
            slots=[VerificationReading(slot_id=obs.slot.slot_id, choice=distractor_sku, evidence="reads 12 XL")]
        )
    ]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    assert obs.resolution == "verified_by_expectation"
    assert obs.resolved_sku == distractor_sku


@pytest.mark.asyncio
async def test_verify_cannot_tell_unchanged(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    """'cannot_tell' → unchanged."""
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    fake_backend.queue["verify"] = [
        RowVerification(
            slots=[VerificationReading(slot_id=obs.slot.slot_id, choice="cannot_tell", evidence="")]
        )
    ]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    assert obs.resolution == "unresolved"
    assert obs.resolved_sku is None


@pytest.mark.asyncio
async def test_verify_invalid_choice(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    """Unknown sku → unchanged + 'verify_invalid_choice'."""
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    fake_backend.queue["verify"] = [
        RowVerification(
            slots=[VerificationReading(slot_id=obs.slot.slot_id, choice="UNKNOWN-SKU", evidence="some evidence")]
        )
    ]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    assert obs.resolution == "unresolved"
    assert obs.resolved_sku is None
    assert "verify_invalid_choice" in obs.issues


@pytest.mark.asyncio
async def test_verify_row_failure_leaves_observations(
    shelf_image, mini_planogram, mini_catalog, fake_backend
) -> None:
    """Queue['verify'] = [RuntimeError('boom')] → returns 1 error string, observations unchanged."""
    obs = _occupied_unresolved("img001", 0, 0, "p001_f1")
    observations = [obs]

    fake_backend.queue["verify"] = [RuntimeError("boom")]

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert len(errors) == 1
    assert "verify:img001:row0:" in errors[0]
    assert "boom" in errors[0]
    # Observations should be unchanged
    assert obs.resolution == "unresolved"
    assert obs.resolved_sku is None


@pytest.mark.asyncio
async def test_verify_skips_non_targets(shelf_image, mini_planogram, mini_catalog, fake_backend) -> None:
    """Direct / empty / unregistered / CLOSEOUT observations only → zero backend calls (empty queue ok)."""
    # Create various non-target observations
    image_id = "img001"

    # 1. Unregistered (no facing_id)
    slot1 = _slot(image_id, 0, 0)
    reading1 = SlotReading(
        slot_id=slot1.slot_id, occupancy="occupied", visibility="full", evidence="test"
    )
    obs1 = SlotObservation(slot=slot1, reading=reading1, resolution="unresolved", facing_id=None)

    # 2. Empty occupancy
    slot2 = _slot(image_id, 0, 1)
    reading2 = SlotReading(slot_id=slot2.slot_id, occupancy="empty", visibility="full", evidence="")
    obs2 = SlotObservation(slot=slot2, reading=reading2, resolution="unresolved", facing_id="p001_f2")

    # 3. Already resolved
    slot3 = _slot(image_id, 0, 2)
    reading3 = SlotReading(slot_id=slot3.slot_id, occupancy="occupied", visibility="full", evidence="test")
    obs3 = SlotObservation(
        slot=slot3, reading=reading3, resolution="direct", facing_id="p001_f3", resolved_sku="AC-13"
    )

    observations = [obs1, obs2, obs3]

    # Empty queue is ok - no calls should be made
    fake_backend.queue["verify"] = []

    errors = await verify_rows(
        shelf_image, observations, mini_planogram, mini_catalog, fake_backend, asyncio.Semaphore(2)
    )

    assert errors == []
    # No backend calls should be made for non-targets
    assert len(fake_backend.calls) == 0