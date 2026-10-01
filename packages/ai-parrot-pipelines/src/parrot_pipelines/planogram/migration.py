"""Offline configuration migration for the perceive → identify → compare cycle (FEAT-574).

Candidate conversion of legacy ProductOnShelves configs into ``slots_definition`` +
``rule_bindings``, and a read-only database preflight. Nothing here writes to a database.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)

logger = logging.getLogger(__name__)

MIGRATED_TYPES = frozenset(
    {
        "product_on_shelves",
        "graphic_panel_display",
        "product_counter",
        "endcap_no_shelves_promotional",
        "endcap_backlit_multitier",
        "ink_wall",
    }
)
_NON_FACING_TYPES = frozenset({"fact_tag", "price_tag", "slot"})
_ZONE_TYPES = frozenset(
    {
        "promotional_graphic",
        "graphic",
        "banner",
        "backlit_graphic",
        "backlit",
        "advertisement",
        "advertisement_graphic",
        "display_graphic",
        "promotional_display",
        "promotional_material",
        "promotional_materials",
        "text_overlay",
    }
)
# Branding / signage / information elements of mixed displays (real products plus branding): zones, never facings.
_BRANDING_ZONE_TYPES = frozenset(
    {
        "signage",
        "hero_graphic",
        "base_branding",
        "product_materials",
        "informational_materials",
        "product_info_panel",
    }
)
_COUNTER_ZONE_TYPES = frozenset({"promotional_background", "background", "information_label", "label"})
_PREFLIGHT_SQL = "SELECT * FROM troc.planograms_configurations WHERE is_active = TRUE ORDER BY config_name"


class ConversionReport(BaseModel):
    """Result of a candidate conversion. ``candidate`` is a proposal for human review."""

    candidate: Dict[str, Any] = Field(default_factory=dict)
    bindings: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    layout_profile: Dict[str, Any] = Field(default_factory=dict)


class PreflightRow(BaseModel):
    """Preflight verdict for one active configuration row."""

    config_name: str
    planogram_type: str
    ok: bool
    problems: List[str] = Field(default_factory=list)


def _fixed_quantity(product: Dict[str, Any]) -> Optional[int]:
    """``n`` when ``quantity_range`` is a fixed ``(n, n)`` (default ``(1, 1)``), else None."""
    raw = product.get("quantity_range", (1, 1))
    if raw is None:
        raw = (1, 1)
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    try:
        low, high = int(raw[0]), int(raw[1])
    except (TypeError, ValueError, IndexError):
        return None
    return low if low == high and low >= 1 else None


def _zone_kind(product_type: str, name: str) -> str:
    """Map a promotional product to a ZoneDefinition kind."""
    text = f"{product_type} {name}".casefold()
    if "backlit" in text:
        return "backlit"
    if "box" in text:
        return "box_stack"
    if "poster" in text or "text_overlay" in text or "banner" in text:
        return "poster"
    return "header"


def _extended_zone_kind(product_type: str, name: str, default: str) -> str:
    """Zone kind for non-shelf types, using the FEAT-612 kinds."""
    text = f"{product_type} {name}".casefold()
    if "information" in text or "label" in text:
        return "information_label"
    if "backlit" in text:
        return "backlit"
    if "counter" in text:
        return "counter"
    if "advertis" in text:
        return "advertisement"
    if "poster" in text or "banner" in text or "text_overlay" in text:
        return "poster"
    if "box" in text:
        return "box_stack"
    return default


class _BindingSet:
    """Collects bindings keyed by ``<kind>:<target_id>`` (merging text requirements of one target)."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}
        # zone_id -> ``y_start_ratio`` of its source shelf (None when the row gives none); orders the selectors.
        self.zone_tops: Dict[str, Optional[float]] = {}

    def add(self, kind: str, target_id: str, params: Dict[str, Any], mandatory: bool = True) -> None:
        rule_id = f"{kind}:{target_id}"
        existing = self.items.get(rule_id)
        if existing is None:
            self.items[rule_id] = {
                "rule_id": rule_id,
                "kind": kind,
                "target_id": target_id,
                "params": copy.deepcopy(params),
                "mandatory": mandatory,
            }
            return
        if kind == "text_requirements":
            seen = {r.get("required_text") for r in existing["params"]["requirements"]}
            for requirement in params.get("requirements", []):
                if requirement.get("required_text") not in seen:
                    existing["params"]["requirements"].append(copy.deepcopy(requirement))
        elif kind == "visual_features":
            for feature in params.get("expected", []):
                if feature not in existing["params"]["expected"]:
                    existing["params"]["expected"].append(feature)


