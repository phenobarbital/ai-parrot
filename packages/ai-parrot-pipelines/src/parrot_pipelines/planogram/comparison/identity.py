"""Shared, descriptor-aware identity resolution: photo evidence -> one catalogue product id (FEAT-612)."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz

from ..contracts import Identification
from .definition import Descriptors, FacingDefinition, SlotsDefinition

ALIAS_MIN_RATIO = 92.0
DEFAULT_VOCABULARY: Tuple[str, ...] = ("family", "colors", "pack", "xl")
DEFAULT_REQUIRED_FIELDS: Tuple[str, ...] = ("family", "xl")
_LINE_SPLIT = re.compile(r"\s*(?:\n|\|)\s*")
_TYPED_FIELDS = frozenset(Descriptors.model_fields) - {"attributes"}


def _norm(text: Optional[str]) -> str:
    """Casefold/strip; empty string for None."""
    return str(text).casefold().strip() if text else ""


def _text_lines(identification: Identification) -> List[str]:
    """Normalised text lines the identification carries: read product, text (OCR/LLM) and evidence."""
    raw: List[str] = []
    for chunk in (identification.product, identification.text, *identification.evidence):
        if chunk:
            raw.extend(_LINE_SPLIT.split(str(chunk)))
    return [line for line in (_norm(r) for r in raw) if line]


def _name_lines(identification: Identification) -> List[str]:
    """Normalised lines that name the product: read product and text, never free-form evidence."""
    raw: List[str] = []
    for chunk in (identification.product, identification.text):
        if chunk:
            raw.extend(_LINE_SPLIT.split(str(chunk)))
    return [line for line in (_norm(r) for r in raw) if line]


def _contained(name: str, line: str) -> bool:
    """Whether ``name`` appears in ``line`` as whole tokens ("et-2980" in "ecotank et-2980", not in "et-29800")."""
    return bool(name) and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", line) is not None


def names_product(text: Optional[str], product: Optional[str]) -> bool:
    """Whether read text names a catalogue product (the product id appears in it as whole tokens)."""
    name = _norm(product)
    return bool(name) and any(_contained(name, line) for line in _LINE_SPLIT.split(_norm(text)) if line)


def _by_containment(pool: Sequence[FacingDefinition], lines: Sequence[str]) -> List[FacingDefinition]:
    """Facings whose product id or identifier is contained in a naming line.

    A name nested in a longer matched name ("et-2980" inside "et-2980 pro") is that longer product.
    """
    found: List[Tuple[str, FacingDefinition]] = []
    for facing in pool:
        for name in (_norm(name) for name in (facing.product, *facing.descriptors.identifiers) if name):
            if any(_contained(name, line) for line in lines):
                found.append((name, facing))
    names = {name for name, _ in found}
    return [
        facing
        for name, facing in found
        if not any(len(other) > len(name) and _contained(name, other) for other in names)
    ]


def _dedupe(facings: Sequence[FacingDefinition]) -> List[str]:
    """Distinct product ids in definition order."""
    seen: List[str] = []
    for facing in facings:
        if facing.product not in seen:
            seen.append(facing.product)
    return seen


def _observed(value: Any) -> bool:
    """A read value counts as observed unless it is None, an empty string, list, or dict."""
    return value is not None and value != "" and value != [] and value != {}


def _expected(descriptors: Descriptors, field: str) -> Any:
    """Expected value of ``field``: typed descriptor field or custom attribute."""
    return getattr(descriptors, field) if field in _TYPED_FIELDS else descriptors.attributes.get(field)


def _agrees(read: Any, expected: Any) -> bool:
    """Whether a read value agrees with an expected descriptor value."""
    if isinstance(expected, list) and isinstance(read, list):
        return {_norm(item) for item in read} == {_norm(item) for item in expected}
    if isinstance(expected, list):
        return _norm(read) in {_norm(item) for item in expected}
    if isinstance(expected, bool):
        return bool(read) == expected
    return _norm(str(read)) == _norm(str(expected))


def resolve_identity(
    identification: Identification,
    definition: SlotsDefinition,
    *,
    vocabulary: Sequence[str] = DEFAULT_VOCABULARY,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
) -> tuple[str | None, list[str]]:
    """Resolve photo evidence to one catalogue id, or return unresolved candidates.

    Rules run in order: exact identifier, descriptor signature, a catalogue name contained in the
    read name, and fuzzy alias. Expected-empty
    facings never participate, and no expected slot is used to select an identity.

    Args:
        identification: What the model or OCR read for one observed target.
        definition: The slots definition containing the catalogue products.
        vocabulary: Descriptor fields compared for contradictions.
        required_fields: Fields whose observation gates signature resolution.

    Returns:
        A resolved product and its candidate list, or ``(None, candidates)``.
    """
    facings = [facing for facing in definition.all_facings() if facing.expected_occupancy == "occupied"]
    brand = _norm(identification.brand)
    pool = [facing for facing in facings if not brand or _norm(facing.brand) == brand]
    if brand and not pool:
        return None, []
    lines = set(_text_lines(identification))

    if lines:
        by_identifier = [
            facing
            for facing in pool
            if any(_norm(identifier) in lines for identifier in facing.descriptors.identifiers if identifier)
        ]
        ids = _dedupe(by_identifier)
        if len(ids) == 1:
            return ids[0], ids
        if ids:
            return None, ids

    read = identification.descriptors or {}
    if required_fields and _observed(read.get(required_fields[0])):
        compared_fields = list(dict.fromkeys([*vocabulary, *required_fields]))
        compared_fields.remove(required_fields[0])
        matches: List[FacingDefinition] = []
        for facing in pool:
            anchor = _expected(facing.descriptors, required_fields[0])
            if not _observed(anchor) or not _agrees(read.get(required_fields[0]), anchor):
                continue
            if any(
                _observed(read.get(field))
                and _observed(expected := _expected(facing.descriptors, field))
                and not _agrees(read.get(field), expected)
                for field in compared_fields
            ):
                continue
            matches.append(facing)
        ids = _dedupe(matches)
        if ids:
            if len(ids) == 1 and all(_observed(read.get(field)) for field in required_fields):
                return ids[0], ids
            return None, ids

    ids = _dedupe(_by_containment(pool, _name_lines(identification)))
    if len(ids) == 1:
        return ids[0], ids
    if ids:
        return None, ids

    if lines:
        alias_matches = [
            facing
            for facing in pool
            if any(
                fuzz.token_set_ratio(_norm(alias), line) >= ALIAS_MIN_RATIO
                for alias in facing.descriptors.aliases
                if alias
                for line in lines
            )
        ]
        ids = _dedupe(alias_matches)
        if len(ids) == 1:
            return ids[0], ids
        if ids:
            return None, ids
    return None, []
