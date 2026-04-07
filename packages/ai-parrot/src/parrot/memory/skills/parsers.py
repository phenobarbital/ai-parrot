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
from pathlib import Path
from typing import List

import frontmatter
import tiktoken

from .models import SkillDefinition, SkillSource


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
    triggers: List[str] = metadata.get("triggers", [])

    if not name:
        raise ValueError(f"Skill file missing 'name' field: {file_path}")
    if not description:
        raise ValueError(f"Skill file missing 'description' field: {file_path}")
    if not triggers:
        raise ValueError(f"Skill file missing 'triggers' field: {file_path}")

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
