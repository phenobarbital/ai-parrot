"""Slots definition: what a fixture is expected to hold, plus the rule bindings that target it."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]
ZoneKind = Literal[
    "header",
    "backlit",
    "poster",
    "box_stack",
    "graphic",
    "advertisement",
    "counter",
    "information_label",
]
AttributeValue = Union[str, int, float, bool, List[str]]
VIRTUAL_SHELF_PREFIX = "zone:"

_DESCRIPTOR_KEYS: Tuple[str, ...] = (
    "display_name",
    "family",
    "xl",
    "colors",
    "pack",
    "identifiers",
    "aliases",
    "price",
    "attributes",
)


class SlotsDefinitionError(ValueError):
    """Invalid slots definition or rule bindings (fail fast at construction time)."""


class Descriptors(BaseModel):
    """Per-position product description. All optional; ``price`` is never required."""

    display_name: Optional[str] = None
    family: Optional[str] = None
    xl: Optional[bool] = None
    colors: List[str] = Field(default_factory=list)
    pack: Optional[int] = None
    identifiers: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    price: Optional[float] = None
    attributes: Dict[str, AttributeValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_typed_collision(self) -> "Descriptors":
        """Reject custom attribute keys that shadow a typed descriptor field."""
        typed = set(type(self).model_fields) - {"attributes"}
        clash = sorted(typed & set(self.attributes))
        if clash:
            raise ValueError(f"descriptor attributes collide with typed fields: {', '.join(clash)}")
        return self

    @property
    def described(self) -> bool:
        """True when ``display_name`` is non-empty (the definition of a described position)."""
        return bool(self.display_name and self.display_name.strip())

    @property
    def sufficient(self) -> bool:
        """True when described or carrying at least one non-empty identifier."""
        return self.described or any(i and i.strip() for i in self.identifiers)


class FacingDefinition(BaseModel):
    """One expected physical facing with a stable id."""

    facing_id: str
    shelf_id: str
    slot: int = Field(ge=1)
    product: Optional[str] = None
    brand: Optional[str] = None
    facings: int = Field(default=1, ge=1)  # facing count of the source position (informational)
    facing_index: int = Field(default=1, ge=1)  # 1..facings
    position: Optional[int] = None  # source position number (page1 layout)
    descriptors: Descriptors = Field(default_factory=Descriptors)
    expected_occupancy: Literal["occupied", "empty"] = "occupied"

    @model_validator(mode="after")
    def _occupied_needs_product(self) -> "FacingDefinition":
        """An occupied position must name its product; an expected-empty one may not."""
        if self.expected_occupancy == "occupied" and not (self.product and self.product.strip()):
            raise ValueError(f"{self.facing_id}: occupied facing requires a nonblank product")
        return self


class ShelfDefinition(BaseModel):
    """One shelf; ``level`` matches ``ShelfConfig.level`` of planogram_config when both exist."""

    shelf_id: str
    shelf_number: int
    level: Optional[str] = None
    facings: List[FacingDefinition] = Field(default_factory=list)


class ZoneDefinition(BaseModel):
    """Non-product zone (header / backlit / poster / box stack) detected apart from product rows."""

    zone_id: str
    kind: ZoneKind
    shelf_id: Optional[str] = None
    required: bool = True


class RuleBinding(BaseModel):
    """Binds one non-product rule of planogram_config to a stable id of the definition."""

    rule_id: str
    kind: RuleKind
    target_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    mandatory: bool = True


class SlotsDefinition(BaseModel):
    """Versioned definition of shelves, facings and zones."""

    version: str = "1"
    meta: Dict[str, Any] = Field(default_factory=dict)
    shelves: List[ShelfDefinition] = Field(default_factory=list)
    zones: List[ZoneDefinition] = Field(default_factory=list)

    def all_facings(self) -> List[FacingDefinition]:
        """Facings in shelf order, then (slot, facing_index)."""
        return [f for shelf in self.shelves for f in shelf.facings]


def _normalise_page1(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the ``{"planogram": ..., "shelves": [{"products": {...}}]}`` layout to the native dict.

    Args:
        data: The page1-layout document.

    Returns:
        A native-layout dict (``version``, ``meta``, ``shelves``, ``zones``).

    Raises:
        SlotsDefinitionError: A shelf or position lacks a required key.
    """
    shelves: List[Dict[str, Any]] = []
    for shelf in data.get("shelves") or []:
        if "shelf_number" not in shelf:
            raise SlotsDefinitionError("page1 shelf without 'shelf_number'")
        shelf_number = int(shelf["shelf_number"])
        shelf_id = f"shelf_{shelf_number}"
        facings: List[Dict[str, Any]] = []
        for key, position in (shelf.get("products") or {}).items():
            missing = [k for k in ("slot", "position", "product") if position.get(k) in (None, "")]
            if missing:
                raise SlotsDefinitionError(f"{shelf_id}: position {key!r} lacks {', '.join(missing)}")
            count = int(position.get("facings") or 1)
            descriptors = {k: position[k] for k in _DESCRIPTOR_KEYS if position.get(k) is not None}
            for index in range(1, count + 1):
                facings.append(
                    {
                        "facing_id": f"p{int(position['position']):03d}_f{index}",
                        "shelf_id": shelf_id,
                        "slot": int(position["slot"]),
                        "product": str(position["product"]),
                        "brand": position.get("brand"),
                        "facings": count,
                        "facing_index": index,
                        "position": int(position["position"]),
                        "descriptors": dict(descriptors),
                    }
                )
        level = shelf.get("level")
        shelves.append(
            {
                "shelf_id": shelf_id,
                "shelf_number": shelf_number,
                "level": str(level) if level is not None else None,
                "facings": facings,
            }
        )
    return {"version": "1", "meta": dict(data.get("planogram") or {}), "shelves": shelves, "zones": []}