def _requirements(raw: Any) -> List[Dict[str, Any]]:
    """Normalise text requirements to dicts with at least ``required_text``."""
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("required_text"):
            out.append(dict(item))
        elif isinstance(item, str) and item.strip():
            out.append({"required_text": item})
    return out


def _product_rules(product: Dict[str, Any], target_id: str, bindings: _BindingSet) -> None:
    """Nested illumination / text / visual keys of one product -> bindings on ``target_id``."""
    if product.get("illumination_required"):
        bindings.add(
            "illumination",
            target_id,
            {
                "required": str(product["illumination_required"]).strip().lower(),
                "penalty": float(product.get("illumination_penalty", 0.5)),
                "name": product.get("name"),
            },
        )
    requirements = _requirements(product.get("text_requirements"))
    if requirements:
        bindings.add("text_requirements", target_id, {"requirements": requirements})
    if product.get("visual_features"):
        bindings.add("visual_features", target_id, {"expected": list(product["visual_features"])})


def _walk_shelves(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Shelves -> candidate shelves/zones; fills ``report.unresolved`` / ``warnings`` and ``bindings``."""
    brand = config.get("brand")
    shelves: List[Dict[str, Any]] = []
    zones: List[Dict[str, Any]] = []
    for index, shelf in enumerate(config.get("shelves") or [], start=1):
        level = str(shelf.get("level") or f"shelf{index}")
        shelf_id = f"shelf-{index}"
        facings: List[Dict[str, Any]] = []
        slot = 0
        zone_count = 0
        skipped = 0
        first_zone: Optional[str] = None
        for product in shelf.get("products") or []:
            name = str(product.get("name") or "").strip()
            ptype = str(product.get("product_type") or "product").strip().lower()
            if ptype in _NON_FACING_TYPES:
                skipped += 1
                continue
            if ptype in _ZONE_TYPES or ptype in _BRANDING_ZONE_TYPES:
                zone_count += 1
                zone_id = f"zone-{level}-{zone_count}"
                first_zone = first_zone or zone_id
                kind = _zone_kind(ptype, name) if ptype in _ZONE_TYPES else _extended_zone_kind(ptype, name, "graphic")
                zones.append({"zone_id": zone_id, "kind": kind, "shelf_id": shelf_id, "required": True})
                bindings.zone_tops[zone_id] = _shelf_top(shelf)
                bindings.add("zone_present", zone_id, {"name": name}, mandatory=bool(product.get("mandatory", True)))
                _product_rules(product, zone_id, bindings)
                continue
            if not name:
                report.unresolved.append(f"{shelf_id} ({level}): product without a name — cannot place it")
                continue
            count = _fixed_quantity(product)
            if count is None:
                report.unresolved.append(
                    f"{shelf_id} ({level}): '{name}' has quantity_range {product.get('quantity_range')!r} — "
                    "decide the exact number of facings (one placeholder facing was created)"
                )
                count = 1
            first_facing: Optional[str] = None
            for _ in range(count):
                slot += 1
                facing_id = f"{shelf_id}:{slot}"
                first_facing = first_facing or facing_id
                facings.append(
                    {
                        "facing_id": facing_id,
                        "shelf_id": shelf_id,
                        "slot": slot,
                        "product": name,
                        "brand": product.get("brand") or brand,
                        "descriptors": copy.deepcopy(product.get("descriptors") or {}),
                    }
                )
            if first_facing:
                _product_rules(product, first_facing, bindings)
        shelf_requirements = _requirements(shelf.get("text_requirements"))
        if shelf_requirements:
            bindings.add("text_requirements", first_zone or shelf_id, {"requirements": shelf_requirements})
        if skipped:
            report.warnings.append(
                f"{shelf_id} ({level}): {skipped} fact/price tag element(s) not converted — "
                "the cycle has no tag-presence or price rule"
            )
        if facings:
            report.warnings.append(f"{shelf_id} ({level}): slot order taken from list order — review")
        if not facings and not zone_count:
            report.unresolved.append(f"{shelf_id} ({level}): no facing and no zone could be derived")
        shelves.append({"shelf_id": shelf_id, "shelf_number": index, "level": level, "facings": facings})
    return shelves, zones


def _shelf_top(shelf: Dict[str, Any]) -> Optional[float]:
    """``y_start_ratio`` of a source shelf as a float, or None when absent or not numeric."""
    try:
        return float(shelf["y_start_ratio"])
    except (KeyError, TypeError, ValueError):
        return None


def _endcap_rules(
    config: Dict[str, Any], targets: Dict[str, str], bindings: _BindingSet, report: ConversionReport
) -> None:
    """Endcap text requirements -> a binding on the target of the endcap's level (never dropped silently).

    Args:
        config: The raw planogram configuration.
        targets: Source shelf ``level`` -> the zone (or shelf) id its rules bind to.
        bindings: The collected bindings.
        report: Receives an unresolved item when no target sits at the endcap position.
    """
    endcap = config.get("advertisement_endcap") or {}
    requirements = _requirements(endcap.get("text_requirements"))
    if not requirements or endcap.get("enabled") is False:
        return
    position = str(endcap.get("position") or "header")
    target = targets.get(position)
    if target is None:
        texts = ", ".join(repr(item["required_text"]) for item in requirements)
        report.unresolved.append(
            f"advertisement_endcap: no shelf or zone at position '{position}' — bind its text requirements "
            f"({texts}) to a target"
        )
        return
    bindings.add("text_requirements", target, {"requirements": requirements})


def _shelf_targets(shelves: List[Dict[str, Any]], zones: List[Dict[str, Any]]) -> Dict[str, str]:
    """Shelf ``level`` -> its first zone id, or the shelf id when it owns no zone (first level wins)."""
    targets: Dict[str, str] = {}
    for shelf in shelves:
        zone = next((z for z in zones if z["shelf_id"] == shelf["shelf_id"]), None)
        targets.setdefault(shelf["level"], zone["zone_id"] if zone else shelf["shelf_id"])
    return targets


def _convert_ink(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Page-1 / slots layout -> native shelves with preserved source descriptors."""
    source = config.get("slots_definition") or config
    shelves = source.get("shelves") if isinstance(source, dict) else []
    is_page1 = isinstance(source, dict) and (
        "planogram" in source
        or (bool(shelves) and isinstance(shelves[0], dict) and isinstance(shelves[0].get("products"), dict))
    )
    if not is_page1:
        report.unresolved.append("ink_wall: no page-1/slots layout found")
        return [], []
    try:
        definition = load_slots_definition(copy.deepcopy(source))
    except SlotsDefinitionError as exc:
        from parrot_pipelines.planogram.comparison.definition import _normalise_page1

        try:
            native = _normalise_page1(copy.deepcopy(source))
        except SlotsDefinitionError as normalise_exc:
            report.unresolved.append(f"ink_wall: invalid page-1/slots layout: {normalise_exc}")
            return [], []
        for shelf in native["shelves"]:
            for facing in shelf["facings"]:
                if not facing.get("descriptors", {}).get("display_name"):
                    report.unresolved.append(f"{facing['facing_id']}: descriptors are required")
        report.unresolved.append(f"candidate does not validate: {exc}")
        return native["shelves"], native["zones"]
    for facing in definition.all_facings():
        if not facing.descriptors.described:
            report.unresolved.append(f"{facing.facing_id}: descriptors are required")
    return (
        [shelf.model_dump(mode="json") for shelf in definition.shelves],
        [zone.model_dump(mode="json") for zone in definition.zones],
    )


def _convert_zones_only(
    config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet, *, default_kind: str
) -> Tuple[list, list]:
    """Promotional / graphic-panel elements -> unowned zones."""
    zones: List[Dict[str, Any]] = []
    targets: Dict[str, str] = {}
    for index, shelf in enumerate(config.get("shelves") or [], start=1):
        level = str(shelf.get("level") or f"shelf{index}")
        for number, product in enumerate(shelf.get("products") or [], start=1):
            name = str(product.get("name") or "").strip()
            ptype = str(product.get("product_type") or "graphic").strip().lower()
            zone_id = f"zone-{level}-{number}"
            targets.setdefault(level, zone_id)
            bindings.zone_tops[zone_id] = _shelf_top(shelf)
            required = bool(product.get("mandatory", True))
            zones.append(
                {
                    "zone_id": zone_id,
                    "kind": _extended_zone_kind(ptype, name, default_kind),
                    "shelf_id": None,
                    "required": required,
                }
            )
            bindings.add("zone_present", zone_id, {"name": name}, mandatory=required)
            _product_rules(product, zone_id, bindings)
        shelf_requirements = _requirements(shelf.get("text_requirements"))
        if shelf_requirements and level in targets:
            bindings.add("text_requirements", targets[level], {"requirements": shelf_requirements})
        elif shelf_requirements:
            report.unresolved.append(f"{level}: text requirements on a level without elements — bind them to a zone")
    _endcap_rules(config, targets, bindings, report)
    return [], zones


def _convert_counter(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Product elements -> counter facings; background and label elements -> zones."""
    shelf_id = "shelf-1"
    facings: List[Dict[str, Any]] = []
    zones: List[Dict[str, Any]] = []
    slot = 0
    zone_number = 0
    elements = [product for shelf in config.get("shelves") or [] for product in shelf.get("products") or []]
    for product in elements:
        name = str(product.get("name") or "").strip()
        ptype = str(product.get("product_type") or "product").strip().lower()
        if ptype in _COUNTER_ZONE_TYPES:
            zone_number += 1
            zone_id = f"zone-counter-{zone_number}"
            required = bool(product.get("mandatory", True))
            zones.append(
                {
                    "zone_id": zone_id,
                    "kind": _extended_zone_kind(ptype, name, "graphic"),
                    "shelf_id": shelf_id,
                    "required": required,
                }
            )
            bindings.add("zone_present", zone_id, {"name": name}, mandatory=required)
            _product_rules(product, zone_id, bindings)
            continue
        if not name:
            report.unresolved.append("shelf-1 (counter): product without a name — cannot place it")
            continue
        count = _fixed_quantity(product)
        if count is None:
            report.unresolved.append(
                f"shelf-1 (counter): '{name}' has quantity_range {product.get('quantity_range')!r} — "
                "decide the exact number of facings (one placeholder facing was created)"
            )
            count = 1
        first_facing: Optional[str] = None
        for _ in range(count):
            slot += 1
            facing_id = f"{shelf_id}:{slot}"
            first_facing = first_facing or facing_id
            facings.append(
                {
                    "facing_id": facing_id,
                    "shelf_id": shelf_id,
                    "slot": slot,
                    "product": name,
                    "brand": product.get("brand") or config.get("brand"),
                    "descriptors": copy.deepcopy(product.get("descriptors") or {}),
                }
            )
        if first_facing:
            _product_rules(product, first_facing, bindings)
    if "scoring_weights" in config:
        report.unresolved.append("scoring_weights: map to definition/profile weights")
    return [{"shelf_id": shelf_id, "shelf_number": 1, "level": "counter", "facings": facings}], zones


def _convert_backlit(config: Dict[str, Any], report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:
    """Backlit shelves -> candidate shelves/zones; sections require human spatial configuration."""
    shelves, zones = _walk_shelves(config, report, bindings)
    _endcap_rules(config, _shelf_targets(shelves, zones), bindings, report)
    for shelf_id, source_shelf in zip(
        (shelf["shelf_id"] for shelf in shelves), config.get("shelves") or [], strict=False
    ):
        for section in source_shelf.get("sections") or []:
            report.unresolved.append(
                f"{shelf_id} section {section.get('id')}: configure a zone selector / section group"
            )
    return shelves, zones


def _zone_selectors(
    zones: List[Dict[str, Any]], tops: Dict[str, Optional[float]], layout: Dict[str, Any], report: ConversionReport
) -> None:
    """Generate one ordinal selector per zone; the runtime matches ordinals to observed zones top to bottom.

    The order is grounded when every zone's source shelf carries a distinct ``y_start_ratio``; otherwise it
    falls back to list order and is reported as unresolved.

    Args:
        zones: The candidate zones, in list order.
        tops: zone_id -> ``y_start_ratio`` of its source shelf.
        layout: The candidate layout profile (extended in place).
        report: Receives the review warning or the unresolved item.
    """
    values = [tops.get(zone["zone_id"]) for zone in zones]
    grounded = all(value is not None for value in values) and len(set(values)) == len(values)
    ordered = sorted(zones, key=lambda zone: tops.get(zone["zone_id"]) or 0.0) if grounded else zones
    for ordinal, zone in enumerate(ordered):
        layout.setdefault("zone_selectors", []).append({"zone_id": zone["zone_id"], "kind": "zone", "ordinal": ordinal})
    if len(zones) < 2:
        return
    zone_ids = ", ".join(zone["zone_id"] for zone in ordered)
    if grounded:
        report.warnings.append(f"zone selectors ordered top to bottom by y_start_ratio: {zone_ids} — review")
    else:
        report.unresolved.append(
            f"zone selectors for {zone_ids} follow list order — confirm the top-to-bottom order or set a region"
        )


def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport:
    """Convert any registered type into a candidate definition and rule bindings.

    Args:
        planogram_config: The raw ``planogram_config`` dict (never mutated).
        planogram_type: The configuration's planogram type.

    Returns:
        A ConversionReport. ``unresolved`` lists every human decision and validation failure.

    Raises:
        ValueError: When ``planogram_type`` is not convertible.
    """
    if planogram_type not in MIGRATED_TYPES:
        raise ValueError(
            f"Unsupported planogram_type '{planogram_type}'; convertible: {', '.join(sorted(MIGRATED_TYPES))}"
        )
    config = copy.deepcopy(planogram_config)
    report = ConversionReport()
    bindings = _BindingSet()
    if planogram_type == "product_on_shelves":
        shelves, zones = _walk_shelves(config, report, bindings)
        _endcap_rules(config, _shelf_targets(shelves, zones), bindings, report)
    elif planogram_type == "ink_wall":
        shelves, zones = _convert_ink(config, report, bindings)
    elif planogram_type == "endcap_backlit_multitier":
        shelves, zones = _convert_backlit(config, report, bindings)
    elif planogram_type == "product_counter":
        shelves, zones = _convert_counter(config, report, bindings)
    else:
        shelves, zones = _convert_zones_only(config, report, bindings, default_kind="graphic")
    layout = copy.deepcopy(config.get("layout_profile") or {})
    if "perception_mode" in config:
        layout["perception_mode"] = config["perception_mode"]
        report.warnings.append("perception_mode accepted and moved to layout_profile")
    _zone_selectors(zones, bindings.zone_tops, layout, report)
    report.layout_profile = layout
    for field in (
        "roi_detection_prompt",
        "object_identification_prompt",
        "detection_model",
        "confidence_threshold",
        "detection_grid",
    ):
        if field in config:
            report.warnings.append(f"{field} accepted and ignored for one release")
    report.candidate = {
        "version": "1",
        "meta": {
            "source": "convert_config",
            "planogram_type": planogram_type,
            "brand": config.get("brand"),
            "category": config.get("category"),
        },
        "shelves": shelves,
        "zones": zones,
    }
    report.bindings = list(bindings.items.values())
    _validate_candidate(report, config, planogram_type)
    return report


def _validate_candidate(report: ConversionReport, config: Dict[str, Any], planogram_type: str) -> None:
    """Append candidate, binding, and layout validation failures to ``unresolved``."""
    try:
        definition = load_slots_definition(copy.deepcopy(report.candidate))
        validate_bindings(definition, {**config, "rule_bindings": report.bindings})
    except SlotsDefinitionError as exc:
        report.unresolved.append(f"candidate does not validate: {exc}")
    problem = _layout_problem(
        planogram_type,
        {**config, "layout_profile": report.layout_profile},
        "convert_config",
    )
    if problem:
        report.unresolved.append(problem)


def _decode(value: Any) -> Any:
    """JSON string -> object (other values unchanged)."""
    return json.loads(value) if isinstance(value, str) else value


def _layout_problem(planogram_type: str, planogram_config: Dict[str, Any], config_name: str) -> Optional[str]:
    """Resolve a type's layout defaults; return validation text when they cannot be resolved."""
    from parrot_pipelines.planogram import types as planogram_types
    from parrot_pipelines.planogram.layout import resolve_layout_profile

    classes = {
        "product_on_shelves": planogram_types.ProductOnShelves,
        "graphic_panel_display": planogram_types.GraphicPanelDisplay,
        "product_counter": planogram_types.ProductCounter,
        "endcap_no_shelves_promotional": planogram_types.EndcapNoShelvesPromotional,
        "endcap_backlit_multitier": planogram_types.EndcapBacklitMultitier,
        "ink_wall": planogram_types.InkWall,
    }
    try:
        resolve_layout_profile(
            classes[planogram_type].default_layout_profile(), planogram_config, config_name=config_name
        )
    except ValueError as exc:
        return f"invalid layout_profile: {exc}"
    return None


def check_row(row: Dict[str, Any]) -> PreflightRow:
    """Pure verdict for one row dict (unit-testable without a database).

    Args:
        row: One ``troc.planograms_configurations`` row as a dict.

    Returns:
        The verdict; unknown types are never ``ok``.
    """
    ptype = row.get("planogram_type") or "product_on_shelves"
    verdict = PreflightRow(config_name=str(row.get("config_name", "")), planogram_type=ptype, ok=True)
    if ptype not in MIGRATED_TYPES:
        return verdict.model_copy(update={"ok": False, "problems": [f"unknown planogram_type '{ptype}'"]})
    problems: List[str] = []
    raw = row.get("slots_definition")
    if raw in (None, "", {}):
        problems.append("slots_definition is missing")
    else:
        try:
            source = _decode(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"slots_definition is not valid JSON: {exc}")
            source = None
        if source is not None:
            try:
                definition = load_slots_definition(source)
            except SlotsDefinitionError as exc:
                problems.append(f"invalid slots_definition: {exc}")
            else:
                try:
                    pg_config = _decode(row.get("planogram_config")) or {}
                except json.JSONDecodeError as exc:
                    problems.append(f"planogram_config is not valid JSON: {exc}")
                else:
                    try:
                        validate_bindings(definition, pg_config)
                    except SlotsDefinitionError as exc:
                        problems.append(f"invalid rule_bindings: {exc}")
                    problem = _layout_problem(ptype, pg_config, verdict.config_name)
                    if problem:
                        problems.append(problem)
    return verdict.model_copy(update={"ok": not problems, "problems": problems})


async def preflight(dsn: str) -> List[PreflightRow]:
    """List active rows and whether each migrated-type row is ready. SELECT-only.

    Args:
        dsn: PostgreSQL DSN.

    Returns:
        One PreflightRow per active configuration (unknown types are never ``ok``).
    """
    from asyncdb import AsyncDB  # lazy: importing this module must not need a DB driver

    db = AsyncDB("pg", dsn=dsn)
    async with await db.connection() as conn:
        rows: Sequence[Any] = await conn.fetch_all(_PREFLIGHT_SQL) or []
    return [check_row(dict(row)) for row in rows]


def _load_config_file(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    """Read a bare planogram_config JSON, or an exported row carrying a ``planogram_config`` key."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "planogram_config" in data:
        return _decode(data["planogram_config"]) or {}, data.get("planogram_type")
    return data, None


def _main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 2 unresolved items / failing rows, 1 usage or I/O error."""
    parser = argparse.ArgumentParser(prog="python -m parrot_pipelines.planogram.migration")
    sub = parser.add_subparsers(dest="command", required=True)
    conv = sub.add_parser("convert", help="candidate slots JSON from a legacy config JSON file")
    conv.add_argument("config", type=Path)
    conv.add_argument("--planogram-type", default=None)
    conv.add_argument("--out", type=Path, default=None)
    pre = sub.add_parser("preflight", help="read-only readiness report")
    pre.add_argument("--dsn", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    if args.command == "convert":
        if args.out is not None and args.out.resolve() == args.config.resolve():
            logger.error("Refusing to overwrite the input configuration: choose another --out")
            return 1
        try:
            config, row_type = _load_config_file(args.config)
            report = convert_config(config, planogram_type=args.planogram_type or row_type or "product_on_shelves")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("convert failed: %s", exc)
            return 1
        payload = report.model_dump_json(indent=2)
        if args.out is not None:
            args.out.write_text(payload + "\n", encoding="utf-8")
        else:
            sys.stdout.write(payload + "\n")
        if report.unresolved:
            logger.warning("%d unresolved item(s): the candidate is NOT a finished migration", len(report.unresolved))
            return 2
        return 0

    try:
        rows = asyncio.run(preflight(args.dsn))
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        logger.error("preflight failed: %s", exc)
        return 1
    sys.stdout.write(json.dumps([r.model_dump() for r in rows], indent=2) + "\n")
    return 0 if all(r.ok for r in rows) else 2


if __name__ == "__main__":
    sys.exit(_main())
