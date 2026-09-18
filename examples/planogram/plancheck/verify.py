"""Pass 2 — closed-set verification with distractors (FEAT-565, Module 9)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING

import numpy as np

from plancheck.identify import render_strip
from plancheck.models import Catalog, PlanogramFacing, PlanogramRef, RowVerification, SlotObservation

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

VERIFY_PROMPT_VERSION = "verify-v1"
STAGE = "verify"
CHOICE_OTHER = "other"
CHOICE_CANNOT_TELL = "cannot_tell"


def pick_distractors(
    facing: PlanogramFacing, planogram: PlanogramRef, catalog: Catalog, n: int = 3
) -> list[str]:
    """Pick up to ``n`` same-brand distractor SKUs for ``facing`` (never the expected SKU).

    Tier 1: same family, other variant. Tier 2: shelf neighbours within ±2 slots. Sorted by SKU
    inside each tier; may return fewer than ``n`` (or none).
    """
    expected_sku = facing.sku
    expected_item = catalog.by_sku(expected_sku)
    if expected_item is None:
        return []

    expected_brand = expected_item.brand
    expected_family = expected_item.family

    distractors: list[str] = []
    seen = {expected_sku}

    # Tier 1: same family, other variant
    if expected_family is not None:
        for item in catalog.items:
            if item.family == expected_family and item.sku not in seen and item.brand == expected_brand:
                distractors.append(item.sku)
                seen.add(item.sku)
                if len(distractors) >= n:
                    break

    # Tier 2: shelf neighbours within ±2 slots
    if len(distractors) < n:
        shelf_facings = planogram.shelf(facing.shelf)
        for neighbour in shelf_facings:
            if neighbour.sku in seen:
                continue
            if neighbour.slot < facing.slot - 2 or neighbour.slot > facing.slot + 2:
                continue
            neighbour_item = catalog.by_sku(neighbour.sku)
            if neighbour_item is None or neighbour_item.brand != expected_brand:
                continue
            distractors.append(neighbour.sku)
            seen.add(neighbour.sku)
            if len(distractors) >= n:
                break

    return sorted(distractors)


def option_order(slot_id: str, skus: list[str]) -> list[str]:
    """Deterministic shuffle seeded by sha256(slot_id) — the expected SKU is not always first."""
    return sorted(set(skus), key=lambda sku: hashlib.sha256(f"{slot_id}|{sku}".encode("utf-8")).hexdigest())


def _targets(
    observations: list[SlotObservation], planogram: PlanogramRef, catalog: Catalog
) -> dict[tuple[str, int], list[tuple[SlotObservation, PlanogramFacing]]]:
    """Group verifiable observations by ``(image_id, row)`` with their expected facing."""
    # Build a map from facing_id to PlanogramFacing
    facing_by_id: dict[str, PlanogramFacing] = {f.facing_id: f for f in planogram.facings}

    result: dict[tuple[str, int], list[tuple[SlotObservation, PlanogramFacing]]] = {}

    for obs in observations:
        # Condition 1: facing_id is not None
        if obs.facing_id is None:
            continue

        # Condition 2: reading is not None and occupancy == "occupied"
        if obs.reading is None or obs.reading.occupancy != "occupied":
            continue

        # Condition 3: resolution in {"unresolved", "ambiguous"}
        if obs.resolution not in {"unresolved", "ambiguous"}:
            continue

        # Condition 4: facing has identity_required == True
        facing = facing_by_id.get(obs.facing_id)
        if facing is None or not facing.identity_required:
            continue

        # Condition 5: expected SKU present in catalog
        if catalog.by_sku(facing.sku) is None:
            continue

        # This is a target observation
        key = (obs.slot.image_id, obs.slot.row)
        if key not in result:
            result[key] = []
        result[key].append((obs, facing))

    # Sort each group by slot index for determinism
    for key in result:
        result[key].sort(key=lambda x: x[0].slot.index)

    return result


def _build_verify_prompt(
    targets: list[tuple[SlotObservation, PlanogramFacing]], planogram: PlanogramRef, catalog: Catalog
) -> tuple[str, dict[str, list[str]]]:
    """Return (prompt, slot_id → offered SKUs). Options carry ``sku`` + catalog ``display_name``."""
    slot_options: dict[str, list[str]] = {}

    slots_data = []
    for obs, facing in targets:
        expected_sku = facing.sku
        distractors = pick_distractors(facing, planogram, catalog, n=3)
        all_skus = [expected_sku] + distractors
        ordered_skus = option_order(obs.slot.slot_id, all_skus)

        slot_options[obs.slot.slot_id] = ordered_skus

        options_list = []
        for sku in ordered_skus:
            item = catalog.by_sku(sku)
            name = item.display_name if item else sku
            options_list.append({"sku": sku, "name": name})

        slots_data.append(
            {
                "slot_id": obs.slot.slot_id,
                "mark": obs.slot.index,
                "options": options_list,
            }
        )

    slots_json = json.dumps(slots_data, separators=(",", ":"))

    prompt = (
        "You are verifying product identities on a retail shelf. For each listed slot, choose the product "
        "you see from the provided options, or choose 'other' / 'cannot_tell' if you're uncertain.\n\n"
        "INSTRUCTIONS:\n"
        "- Examine ONLY the numbered slots shown in the image.\n"
        "- For each slot, select ONE option from the list: one of the offered SKUs, 'other', or 'cannot_tell'.\n"
        "- If you choose a SKU, you MUST provide visible evidence (text, color, packaging feature) that supports your choice.\n"
        "- Evidence is mandatory for any SKU choice — without it, your answer will be treated as 'cannot tell'.\n"
        "- Your answer must be the SKU string (e.g., 'AC-12') for product choices.\n"
        "- Do NOT report on any slots other than those listed below.\n\n"
        f"SLOTS TO VERIFY: {slots_json}\n\n"
        "Respond with a JSON object containing a 'slots' array. Each entry must have:\n"
        "- slot_id: exactly as provided\n"
        "- choice: the SKU string, 'other', or 'cannot_tell'\n"
        "- evidence: visible proof for your choice (required for SKU choices, can be empty for 'other'/'cannot_tell')"
    )

    return prompt, slot_options


async def verify_rows(
    image: np.ndarray,
    observations: list[SlotObservation],
    planogram: PlanogramRef,
    catalog: Catalog,
    backend: "VisionBackend",
    semaphore: asyncio.Semaphore,
) -> list[str]:
    """Verify registered, occupied, unresolved slots of ONE image against their expectation.

    Mutates ``observations`` in place per the outcome table of the task; returns error strings.
    Any exception from ``backend.ask`` fails only its row.
    """
    targets_by_row = _targets(observations, planogram, catalog)

    if not targets_by_row:
        return []

    # Build a map from slot_id to observation for quick lookup
    obs_by_slot_id: dict[str, SlotObservation] = {obs.slot.slot_id: obs for obs in observations}

    async def _verify_one_row(
        image_id: str, row: int, row_targets: list[tuple[SlotObservation, PlanogramFacing]]
    ) -> list[str]:
        errors: list[str] = []
        try:
            # Get all slots for this image+row (for render_strip)
            row_slots = sorted(
                [obs.slot for obs in observations if obs.slot.image_id == image_id and obs.slot.row == row],
                key=lambda s: s.index,
            )

            # Render the strip
            png, _ = await asyncio.to_thread(render_strip, image, row_slots)

            # Build prompt
            prompt, slot_options = _build_verify_prompt(row_targets, planogram, catalog)

            # Call backend
            async with semaphore:
                result = await backend.ask(
                    prompt, [png], RowVerification, stage=STAGE, prompt_version=VERIFY_PROMPT_VERSION
                )

            # Apply outcomes
            answer_by_slot = {reading.slot_id: reading for reading in result.slots}

            for obs, facing in row_targets:
                slot_id = obs.slot.slot_id
                expected_sku = facing.sku

                if slot_id not in answer_by_slot:
                    # Requested slot missing from answer - unchanged
                    continue

                reading = answer_by_slot[slot_id]
                choice = reading.choice
                evidence = reading.evidence.strip()

                # Check if choice is valid
                offered_skus = slot_options.get(slot_id, [])
                is_valid_sku = choice in offered_skus
                is_other = choice == CHOICE_OTHER
                is_cannot_tell = choice == CHOICE_CANNOT_TELL

                if is_cannot_tell or is_other:
                    # Unchanged
                    continue

                if not is_valid_sku:
                    # Invalid choice - unchanged, add issue
                    obs.issues.append("verify_invalid_choice")
                    continue

                # Valid SKU choice
                if evidence:
                    # Has evidence
                    if choice == expected_sku:
                        obs.resolved_sku = expected_sku
                        obs.resolution = "verified_by_expectation"
                    else:
                        obs.resolved_sku = choice
                        obs.resolution = "verified_by_expectation"
                else:
                    # No evidence
                    if choice == expected_sku:
                        obs.resolution = "inferred"
                        obs.issues.append("verify_no_evidence")
                    else:
                        obs.issues.append("verify_no_evidence")
                    # resolved_sku stays None

        except Exception as exc:
            logger.warning("verify failed for row %s/%s: %s", image_id, row, exc)
            errors.append(f"verify:{image_id}:row{row}: {exc}")

        return errors

    # Run all rows concurrently
    tasks = [
        _verify_one_row(image_id, row, row_targets)
        for (image_id, row), row_targets in sorted(targets_by_row.items())
    ]
    results = await asyncio.gather(*tasks)
    return [e for errs in results for e in errs]