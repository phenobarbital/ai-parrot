"""Pass 1 — area-constrained open-set identification (FEAT-565, Module 7).

One full-resolution row strip + JSON of slot areas per call; answers are keyed by supplied slot id.
The model is never told what the planogram expects.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import TYPE_CHECKING

import cv2
import numpy as np

from plancheck.grid import strip_box, to_strip_norm
from plancheck.models import Box, Catalog, RowReading, Slot, SlotObservation, SlotReading
from plancheck.reference import normalize_brand, resolve_identity

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

IDENTIFY_PROMPT_VERSION: str = "identify-v1"
IDENTIFY_STAGE: str = "identify"
SUBSTRIP_MAX_SLOTS: int = 8
CLOUD_SPLIT_ABOVE: int = 20


def _plan_calls(slots: list[Slot], *, is_local: bool) -> list[list[Slot]]:
    """Group slots into LLM calls: rows ordered by ``row``; chunks contiguous, balanced, ordered by ``index``."""
    if not slots:
        return []
    
    # Group slots by row
    rows: dict[int, list[Slot]] = {}
    for slot in slots:
        if slot.row not in rows:
            rows[slot.row] = []
        rows[slot.row].append(slot)
    
    # Sort slots within each row by index
    for row_slots in rows.values():
        row_slots.sort(key=lambda s: s.index)
    
    # Create calls
    calls: list[list[Slot]] = []
    for row_num in sorted(rows.keys()):
        row_slots = rows[row_num]
        
        # Determine if we need to split
        should_split = is_local or len(row_slots) > CLOUD_SPLIT_ABOVE
        
        if should_split and len(row_slots) > SUBSTRIP_MAX_SLOTS:
            # Split into balanced chunks
            n_slots = len(row_slots)
            n_chunks = math.ceil(n_slots / SUBSTRIP_MAX_SLOTS)
            chunk_size = math.ceil(n_slots / n_chunks)
            
            for i in range(0, n_slots, chunk_size):
                chunk = row_slots[i:i + chunk_size]
                calls.append(chunk)
        else:
            # Single call for the whole row
            calls.append(row_slots)
    
    return calls


def render_strip(image: np.ndarray, slots: list[Slot], *, marks: bool = True) -> tuple[bytes, Box]:
    """PNG of one row at native resolution with 2-px numbered outlines; returns (png, strip box).

    The mark number is the slot ``index``; labels are drawn over the TAG area, never the product.
    """
    height, width = image.shape[:2]
    strip = strip_box(slots, (width, height))
    x1, y1, x2, y2 = strip
    crop = image[y1:y2, x1:x2].copy()
    if marks:
        for slot in slots:
            # Translate slot box coordinates to crop coordinates
            slot_x1 = slot.box[0] - x1
            slot_y1 = slot.box[1] - y1
            slot_x2 = slot.box[2] - x1
            slot_y2 = slot.box[3] - y1
            
            # Draw 2-px rectangle on slot.box
            cv2.rectangle(crop, (slot_x1, slot_y1), (slot_x2, slot_y2), (0, 255, 0), 2)
            
            # Number = str(slot.index)
            text = str(slot.index)
            
            # Determine where to place the number
            if slot.tag_box is not None:
                # Place over tag area
                tag_x1 = slot.tag_box[0] - x1
                tag_y1 = slot.tag_box[1] - y1
                tag_x2 = slot.tag_box[2] - x1
                tag_y2 = slot.tag_box[3] - y1
                
                # Center the text in the tag box
                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                text_x = tag_x1 + (tag_x2 - tag_x1 - text_size[0]) // 2
                text_y = tag_y1 + (tag_y2 - tag_y1 + text_size[1]) // 2
                
                # Draw filled dark background
                cv2.rectangle(crop, (text_x - 2, text_y - text_size[1] - 2), 
                             (text_x + text_size[0] + 2, text_y + 2), (0, 0, 0), -1)
                
                # Draw light text
                cv2.putText(crop, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            else:
                # Place in a band just below slot.box (where the tag would be)
                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                text_x = slot_x1 + (slot_x2 - slot_x1 - text_size[0]) // 2
                text_y = min(slot_y2 + text_size[1] + 5, crop.shape[0] - 5)  # Clipped to crop
                
                # Draw filled dark background
                cv2.rectangle(crop, (text_x - 2, text_y - text_size[1] - 2), 
                             (text_x + text_size[0] + 2, text_y + 2), (0, 0, 0), -1)
                
                # Draw light text
                cv2.putText(crop, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    ok, buffer = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("strip PNG encoding failed")
    return buffer.tobytes(), strip


def build_identify_prompt(slots: list[Slot], strip: Box) -> str:
    """Instructions + JSON list ``[{"slot_id","mark","box_2d"}]``; forbids reporting anything outside the
    listed areas; does NOT mention the planogram or expected products."""
    areas = [{"slot_id": s.slot_id, "mark": s.index, "box_2d": to_strip_norm(s.box, strip)} for s in slots]
    areas_json = json.dumps(areas, separators=(",", ":"))
    
    prompt = (
        "You are analyzing a retail shelf image. Below is a list of product slot areas in this image. "
        "For each slot, determine what product is present and describe its characteristics.\n\n"
        "INSTRUCTIONS:\n"
        "- Analyze ONLY the areas listed below. Do NOT report products outside these areas.\n"
        "- For each slot, report exactly one entry with the slot_id as provided.\n"
        "- Determine occupancy: 'occupied' (product present), 'empty' (no product), or 'uncertain' (cannot tell).\n"
        "- Assess visibility: 'full' (entirely visible), 'partial' (partially obscured), or 'unusable' (too obscured).\n"
        "- For occupied slots, identify the brand, family/model, whether it's XL size, colors, pack size, and visible text.\n"
        "- Use null/empty values when information is not legible - do NOT guess.\n"
        "- Provide a one-sentence evidence for your assessment.\n"
        "- Numbered outlines, when visible, correspond to the 'mark' field.\n\n"
        "REPORT ONLY THE FOLLOWING FIELDS FOR EACH SLOT:\n"
        "- slot_id: exactly as provided\n"
        "- occupancy: 'occupied', 'empty', or 'uncertain'\n"
        "- visibility: 'full', 'partial', or 'unusable'\n"
        "- brand: brand name if visible, null otherwise\n"
        "- family: family/model number if visible, null otherwise\n"
        "- xl: true if XL size, false if standard, null if unknown\n"
        "- colors: list of visible colors (max 8), empty if none\n"
        "- pack: pack size if visible, null otherwise\n"
        "- visible_text: list of visible text lines (max 20), empty if none\n"
        "- evidence: one-sentence justification (max 400 chars)\n\n"
        f"AREAS: {areas_json}"
    )
    
    return prompt


def _uncertain(slot: Slot, issue: str, evidence: str = "") -> SlotObservation:
    """Observation for a slot the model did not (usably) assess."""
    reading = SlotReading(slot_id=slot.slot_id, occupancy="uncertain", visibility="unusable", evidence=evidence[:400])
    return SlotObservation(slot=slot, reading=reading, issues=[issue])


def _apply_reading_rules(slots: list[Slot], answer: RowReading, catalog: Catalog) -> tuple[list[SlotObservation], list[str]]:
    """Filter one call's answer and resolve identities. Returns (observations for ALL ``slots``, unknown ids)."""
    # Index the answer by slot_id, FIRST occurrence wins
    answer_dict = {}
    unknown_ids = []
    
    for reading in answer.slots:
        if reading.slot_id in answer_dict:
            # First wins, skip duplicates
            continue
        # Check if this slot_id is in our expected slots
        if any(slot.slot_id == reading.slot_id for slot in slots):
            answer_dict[reading.slot_id] = reading
        else:
            # Unknown slot id - add to unknown list (will be dropped)
            unknown_ids.append(reading.slot_id)
    
    observations = []
    
    # Process each slot
    for slot in slots:
        if slot.slot_id not in answer_dict:
            # Slot missing from the answer
            observations.append(_uncertain(slot, "missing_in_response"))
            continue
            
        reading = answer_dict[slot.slot_id]
        
        # Apply downgrade rule: occupancy == "empty" and visibility != "full" -> uncertain
        if reading.occupancy == "empty" and reading.visibility != "full":
            reading = reading.model_copy(update={"occupancy": "uncertain"})
            issues = ["empty_downgraded_partial_visibility"]
        else:
            issues = []
            
        # Normalize brand
        if reading.brand:
            normalized_brand = normalize_brand(reading.brand, catalog)
            if normalized_brand:
                reading = reading.model_copy(update={"brand": normalized_brand})
        
        # Resolve identity for occupied slots
        resolved_sku = None
        candidate_skus = []
        resolution = "unresolved"
        
        if reading.occupancy == "occupied":
            resolved_sku, candidate_skus, resolution = resolve_identity(reading, catalog)
        
        observation = SlotObservation(
            slot=slot,
            reading=reading,
            resolved_sku=resolved_sku,
            candidate_skus=candidate_skus,
            resolution=resolution,
            issues=issues
        )
        observations.append(observation)
    
    return observations, unknown_ids


