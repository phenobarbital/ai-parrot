"""Evidence-only evaluation of bound planogram rules."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from parrot.models.compliance import TextMatcher
from parrot.models.detections import TextRequirement
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, ZoneDefinition
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationRef,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    RuleOutcome,
    Shape,
    ShapeKind,
    Slot,
)

logger = logging.getLogger(__name__)

ZONE_REGION_TARGET = "{image_id}:zone-region:{zone_id}"


def normalize_text(text: str) -> str:
    """Normalize OCR text using the ProductOnShelves comparison semantics."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = re.sub(
        r"[\u2014\u2013\u2010-\u2012\u2e3a\u2026\u201c\u201d\"'\u00b7\u2022\u2219\u00b7\u2022\u2014\u2013/\\|_=+^°™®©§]",
        " ",
        text,
    )
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def visual_feature_match(expected: Sequence[str], detected: Sequence[str]) -> float:
    """Calculate visual-feature similarity using the ProductOnShelves semantics."""
    if not expected:
        return 1.0
    if not detected:
        return 0.0

    stop_words = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "on",
        "of",
        "in",
        "at",
        "to",
        "for",
        "with",
        "visible",
        "displayed",
        "showing",
    }
    semantic_mappings = {
        "active": ["active", "on", "powered", "illuminated", "lit"],
        "display": ["display", "screen", "tv", "television", "monitor"],
        "illuminated": ["illuminated", "backlit", "lit", "bright", "glowing"],
        "logo": ["logo", "text", "branding", "brand"],
        "dynamic": ["dynamic", "colorful", "graphics", "content"],
        "official": ["official", "partner"],
        "white": ["white", "large"],
    }

    def keywords(value: str) -> set[str]:
        return {word for word in value.lower().strip().split() if word not in stop_words and len(word) > 1}

    detected_keywords: set[str] = set()
    for value in detected:
        detected_keywords.update(keywords(value))

    def matches(word: str) -> bool:
        if word in detected_keywords:
            return True
        synonyms = semantic_mappings.get(word)
        if synonyms and any(synonym in detected_keywords for synonym in synonyms):
            return True
        return any(word in keyword for keyword in detected_keywords)

    matched = sum(any(matches(word) for word in keywords(value)) for value in expected)
    return matched / len(expected)


def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:
    """Return an explicit unknown outcome; unknown evidence is not failure."""
    return RuleOutcome(rule_id=binding.rule_id, assessed=False, passed=None, score=0.0, penalty=0.0, detail=detail)


def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:
    """Create a provenance reference for rule evidence."""
    return ObservationRef(image_id=image_id, shape_id=target_id, source=source)


