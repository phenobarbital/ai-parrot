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

MIGRATED_TYPES = frozenset({"product_on_shelves", "ink_wall"})
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
_PREFLIGHT_SQL = "SELECT * FROM troc.planograms_configurations WHERE is_active = TRUE ORDER BY config_name"


class ConversionReport(BaseModel):
    """Result of a candidate conversion. ``candidate`` is a proposal for human review."""

    candidate: Dict[str, Any] = Field(default_factory=dict)
    bindings: List[Dict[str, Any]] = Field(default_factory=list)
    unresolved: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


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


class _BindingSet:
    """Collects bindings keyed by ``<kind>:<target_id>`` (merging text requirements of one target)."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}

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
        for product in shelf.get("products") or []:
            name = str(product.get("name") or "").strip()
            ptype = str(product.get("product_type") or "product").strip().lower()
            if ptype in _NON_FACING_TYPES:
                continue
            if ptype in _ZONE_TYPES:
                zone_count += 1
                zone_id = f"zone-{level}-{zone_count}"
                zones.append(
                    {"zone_id": zone_id, "kind": _zone_kind(ptype, name), "shelf_id": shelf_id, "required": True}
                )
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
                        "descriptors": {},
                    }
                )
            if first_facing:
                _product_rules(product, first_facing, bindings)
        if facings:
            report.warnings.append(f"{shelf_id} ({level}): slot order taken from list order — review")
        if not facings and not zone_count:
            report.unresolved.append(f"{shelf_id} ({level}): no facing and no zone could be derived")
        shelves.append({"shelf_id": shelf_id, "shelf_number": index, "level": level, "facings": facings})
    return shelves, zones


def _endcap_rules(
    config: Dict[str, Any], shelves: List[Dict[str, Any]], zones: List[Dict[str, Any]], bindings: _BindingSet
) -> None:
    """Endcap text requirements -> a binding on the endcap shelf's zone (or the shelf itself)."""
    endcap = config.get("advertisement_endcap") or {}
    requirements = _requirements(endcap.get("text_requirements"))
    if not requirements or endcap.get("enabled") is False:
        return
    position = str(endcap.get("position") or "header")
    shelf = next((s for s in shelves if s["level"] == position), None)
    if shelf is None:
        return
    zone = next((z for z in zones if z["shelf_id"] == shelf["shelf_id"]), None)
    target = zone["zone_id"] if zone else shelf["shelf_id"]
    bindings.add("text_requirements", target, {"requirements": requirements})


def convert_config(planogram_config: Dict[str, Any], *, planogram_type: str) -> ConversionReport:
    """Build a candidate slots definition and rule bindings from a legacy config dict.

    Args:
        planogram_config: The raw ``planogram_config`` dict (never mutated).
        planogram_type: The configuration's planogram type.

    Returns:
        A ConversionReport. ``unresolved`` lists everything a human must decide.

    Raises:
        ValueError: When ``planogram_type`` is not ``"product_on_shelves"``.
    """
    if planogram_type != "product_on_shelves":
        raise ValueError(f"Only product_on_shelves configs are convertible, got '{planogram_type}'")
    config = copy.deepcopy(planogram_config)
    report = ConversionReport()
    bindings = _BindingSet()
    shelves, zones = _walk_shelves(config, report, bindings)
    _endcap_rules(config, shelves, zones, bindings)
    report.candidate = {
        "version": "1",
        "meta": {"source": "convert_config", "brand": config.get("brand"), "category": config.get("category")},
        "shelves": shelves,
        "zones": zones,
    }
    report.bindings = list(bindings.items.values())
    try:
        definition = load_slots_definition(copy.deepcopy(report.candidate))
        validate_bindings(definition, {**config, "rule_bindings": report.bindings})
    except SlotsDefinitionError as exc:
        report.warnings.append(f"candidate does not validate yet: {exc}")
    return report


def _decode(value: Any) -> Any:
    """JSON string -> object (other values unchanged)."""
    return json.loads(value) if isinstance(value, str) else value


def check_row(row: Dict[str, Any]) -> PreflightRow:
    """Pure verdict for one row dict (unit-testable without a database).

    Args:
        row: One ``troc.planograms_configurations`` row as a dict.

    Returns:
        The verdict; legacy types are always ``ok``.
    """
    ptype = row.get("planogram_type") or "product_on_shelves"
    verdict = PreflightRow(config_name=str(row.get("config_name", "")), planogram_type=ptype, ok=True)
    if ptype not in MIGRATED_TYPES:
        return verdict
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
                    validate_bindings(definition, pg_config)
                except json.JSONDecodeError as exc:
                    problems.append(f"planogram_config is not valid JSON: {exc}")
                except SlotsDefinitionError as exc:
                    problems.append(f"invalid rule_bindings: {exc}")
    return verdict.model_copy(update={"ok": not problems, "problems": problems})


async def preflight(dsn: str) -> List[PreflightRow]:
    """List active rows and whether each migrated-type row is ready. SELECT-only.

    Args:
        dsn: PostgreSQL DSN.

    Returns:
        One PreflightRow per active configuration (legacy types are always ``ok``).
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
