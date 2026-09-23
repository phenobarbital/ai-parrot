"""Closed-set identification prompt for Nova (FEAT-592).

Deliberately example-local: the shared ``build_identify_prompt`` must NOT mention a
planogram or expected products (verified: identify.py:125).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import BaseModel

#: Distinct from IDENTIFY_PROMPT_VERSION / IDENTIFY_STAGE (verified: identify.py:33-34)
#: so cache entries can never collide — cache_key mixes both (verified: vision.py:63).
NOVA_PROMPT_VERSION: str = "nova-closed-set-v1"
NOVA_STAGE: str = "identify-nova"


class PlanogramVocabulary(BaseModel):
    """Closed-set candidates: ``product`` and ``brand`` ONLY (resolved decision)."""

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
    """Closed-set counterpart of build_identify_prompt (verified: identify.py:119).

    Keeps that function's AREAS contract verbatim and differs in exactly one way: it
    offers the planogram's products and brands as expected candidates.

    Returns:
        The prompt text.
    """
    areas_json = json.dumps(list(areas), separators=(",", ":"), ensure_ascii=False)
    products_json = json.dumps(vocabulary.products, ensure_ascii=False)
    brands_json = json.dumps(vocabulary.brands, ensure_ascii=False)
    return (
        "You are analysing a retail shelf image using a planogram's expected product and brand candidates. "
        "Below is a list of numbered AREAS in this image; each has an id, an optional mark (the number drawn "
        "on its outline), a box_2d as [ymin, xmin, ymax, xmax] normalised to 0-1000 relative to the image "
        "you receive, and the text a local OCR read inside it (ocr_text, may be empty or wrong).\n\n"
        f"EXPECTED PRODUCTS: {products_json}\n"
        f"EXPECTED BRANDS: {brands_json}\n"
        "Use these as expected candidates when identifying packages. If the package clearly shows something "
        "else, answer with the product or brand outside these lists rather than forcing a candidate.\n\n"
        "INSTRUCTIONS:\n"
        "- Report on each listed area ONLY from what is visible inside its own box. Never describe something "
        "outside an area under that area's id.\n"
        "- Return exactly one entry per area in existing_identifications, with shape_id equal to the area id.\n"
        "- Confirm or correct ocr_text in the text field.\n"
        "- For each area report: occupancy ('occupied', 'empty' or 'unknown'), product (the model/SKU text "
        "you can read), brand, raw_confidence 0..1, and evidence: one short sentence saying what you saw.\n"
        "- Use null when something is not legible - do not guess.\n"
        "- If you see a product that no area covers, report it ONLY under added_shapes with box_norm "
        "[ymin, xmin, ymax, xmax] in 0-1000 relative to the image you receive, plus product, brand, text, "
        "raw_confidence and evidence.\n\n"
        f"AREAS: {areas_json}\n\n"
        f"{schema_instruction}"
    )