def _dedupe_refs(refs: Sequence[ObservationRef]) -> List[ObservationRef]:
    """Keep provenance order while removing duplicate references."""
    seen: set[Tuple[str, str, ObservationSource]] = set()
    result: List[ObservationRef] = []
    for ref in refs:
        key = (ref.image_id, ref.shape_id, ref.source)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def match_zone(
    zone: ZoneDefinition,
    perception: PerceptionResult,
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> Tuple[Optional[Shape], str]:
    """Match one definition zone to at most one observed zone in one image."""
    candidates = sorted(
        (candidate for candidate in perception.zones if candidate.membership != FixtureMembership.OFF_FIXTURE),
        key=lambda candidate: (candidate.box.y1, candidate.box.x1),
    )
    selector = next((item for item in selectors if getattr(item, "zone_id", None) == zone.zone_id), None)
    if selector is None:
        if len(definition.zones) != 1:
            return None, "ambiguous"
        if not candidates:
            return None, "not_observed"
        return (candidates[0], "matched") if len(candidates) == 1 else (None, "ambiguous")

    region = getattr(selector, "region", None)
    width, height = perception.image_size
    filtered = [
        candidate
        for candidate in candidates
        if (getattr(selector, "profile", None) is None or candidate.profile == selector.profile)
        and (getattr(selector, "kind", None) is None or candidate.kind.value == selector.kind)
        and (
            region is None
            or (
                region[0] * width <= (candidate.box.x1 + candidate.box.x2) / 2 <= region[2] * width
                and region[1] * height <= (candidate.box.y1 + candidate.box.y2) / 2 <= region[3] * height
            )
        )
    ]
    same_group = [
        item
        for item in selectors
        if getattr(item, "profile", None) == getattr(selector, "profile", None)
        and getattr(item, "kind", None) == getattr(selector, "kind", None)
    ]
    ordinal = getattr(selector, "ordinal", None)
    if ordinal is not None:
        if len(filtered) != len(same_group) or ordinal >= len(filtered):
            return None, "ambiguous"
        return filtered[ordinal], "matched"
    if not filtered:
        return None, "not_observed"
    return (filtered[0], "matched") if len(filtered) == 1 else (None, "ambiguous")


def _zone_matches(
    target_id: str,
    perceptions: Sequence[PerceptionResult],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> List[Tuple[str, ZoneDefinition, Optional[Shape], str]]:
    """Return one selector decision for every definition zone and image."""
    zones = [zone for zone in definition.zones if zone.zone_id == target_id]
    if not zones:
        zones = [zone for zone in definition.zones if zone.shelf_id == target_id]
    return [
        (perception.image_id, zone, *match_zone(zone, perception, definition, selectors))
        for perception in perceptions
        for zone in zones
    ]


def _rule_observations(
    observations: Sequence[RuleObservation], image_id: str, target_ids: Sequence[str], kind: str
) -> List[RuleObservation]:
    """Select assessed neutral observations for one image and target set."""
    return [
        observation
        for observation in observations
        if observation.image_id == image_id
        and observation.target_id in target_ids
        and observation.kind == kind
        and observation.assessed
    ]


def _facing_targets(target_id: str, definition: SlotsDefinition) -> List[str]:
    """Expand a shelf or facing target to facing ids."""
    if any(shelf.shelf_id == target_id for shelf in definition.shelves):
        return [facing.facing_id for facing in definition.all_facings() if facing.shelf_id == target_id]
    return [target_id]


def _registered_identifications(
    target_id: str,
    registrations: Sequence[ImageRegistration],
    by_image: Dict[str, Dict[str, Identification]],
    definition: SlotsDefinition,
) -> List[Tuple[str, Identification]]:
    """Collect identifications registered to a facing or shelf target."""
    target_ids = set(_facing_targets(target_id, definition))
    result: List[Tuple[str, Identification]] = []
    for registration in registrations:
        image_idents = by_image.get(registration.image_id, {})
        for shape_id, facing_id in registration.assignments.items():
            if facing_id in target_ids and shape_id in image_idents:
                result.append((registration.image_id, image_idents[shape_id]))
    return result


def _entity_texts(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> Tuple[bool, List[str], List[ObservationRef]]:
    """Collect OCR, zone, and registered-facing text evidence for a target."""
    features: List[str] = []
    refs: List[ObservationRef] = []
    observed = False
    results = {result.image_id: result for result in identifications}
    for image_id, _zone, shape, status in _zone_matches(binding.target_id, perceptions, definition, selectors):
        if status != "matched" or shape is None:
            continue
        observed = True
        refs.append(_ref(image_id, shape.shape_id, shape.source))
        if shape.ocr_text:
            features.extend([f"ocr:{shape.ocr_text}", shape.ocr_text])
        reading = next(
            (
                perception.ocr_readings.get(shape.shape_id)
                for perception in perceptions
                if perception.image_id == image_id
            ),
            None,
        )
        if reading and reading.text:
            features.extend([f"ocr:{reading.text}", reading.text])
        result = results.get(image_id)
        if result:
            for identification in result.identifications:
                if identification.shape_id == shape.shape_id:
                    observed = True
                    for text in (identification.text, identification.product, *identification.evidence):
                        if text:
                            features.extend([f"ocr:{text}", text])
                    refs.append(_ref(image_id, identification.shape_id, identification.source))
    for image_id, identification in _registered_identifications(
        binding.target_id,
        registrations,
        {result.image_id: {item.shape_id: item for item in result.identifications} for result in identifications},
        definition,
    ):
        observed = True
        for text in (identification.text, identification.product, *identification.evidence):
            if text:
                features.extend([f"ocr:{text}", text])
        refs.append(_ref(image_id, identification.shape_id, identification.source))
    return observed, [normalize_text(feature) for feature in features if feature], _dedupe_refs(refs)


def _rule_zone_present(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    observations: Sequence[RuleObservation],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> RuleOutcome:
    """Evaluate positive zone presence and explicit inspected absence."""
    present: List[ObservationRef] = []
    absent: List[ObservationRef] = []
    for image_id, zone, shape, status in _zone_matches(binding.target_id, perceptions, definition, selectors):
        if status == "matched" and shape is not None:
            present.append(_ref(image_id, shape.shape_id, shape.source))
        region_target = ZONE_REGION_TARGET.format(image_id=image_id, zone_id=zone.zone_id)
        for observation in _rule_observations(observations, image_id, [region_target], "zone_present"):
            ref = _ref(image_id, observation.target_id, observation.source)
            if observation.value is True:
                present.append(ref)
            elif observation.value is False:
                absent.append(ref)
    present = _dedupe_refs(present)
    absent = _dedupe_refs(absent)
    if present and absent:
        return RuleOutcome(
            rule_id=binding.rule_id,
            assessed=False,
            passed=None,
            score=0.0,
            penalty=0.0,
            detail="conflict: zone presence differs across images",
            observations=[*present, *absent],
        )
    if present:
        return RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=True, score=1.0, observations=present)
    if absent:
        return RuleOutcome(
            rule_id=binding.rule_id,
            assessed=True,
            passed=False,
            score=0.0,
            detail="zone region inspected: absent",
            observations=absent,
        )
    if any(
        status == "ambiguous"
        for _, _, _, status in _zone_matches(binding.target_id, perceptions, definition, selectors)
    ):
        return _unassessed(binding, "ambiguous zone match")
    return _unassessed(binding, "zone visibility unknown")


def _rule_illumination(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    observations: Sequence[RuleObservation],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> RuleOutcome:
    """Evaluate illumination states already collected by the identification stage."""
    matched = _zone_matches(binding.target_id, perceptions, definition, selectors)
    states: List[Tuple[str, ObservationRef]] = []
    for image_id, _zone, shape, status in matched:
        if status != "matched" or shape is None:
            continue
        for observation in _rule_observations(observations, image_id, [shape.shape_id], "illumination"):
            if isinstance(observation.value, str):
                states.append(
                    (observation.value.strip().lower(), _ref(image_id, observation.target_id, observation.source))
                )
    if not states:
        return _unassessed(binding, "illumination target not observed")
    distinct = {state for state, _ in states}
    refs = _dedupe_refs([ref for _, ref in states])
    if {"on", "off"}.issubset(distinct):
        return RuleOutcome(
            rule_id=binding.rule_id,
            assessed=False,
            passed=None,
            score=0.0,
            detail="conflict: illumination differs across images",
            observations=refs,
        )
    required = str(binding.params.get("required", "on")).strip().lower()
    state = states[0][0]
    if state == required:
        return RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=True, score=1.0, observations=refs)
    name = str(binding.params.get("name") or binding.target_id)
    return RuleOutcome(
        rule_id=binding.rule_id,
        assessed=True,
        passed=False,
        score=0.0,
        penalty=float(binding.params.get("penalty", 0.5)),
        detail=f"{name} — backlight {state.upper()} (required: {required.upper()})",
        observations=refs,
    )


def _rule_text(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> RuleOutcome:
    """Evaluate text requirements against OCR and identification evidence."""
    requirements = [
        TextRequirement(**requirement) if isinstance(requirement, dict) else requirement
        for requirement in binding.params.get("requirements", [])
    ]
    if not requirements:
        return _unassessed(binding, "no text requirements")
    observed, features, refs = _entity_texts(
        binding, perceptions, identifications, registrations, definition, selectors
    )
    if not observed:
        return _unassessed(binding, "text target not observed")
    results = [
        TextMatcher.check_text_match(
            required_text=requirement.required_text,
            visual_features=features,
            match_type=requirement.match_type,
            case_sensitive=requirement.case_sensitive,
            confidence_threshold=requirement.confidence_threshold,
        )
        for requirement in requirements
    ]
    score = sum(result.confidence for result in results if result.found) / len(results)
    missing = [
        requirement.required_text
        for requirement, result in zip(requirements, results, strict=True)
        if requirement.mandatory and not result.found
    ]
    return RuleOutcome(
        rule_id=binding.rule_id,
        assessed=True,
        passed=not missing,
        score=max(0.0, min(1.0, score)),
        detail=f"missing mandatory text: {', '.join(missing)}" if missing else None,
        observations=refs,
    )


def _rule_visual(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
    observations: Sequence[RuleObservation],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> RuleOutcome:
    """Evaluate visual features from neutral observations and text evidence."""
    observed, detected, refs = _entity_texts(
        binding, perceptions, identifications, registrations, definition, selectors
    )
    matched = _zone_matches(binding.target_id, perceptions, definition, selectors)
    for image_id, _zone, shape, status in matched:
        if status != "matched" or shape is None:
            continue
        for observation in _rule_observations(observations, image_id, [shape.shape_id], "visual_features"):
            if isinstance(observation.value, list):
                observed = True
                detected.extend(str(item) for item in observation.value)
                refs.append(_ref(image_id, observation.target_id, observation.source))
    if not observed:
        return _unassessed(binding, "visual target not identified")
    expected = [str(value) for value in binding.params.get("expected", [])]
    score = visual_feature_match(expected, detected)
    return RuleOutcome(
        rule_id=binding.rule_id,
        assessed=True,
        passed=score >= float(binding.params.get("threshold", 0.5)),
        score=max(0.0, min(1.0, score)),
        observations=_dedupe_refs(refs),
    )


_TAG_KINDS = frozenset({ShapeKind.FACT_TAG, ShapeKind.PRICE_TAG})


def _rule_fact_tag(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
) -> RuleOutcome:
    """Evaluate tag presence and an optionally required legible price for one facing."""
    price_required = bool(binding.params.get("price_required"))
    reads = {result.image_id: {item.shape_id: item for item in result.identifications} for result in identifications}
    by_image = {registration.image_id: registration for registration in registrations}
    seen = False
    tagged: List[ObservationRef] = []
    priced: List[ObservationRef] = []
    facing_refs: List[ObservationRef] = []
    for perception in perceptions:
        registration = by_image.get(perception.image_id)
        if registration is None:
            continue
        registered = {shape_id for shape_id, facing in registration.assignments.items() if facing == binding.target_id}
        if not registered:
            continue
        seen = True
        facing_slots = {
            slot.slot_id
            for slot in perception.slots
            if slot.slot_id in registered or slot.anchor_shape_id in registered
        }
        anchors = {slot.anchor_shape_id for slot in perception.slots if slot.slot_id in facing_slots}
        facing_refs.extend(_ref(perception.image_id, shape_id, ObservationSource.CV) for shape_id in registered)
        for tag in perception.shapes:
            if tag.kind not in _TAG_KINDS or tag.membership == FixtureMembership.OFF_FIXTURE:
                continue
            above: Optional[Slot] = slot_above(tag, perception.slots)
            if tag.shape_id not in anchors and (above is None or above.slot_id not in facing_slots):
                continue
            tag_ref = _ref(perception.image_id, tag.shape_id, tag.source)
            tagged.append(tag_ref)
            text = tag_text(tag, perception.ocr_readings, reads.get(perception.image_id, {}))
            if tag_price(text) is not None:
                priced.append(tag_ref)

    if not seen:
        return _unassessed(binding, "facing not observed")
    if tagged and (not price_required or priced):
        return RuleOutcome(
            rule_id=binding.rule_id,
            assessed=True,
            passed=True,
            score=1.0,
            penalty=0.0,
            observations=_dedupe_refs(priced or tagged),
        )
    if tagged:
        return RuleOutcome(
            rule_id=binding.rule_id,
            assessed=True,
            passed=False,
            score=0.0,
            penalty=0.0,
            detail="fact tag present, price not legible",
            observations=_dedupe_refs(facing_refs),
        )
    return RuleOutcome(
        rule_id=binding.rule_id,
        assessed=True,
        passed=False,
        score=0.0,
        penalty=0.0,
        detail="fact tag not observed",
        observations=_dedupe_refs(facing_refs),
    )


def evaluate_rules(
    perceptions: Sequence[PerceptionResult],
    identifications: Sequence[IdentificationResult],
    registrations: Sequence[ImageRegistration],
    ctx: CycleContext,
) -> Dict[str, RuleOutcome]:
    """Evaluate every bound rule from collected evidence only."""
    definition = ctx.definition
    if definition is None:
        raise ValueError("evaluate_rules requires a slots definition")
    selectors = list(ctx.layout.zone_selectors) if ctx.layout is not None else []
    observations = [observation for result in identifications for observation in result.rule_observations]
    outcomes: Dict[str, RuleOutcome] = {}
    for binding in ctx.bindings:
        try:
            if binding.kind == "zone_present":
                outcome = _rule_zone_present(binding, perceptions, observations, definition, selectors)
            elif binding.kind == "illumination":
                outcome = _rule_illumination(binding, perceptions, observations, definition, selectors)
            elif binding.kind == "text_requirements":
                outcome = _rule_text(binding, perceptions, identifications, registrations, definition, selectors)
            elif binding.kind == "visual_features":
                outcome = _rule_visual(
                    binding, perceptions, identifications, registrations, observations, definition, selectors
                )
            elif binding.kind == "fact_tag_present":
                outcome = _rule_fact_tag(binding, perceptions, identifications, registrations)
            else:
                outcome = _unassessed(binding, "unknown rule kind")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rule %s not assessed: %s", binding.rule_id, exc)
            ctx.errors.append(f"rule {binding.rule_id}: {exc}")
            outcome = _unassessed(binding, str(exc))
        outcomes[binding.rule_id] = outcome
    return outcomes
