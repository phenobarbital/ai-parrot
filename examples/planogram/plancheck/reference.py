"""Reference side of the planogram check: planogram + its product descriptions, prices, identity resolution.

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


# Per-position product description, filled in by hand in the planogram JSON (``--init-descriptors`` adds
# them as ``null``). ``display_name`` is what marks a position as described.
DESCRIPTOR_FIELDS: tuple[str, ...] = (
    "display_name",
    "family",
    "xl",
    "colors",
    "pack",
    "identifiers",
    "aliases",
    "price",
)


def _descriptor(product: dict, sku: str) -> tuple[CatalogItem, Decimal | None]:
    """Build the ``CatalogItem`` (and expected price) of one described planogram position.

    Raises:
        ValueError: The position has no brand, or a malformed descriptor field.
    """
    brand = product.get("brand")
    if not brand:
        raise ValueError(f"Position {product.get('position')} ({sku}) has a display_name but no brand")
    extra_ids = [str(i) for i in product.get("identifiers") or []]
    try:
        item = CatalogItem(
            sku=sku,
            brand=str(brand),
            display_name=str(product["display_name"]),
            family=product.get("family"),
            xl=bool(product.get("xl") or False),
            colors=product.get("colors") or [],
            pack=int(product.get("pack") or 1),
            identifiers=list(dict.fromkeys([sku, *extra_ids])),
            aliases=product.get("aliases") or [],
            provenance="planogram",
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Position {product.get('position')} ({sku}): invalid descriptor: {exc}") from exc
    price = product.get("price")
    if price is None:
        return item, None
    try:
        return item, Decimal(str(price))
    except InvalidOperation as exc:
        raise ValueError(f"Position {product.get('position')} ({sku}): non-numeric price {price!r}") from exc


def load_descriptors(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str], dict[str, Decimal]]:
    """Read the product descriptions embedded in the planogram positions.

    A position is *described* when its ``display_name`` is non-empty; its ``family``/``xl``/``colors``/
    ``pack``/``identifiers``/``aliases`` feed identity resolution and ``price`` the expected price. The SKU
    itself is always an identifier. A SKU placed in several positions may be described in any of them, but
    every described occurrence must agree.

    Args:
        path: The planogram JSON (same file as :func:`load_planogram`).
        planogram: Loaded reference, used for the identity-required SKU order.

    Returns:
        ``(catalog, undescribed, prices)``: one catalog item per described SKU, the identity-required SKUs
        with no description (planogram order, no repeats — returned, never raised) and ``{sku: price}``.

    Raises:
        ValueError: A described position without brand, a malformed field, or conflicting descriptions.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items: dict[str, CatalogItem] = {}
    prices: dict[str, Decimal] = {}
    for shelf in data.get("shelves") or []:
        for product in shelf["products"].values():
            sku = str(product["product"])
            if sku.upper() == CLOSEOUT or not str(product.get("display_name") or "").strip():
                continue
            item, price = _descriptor(product, sku)
            if sku in items and items[sku] != item:
                raise ValueError(f"SKU {sku} is described differently in two planogram positions")
            if sku in prices and price is not None and prices[sku] != price:
                raise ValueError(f"SKU {sku} has conflicting prices in the planogram: {prices[sku]} vs {price}")
            items[sku] = item
            if price is not None:
                prices[sku] = price
    order = list(dict.fromkeys(f.sku for f in planogram.facings if f.identity_required))
    undescribed = [sku for sku in order if sku not in items]
    if undescribed:
        logger.warning("Planogram has %d undescribed SKUs (no display_name): %s", len(undescribed), undescribed)
    return Catalog(items=[items[sku] for sku in order if sku in items]), undescribed, prices


def init_descriptor_fields(path: Path) -> int:
    """Add every missing descriptor field as ``null`` to each planogram position, in place.

    Existing values are never touched, so the call is idempotent.

    Returns:
        The number of positions that gained at least one field.
    """
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    changed = 0
    for shelf in data.get("shelves") or []:
        for product in shelf["products"].values():
            missing = [name for name in DESCRIPTOR_FIELDS if name not in product]
            for name in missing:
                product[name] = None
            changed += bool(missing)
    if changed:
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


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
        # An item without a family has no signature: it can only match by identifier or alias.
        if reading.family is None or item.family is None:
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
        # Spec §2 "Decided semantics": rule 2 with reading.xl is None can only produce
        # candidates -- ambiguous even with a single match, never direct.
        if len(signature_matches) == 1 and reading.xl is not None:
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
