"""Fact/price tag helpers shared by type hooks and rule evaluation (FEAT-624)."""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

from parrot_pipelines.planogram.contracts import Identification, Shape, Slot

_PRICE = re.compile(r"(\d+)[.,](\d{2})")
#: A price printed with superscript cents and read without a separator ("149999" = 1499.99). A "$" amount on a
#: fact tag is the saving ("SAVE $200"), and a "%" number is a discount: neither is the price.
_SUPERSCRIPT_PRICE = re.compile(r"(?<![\d$])(?<!\$ )(\d{1,4})(\d{2})(?![\d%])")


def tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:
    """Return own-box OCR of a tag, falling back to shape or vision text; None when blank."""
    reading = readings.get(tag.shape_id)
    text = getattr(reading, "text", "") or tag.ocr_text
    if not text and tag.shape_id in reads:
        text = reads[tag.shape_id].text
    return text.strip() if text and text.strip() else None


def slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:
    """Return the slot whose lower area is labelled by a tag, or None."""
    cx = (tag.box.x1 + tag.box.x2) / 2
    cy = (tag.box.y1 + tag.box.y2) / 2
    best: Optional[Slot] = None
    for slot in slots:
        height = max(1, slot.box.y2 - slot.box.y1)
        if not slot.box.x1 <= cx <= slot.box.x2:
            continue
        if not (slot.box.y1 + slot.box.y2) / 2 <= cy <= slot.box.y2 + height:
            continue
        if best is None or abs(tag.box.y1 - slot.box.y2) < abs(tag.box.y1 - best.box.y2):
            best = slot
    return best


def tag_price(text: Optional[str]) -> Optional[float]:
    """First ``12.99`` / ``12,99`` amount in a text, else the last superscript-cents run (``149999``); or None."""
    match = _PRICE.search(text or "")
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    runs = _SUPERSCRIPT_PRICE.findall(text or "")
    if not runs:
        return None
    dollars, cents = runs[-1]
    return float(f"{dollars}.{cents}")
