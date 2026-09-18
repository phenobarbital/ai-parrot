"""Multi-photo merge, position statuses, credits and metrics (FEAT-565, Module 10).

Pure functions — no I/O, no LLM, no ``parrot`` import. Price never influences a status.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from plancheck.models import (
    BrandShare,
    Catalog,
    ComplianceSummary,
    PlanogramFacing,
    PlanogramRef,
    PositionResult,
    PositionStatus,
    PriceCompliance,
    PriceReading,
    Resolution,
    ScoringWeights,
    ShelfScore,
    SlotObservation,
)

logger = logging.getLogger(__name__)

UNCOVERED: frozenset[str] = frozenset({"not_visible", "not_assessed", "conflict"})
OCCUPIED: frozenset[str] = frozenset(
    {"match", "misplaced", "variant_unresolved", "mismatch", "inferred_present", "occupied_unassigned"}
)
UNKNOWN_BRAND = "unknown"


def _pct(numerator: float, denominator: float) -> float | None:
    """Percentage 0–100 rounded to 2 decimals; ``None`` when the denominator is 0."""
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _share(numerator: float, denominator: float) -> float | None:
    """Fraction 0–1 rounded to 4 decimals; ``None`` when the denominator is 0."""
    return round(numerator / denominator, 4) if denominator else None


def _norm(text: str | None) -> str | None:
    """Casefold/strip a brand or family token; ``None`` stays ``None``."""
    return text.casefold().strip() if text else None


def _is_reliable(obs: SlotObservation) -> bool:
    """Occupied with usable visibility, or empty with FULL visibility."""
    if obs.reading is None:
        return False
    if obs.reading.visibility == "unusable":
        return False
    if obs.reading.occupancy == "uncertain":
        return False
    if obs.reading.occupancy == "occupied":
        return True
    if obs.reading.occupancy == "empty" and obs.reading.visibility == "full":
        return True
    return False


def _merge_price(views: list[SlotObservation]) -> PriceReading | None:
    """Merge tag prices of one facing across photos by normalised Decimal amount."""
    # Get all views with readable prices
    read_views = [obs for obs in views if obs.price and obs.price.status == "read"]

    if not read_views:
        # No read views, look for the best of other statuses
        for status in ["partial", "unreadable", "not_assessed"]:
            status_views = [obs for obs in views if obs.price and obs.price.status == status]
            if status_views:
                # Return the first one by slot_id order
                return sorted(status_views, key=lambda obs: obs.slot.slot_id)[0].price
        return None

    # Group by normalized amount
    amount_groups = defaultdict(list)
    for obs in read_views:
        if obs.price.amount is not None:
            amount_groups[obs.price.amount].append(obs)

    if len(amount_groups) == 1:
        # All amounts are the same
        return list(amount_groups.values())[0][0].price
    else:
        # Conflict: different amounts
        # Sort by slot_id to ensure consistent ordering
        sorted_views = sorted(read_views, key=lambda obs: obs.slot.slot_id)
        raws = [obs.price.raw for obs in sorted_views if obs.price.raw]
        first_price = sorted_views[0].price

        return PriceReading(
            raw=" | ".join(raws) if raws else None,
            amount=None,
            currency=None,
            source=first_price.source,
            status="conflict",
        )


def _decide(
    facing: PlanogramFacing,
    views: list[SlotObservation],
    catalog: Catalog,
    direct_elsewhere_on_shelf: bool,
) -> tuple[PositionStatus, Resolution | None, SlotObservation | None]:
    """Apply the 10-step decision list. Returns (status, deciding resolution, deciding view)."""
    # Step 1: no views → not_visible
    if not views:
        return "not_visible", None, None

    # Step 2: no reliable view → not_assessed
    reliable_views = [obs for obs in views if _is_reliable(obs)]
    if not reliable_views:
        return "not_assessed", None, None

    # Step 3: reliable views contain both occupied and empty, or ≥ 2 distinct direct SKUs → conflict
    occupied_reliable = [obs for obs in reliable_views if obs.reading and obs.reading.occupancy == "occupied"]
    empty_reliable = [obs for obs in reliable_views if obs.reading and obs.reading.occupancy == "empty"]

    direct_views = [obs for obs in views if obs.resolution == "direct" and obs.resolved_sku]
    direct_skus = {obs.resolved_sku for obs in direct_views if obs.resolved_sku}

    if (occupied_reliable and empty_reliable) or len(direct_skus) >= 2:
        return "conflict", None, None

    # Step 4: all reliable views empty → empty
    if reliable_views and not occupied_reliable:
        return "empty", None, None

    # From here on, we have at least one occupied reliable view
    occupied_views = occupied_reliable

    # Step 5: not identity_required → occupied_unassigned
    if not facing.identity_required:
        return "occupied_unassigned", None, occupied_views[0]

    expected_sku = facing.sku

    # Step 6: direct match or verified_by_expectation match
    direct_match_views = [obs for obs in direct_views if obs.resolved_sku == expected_sku]
    if direct_match_views:
        return "match", "direct", direct_match_views[0]

    # Check for verified_by_expectation match (only if no direct to another SKU)
    other_direct_views = [obs for obs in direct_views if obs.resolved_sku != expected_sku]
    if not other_direct_views:
        verified_views = [
            obs for obs in views if obs.resolution == "verified_by_expectation" and obs.resolved_sku == expected_sku
        ]
        if verified_views:
            return "match", "verified_by_expectation", verified_views[0]

    # Step 7: misplaced (direct elsewhere on same shelf)
    if direct_elsewhere_on_shelf:
        return "misplaced", None, None

    # Step 8: variant_unresolved
    # Check for ambiguous view with expected SKU in candidates
    ambiguous_views = [obs for obs in views if obs.resolution == "ambiguous"]
    for obs in ambiguous_views:
        if expected_sku in obs.candidate_skus:
            return "variant_unresolved", None, obs

    # Check for unresolved/ambiguous/inferred view with matching brand and family
    catalog_item = catalog.by_sku(expected_sku)
    if catalog_item and catalog_item.brand and catalog_item.family:
        expected_brand_norm = _norm(catalog_item.brand)
        expected_family_norm = _norm(catalog_item.family)

        for obs in views:
            if obs.resolution in {"unresolved", "ambiguous", "inferred"}:
                if obs.reading and obs.reading.brand:
                    observed_brand_norm = _norm(obs.reading.brand)
                    if observed_brand_norm == expected_brand_norm:
                        observed_family_norm = _norm(obs.reading.family)
                        if observed_family_norm == expected_family_norm:
                            return "variant_unresolved", None, obs

    # Step 9: mismatch
    # Direct or verified_by_expectation to different SKU
    different_sku_views = [
        obs
        for obs in views
        if obs.resolution in {"direct", "verified_by_expectation"}
        and obs.resolved_sku
        and obs.resolved_sku != expected_sku
    ]
    if different_sku_views:
        return "mismatch", None, different_sku_views[0]

    # Observed brand differs from expected brand
    if catalog_item and catalog_item.brand:
        expected_brand_norm = _norm(catalog_item.brand)
        for obs in occupied_views:
            if obs.reading and obs.reading.brand:
                observed_brand_norm = _norm(obs.reading.brand)
                if observed_brand_norm and observed_brand_norm != expected_brand_norm:
                    return "mismatch", None, obs

    # Step 10: inferred_present
    return "inferred_present", None, occupied_views[0]


def _credits(
    status: PositionStatus,
    resolution: Resolution | None,
    facing: PlanogramFacing,
    views: list[SlotObservation],
    weights: ScoringWeights,
) -> tuple[float, float]:
    """Return (strict_credit, lenient_credit)."""
    # Identity not required facings always get 0 credits
    if not facing.identity_required:
        return 0.0, 0.0

    # Strict credit calculation
    strict_credit = 0.0
    if status == "match" and resolution == "direct":
        # Check if at least one direct matching view has registration_grade != "low"
        direct_match_views = [
            obs
            for obs in views
            if obs.resolution == "direct" and obs.resolved_sku == facing.sku and obs.registration_grade != "low"
        ]
        if direct_match_views:
            strict_credit = 1.0

    # Lenient credit calculation
    lenient_credit = 0.0
    if status == "match":
        if resolution == "direct":
            lenient_credit = 1.0
        elif resolution == "verified_by_expectation":
            lenient_credit = weights.verified_by_expectation
    elif status == "misplaced":
        lenient_credit = weights.misplaced
    elif status == "variant_unresolved":
        lenient_credit = weights.variant_unresolved
    elif status == "inferred_present":
        lenient_credit = weights.inferred_present

    return strict_credit, lenient_credit


def merge_positions(
    planogram: PlanogramRef,
    observations: list[SlotObservation],
    catalog: Catalog,
    weights: ScoringWeights,
    prices: dict[str, Decimal] | None,
) -> list[PositionResult]:
    """One result per expected facing using the §2 status decision list and credits.

    Args:
        planogram: Expected facings (outer list order preserved).
        observations: Every observation of every slot of every photo (unfiltered).
        catalog: Product definitions (may be empty).
        weights: Lenient partial-credit multipliers.
        prices: Map of known SKUs to reference prices (optional).

    Returns:
        One result per ``planogram.facings``, in the same order. Every contributing
        ``slot_id`` is retained in ``PositionResult.slot_ids`` (sorted).
    """
    # Group observations by facing_id
    observations_by_facing = defaultdict(list)
    for obs in observations:
        if obs.facing_id:
            observations_by_facing[obs.facing_id].append(obs)

    # Build same-shelf direct index for misplaced detection
    direct_by_shelf_and_sku = defaultdict(lambda: defaultdict(set))
    for obs in observations:
        if obs.facing_id and obs.resolution == "direct" and obs.resolved_sku:
            # Find the facing this observation belongs to, to get shelf info
            facing = next((f for f in planogram.facings if f.facing_id == obs.facing_id), None)
            if facing:
                direct_by_shelf_and_sku[facing.shelf][obs.resolved_sku].add(obs.facing_id)

    results = []
    for facing in planogram.facings:
        views = observations_by_facing.get(facing.facing_id, [])

        # Sort views by slot_id for consistent ordering
        views.sort(key=lambda obs: obs.slot.slot_id)

        # Check if expected SKU is directly observed elsewhere on the same shelf
        direct_elsewhere_on_shelf = False
        if facing.sku in direct_by_shelf_and_sku[facing.shelf]:
            facing_ids_with_sku = direct_by_shelf_and_sku[facing.shelf][facing.sku]
            # Check if there are direct observations of this SKU on OTHER facings of the same shelf
            if len(facing_ids_with_sku) > (1 if facing.facing_id in facing_ids_with_sku else 0):
                direct_elsewhere_on_shelf = True

        # Decide status
        status, resolution, deciding_view = _decide(facing, views, catalog, direct_elsewhere_on_shelf)

        # Calculate credits
        strict_credit, lenient_credit = _credits(status, resolution, facing, views, weights)

        # Merge prices
        merged_price = _merge_price(views)

        # Get observed SKU and brand
        observed_sku = deciding_view.resolved_sku if deciding_view and deciding_view.resolved_sku else None
        observed_brand = None
        if observed_sku:
            catalog_item = catalog.by_sku(observed_sku)
            if catalog_item and catalog_item.brand:
                observed_brand = catalog_item.brand
            elif deciding_view and deciding_view.reading and deciding_view.reading.brand:
                observed_brand = deciding_view.reading.brand

        # Get expected price
        price_expected = prices.get(facing.sku) if prices else None

        # Determine price match
        price_match = None
        if (
            status == "match"
            and merged_price
            and merged_price.status == "read"
            and price_expected is not None
            and merged_price.amount is not None
        ):
            price_match = merged_price.amount == price_expected

        # Collect slot IDs
        slot_ids = sorted([obs.slot.slot_id for obs in views])

        results.append(
            PositionResult(
                facing=facing,
                status=status,
                resolution=resolution,
                strict_credit=strict_credit,
                lenient_credit=lenient_credit,
                observed_sku=observed_sku,
                observed_brand=observed_brand,
                price=merged_price,
                price_expected=price_expected,
                price_match=price_match,
                slot_ids=slot_ids,
            )
        )

    return results


def shelf_scores(positions: list[PositionResult]) -> list[ShelfScore]:
    """Per-shelf metrics: coverage, compliance %, occupancy %, empty facing list."""
    # Group positions by shelf
    positions_by_shelf = defaultdict(list)
    for pos in positions:
        positions_by_shelf[pos.facing.shelf].append(pos)

    scores = []
    for shelf_num in sorted(positions_by_shelf.keys()):
        shelf_positions = positions_by_shelf[shelf_num]

        expected = len(shelf_positions)

        # Covered = status not in UNCOVERED
        covered_positions = [pos for pos in shelf_positions if pos.status not in UNCOVERED]
        covered = len(covered_positions)

        # Decided = covered and identity_required
        decided_positions = [pos for pos in covered_positions if pos.facing.identity_required]
        decided = len(decided_positions)

        # Occupied positions
        occupied_positions = [pos for pos in shelf_positions if pos.status in OCCUPIED]
        occupied = len(occupied_positions)

        # Empty positions
        empty_positions = [pos for pos in shelf_positions if pos.status == "empty"]
        empty_facing_ids = sorted([pos.facing.facing_id for pos in empty_positions])

        # Calculate percentages
        strict_pct = _pct(sum(pos.strict_credit for pos in decided_positions), decided)
        lenient_pct = _pct(sum(pos.lenient_credit for pos in decided_positions), decided)

        # Occupancy percentage (occupied / (occupied + empty))
        occupancy_denominator = occupied + len(empty_positions)
        occupancy_pct = _pct(occupied, occupancy_denominator)

        scores.append(
            ShelfScore(
                shelf=shelf_num,
                expected=expected,
                covered=covered,
                decided=decided,
                strict_pct=strict_pct,
                lenient_pct=lenient_pct,
                occupancy_pct=occupancy_pct,
                empty_facing_ids=empty_facing_ids,
            )
        )

    return scores


def brand_shares(positions: list[PositionResult], catalog: Catalog) -> list[BrandShare]:
    """Expected vs observed brand shares (facings and linear)."""
    # Group positions by expected brand
    expected_by_brand = defaultdict(int)
    for pos in positions:
        brand_key = pos.facing.brand or UNKNOWN_BRAND
        expected_by_brand[brand_key] += 1

    total_expected = sum(expected_by_brand.values())

    # Group occupied positions by observed brand
    observed_by_brand = defaultdict(int)
    for pos in positions:
        if pos.status in OCCUPIED:
            brand_key = pos.observed_brand or UNKNOWN_BRAND
            observed_by_brand[brand_key] += 1

    total_observed = sum(observed_by_brand.values())

    # For linear share calculation, we need to group by first slot per position
    # This is a simplified approach - in a real implementation we'd need actual slot widths
    linear_by_brand = defaultdict(float)
    total_linear = 0.0

    # Occupancy by expected brand
    occupancy_by_brand = {}
    for brand in expected_by_brand:
        brand_positions = [pos for pos in positions if (pos.facing.brand or UNKNOWN_BRAND) == brand]
        occupied_count = sum(1 for pos in brand_positions if pos.status in OCCUPIED)
        empty_count = sum(1 for pos in brand_positions if pos.status == "empty")
        denominator = occupied_count + empty_count
        occupancy_by_brand[brand] = _pct(occupied_count, denominator) if denominator > 0 else None

    # Build results
    all_brands = set(expected_by_brand.keys()) | set(observed_by_brand.keys())
    brand_shares_list = []

    for brand in sorted(all_brands):
        expected_facings = expected_by_brand.get(brand, 0)
        expected_share = _share(expected_facings, total_expected) if total_expected > 0 else 0.0

        observed_facings = observed_by_brand.get(brand, 0)
        observed_share = _share(observed_facings, total_observed) if total_observed > 0 else None

        # Linear share is simplified here - in reality would use actual slot widths
        linear_share = observed_share  # Simplified approximation

        occupancy_pct = occupancy_by_brand.get(brand)

        brand_shares_list.append(
            BrandShare(
                brand=brand,
                expected_facings=expected_facings,
                expected_share=expected_share or 0.0,
                observed_facings=observed_facings,
                observed_share=observed_share,
                linear_share=linear_share,
                occupancy_pct=occupancy_pct,
            )
        )

    return brand_shares_list


def summarize(
    positions: list[PositionResult],
    shelf_scores_: list[ShelfScore],
    catalog: Catalog,
    prices: dict[str, Decimal] | None,
) -> ComplianceSummary:
    """Overall strict/lenient %, coverage, occupancy, products, unexpected SKUs, reference-confidence
    metrics and (only when ``prices`` is given) the price-compliance block."""

    # Filter covered positions (not in UNCOVERED set)
    covered_positions = [pos for pos in positions if pos.status not in UNCOVERED]

    # Filter decided positions (covered and identity_required)
    decided_positions = [pos for pos in covered_positions if pos.facing.identity_required]

    # Occupied positions
    occupied_positions = [pos for pos in positions if pos.status in OCCUPIED]

    # Empty positions
    empty_positions = [pos for pos in positions if pos.status == "empty"]

    # Calculate coverage (covered / total)
    coverage = _share(len(covered_positions), len(positions)) or 0.0

    # Calculate occupancy percentage (occupied / (occupied + empty))
    occupancy_denominator = len(occupied_positions) + len(empty_positions)
    occupancy_pct = _pct(len(occupied_positions), occupancy_denominator)

    # Calculate strict and lenient percentages over decided positions
    decided_count = len(decided_positions)
    strict_pct = _pct(sum(pos.strict_credit for pos in decided_positions), decided_count)
    lenient_pct = _pct(sum(pos.lenient_credit for pos in decided_positions), decided_count)

    # Products expected (distinct identity-required SKUs)
    expected_skus = {pos.facing.sku for pos in positions if pos.facing.identity_required}
    products_expected = len(expected_skus)

    # Products present (distinct expected SKUs with match/misplaced positions)
    present_skus = set()
    for pos in positions:
        if pos.status in {"match", "misplaced"} and pos.facing.identity_required:
            present_skus.add(pos.facing.sku)
    products_present = len(present_skus)

    # Unexpected SKUs (resolved direct/verified_by_expectation by ANY observation that are not expected)
    expected_sku_set = {pos.facing.sku for pos in positions}
    observed_skus = set()
    for pos in positions:
        if pos.observed_sku:
            observed_skus.add(pos.observed_sku)
    unexpected_skus = sorted(observed_skus - expected_sku_set)

    # Reference confidence metrics
    direct_reference_positions = [pos for pos in decided_positions if pos.facing.reference_read_method == "direct"]
    reference_direct_facings = len(direct_reference_positions)

    direct_ref_decided = len(direct_reference_positions)
    strict_pct_direct_reference = _pct(sum(pos.strict_credit for pos in direct_reference_positions), direct_ref_decided)
    lenient_pct_direct_reference = _pct(
        sum(pos.lenient_credit for pos in direct_reference_positions), direct_ref_decided
    )

    # Price compliance block
    price_compliance = None
    if prices is not None:
        # Positions with price_match not None (match status with readable price)
        priced_positions = [pos for pos in positions if pos.price_match is not None]
        compared = len(priced_positions)

        # Matched positions
        matched_positions = [pos for pos in priced_positions if pos.price_match is True]
        matched = len(matched_positions)
        match_pct = _pct(matched, compared)

        # Mismatches (facing ids)
        mismatches = sorted([pos.facing.facing_id for pos in priced_positions if pos.price_match is False])

        # SKUs missing from prices
        price_skus = set(prices.keys())
        identity_required_skus = {pos.facing.sku for pos in positions if pos.facing.identity_required}
        skus_missing_from_prices = sorted(identity_required_skus - price_skus)

        # Unknown price SKUs (in prices but not in planogram)
        unknown_price_skus = sorted(price_skus - expected_sku_set)

        price_compliance = PriceCompliance(
            compared=compared,
            matched=matched,
            match_pct=match_pct,
            mismatches=mismatches,
            skus_missing_from_prices=skus_missing_from_prices,
            unknown_price_skus=unknown_price_skus,
        )

    return ComplianceSummary(
        strict_pct=strict_pct,
        lenient_pct=lenient_pct,
        coverage=coverage,
        occupancy_pct=occupancy_pct,
        products_expected=products_expected,
        products_present=products_present,
        unexpected_skus=unexpected_skus,
        price=price_compliance,
        reference_direct_facings=reference_direct_facings,
        strict_pct_direct_reference=strict_pct_direct_reference,
        lenient_pct_direct_reference=lenient_pct_direct_reference,
    )
