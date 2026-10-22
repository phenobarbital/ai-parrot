"""Pure entity vocabulary and frontmatter normalization."""

from collections.abc import Mapping
from datetime import date, datetime
import logging
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

EntityType = Literal["project", "engagement", "meeting", "ticket", "task", "decision", "deliverable", "person"]

STATUS_BY_TYPE: dict[EntityType, tuple[str, ...]] = {
    "project": ("active", "paused", "done", "archived"),
    "engagement": ("active", "paused", "done", "archived"),
    "meeting": ("scheduled", "held", "cancelled"),
    "ticket": ("open", "in-progress", "blocked", "in-review", "closed"),
    "task": ("pending", "in-progress", "done", "done-with-issues"),
    "decision": ("proposed", "accepted", "rejected", "superseded", "deprecated"),
    "deliverable": ("draft", "sent", "approved", "rejected"),
    "person": (),
}

OPEN_STATUSES: dict[EntityType, frozenset[str]] = {
    "project": frozenset({"active", "paused"}),
    "engagement": frozenset({"active", "paused"}),
    "meeting": frozenset({"scheduled"}),
    "ticket": frozenset({"open", "in-progress", "blocked", "in-review"}),
    "task": frozenset({"pending", "in-progress"}),
    "decision": frozenset({"proposed"}),
    "deliverable": frozenset({"draft"}),
    "person": frozenset(),
}

URGENT_STATUSES = frozenset({"blocked"})
ATTR_KEYS = (
    "type",
    "status",
    "status_raw",
    "project",
    "date",
    "due",
    "owner",
    "source",
    "language",
    "period",
    "items",
    "urgent",
)
TYPE_ALIASES: dict[str, EntityType] = {"meeting-source": "meeting", "issue": "ticket"}
KEY_ALIASES: dict[str, str] = {
    "meeting_date": "date",
    "primary_project": "project",
    "updated_at": "date",
    "due_date": "due",
}

_FRONTMATTER_DELIMITER = "---"
_YAML_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")
_ENTITY_TYPES = frozenset(STATUS_BY_TYPE)
_SCALAR_KEYS = frozenset((*ATTR_KEYS, "projects", *KEY_ALIASES))
logger = logging.getLogger(__name__)


class EntityValidationError(ValueError):
    """Strict normalization error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the error with its stable code and explanatory message."""
        super().__init__(message)
        self.code = code


class EntityAttrs(BaseModel):
    """Validated entity fields and prefixed scalar extensions."""

    type: EntityType | None = None
    status: str | None = None
    status_raw: str | None = None
    project: str | None = None
    date: str | None = None
    due: str | None = None
    owner: str | None = None
    source: str | None = None
    language: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)

    def to_rows(self) -> dict[str, str]:
        """Flatten non-null fields and x_-prefixed extensions to string rows.

        Returns:
            A page-attributes mapping with non-null canonical fields and extensions.
        """
        rows = {
            key: value
            for key, value in self.model_dump(exclude={"extra"}, exclude_none=True).items()
            if isinstance(value, str)
        }
        rows.update({f"x_{key.removeprefix('x_')}": value for key, value in self.extra.items()})
        return rows


def _as_scalar(value: Any) -> str | None:
    """Return a stable string representation for accepted scalar values."""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return None


def _coerce_date(value: Any) -> str | None:
    """Coerce a date or ISO datetime input to its ISO calendar date."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None


def normalize_frontmatter(fm: Mapping[str, Any], *, source: str, strict: bool = False) -> EntityAttrs:
    """Normalize aliases, dates and per-type statuses; optionally reject invalid values.

    Args:
        fm: Parsed frontmatter values.
        source: Provenance to attach to the normalized attributes.
        strict: Whether invalid entity types, statuses, and dates raise errors.

    Returns:
        The normalized, persistence-ready entity attributes.

    Raises:
        EntityValidationError: If strict validation rejects a type, status, or date.
    """
    normalized: dict[str, Any] = {}
    extras: dict[str, str] = {}
    projects: list[str] | None = None

    for raw_key, value in fm.items():
        if not isinstance(raw_key, str):
            continue
        key = KEY_ALIASES.get(raw_key.lower(), raw_key.lower())
        if key == "projects" and isinstance(value, list):
            projects = [item for item in (_as_scalar(item) for item in value) if item is not None]
            continue
        if key in _SCALAR_KEYS:
            normalized[key] = value
            continue
        scalar = _as_scalar(value)
        if scalar is not None:
            extras[key] = scalar

    raw_type = _as_scalar(normalized.get("type"))
    entity_type: EntityType | None = None
    if raw_type:
        type_key = raw_type.strip().lower()
        resolved_type = TYPE_ALIASES.get(type_key, type_key)
        if resolved_type in _ENTITY_TYPES:
            entity_type = resolved_type  # type: ignore[assignment]
        elif strict:
            raise EntityValidationError("E_ENTITY_TYPE", f"Unknown entity type: {raw_type}")

    project = _as_scalar(normalized.get("project"))
    if projects:
        extras["projects"] = ",".join(projects)
        if project is None:
            project = projects[0]

    date_values: dict[str, str | None] = {}
    for key in ("date", "due"):
        if key not in normalized:
            date_values[key] = None
            continue
        coerced = _coerce_date(normalized[key])
        if coerced is None and strict:
            raise EntityValidationError("E_ENTITY_DATE", f"Invalid {key}: {normalized[key]!r}")
        date_values[key] = coerced

    raw_status = _as_scalar(normalized.get("status"))
    canonical_status: str | None = None
    if raw_status is not None:
        candidate = raw_status.strip().lower()
        if entity_type is not None and candidate in STATUS_BY_TYPE[entity_type]:
            canonical_status = candidate
        elif strict:
            raise EntityValidationError("E_ENTITY_STATUS", f"Invalid status: {raw_status}")

    return EntityAttrs(
        type=entity_type,
        status=canonical_status,
        status_raw=raw_status,
        project=project,
        date=date_values["date"],
        due=date_values["due"],
        owner=_as_scalar(normalized.get("owner")),
        source=source,
        language=_as_scalar(normalized.get("language")),
        extra=extras,
    )


def parse_leading_yaml(text: str) -> dict[str, Any] | None:
    """Return a leading YAML mapping, or None for missing/invalid frontmatter.

    Args:
        text: Markdown or text content that may begin with YAML frontmatter.

    Returns:
        The parsed mapping, or ``None`` when no valid leading block exists.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() != _FRONTMATTER_DELIMITER:
            continue
        block = lines[1:index]
        if not any(_YAML_KEY_RE.match(line) for line in block):
            return None
        try:
            parsed = yaml.safe_load("\n".join(block))
        except yaml.YAMLError:
            logger.debug("Malformed leading YAML frontmatter", exc_info=True)
            return None
        if not isinstance(parsed, dict):
            logger.debug("Leading YAML frontmatter is not a mapping")
            return None
        return parsed
    return None


def canonical_ticket_status(raw: str | None, status_map: Mapping[str, str]) -> str | None:
    """Map a case-insensitive raw ticket status, returning None when unmapped.

    Args:
        raw: Source ticket status.
        status_map: Raw-to-canonical status mapping.

    Returns:
        The canonical mapped status, or ``None`` if no mapping exists.
    """
    if raw is None:
        return None
    normalized_raw = raw.strip().casefold()
    for key, value in status_map.items():
        if key.strip().casefold() == normalized_raw:
            return value
    return None
