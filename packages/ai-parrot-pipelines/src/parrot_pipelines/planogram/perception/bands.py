"""Fixture-relative vertical bands: several observed zone fragments, one configured zone.

A zone detector rarely returns one box per physical panel: a header comes back as its logo, its
headline and its side card, and a neighbouring fixture adds boxes of its own. A band selector
(``ZoneSelector.band``) names the vertical slice of the *fixture* a zone occupies, so every fragment
whose centre falls in that slice is evidence of the zone, and fragments beside the fixture are not.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Sequence, Set, Tuple

from parrot_pipelines.planogram.contracts import FixtureMembership, Shape

SELECTOR_EVIDENCE_PREFIX = "zone_selector:"
OUTSIDE_FIXTURE_EVIDENCE = "zone_band:outside_fixture"
#: Two zones belong to the same fixture column when their x-ranges share this fraction of the narrower one.
MIN_X_OVERLAP = 0.2

Box = Tuple[int, int, int, int]


class BandSelector(Protocol):
    """The selector fields band matching reads (``layout.ZoneSelector`` satisfies it)."""

    zone_id: str
    profile: Optional[str]
    kind: Optional[str]
    band: Optional[Tuple[float, float]]


def _x_overlap(a: Shape, b: Shape) -> float:
    """Shared x-range of two shapes as a fraction of the narrower one."""
    shared = min(a.box.x2, b.box.x2) - max(a.box.x1, b.box.x1)
    narrower = min(a.box.x2 - a.box.x1, b.box.x2 - b.box.x1)
    return shared / narrower if narrower > 0 else 0.0


def fixture_members(zones: Sequence[Shape]) -> List[Shape]:
    """The zones of the fixture: the x-overlapping group covering the largest area.

    Args:
        zones: Observed zones of one image; off-fixture zones are ignored.

    Returns:
        The members of the dominant column, top to bottom; empty when no zone is usable.
    """
    usable = [zone for zone in zones if zone.membership != FixtureMembership.OFF_FIXTURE]
    groups: List[List[Shape]] = []
    for zone in sorted(usable, key=lambda item: -(item.box.x2 - item.box.x1)):
        joined = [group for group in groups if any(_x_overlap(zone, other) >= MIN_X_OVERLAP for other in group)]
        merged = [zone, *(member for group in joined for member in group)]
        groups = [group for group in groups if not any(group is other for other in joined)]
        groups.append(merged)
    if not groups:
        return []

    def area(group: Sequence[Shape]) -> int:
        return sum((zone.box.x2 - zone.box.x1) * (zone.box.y2 - zone.box.y1) for zone in group)

    return sorted(max(groups, key=area), key=lambda zone: (zone.box.y1, zone.box.x1))


def fixture_box(zones: Sequence[Shape]) -> Optional[Box]:
    """Bounding box of the fixture's zones, or ``None`` when nothing was observed."""
    members = fixture_members(zones)
    if not members:
        return None
    return (
        min(zone.box.x1 for zone in members),
        min(zone.box.y1 for zone in members),
        max(zone.box.x2 for zone in members),
        max(zone.box.y2 for zone in members),
    )


def band_box(fixture: Box, band: Tuple[float, float]) -> Optional[Box]:
    """Pixel box of one vertical band of the fixture, if non-degenerate."""
    x1, y1, x2, y2 = fixture
    top = round(y1 + band[0] * (y2 - y1))
    bottom = round(y1 + band[1] * (y2 - y1))
    return (x1, top, x2, bottom) if x2 > x1 and bottom > top else None


def assign_bands(zones: Sequence[Shape], selectors: Sequence[BandSelector]) -> Tuple[Dict[str, str], Set[str]]:
    """Assign observed zones to the band selectors of a layout.

    Args:
        zones: Observed zones of one image.
        selectors: Zone selectors; only those with a ``band`` take part.

    Returns:
        ``(shape_id -> zone_id, shape ids beside the fixture)``. A zone whose centre falls in no band
        (or in a band whose selector rejects its profile or kind) is in neither.
    """
    banded = [selector for selector in selectors if selector.band is not None]
    members = fixture_members(zones) if banded else []
    if not members:
        return {}, set()
    member_ids = {zone.shape_id for zone in members}
    outside = {
        zone.shape_id
        for zone in zones
        if zone.shape_id not in member_ids and zone.membership != FixtureMembership.OFF_FIXTURE
    }
    top = min(zone.box.y1 for zone in members)
    height = max(zone.box.y2 for zone in members) - top
    assigned: Dict[str, str] = {}
    if height <= 0:
        return assigned, outside
    for zone in members:
        centre = ((zone.box.y1 + zone.box.y2) / 2 - top) / height
        for selector in banded:
            start, end = selector.band  # type: ignore[misc]
            if (
                start <= centre <= end
                and (selector.profile is None or zone.profile == selector.profile)
                and (selector.kind is None or zone.kind.value == selector.kind)
            ):
                assigned[zone.shape_id] = selector.zone_id
                break
    return assigned, outside


def banded_zones(zones: Sequence[Shape], zone_id: str) -> List[Shape]:
    """Observed zones already assigned to ``zone_id`` by a selector, top to bottom."""
    evidence = f"{SELECTOR_EVIDENCE_PREFIX}{zone_id}"
    return sorted(
        (
            zone
            for zone in zones
            if zone.membership != FixtureMembership.OFF_FIXTURE and evidence in zone.membership_evidence
        ),
        key=lambda zone: (zone.box.y1, zone.box.x1),
    )
