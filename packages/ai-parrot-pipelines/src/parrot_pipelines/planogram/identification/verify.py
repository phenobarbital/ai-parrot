"""Closed-set, evidence-gated verification of unresolved identifications."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from pydantic import BaseModel, Field

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition
from parrot_pipelines.planogram.contracts import CycleContext, Identification
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png

logger = logging.getLogger(__name__)

VERIFY_PROMPT_VERSION: str = "verify-v1"
VERIFY_STAGE: str = "verify"
CHOICE_OTHER: str = "other"
CHOICE_CANNOT_TELL: str = "cannot_tell"
_MIN_TOKEN = 3
_TOKEN_SPLIT = re.compile(r"[\s,;/|()]+")
_COMPARABLE_FIELDS = ("family", "xl", "pack")


class VerificationAnswer(BaseModel):
    """LLM structured output for one crop."""

    choice: str = Field(description="One of the offered product ids, 'other' or 'cannot_tell'")
    visible_text: List[str] = Field(default_factory=list, description="Text actually legible in the crop")
    evidence: str = Field(default="", description="One sentence: what in the crop supports the choice")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _norm(value: object) -> Optional[str]:
    """Casefolded string or None for empty values."""
    if value is None:
        return None
    text = str(value).casefold().strip()
    return text or None


def _partial_read(identification: Identification) -> bool:
    """True when the identification read a brand or at least one descriptor field."""
    if _norm(identification.brand):
        return True
    return any(value not in (None, "", [], {}) for value in identification.descriptors.values())


def pick_candidates(identification: Identification, definition: SlotsDefinition, n: int) -> List[FacingDefinition]:
    """Up to ``n + 1`` distinct-product candidates compatible with the PARTIAL READ (brand / descriptors).

    Returns [] when the identification has no partial read — a closed set is never built from expectation alone.

    Args:
        identification: The unresolved identification.
        definition: The slots definition.
        n: Number of distractors (candidates returned: at most ``n + 1``).

    Returns:
        Candidate facings (one per distinct product), described ones first, then by product id.
    """
    if not _partial_read(identification):
        return []
    brand = _norm(identification.brand)
    read = {k: _norm(identification.descriptors.get(k)) for k in _COMPARABLE_FIELDS}
    by_product: Dict[str, FacingDefinition] = {}
    for facing in definition.all_facings():
        if brand and _norm(facing.brand) != brand:
            continue
        contradicts = False
        for key, observed in read.items():
            expected = _norm(getattr(facing.descriptors, key))
            if observed and expected and observed != expected:
                contradicts = True
                break
        if contradicts:
            continue
        current = by_product.get(facing.product)
        if current is None or (not current.descriptors.described and facing.descriptors.described):
            by_product[facing.product] = facing
    ordered = sorted(by_product.values(), key=lambda f: (not f.descriptors.described, f.product))
    return ordered[: n + 1]


def option_order(shape_id: str, products: Sequence[str]) -> List[str]:
    """Deterministic order seeded by sha256(shape_id|product) — no option is systematically first."""
    return sorted(set(products), key=lambda p: hashlib.sha256(f"{shape_id}|{p}".encode("utf-8")).hexdigest())


def _tokens(candidate: FacingDefinition) -> Set[str]:
    """Discriminating-token pool of a candidate: identifiers, aliases, family, display-name words (len >= 3)."""
    d = candidate.descriptors
    raw: List[str] = [*d.identifiers, *d.aliases]
    if d.family:
        raw.append(d.family)
    if d.display_name:
        raw.extend(_TOKEN_SPLIT.split(d.display_name))
    return {t.casefold().strip() for t in raw if t and len(t.strip()) >= _MIN_TOKEN}


def _evidence_supports(
    answer: VerificationAnswer, candidate: FacingDefinition, others: Sequence[FacingDefinition] = ()
) -> bool:
    """True only when ``visible_text`` cites a discriminating token of ``candidate``.

    An offered SKU is never evidence by itself: the token must come from the crop (visible_text), not the prompt.
    Tokens shared with another offered candidate do not discriminate and are ignored.

    Args:
        answer: The verification answer.
        candidate: The chosen candidate.
        others: The other offered candidates.

    Returns:
        Whether the crop's visible text supports the choice.
    """
    shared: Set[str] = set()
    for other in others:
        if other.product != candidate.product:
            shared |= _tokens(other)
    tokens = _tokens(candidate) - shared
    visible = " ".join(answer.visible_text).casefold()
    return bool(visible) and any(token in visible for token in tokens)


def crop_and_encode(image: np.ndarray, box: Tuple[int, int, int, int], pad: float = 0.08) -> bytes:
    """Padded crop clamped to the image, PNG bytes. Picklable (CPU executor).

    Args:
        image: Source BGR image.
        box: ``(x1, y1, x2, y2)`` in source pixels.
        pad: Padding per side, as a fraction of the box size.

    Returns:
        PNG bytes of the crop.
    """
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box
    dx, dy = int(round(pad * (x2 - x1))), int(round(pad * (y2 - y1)))
    x1, y1 = max(0, x1 - dx), max(0, y1 - dy)
    x2, y2 = min(width, x2 + dx), min(height, y2 + dy)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("empty crop")
    return encode_png(image[y1:y2, x1:x2].copy())


def _prompt(options: Sequence[FacingDefinition]) -> str:
    """Closed-set prompt: offered products + the two escape choices; visible text is mandatory."""
    listing = json.dumps(
        [{"product": o.product, "name": o.descriptors.display_name or o.product} for o in options],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (
        "Look at this crop of a retail shelf. Which product is it? Choose exactly one option: one of the "
        f"offered products, '{CHOICE_OTHER}' (a product not in the list) or '{CHOICE_CANNOT_TELL}'.\n"
        "List in visible_text ONLY the text you can actually read in the crop — never copy it from the "
        "options. A product choice without supporting visible text is treated as cannot_tell.\n"
        "Give one sentence of evidence and a confidence 0..1.\n\n"
        f"OPTIONS: {listing}"
    )


async def _verify_one(
    image: np.ndarray,
    identification: Identification,
    box: DetectionBox,
    candidates: List[FacingDefinition],
    ctx: CycleContext,
) -> Identification:
    """Verify one identification; returns it unchanged unless the evidence gate passes."""
    order = option_order(identification.shape_id, [c.product for c in candidates])
    by_product = {c.product: c for c in candidates}
    options = [by_product[p] for p in order]
    try:
        png = await ctx.executor.run(crop_and_encode, image, (box.x1, box.y1, box.x2, box.y2))
        answer = await ctx.vision.ask(
            _prompt(options), [png], VerificationAnswer, stage=VERIFY_STAGE, prompt_version=VERIFY_PROMPT_VERSION
        )
    except (VisionError, ValueError) as exc:
        ctx.errors.append(f"verify {identification.shape_id}: {exc}")
        return identification
    chosen = by_product.get(answer.choice)
    if chosen is None:  # other / cannot_tell / not offered
        return identification
    if not _evidence_supports(answer, chosen, options):
        logger.debug("verify %s: choice %s without visible evidence", identification.shape_id, answer.choice)
        return identification
    return identification.model_copy(
        update={
            "product": chosen.product,
            "uncertain": False,
            "evidence": [*identification.evidence, f"verify: {answer.evidence}"],
            "raw_confidence": answer.confidence,
        }
    )


async def verify_unresolved(
    image: np.ndarray,
    identifications: List[Identification],
    definition: SlotsDefinition,
    ctx: CycleContext,
    *,
    n_distractors: int = 3,
    boxes: Optional[Dict[str, DetectionBox]] = None,
) -> List[Identification]:
    """Closed-set pass for unresolved slots. An offered expected SKU is never evidence by itself.

    Returns a NEW list, same order and length. Untouched when: already resolved, no box, no partial read,
    choice is other/cannot_tell/not offered, evidence gate fails, or the call failed (error → ctx.errors).

    Args:
        image: Untouched full-resolution BGR image.
        identifications: Identifications of the image.
        definition: The slots definition (candidate products).
        ctx: Per-run services.
        n_distractors: Distractors per closed set (at most ``n + 1`` options).
        boxes: ``shape_id -> DetectionBox`` crops (identifications carry no geometry).

    Returns:
        A new list, same order and length.
    """
    boxes = boxes or {}
    result = list(identifications)
    coroutines = []
    indexes: List[int] = []
    for index, ident in enumerate(identifications):
        if ident.product is not None and not ident.uncertain:
            continue
        box = boxes.get(ident.shape_id)
        if box is None:
            continue
        candidates = pick_candidates(ident, definition, n_distractors)
        if not candidates:
            continue
        indexes.append(index)
        coroutines.append(_verify_one(image, ident, box, candidates, ctx))
    for index, verified in zip(indexes, await asyncio.gather(*coroutines), strict=True):
        result[index] = verified
    return result
