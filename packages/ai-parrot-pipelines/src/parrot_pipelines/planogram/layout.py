"""Validated layout profiles and configuration overrides (FEAT-612)."""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .comparison.definition import SlotsDefinition
from .contracts import IdentifyStrategy, ShapeKind
from .perception.profiles import ShapeProfile
from .perception.slots import AnchorRule

logger = logging.getLogger(__name__)

LAYOUT_KEY = "layout_profile"
_SHAPE_KINDS = frozenset(kind.value for kind in ShapeKind)


class ReferencePolicy(BaseModel):
    """Bound and select references without using expected shelf identity."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    selection: Literal["all", "by_brand"] = "all"
    max_per_call: int = Field(default=5, gt=0)
    brand_by_reference: Dict[str, str] = Field(default_factory=dict)


class ZoneSelector(BaseModel):
    """Match observed zones, never invent them from an expected id."""

    model_config = ConfigDict(extra="forbid")

    zone_id: str = Field(min_length=1)
    profile: Optional[str] = None
    kind: Optional[str] = None
    ordinal: Optional[int] = Field(default=None, ge=0)
    region: Optional[Tuple[float, float, float, float]] = None
    #: ``(y_start, y_end)`` as fractions of the observed fixture height: every zone fragment whose centre
    #: falls in the band belongs to this zone (see ``perception.bands``).
    band: Optional[Tuple[float, float]] = None

    @model_validator(mode="after")
    def _check(self) -> "ZoneSelector":
        """Validate kind, normalized non-reversed region bounds, and the fixture band."""
        if self.band is not None:
            if self.region is not None or self.ordinal is not None:
                raise ValueError("band: cannot be combined with region or ordinal")
            if not 0.0 <= self.band[0] < self.band[1] <= 1.0:
                raise ValueError("band: 0 <= y_start < y_end <= 1 is required")
        if self.kind is not None and self.kind not in _SHAPE_KINDS:
            raise ValueError(f"kind: {self.kind!r} is not a ShapeKind value")
        if self.region is not None:
            x1, y1, x2, y2 = self.region
            if any(value < 0.0 or value > 1.0 for value in self.region):
                raise ValueError("region: coordinates must be in 0..1")
            if x1 >= x2 or y1 >= y2:
                raise ValueError("region: x1 < x2 and y1 < y2 are required")
        return self


class LayoutProfile(BaseModel):
    """Strict, validated perception and identification settings; extra keys forbidden."""

    model_config = ConfigDict(extra="forbid")

    shape_profiles: List[ShapeProfile]
    anchor_rule: AnchorRule = AnchorRule.SHAPE_IS_SLOT
    fill_gaps: bool = False
    untagged_bottom_row: bool = False
    identify_strategy: IdentifyStrategy = IdentifyStrategy.FULL_IMAGE
    perception_mode: Literal["cv", "llm_detector"] = "cv"
    min_usable_shapes: int = Field(default=1, ge=0)
    min_row_items: int = Field(default=1, ge=1)
    max_row_slope: float = Field(default=0.12, ge=0.0)
    work_width: int = Field(default=2048, gt=0)
    substrip_max_slots: int = Field(default=8, gt=0)
    ocr_batch_size: int = Field(default=16, gt=0)
    descriptor_fields: List[str] = Field(default_factory=list)
    required_descriptor_fields: List[str] = Field(default_factory=list)
    ocr_targets: List[Literal["slot", "tag", "zone"]] = Field(default_factory=lambda: ["slot", "tag", "zone"])
    references: ReferencePolicy = Field(default_factory=ReferencePolicy)
    zone_selectors: List[ZoneSelector] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "LayoutProfile":
        """Validate cross-field layout-profile constraints."""
        if self.perception_mode == "cv" and not self.shape_profiles:
            raise ValueError("shape_profiles: required for cv")
        for index, profile in enumerate(self.shape_profiles):
            if profile.kind not in _SHAPE_KINDS:
                raise ValueError(f"shape_profiles.{index}.kind: {profile.kind!r} is not a ShapeKind value")
        self._check_unique("shape_profiles", [profile.name for profile in self.shape_profiles])
        self._check_unique("zone_selectors", [selector.zone_id for selector in self.zone_selectors])
        self._check_unique("descriptor_fields", self.descriptor_fields)
        self._check_unique("ocr_targets", self.ocr_targets)
        undeclared = sorted(set(self.required_descriptor_fields) - set(self.descriptor_fields))
        if undeclared:
            raise ValueError(f"required_descriptor_fields: not declared in descriptor_fields: {', '.join(undeclared)}")
        names = {profile.name for profile in self.shape_profiles}
        for index, selector in enumerate(self.zone_selectors):
            if selector.profile is not None and names and selector.profile not in names:
                raise ValueError(f"zone_selectors.{index}.profile: unknown profile {selector.profile!r}")
        return self

    @staticmethod
    def _check_unique(field: str, values: List[str]) -> None:
        """Reject duplicate values while naming the affected profile field."""
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ValueError(f"{field}: duplicate values: {', '.join(duplicates)}")


def _reject_unknown_shape_keys(overrides: Dict[str, Any]) -> List[str]:
    """Return unknown field paths inside shape-profile override entries."""
    unknown: List[str] = []
    for index, item in enumerate(overrides.get("shape_profiles") or []):
        if isinstance(item, dict):
            unknown.extend(
                f"layout_profile.shape_profiles.{index}.{key}" for key in item if key not in ShapeProfile.model_fields
            )
    return unknown


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge nested dictionaries; replace every other value atomically."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile:
    """Merge and validate a config override without mutating its inputs.

    Args:
        defaults: The planogram type's default profile.
        config: Raw planogram configuration containing optional profile overrides.
        config_name: Name included in validation errors.

    Returns:
        A new validated layout profile.

    Raises:
        ValueError: The override does not satisfy the layout-profile contract.
    """
    raw = (config or {}).get(LAYOUT_KEY)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_name}: invalid layout_profile: expected an object, got {type(raw).__name__}")
    overrides = copy.deepcopy(raw)
    top_perception_mode = (config or {}).get("perception_mode")
    if top_perception_mode is not None:
        if "perception_mode" in overrides and overrides["perception_mode"] != top_perception_mode:
            raise ValueError(
                f"{config_name}: invalid layout_profile.perception_mode: contradicts top-level perception_mode"
            )
        overrides["perception_mode"] = top_perception_mode
    unknown = _reject_unknown_shape_keys(overrides)
    if unknown:
        raise ValueError(f"{config_name}: invalid layout_profile: unknown keys: {', '.join(unknown)}")
    merged = _deep_merge(defaults.model_dump(), overrides)
    try:
        profile = LayoutProfile.model_validate(merged)
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            path = ".".join(str(part) for part in error["loc"])
            message = error["msg"]
            if message.startswith("Value error, ") and ":" in message:
                field, message = message.removeprefix("Value error, ").split(":", maxsplit=1)
                path = ".".join(part for part in (path, field) if part)
            if path:
                errors.append(f"layout_profile.{path}: {message}")
            else:
                errors.append(f"layout_profile.{message}")
        raise ValueError(f"{config_name}: invalid layout_profile: {'; '.join(errors)}") from exc
    logger.debug(
        "layout profile resolved for %s: mode=%s strategy=%s",
        config_name,
        profile.perception_mode,
        profile.identify_strategy.value,
    )
    return profile


def validate_zone_selectors(profile: LayoutProfile, definition: SlotsDefinition, *, config_name: str) -> None:
    """Validate selector ids and ambiguous repeated zone kinds against a definition.

    Args:
        profile: Validated configuration profile.
        definition: Loaded expected planogram definition.
        config_name: Name included in validation errors.

    Raises:
        ValueError: A selector is dangling or repeated zone kinds lack selectors.
    """
    zone_ids = {zone.zone_id for zone in definition.zones}
    selected_ids = {selector.zone_id for selector in profile.zone_selectors}
    for index, selector in enumerate(profile.zone_selectors):
        if selector.zone_id not in zone_ids:
            raise ValueError(
                f"{config_name}: invalid layout_profile.zone_selectors.{index}.zone_id: "
                f"unknown zone {selector.zone_id!r}"
            )
    zones_by_kind: Dict[str, List[str]] = {}
    for zone in definition.zones:
        zones_by_kind.setdefault(zone.kind, []).append(zone.zone_id)
    missing = sorted(
        zone_id
        for zone_ids_by_kind in zones_by_kind.values()
        if len(zone_ids_by_kind) >= 2
        for zone_id in zone_ids_by_kind
        if zone_id not in selected_ids
    )
    if missing:
        raise ValueError(
            f"{config_name}: invalid layout_profile.zone_selectors: required for repeated zone kinds: "
            f"{', '.join(missing)}"
        )
