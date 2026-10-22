"""Post-identify guard against a neighbouring product spilling into an adjacent slot area."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from parrot_pipelines.planogram.contracts import Identification, Slot

logger = logging.getLogger(__name__)

SPILL_EVIDENCE: str = "neighbour_spill"
_EMPTY_TOKENS = frozenset({"", "none", "null", "unknown", "n/a", "na", "empty", "empty slot"})


def _meaningful(value: Any) -> bool:
    """Whether a structured identity value says something (``False``/blank/"none" do not)."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in _EMPTY_TOKENS
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_meaningful(item) for item in value)
    return bool(value)


def _norm(value: Any) -> Optional[str]:
    """Casefolded comparable form of a meaningful value, else None."""
    return str(value).casefold().strip() if _meaningful(value) else None


def _occupied(ident: Identification) -> bool:
    """A reliable, occupied observation."""
    return not ident.uncertain and ident.occupancy == "occupied"


def _brand_only(ident: Identification) -> bool:
    """Occupied with a brand but no product code."""
    return _occupied(ident) and _norm(ident.brand) is not None and not _meaningful(ident.product)


def _richer(ident: Identification) -> bool:
    """Carries identity beyond the brand (product, text or a descriptor value)."""
    return _meaningful(ident.product) or _meaningful(ident.text) or _meaningful(ident.descriptors)


def _own_identity(suspect: Identification, neighbour: Identification) -> bool:
    """The suspect read text or a descriptor the neighbour does not share, so it saw its own product."""
    if _norm(suspect.text) is not None and _norm(suspect.text) != _norm(neighbour.text):
        return True
    return any(
        _norm(value) is not None and _norm(value) != _norm(neighbour.descriptors.get(name))
        for name, value in suspect.descriptors.items()
    )


def suppress_neighbour_spill(identifications: Sequence[Identification], slots: Sequence[Slot]) -> List[Identification]:
    """Mark brand-only slot readings that merely repeat an adjacent, better-read slot as uncertain.

    Slot areas are bounded by the midpoints between price tags, so a wide or offset package over one
    tag often reaches into the neighbouring slot area: the model then reports that empty slot as
    occupied by the same brand without being able to read a product code. Such a reading is turned
    ``uncertain`` (never ``empty``: emptiness is not proven) when an adjacent slot of the same row is
    occupied by the same brand, carries richer identity, and the suspect read nothing of its own.

    Args:
        identifications: Identifications of ONE image (slot ids as ``shape_id``).
        slots: The slots of that image.

    Returns:
        The identifications in their original order, suspects replaced by uncertain copies.
    """
    by_id: Dict[str, Identification] = {ident.shape_id: ident for ident in identifications}
    position: Dict[Tuple[int, int], Slot] = {(slot.row_index, slot.slot_index): slot for slot in slots}
    replaced: Dict[str, Identification] = {}
    for slot in slots:
        suspect = by_id.get(slot.slot_id)
        if suspect is None or not _brand_only(suspect):
            continue
        for offset in (-1, 1):
            other = position.get((slot.row_index, slot.slot_index + offset))
            neighbour = by_id.get(other.slot_id) if other is not None else None
            if (
                neighbour is None
                or not _occupied(neighbour)
                or _norm(neighbour.brand) != _norm(suspect.brand)
                or not _richer(neighbour)
                or _own_identity(suspect, neighbour)
            ):
                continue
            logger.info(
                "%s: brand-only reading of %s repeats neighbour %s; marked uncertain",
                suspect.image_id,
                slot.slot_id,
                neighbour.shape_id,
            )
            replaced[slot.slot_id] = suspect.model_copy(
                update={
                    "uncertain": True,
                    "evidence": [
                        *suspect.evidence,
                        f"{SPILL_EVIDENCE}: identity repeats adjacent {neighbour.shape_id}",
                    ],
                }
            )
            break
    return [replaced.get(ident.shape_id, ident) for ident in identifications]
