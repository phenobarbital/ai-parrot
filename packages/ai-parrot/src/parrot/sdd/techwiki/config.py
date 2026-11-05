"""TechwikiConfig — Pydantic v2 model for the ``techwiki`` section of ``sdd/config.json``."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class TechwikiPackage(BaseModel):
    """One Python distribution in the workspace whose public API is rendered."""

    model_config = ConfigDict(extra="forbid")

    dist: str
    src: str
    roots: list[str]


class TechwikiConfig(BaseModel):
    """Settings for the technical-wiki pipeline."""

    model_config = ConfigDict(extra="forbid")

    source_dir: str = "wiki"
    index_file: str = "wiki/_index.yaml"
    packages: list[TechwikiPackage] = []
    include_adrs: list[str] = ["docs/decisions/**/*.md"]
    adr_section: str = "Decisions"
    reference_section: str = "API Reference"
    site_url: str | None = None
    source_url: str | None = None
    exclude: list[str] = []


def load_techwiki_config(root: Path) -> TechwikiConfig:
    """Return the ``techwiki`` section of ``sdd/config.json`` or defaults.

    Args:
        root: Repository root directory.

    Returns:
        Parsed technical-wiki settings, or defaults when no section exists.
    """
    config_path = root / "sdd" / "config.json"
    if not config_path.exists():
        logger.debug("No sdd/config.json at %s — returning defaults", root)
        return TechwikiConfig()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    raw = data.get("techwiki")
    if raw is None:
        return TechwikiConfig()
    return TechwikiConfig(**raw)
