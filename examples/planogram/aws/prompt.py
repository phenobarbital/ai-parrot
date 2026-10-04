"""Identification prompt for Nova (FEAT-592), v2: OCR-anchored, brand-hinted.

Deliberately example-local: the shared ``build_identify_prompt`` must NOT mention a
planogram (verified: identify.py:125).

v1 offered the planogram's product SKUs (``3YM58AN#140``, ``T822XL-BCS``) as expected
candidates. Those part numbers are not printed on the package front - the front shows
the retail code (``62XL``, ``564``, ``TN-830``) - so Nova read the code correctly in
``evidence`` and then snapped ``product`` (and sometimes ``brand``) to an unrelated SKU.
v2+ drops the SKU list, keeps the brand list as a logo-reading hint only, and feeds each
area the text RapidOCR read inside its own box. Matching the printed code back to a
planogram SKU is a deterministic post-step, not the model's job.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel

#: Distinct from IDENTIFY_PROMPT_VERSION / IDENTIFY_STAGE (verified: identify.py:33-34)
#: so cache entries can never collide — cache_key mixes both (verified: vision.py:63).
NOVA_PROMPT_VERSION: str = "nova-ocr-v3"
NOVA_STAGE: str = "identify-nova"


class PlanogramVocabulary(BaseModel):
    """Planogram vocabulary. v2+ prompts with ``brands`` only; ``products`` (SKUs) is kept
    for a deterministic printed-code -> SKU matcher and never shown to the model."""

    products: List[str]
    brands: List[str]


def load_planogram_vocabulary(path: Path) -> PlanogramVocabulary:
    """Distinct product/brand values from ``shelves[].products{}`` of a planogram JSON.

    Returns:
        Sorted, de-duplicated products and brands; empty lists are legal.

    Raises:
        ValueError: the file is not a planogram JSON (no ``shelves`` list).
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload.get("shelves"), list):
        raise ValueError(f"{path}: not a planogram JSON - no 'shelves' list")

    products: set[str] = set()
    brands: set[str] = set()
    for shelf in payload["shelves"]:
        if not isinstance(shelf, dict) or not isinstance(shelf.get("products"), dict):
            continue
        for position in shelf["products"].values():
            if not isinstance(position, dict):
                continue
            for key, values in (("product", products), ("brand", brands)):
                value = position.get(key)
                if isinstance(value, str) and value.strip():
                    values.add(value.strip())

    return PlanogramVocabulary(products=sorted(products), brands=sorted(brands))


def build_nova_identify_prompt(
    areas: Sequence[Dict[str, Any]],
    vocabulary: PlanogramVocabulary,
    schema_instruction: str,
) -> str:
    """OCR-anchored counterpart of build_identify_prompt (verified: identify.py:119).

    Keeps that function's AREAS contract (``id``, ``mark``, ``box_2d``, ``ocr_text``) and adds
    ``ocr_confidence`` per area. Differs from the shared prompt in two ways: it names the
    planogram's brands as a logo-reading hint, and it spells out what ``empty`` means.

    Args:
        areas: One dict per target with ``id``, ``mark``, ``box_2d``, ``ocr_text`` and
            ``ocr_confidence`` (``None`` when nothing was read).
        vocabulary: Planogram vocabulary; only ``brands`` is used.
        schema_instruction: The "reply with only this JSON" rule for the response schema.

    Returns:
        The prompt text.
    """
    areas_json = json.dumps(list(areas), separators=(",", ":"), ensure_ascii=False)
    brands_json = json.dumps(vocabulary.brands, ensure_ascii=False)
    return (
        "You are analysing a retail shelf image. Below is a list of numbered AREAS in this image; each "
        "has an id, an optional mark (the number drawn on its outline), a box_2d as [ymin, xmin, ymax, "
        "xmax] normalised to 0-1000 relative to the image you receive, and ocr_text: the text a local OCR "
        "read INSIDE that area (fragments joined by ' | '; may be empty, partial or slightly wrong) with "
        "its ocr_confidence 0..1.\n\n"
        f"KNOWN BRANDS: {brands_json}\n"
        "These brands may appear on this shelf. Use them to read logos, but report the brand you actually "
        "see even when it is not listed.\n\n"
        "INSTRUCTIONS:\n"
        "- Judge each area independently and ONLY from what is visible inside its own box. Adjacent areas "
        "often differ - an empty slot next to a full one is normal. Never copy an answer from one area to "
        "another and never describe something outside an area under that area's id.\n"
        "- Return exactly one entry per area in existing_identifications, with shape_id equal to the area id.\n"
        "- occupancy: 'occupied' when a package or product body is visible inside the box - including a "
        "box seen from its side, tilted, dark, or with glare on it. An area that shows only shelf backing, "
        "a peg hook, a plastic divider, a price tag or other fixture parts is 'empty'. Use 'unknown' only "
        "when the box itself is unreadable (blur, heavy occlusion).\n"
        "- ocr_text tells you WHICH product is there: a product code in ocr_text means the area is almost "
        "certainly occupied by that product. It is NOT evidence of emptiness - OCR often reads nothing on "
        "occupied areas (glare, tilted or dark packages, boxes seen from the side). Decide 'empty' only "
        "from what you see - fixture parts and backing with no package body - never from an empty "
        "ocr_text.\n"
        "- text: the product code printed largest on the package front (for example '62XL', '564', "
        "'822XL', 'TN-830', 'LC401XL'), corrected from ocr_text where OCR misread it; null when nothing "
        "legible is printed.\n"
        "- brand: the brand shown by the logo or brand name on that package; null when none is visible.\n"
        "- product: the same printed code as text. Never invent part numbers or SKUs that are not printed "
        "on the package.\n"
        "- raw_confidence 0..1: how sure you are of the occupancy and brand judgement for that area. It "
        "applies to 'empty' areas too - a clearly empty slot deserves a high value.\n"
        "- evidence: one short sentence saying what you saw inside the box.\n"
        "- Use null when something is not legible - do not guess.\n"
        "- If you see a product that no area covers, report it ONLY under added_shapes with box_norm "
        "[ymin, xmin, ymax, xmax] in 0-1000 relative to the image you receive, plus product, brand, text, "
        "raw_confidence and evidence.\n\n"
        f"AREAS: {areas_json}\n\n"
        f"{schema_instruction}"
    )
