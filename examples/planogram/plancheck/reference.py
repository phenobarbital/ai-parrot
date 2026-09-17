"""Reference side of the planogram check: planogram, catalog, prices, identity resolution (FEAT-565).

Pure module: no parrot import, no network. ``resolve_identity`` never sees planogram expectations.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rapidfuzz import fuzz

from .models import Catalog, CatalogItem, PlanogramFacing, PlanogramRef, Resolution, SlotReading

logger = logging.getLogger(__name__)

BRAND_MIN_RATIO = 90.0
ALIAS_MIN_RATIO = 92.0
CLOSEOUT = "CLOSEOUT"


def _norm(text: str) -> str:
    """Casefold and collapse whitespace; the single normaliser used by every comparison."""
    return " ".join(text.casefold().split())


def load_planogram(path: Path) -> PlanogramRef:
    """Load the planogram source JSON into an ordered ``PlanogramRef``.

    Args:
        path: File with ``{"planogram": {...}, "shelves": [...]}``.

    Returns:
        Facings of every shelf ordered by ``slot`` then ``facing`` (never by ``position`` or dict order).

    Raises:
        ValueError: Empty input, duplicate facing ids, or a shelf whose ``slot`` values are not exactly ``1..n``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    shelves = data.get("shelves") or []
    if not shelves:
        raise ValueError(f"Planogram has no shelves: {path}")
    meta = data.get("planogram") or {}
    facings: list[PlanogramFacing] = []
    for shelf in shelves:
        products = sorted(shelf["products"].values(), key=lambda p: int(p["slot"]))
        slots = [int(p["slot"]) for p in products]
        if slots != list(range(1, len(products) + 1)):
            raise ValueError(f"Shelf {shelf.get('shelf_number')}: slots must be exactly 1..n, got {slots}")
        for product in products:
            sku = str(product["product"])
            for index in range(1, int(product.get("facings", 1)) + 1):
                facings.append(
                    PlanogramFacing(
                        facing_id=f"p{int(product['position']):03d}_f{index}",
                        position=int(product["position"]),
                        shelf=int(product["shelf"]),
                        segment=str(product["segment"]),
                        slot=int(product["slot"]),
                        segment_slot=int(product["segment_slot"]),
                        facing=index,
                        sku=sku,
                        brand=product.get("brand"),
                        identity_required=sku.upper() != CLOSEOUT,
                        source_confidence=str(product.get("confidence", "unknown")),
                        reference_read_method=str(product.get("read_method", "unknown")),
                        notes=product.get("notes"),
                    )
                )
    ids = [f.facing_id for f in facings]
    if len(set(ids)) != len(ids):
        raise ValueError("Planogram has duplicate facing ids")
    # Build planogram_id from meta fields
    planogram_id_parts = []
    for key in ("planogram", "fixture", "option"):
        if key in meta and meta[key]:
            part = str(meta[key])
            part = re.sub(r"[^a-zA-Z0-9]+", "-", part.casefold())
            planogram_id_parts.append(part)
    if not planogram_id_parts:
        planogram_id_parts.append(Path(path).stem)
    planogram_id = "-".join(planogram_id_parts)
    return PlanogramRef(
        planogram_id=planogram_id,
        source=str(meta.get("source", path)),
        shelf_count=len(shelves),
        facings=facings,
    )


def load_catalog(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str]]:
    """Load the user-supplied catalog and report planogram SKUs it does not cover.

    Args:
        path: JSON file shaped as ``Catalog`` (``{"items": [CatalogItem, ...]}``).
        planogram: Loaded reference, used only to compute coverage.

    Returns:
        ``(catalog, missing)`` where ``missing`` lists, in planogram order and without repeats, the
        identity-required SKUs that have no catalog item. Missing SKUs are returned, never raised.

    Raises:
        ValueError: Invalid catalog file or duplicate ``sku`` entries.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
        catalog = Catalog.model_validate_json(text)
    except Exception as e:
        raise ValueError(f"Invalid catalog file {path}: {e}") from e
    # Check for duplicate SKUs
    seen_skus = set()
    for item in catalog.items:
        if item.sku in seen_skus:
            raise ValueError(f"Duplicate SKU in catalog: {item.sku}")
        seen_skus.add(item.sku)
    # Compute missing SKUs
    missing_skus: list[str] = []
    seen_in_catalog = set()
    for facing in planogram.facings:
        if facing.identity_required and facing.sku not in seen_in_catalog:
            if catalog.by_sku(facing.sku) is None:
                missing_skus.append(facing.sku)
            seen_in_catalog.add(facing.sku)
    if missing_skus:
        logger.warning(f"Catalog missing {len(missing_skus)} identity-required SKUs: {missing_skus}")
    return catalog, missing_skus


def load_prices(path: Path) -> dict[str, Decimal]:
    """Load expected prices ``{"<sku>": "29.99"}`` as Decimals.

    Raises:
        ValueError: The file is not a JSON object or a value is not numeric.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Prices file must be a JSON object, got {type(data).__name__}")
    result: dict[str, Decimal] = {}
    for sku, value in data.items():
        try:
            result[sku] = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"Non-numeric price for SKU {sku}: {value}") from exc
    return result


