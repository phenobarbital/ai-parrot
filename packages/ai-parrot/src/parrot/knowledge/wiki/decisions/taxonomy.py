"""Curated subsystem taxonomy for the decision ``about`` axis (FEAT-784 Module 3)."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from parrot.knowledge.wiki.decisions.models import TAXONOMY_INVALID, DecisionError, _Strict
from parrot.knowledge.wiki.ledger.sdd_meta import KNOWN_PROJECTS
from parrot.knowledge.wiki.store import WikiPageRecord

logger = logging.getLogger(__name__)


class Subsystem(_Strict):
    """One curated subsystem id."""

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(..., min_length=1)
    description: str = ""
    parent: str | None = None
    projects: list[str]


class _TaxonomyFile(_Strict):
    """Strict representation of one subsystem taxonomy file."""

    schema_version: Literal[1]
    subsystems: list[Subsystem]
    mapping: dict[str, str] = Field(default_factory=dict)


class Taxonomy:
    """Validated, immutable subsystem vocabulary."""

    def __init__(self, data: _TaxonomyFile) -> None:
        self._data = data
        self._by_id = {subsystem.id: subsystem for subsystem in data.subsystems}

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        """Load and validate a subsystem taxonomy.

        Args:
            path: YAML taxonomy file.

        Returns:
            The validated taxonomy.

        Raises:
            DecisionError: If the file or any taxonomy relationship is invalid.
        """
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            data = _TaxonomyFile.model_validate(raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
            raise DecisionError(TAXONOMY_INVALID, f"{path}: {exc}") from exc

        ids = [subsystem.id for subsystem in data.subsystems]
        duplicate_ids = sorted({subsystem_id for subsystem_id in ids if ids.count(subsystem_id) > 1})
        if duplicate_ids:
            raise DecisionError(TAXONOMY_INVALID, f"duplicate subsystem ids: {duplicate_ids}")

        known_ids = frozenset(ids)
        for subsystem in data.subsystems:
            if subsystem.parent is not None and subsystem.parent not in known_ids:
                raise DecisionError(
                    TAXONOMY_INVALID,
                    f"subsystem {subsystem.id!r} has unknown parent {subsystem.parent!r}",
                )
            unknown_projects = sorted(set(subsystem.projects) - KNOWN_PROJECTS)
            if unknown_projects:
                raise DecisionError(
                    TAXONOMY_INVALID,
                    f"subsystem {subsystem.id!r} has unknown projects: {unknown_projects}",
                )

        parents = {subsystem.id: subsystem.parent for subsystem in data.subsystems}
        for subsystem_id in sorted(known_ids):
            seen: set[str] = set()
            current: str | None = subsystem_id
            while current is not None:
                if current in seen:
                    raise DecisionError(TAXONOMY_INVALID, f"parent cycle includes subsystem {current!r}")
                seen.add(current)
                current = parents[current]

        for tag, subsystem_id in data.mapping.items():
            if subsystem_id not in known_ids:
                raise DecisionError(
                    TAXONOMY_INVALID,
                    f"mapping for tag {tag!r} references unknown subsystem {subsystem_id!r}",
                )

        return cls(data)

    def ids(self) -> frozenset[str]:
        """Return every subsystem id."""
        return frozenset(self._by_id)

    def closest(self, raw: str, limit: int = 3) -> list[str]:
        """Return suggestions without modifying the supplied id."""
        return difflib.get_close_matches(raw, sorted(self._by_id), n=limit, cutoff=0.5)

    def map_projects(self, projects: list[str], tags: list[str]) -> list[str]:
        """Map project and tag metadata to sorted, unique subsystem ids."""
        project_set = set(projects)
        mapped = {
            subsystem.id
            for subsystem in self._data.subsystems
            if project_set.intersection(subsystem.projects)
        }
        mapped.update(self._data.mapping[tag] for tag in tags if tag in self._data.mapping)
        return sorted(mapped)

    def unmapped(self, tags: list[str]) -> list[str]:
        """Return sorted tags with no mapping entry."""
        return sorted({tag for tag in tags if tag not in self._data.mapping})

    def project_pages(self) -> list[WikiPageRecord]:
        """Project one ``concept:<id>`` page per subsystem for ABOUT edges."""
        pages: list[WikiPageRecord] = []
        for subsystem in sorted(self._data.subsystems, key=lambda item: item.id):
            concept_id = f"concept:{subsystem.id}"
            pages.append(
                WikiPageRecord(
                    concept_id=concept_id,
                    node_id=concept_id,
                    title=subsystem.title,
                    category="concept",
                    summary=subsystem.description,
                    body=subsystem.description,
                    origin="authored",
                    content_hash=hashlib.sha1(subsystem.description.encode("utf-8")).hexdigest(),
                )
            )
        return pages

    def digest(self) -> str:
        """Return sha256 over canonical JSON of the validated file."""
        canonical = json.dumps(self._data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