def _duplicates(ids: List[str]) -> List[str]:
    """Ids occurring more than once, in first-seen order."""
    seen: set[str] = set()
    dupes: List[str] = []
    for item in ids:
        if item in seen and item not in dupes:
            dupes.append(item)
        seen.add(item)
    return dupes


def _validate(definition: SlotsDefinition) -> None:
    """Cross-object validation. Raises SlotsDefinitionError naming the offending shelf / id.

    Args:
        definition: The parsed definition.

    Raises:
        SlotsDefinitionError: On the first failing check.
    """
    if not definition.all_facings() and not definition.zones:
        raise SlotsDefinitionError("empty definition: no facings and no zones")

    for label, ids in (
        ("shelf_id", [s.shelf_id for s in definition.shelves]),
        ("zone_id", [z.zone_id for z in definition.zones]),
        ("facing_id", [f.facing_id for f in definition.all_facings()]),
    ):
        dupes = _duplicates(ids)
        if dupes:
            raise SlotsDefinitionError(f"duplicate {label}: {', '.join(dupes)}")

    for shelf in definition.shelves:
        slots = sorted({f.slot for f in shelf.facings})
        if slots and slots != list(range(1, len(slots) + 1)):
            raise SlotsDefinitionError(f"{shelf.shelf_id}: slots must be exactly 1..n, got {slots}")

    zone_shelves = {z.shelf_id for z in definition.zones if z.shelf_id}
    for shelf in definition.shelves:
        if not shelf.facings and shelf.shelf_id not in zone_shelves:
            raise SlotsDefinitionError(f"{shelf.shelf_id}: shelf has neither facings nor zones")

    described: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for facing in definition.all_facings():
        if facing.expected_occupancy == "empty" or not facing.descriptors.described:
            continue
        dump = facing.descriptors.model_dump()
        previous = described.get(facing.product)
        if previous is None:
            described[facing.product] = (facing.facing_id, dump)
        elif previous[1] != dump:
            raise SlotsDefinitionError(
                f"conflicting descriptors for product {facing.product!r}: {previous[0]} vs {facing.facing_id}"
            )

    occupied = [f for f in definition.all_facings() if f.expected_occupancy == "occupied"]
    if occupied and not described:
        raise SlotsDefinitionError("zero described positions: at least one occupied facing needs a display_name")


def _normalise_zone_shelves(definition: SlotsDefinition) -> None:
    """Give every unowned zone a deterministic virtual score shelf ``zone:<zone_id>`` (in place, after sorting).

    Raises:
        SlotsDefinitionError: a physical shelf already uses the virtual id of an unowned zone.
    """
    physical_shelf_ids = {shelf.shelf_id for shelf in definition.shelves}
    next_shelf_number = max((shelf.shelf_number for shelf in definition.shelves), default=0) + 1
    for index, zone in enumerate(definition.zones):
        if zone.shelf_id is not None:
            continue
        virtual_shelf_id = f"{VIRTUAL_SHELF_PREFIX}{zone.zone_id}"
        if virtual_shelf_id in physical_shelf_ids:
            raise SlotsDefinitionError(f"virtual shelf id collision: {virtual_shelf_id}")
        zone.shelf_id = virtual_shelf_id
        definition.shelves.append(
            ShelfDefinition(
                shelf_id=virtual_shelf_id,
                shelf_number=next_shelf_number + index,
                level=None,
                facings=[],
            )
        )