def emit_catalog_template(planogram: PlanogramRef, path: Path) -> None:
    """Write a fill-in catalog skeleton: one item per distinct identity-required SKU.

    Each item pre-fills ``sku``, ``brand`` (empty string when the planogram has none), ``identifiers=[sku]``,
    ``display_name=""`` and leaves the descriptor fields at their defaults.

    Raises:
        FileExistsError: ``path`` already exists (never overwritten).
    """
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing catalog: {target}")
    # Build ordered-unique items
    seen_skus = set()
    items: list[CatalogItem] = []
    for facing in planogram.facings:
        if facing.identity_required and facing.sku not in seen_skus:
            items.append(
                CatalogItem(
                    sku=facing.sku,
                    brand=facing.brand or "",
                    display_name="",
                    identifiers=[facing.sku],
                )
            )
            seen_skus.add(facing.sku)
    catalog = Catalog(items=items)
    target.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")


def normalize_brand(text: str | None, catalog: Catalog) -> str | None:
    """Map free text to a catalog brand.

    Exact casefold match first; otherwise the single best ``fuzz.ratio`` (both sides casefolded) when it is
    ``>= BRAND_MIN_RATIO``. Returns the catalog's own spelling, or ``None``.
    """
    if not text or not text.strip():
        return None
    brands = sorted({item.brand for item in catalog.items if item.brand})
    norm_text = _norm(text)
    # Exact match
    for brand in brands:
        if _norm(brand) == norm_text:
            return brand
    # Fuzzy match
    best_brand = None
    best_score = -1.0
    second_score = -1.0
    for brand in brands:
        score = fuzz.ratio(norm_text, _norm(brand))
        if score > best_score:
            second_score = best_score
            best_score = score
            best_brand = brand
        elif score > second_score:
            second_score = score
    if best_brand and best_score >= BRAND_MIN_RATIO and best_score > second_score:
        return best_brand
    return None


def resolve_identity(reading: SlotReading, catalog: Catalog) -> tuple[str | None, list[str], Resolution]:
    """Map a reading to a SKU using the three rules in order.

    Returns ``(sku, candidate_skus, resolution)`` where ``resolution`` is ``"direct"`` (one SKU),
    ``"ambiguous"`` (``sku is None``, several candidates, catalog order) or ``"unresolved"`` (``None, []``).
    Never uses planogram expectations.
    """
    brand = normalize_brand(reading.brand, catalog)
    if brand is None:
        return None, [], "unresolved"
    items = [item for item in catalog.items if _norm(item.brand) == _norm(brand)]
    # Rule 1: identifier
    if reading.visible_text:
        norm_texts = {_norm(line) for line in reading.visible_text}
        identifier_matches = [item for item in items if any(_norm(id_) in norm_texts for id_ in item.identifiers)]
        if identifier_matches:
            if len(identifier_matches) == 1:
                return identifier_matches[0].sku, [identifier_matches[0].sku], "direct"
            return None, [item.sku for item in identifier_matches], "ambiguous"
    # Rule 2: descriptor signature
    signature_matches = []
    for item in items:
        if reading.family is None:
            continue
        if _norm(item.family) != _norm(reading.family):
            continue
        if item.colors and reading.colors:
            if {_norm(c) for c in item.colors} != {_norm(c) for c in reading.colors}:
                continue
        if reading.pack is not None and item.pack != reading.pack:
            continue
        if reading.xl is not None and item.xl != reading.xl:
            continue
        signature_matches.append(item)
    if signature_matches:
        if len(signature_matches) == 1:
            return signature_matches[0].sku, [signature_matches[0].sku], "direct"
        return None, [item.sku for item in signature_matches], "ambiguous"
    # Rule 3: alias
    if reading.visible_text:
        norm_texts = [_norm(line) for line in reading.visible_text]
        alias_matches = []
        for item in items:
            for alias in item.aliases:
                for text_line in norm_texts:
                    if fuzz.token_set_ratio(_norm(alias), text_line) >= ALIAS_MIN_RATIO:
                        alias_matches.append(item)
                        break
        if alias_matches:
            if len(alias_matches) == 1:
                return alias_matches[0].sku, [alias_matches[0].sku], "direct"
            return None, [item.sku for item in alias_matches], "ambiguous"
    return None, [], "unresolved"
