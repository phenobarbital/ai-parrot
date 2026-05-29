"""
Skill file parser for .md files with YAML frontmatter.

Parses skill definitions from markdown files that follow the format:
---
name: resumen
description: Resume textos largos en bullet points
triggers:
  - /resumen
source: authored
---

<skill instructions body>
"""
import logging
from pathlib import Path
from typing import Iterable, List

import frontmatter
import tiktoken

from .models import SkillDefinition, SkillSource


_LOGGER = logging.getLogger(__name__)


# Reuse encoder across calls for performance
_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding (GPT-4 tokenizer)."""
    return len(_ENCODING.encode(text))


def parse_skill_file(file_path: Path) -> SkillDefinition:
    """Parse a .md skill file with YAML frontmatter into a SkillDefinition.

    Args:
        file_path: Path to the .md file.

    Returns:
        Parsed and validated SkillDefinition.

    Raises:
        ValueError: If required frontmatter fields are missing.
        ValidationError: If the skill fails Pydantic validation (e.g., token limit).
        FileNotFoundError: If the file does not exist.
    """
    post = frontmatter.load(str(file_path))

    # Extract required fields from frontmatter
    metadata = post.metadata
    name: str = metadata.get("name", "")
    description: str = metadata.get("description", "")
    # triggers may be an empty list (for composite/directory skills) — allow it
    # but raise if the key is entirely absent from frontmatter
    _triggers_sentinel = object()
    _raw_triggers = metadata.get("triggers", _triggers_sentinel)
    if _raw_triggers is _triggers_sentinel:
        raise ValueError(f"Skill file missing 'triggers' field: {file_path}")
    if isinstance(_raw_triggers, str):
        triggers: List[str] = [_raw_triggers]
    elif isinstance(_raw_triggers, list):
        triggers = _raw_triggers
    else:
        triggers = list(_raw_triggers)

    if not name:
        raise ValueError(f"Skill file missing 'name' field: {file_path}")
    if not description:
        raise ValueError(f"Skill file missing 'description' field: {file_path}")

    # Body is everything after the frontmatter
    template_body = post.content.strip()

    # Auto-detect source based on path
    source_str = metadata.get("source", None)
    if source_str:
        source = SkillSource(source_str)
    elif "learned" in file_path.parts:
        source = SkillSource.LEARNED
    else:
        source = SkillSource.AUTHORED

    # Optional fields
    version = str(metadata.get("version", "1.0"))
    category = metadata.get("category", None)
    priority = int(metadata.get("priority", 90))

    # Count tokens
    token_count = _count_tokens(template_body)

    return SkillDefinition(
        name=name,
        description=description,
        triggers=triggers,
        source=source,
        priority=priority,
        version=version,
        category=category,
        template_body=template_body,
        token_count=token_count,
        file_path=file_path,
    )


def parse_skill_directory(skill_dir: Path) -> SkillDefinition:
    """Parse a composite skill: ``{dir}/SKILL.md`` plus adjacent asset files.

    A composite skill is a directory containing a ``SKILL.md`` entry point
    (parsed via :func:`parse_skill_file`) and zero or more adjacent asset
    files (scripts, templates, examples). The ``assets_dir`` field on the
    returned :class:`~parrot.skills.models.SkillDefinition` is set to the
    directory path so downstream components can enumerate assets.

    Args:
        skill_dir: Path to the skill directory (must contain ``SKILL.md``).

    Returns:
        Parsed and validated SkillDefinition with ``assets_dir`` set to
        ``skill_dir``.

    Raises:
        FileNotFoundError: If ``SKILL.md`` is absent in ``skill_dir``.
        ValueError: If required frontmatter fields are missing from
            ``SKILL.md``.
        ValidationError: If the skill fails Pydantic validation.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(
            f"Missing SKILL.md in composite skill directory: {skill_dir}"
        )
    skill = parse_skill_file(skill_md)
    skill = skill.model_copy(update={"assets_dir": skill_dir})
    return skill


def discover_skills_in_dir(
    directory: Path,
    logger: logging.Logger = _LOGGER,
    exclude_names: Iterable[str] = (),
) -> List[SkillDefinition]:
    """Discover single-file and composite skills in a directory (non-recursive).

    Implements the per-directory contract shared by Claude Code, Cursor and
    Gemini: a directory entry is a skill if it is either a single ``.md`` file
    or a subdirectory containing a ``SKILL.md`` entry point.

    - **Single-file**: ``{directory}/{name}.md`` → :func:`parse_skill_file`.
    - **Composite**: ``{directory}/{name}/SKILL.md`` → :func:`parse_skill_directory`.

    Entries are iterated in sorted order for deterministic discovery. Entries
    whose name appears in ``exclude_names`` are skipped (e.g. the reserved
    ``learned`` subdirectory). Non-``.md`` files and directories lacking a
    ``SKILL.md`` are silently ignored. Malformed skills are logged as warnings
    and skipped so one bad skill never aborts discovery.

    Args:
        directory: Directory to scan. Returns an empty list if it does not
            exist or is not a directory.
        logger: Logger for malformed-skill warnings.
        exclude_names: Entry names to skip (matched against ``entry.name``).

    Returns:
        List of successfully parsed :class:`~parrot.skills.models.SkillDefinition`.
    """
    skills: List[SkillDefinition] = []
    if not directory.exists() or not directory.is_dir():
        return skills

    excluded = set(exclude_names)
    for entry in sorted(directory.iterdir()):
        if entry.name in excluded:
            continue
        try:
            if entry.is_file() and entry.suffix == ".md":
                skills.append(parse_skill_file(entry))
            elif entry.is_dir() and (entry / "SKILL.md").exists():
                skills.append(parse_skill_directory(entry))
            # Non-.md files and dirs without SKILL.md are silently skipped
        except Exception as exc:  # noqa: BLE001 — one bad skill must not abort discovery
            logger.warning("Failed to parse skill at %s: %s", entry, exc)
    return skills
