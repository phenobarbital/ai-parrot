"""Shared compatibility codec for stored crew definitions."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition


def strip_unknown_keys(crew_dict: dict[str, Any], crew_id: str, logger: logging.Logger) -> dict[str, Any]:
    """Copy declared root/nested fields and preserve existing drift warnings.

    Args:
        crew_dict: The decoded stored document.
        crew_id: Crew identifier, for the log message.
        logger: Logger used to report schema drift.

    Returns:
        A copy carrying only fields declared by the crew definition models.
    """
    dropped: list[str] = []

    def _prune(payload: Any, model: Any, path: str) -> Any:
        if not isinstance(payload, dict):
            return payload
        known = set(model.model_fields)
        dropped.extend(f"{path}{key}" for key in sorted(set(payload) - known))
        return {key: value for key, value in payload.items() if key in known}

    cleaned = _prune(crew_dict, CrewDefinition, "")
    for field, model in (
        ("agents", AgentDefinition),
        ("tool_nodes", ToolNodeDefinition),
        ("flow_relations", FlowRelation),
    ):
        entries = cleaned.get(field)
        if isinstance(entries, list):
            cleaned[field] = [_prune(entry, model, f"{field}[{index}].") for index, entry in enumerate(entries)]

    if dropped:
        logger.warning(
            "Ignoring unknown key(s) %s in stored crew %r; the field(s) "
            "are not part of the crew definition models and were never "
            "applied.",
            dropped,
            crew_id,
        )
    return cleaned


def crew_definition_from_dict(crew_dict: dict[str, Any], logger: logging.Logger) -> CrewDefinition:
    """Parse ISO timestamps, strip unknown keys, and validate the stored document.

    Args:
        crew_dict: Decoded stored crew definition.
        logger: Logger used to report schema drift.

    Returns:
        The validated crew definition.

    Raises:
        ValueError: If the stored data is incompatible with ``CrewDefinition``.
    """
    if "created_at" in crew_dict and isinstance(crew_dict["created_at"], str):
        crew_dict["created_at"] = datetime.fromisoformat(crew_dict["created_at"])
    if "updated_at" in crew_dict and isinstance(crew_dict["updated_at"], str):
        crew_dict["updated_at"] = datetime.fromisoformat(crew_dict["updated_at"])

    cleaned = strip_unknown_keys(crew_dict, crew_dict.get("crew_id", "<unknown>"), logger)
    return CrewDefinition(**cleaned)


def crew_definition_to_document(crew: CrewDefinition) -> dict[str, Any]:
    """Return the JSON-compatible definition without double encoding.

    Args:
        crew: Crew definition to encode.

    Returns:
        JSON-compatible crew document.
    """
    return crew.model_dump(mode="json")
