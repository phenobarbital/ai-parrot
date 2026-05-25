"""
SkillsDirectoryLoader — Filesystem discovery for skills.

Scans configured filesystem paths to discover both single-file (``.md``)
and composite (``dir/SKILL.md``) skill layouts. Discovered skills are
hot-added to a :class:`~parrot.skills.file_registry.SkillFileRegistry`
via :meth:`load_into`.

Boot-time usage::

    loader = SkillsDirectoryLoader(paths=[Path(".agent/skills/")])
    count = await loader.load_into(registry)
"""
from __future__ import annotations

import logging
from logging import Logger
from pathlib import Path
from typing import List, Optional

from .file_registry import SkillFileRegistry
from .models import SkillDefinition
from .parsers import parse_skill_directory, parse_skill_file


class SkillsDirectoryLoader:
    """Discover and load skills from one or more filesystem directories.

    Supports two skill layouts:

    - **Single-file**: ``{dir}/{name}.md`` — a plain Markdown file with
      YAML frontmatter.
    - **Composite**: ``{dir}/{name}/SKILL.md`` — a directory containing
      ``SKILL.md`` plus adjacent asset files (scripts, templates, etc.).

    Failed parses are logged as warnings and skipped; the loader never
    crashes on malformed input.

    Args:
        paths: List of filesystem paths to scan. Paths that do not exist
            or are not directories are logged at DEBUG level and skipped.
        logger: Optional logger; if not provided, a module-level logger is
            used.

    Example::

        loader = SkillsDirectoryLoader(
            paths=[Path(".agent/skills/")],
            logger=self.logger,
        )
        count = await loader.load_into(self._skill_file_registry)
    """

    def __init__(
        self,
        paths: List[Path],
        logger: Optional[Logger] = None,
    ) -> None:
        self._paths = [Path(p).expanduser().resolve() for p in paths]
        self._logger = logger or logging.getLogger(__name__)

    async def discover(self) -> List[SkillDefinition]:
        """Scan all configured paths and return discovered SkillDefinitions.

        Iterates each path in sorted order for deterministic discovery.
        Skips non-existent paths and malformed skill files with a warning.

        Returns:
            List of successfully parsed :class:`~parrot.skills.models.SkillDefinition`
            instances. Empty list if no skills are found or all paths are invalid.
        """
        skills: List[SkillDefinition] = []
        for base in self._paths:
            if not base.exists() or not base.is_dir():
                self._logger.debug("Skills path not found or not a directory: %s", base)
                continue
            for entry in sorted(base.iterdir()):
                try:
                    if entry.is_file() and entry.suffix == ".md":
                        skills.append(parse_skill_file(entry))
                    elif entry.is_dir() and (entry / "SKILL.md").exists():
                        skills.append(parse_skill_directory(entry))
                    # Non-.md files and dirs without SKILL.md are silently skipped
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning(
                        "Failed to parse skill at %s: %s", entry, exc
                    )
        return skills

    async def load_into(self, registry: SkillFileRegistry) -> int:
        """Discover skills and hot-add them to an existing registry.

        Calls :meth:`discover` to enumerate all skills, then adds each
        to ``registry`` via :meth:`~parrot.skills.file_registry.SkillFileRegistry.add`.
        Individual registration failures are logged as warnings.

        Args:
            registry: The :class:`~parrot.skills.file_registry.SkillFileRegistry`
                to hot-add discovered skills into.

        Returns:
            Count of successfully loaded (registered) skills.
        """
        skills = await self.discover()
        loaded = 0
        for skill in skills:
            try:
                registry.add(skill)
                loaded += 1
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "Failed to register skill '%s': %s", skill.name, exc
                )
        return loaded
