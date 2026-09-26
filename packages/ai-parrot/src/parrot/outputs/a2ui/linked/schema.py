"""JSON Schema of ``parrot_data_sources`` (FEAT-598 M1, S7) — the published renderer contract."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from parrot.outputs.a2ui.linked.models import LinkedSources

logger = logging.getLogger(__name__)

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://ai-parrot.dev/schemas/a2ui/linked-sources.v1.json"
SCHEMA_PATH = Path(__file__).parent / "contract" / "schema.json"


def export_json_schema() -> dict[str, Any]:
    """Return the JSON Schema (draft 2020-12) of ``LinkedSources``."""
    schema = LinkedSources.model_json_schema(by_alias=True, mode="validation")
    schema = {"$schema": SCHEMA_DRAFT, "$id": SCHEMA_ID, **schema, "title": "LinkedSources"}
    return schema


def dumps_schema(schema: dict[str, Any] | None = None) -> str:
    """Serialise the schema deterministically (sorted keys, 2-space indent, trailing newline)."""
    return json.dumps(schema or export_json_schema(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_json_schema(path: Path | None = None) -> Path:
    """Write the schema to ``path`` (default ``contract/schema.json``) and return the path."""
    target = path or SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps_schema(), encoding="utf-8")
    logger.info("linked-sources JSON Schema written to %s", target)
    return target


if __name__ == "__main__":
    write_json_schema()