def load_slots_definition(source: Union[Dict[str, Any], str, Path]) -> SlotsDefinition:
    """Parse and validate a slots definition.

    Blocking file read for a path source — call via ``asyncio.to_thread`` from async code.

    Args:
        source: A dict (JSONB column value) or a path to a JSON file, in native or page1 layout.

    Returns:
        The validated definition; shelves ordered by ``shelf_number``, facings by ``(slot, facing_index)``.
        Unowned zones receive deterministic virtual shelves after physical shelves.

    Raises:
        SlotsDefinitionError: unreadable / non-JSON source, schema error, or any rule of ``_validate``.
    """
    if isinstance(source, (str, Path)):
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SlotsDefinitionError(f"cannot read slots definition {source}: {exc}") from exc
    elif isinstance(source, dict):
        data = source
    else:
        raise SlotsDefinitionError(f"unsupported slots definition source: {type(source).__name__}")
    if not isinstance(data, dict):
        raise SlotsDefinitionError("slots definition must be a JSON object")

    shelves = data.get("shelves") or []
    is_page1 = "planogram" in data or (
        bool(shelves) and isinstance(shelves[0], dict) and isinstance(shelves[0].get("products"), dict)
    )
    native = _normalise_page1(data) if is_page1 else data
    try:
        definition = SlotsDefinition.model_validate(native)
    except ValidationError as exc:
        raise SlotsDefinitionError(f"invalid slots definition: {exc}") from exc

    definition.shelves.sort(key=lambda s: s.shelf_number)
    for shelf in definition.shelves:
        shelf.facings.sort(key=lambda f: (f.slot, f.facing_index))
    _normalise_zone_shelves(definition)
    _validate(definition)
    logger.debug(
        "slots definition loaded: %d shelves, %d facings, %d zones",
        len(definition.shelves),
        len(definition.all_facings()),
        len(definition.zones),
    )
    return definition


def definition_coverage(definition: SlotsDefinition) -> Tuple[float, List[str]]:
    """Return ``(fraction of facings with sufficient descriptors, undescribed facing_ids)``. Never raises.

    Args:
        definition: A loaded definition.

    Returns:
        The coverage fraction (``1.0`` for a definition without facings) and the ids of occupied facings
        lacking sufficient descriptors. Expected-empty facings count as covered, and a described occurrence
        of the same ``product`` counts for every occupied facing of it.
    """
    facings = definition.all_facings()
    if not facings:
        return 1.0, []
    occupied = [f for f in facings if f.expected_occupancy == "occupied"]
    sufficient_products = {f.product for f in occupied if f.descriptors.sufficient}
    undescribed = [f.facing_id for f in occupied if f.product not in sufficient_products]
    return (len(facings) - len(undescribed)) / len(facings), undescribed


def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:
    """Validate ``planogram_config["rule_bindings"]`` against the definition's stable ids.

    Args:
        definition: A loaded definition.
        planogram_config: The raw planogram configuration.

    Returns:
        The validated bindings (``[]`` when the key is absent).

    Raises:
        SlotsDefinitionError: malformed binding, duplicate ``rule_id``, dangling ``target_id``, ambiguous
            ``target_id`` (present in more than one of facing / zone / shelf namespaces), or a shelf with
            no facings that ends up with no mandatory bound rule, or a required zone without a mandatory
            ``zone_present`` binding targeting that zone.
    """
    raw = (planogram_config or {}).get("rule_bindings")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise SlotsDefinitionError("rule_bindings must be a list")
    bindings: List[RuleBinding] = []
    for index, item in enumerate(raw):
        try:
            bindings.append(RuleBinding.model_validate(item))
        except ValidationError as exc:
            raise SlotsDefinitionError(f"malformed rule binding #{index}: {exc}") from exc

    dupes = _duplicates([b.rule_id for b in bindings])
    if dupes:
        raise SlotsDefinitionError(f"duplicate rule_id: {', '.join(dupes)}")

    namespaces = {
        "facing": {f.facing_id for f in definition.all_facings()},
        "zone": {z.zone_id for z in definition.zones},
        "shelf": {s.shelf_id for s in definition.shelves},
    }
    for binding in bindings:
        hits = [name for name, ids in namespaces.items() if binding.target_id in ids]
        if not hits:
            raise SlotsDefinitionError(f"rule {binding.rule_id}: dangling target_id {binding.target_id!r}")
        if len(hits) > 1:
            raise SlotsDefinitionError(
                f"rule {binding.rule_id}: ambiguous target_id {binding.target_id!r} ({' / '.join(hits)})"
            )

    mandatory_targets = {b.target_id for b in bindings if b.mandatory}
    for shelf in definition.shelves:
        if shelf.facings:
            continue
        shelf_zone_ids = {z.zone_id for z in definition.zones if z.shelf_id == shelf.shelf_id}
        if shelf.shelf_id not in mandatory_targets and not (shelf_zone_ids & mandatory_targets):
            raise SlotsDefinitionError(f"{shelf.shelf_id}: zone-only shelf has no mandatory bound rule")
    presence = {b.target_id for b in bindings if b.kind == "zone_present" and b.mandatory}
    for zone in definition.zones:
        if zone.required and zone.zone_id not in presence:
            raise SlotsDefinitionError(f"required zone {zone.zone_id}: no mandatory zone_present binding")
    return bindings