async def identify_rows(image: np.ndarray, slots: list[Slot], backend: "VisionBackend", catalog: Catalog,
                        semaphore: asyncio.Semaphore, *, marks: bool = True) -> tuple[list[SlotObservation], list[str]]:
    """Run pass 1 over every slot of one image.

    One call per row on cloud backends. On local backends EVERY row is split into sub-strips of <= 8 slots,
    one call each; cloud rows are split the same way only above 20 slots. Unknown slot ids are dropped and
    reported; missing ids -> uncertain/unusable; an ``empty`` with visibility != full is downgraded to
    ``uncertain``. A failed call -> all its slots uncertain + one error string. Returns (observations, errors).
    """
    calls = _plan_calls(slots, is_local=backend.is_local)

    async def _one(chunk: list[Slot]) -> tuple[list[SlotObservation], list[str]]:
        try:
            png, strip = await asyncio.to_thread(render_strip, image, chunk, marks=marks)
            prompt = build_identify_prompt(chunk, strip)
            async with semaphore:
                answer = await backend.ask(prompt, [png], RowReading,
                                         stage=IDENTIFY_STAGE, prompt_version=IDENTIFY_PROMPT_VERSION)
            
            observations, unknown_ids = _apply_reading_rules(chunk, answer, catalog)
            
            errors = []
            if unknown_ids:
                first_slot = chunk[0]
                unknown_str = ", ".join(sorted(unknown_ids))
                errors.append(f"identify {first_slot.image_id} row {first_slot.row}: dropped unknown slot ids {unknown_str}")
            
            return observations, errors
            
        except Exception as exc:
            logger.warning("identify failed for chunk: %s", exc)
            error_msg = str(exc)
            first_slot = chunk[0]
            last_slot = chunk[-1]
            error_str = f"identify {first_slot.image_id} row {first_slot.row} [s{first_slot.index:02d}-s{last_slot.index:02d}]: {error_msg}"
            observations = [_uncertain(slot, "identify_failed", error_msg) for slot in chunk]
            return observations, [error_str]

    results = await asyncio.gather(*(_one(chunk) for chunk in calls))
    observations = sorted((o for obs, _ in results for o in obs), key=lambda o: (o.slot.row, o.slot.index))
    errors = [e for _, errs in results for e in errs]
    return observations, errors