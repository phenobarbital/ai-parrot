"""
Filesystem-based skill registry with eager loading.

Scans AGENTS_DIR/{agent_id}/skills/ (authored) and skills/learned/ (LLM-generated)
at configure time, parses .md files, validates, and indexes by trigger name.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .models import SkillDefinition, SkillSource
from .parsers import parse_skill_file


class SkillFileRegistry:
    """Filesystem-based skill registry with eager loading.

    Loads .md skill files from a skills directory and an optional learned
    subdirectory, validates them, and indexes by trigger name in a dict.

    Args:
        skills_dir: Path to the authored skills directory.
        learned_dir: Path to the learned skills directory. Defaults to
            ``skills_dir / "learned"``.
    """

    def __init__(
        self,
        skills_dir: Path,
        learned_dir: Optional[Path] = None,
    ) -> None:
        self.skills_dir = skills_dir
        self.learned_dir = learned_dir or skills_dir / "learned"
        self._skills: Dict[str, SkillDefinition] = {}  # trigger -> skill
        self._by_name: Dict[str, SkillDefinition] = {}  # name -> skill
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def load(self) -> None:
        """Eagerly load all .md skill files from both directories."""
        authored = self._scan_dir(self.skills_dir, exclude_subdir="learned")
        learned = self._scan_dir(self.learned_dir)

        # Detect name collisions between authored and learned
        authored_names = {s.name for s in authored}
        learned_names = {s.name for s in learned}
        collisions = authored_names & learned_names

        if collisions:
            for name in collisions:
                self.logger.error(
                    "Skill name collision between authored and learned: '%s' — "
                    "both skipped",
                    name,
                )

        # Register non-colliding skills
        for skill in authored + learned:
            if skill.name in collisions:
                continue
            self._register(skill)

    def _scan_dir(
        self,
        directory: Path,
        exclude_subdir: Optional[str] = None,
    ) -> List[SkillDefinition]:
        """Scan a directory for .md skill files, returning parsed definitions."""
        skills: List[SkillDefinition] = []
        if not directory.exists() or not directory.is_dir():
            return skills

        for md_file in sorted(directory.glob("*.md")):
            if exclude_subdir and md_file.parent.name == exclude_subdir:
                continue
            try:
                skill = parse_skill_file(md_file)
                skills.append(skill)
            except Exception as exc:
                self.logger.warning(
                    "Skipping malformed skill file '%s': %s",
                    md_file,
                    exc,
                )
        return skills

    def _register(self, skill: SkillDefinition) -> None:
        """Register a skill by name and all its triggers."""
        if skill.name in self._by_name:
            self.logger.error(
                "Duplicate skill name '%s' — skipping duplicate",
                skill.name,
            )
            return

        self._by_name[skill.name] = skill
        for trigger in skill.triggers:
            if trigger in self._skills:
                self.logger.error(
                    "Trigger collision: '%s' already registered by '%s' — "
                    "skipping for '%s'",
                    trigger,
                    self._skills[trigger].name,
                    skill.name,
                )
                continue
            self._skills[trigger] = skill

    def get(self, trigger: str) -> Optional[SkillDefinition]:
        """Look up a skill by its trigger name.

        Args:
            trigger: The trigger string, e.g. ``"/resumen"``.

        Returns:
            The matching SkillDefinition or None.
        """
        return self._skills.get(trigger)

    def add(self, skill: SkillDefinition) -> None:
        """Hot-add a skill. Used for learned skills saved during session.

        Args:
            skill: The validated SkillDefinition to add.
        """
        self._register(skill)

    def list_skills(self) -> List[SkillDefinition]:
        """Return all loaded skills."""
        return list(self._by_name.values())

    def has_trigger(self, trigger: str) -> bool:
        """Check if a trigger is registered.

        Args:
            trigger: The trigger string to check.
        """
        return trigger in self._skills
