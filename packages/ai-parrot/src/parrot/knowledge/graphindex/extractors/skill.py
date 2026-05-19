"""SKILL.md extractor for GraphIndex.

Parses SKILL.md files (YAML frontmatter + markdown body) and emits
``UniversalNode`` instances with ``kind=NodeKind.SKILL``.  The ``title``
is derived from the frontmatter ``name`` field and ``summary`` from
``description``.  All other frontmatter fields are stored in
``domain_tags``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

import yaml

from parrot.knowledge.graphindex.schema import (
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

# Regex to match YAML frontmatter block
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _make_node_id(file_path: str, name: str) -> str:
    """Stable node ID from file path and skill name.

    Args:
        file_path: Path to the SKILL.md file.
        name: Skill name from frontmatter.

    Returns:
        16-char hex SHA-1 prefix.
    """
    raw = f"{file_path}::skill::{name}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class SkillExtractor:
    """Extract Skill nodes from SKILL.md files.

    Parses YAML frontmatter to populate node metadata and ``domain_tags``.

    Args:
        source_uri_prefix: Optional prefix prepended to file paths when
            constructing ``source_uri``.  Defaults to empty string.
    """

    def __init__(self, source_uri_prefix: str = "") -> None:
        self.source_uri_prefix = source_uri_prefix

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def extract(
        self, file_path: str, content: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Parse a SKILL.md file and return Skill nodes.

        Args:
            file_path: Path to the SKILL.md file — used as ``source_uri``.
            content: Raw file content (frontmatter + body).

        Returns:
            Tuple of ``(nodes, edges)``.  Edges are empty for standalone
            skills (no explicit containment hierarchy).
        """
        source_uri = (self.source_uri_prefix + file_path) if self.source_uri_prefix else file_path

        frontmatter, body = self._parse_frontmatter(content)

        if frontmatter is None:
            # No valid frontmatter — cannot create a typed Skill node
            logger.debug("No frontmatter found in %s — skipping", file_path)
            return [], []

        name = frontmatter.get("name")
        if not name:
            logger.debug("Frontmatter in %s missing 'name' — skipping", file_path)
            return [], []

        description: Optional[str] = frontmatter.get("description")

        # Build domain_tags from all frontmatter keys except name/description
        domain_tags: dict = {
            k: v
            for k, v in frontmatter.items()
            if k not in ("name", "description")
        }

        node_id = _make_node_id(source_uri, str(name))
        skill_node = UniversalNode(
            node_id=node_id,
            kind=NodeKind.SKILL,
            title=str(name),
            source_uri=source_uri,
            summary=description,
            domain_tags=domain_tags,
            provenance=Provenance.EXTRACTED,
        )

        return [skill_node], []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_frontmatter(self, content: str) -> tuple[Optional[dict], str]:
        """Extract YAML frontmatter and the remaining body.

        Args:
            content: Raw file content.

        Returns:
            Tuple of ``(frontmatter_dict, body_text)``.  ``frontmatter_dict``
            is ``None`` if the frontmatter block is absent or malformed.
        """
        match = FRONTMATTER_RE.match(content)
        if not match:
            return None, content

        yaml_text = match.group(1)
        body = content[match.end():]

        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            logger.warning("YAML parse error in frontmatter: %s", exc)
            return None, content

        if not isinstance(data, dict):
            logger.debug("Frontmatter is not a mapping — skipping")
            return None, content

        return data, body
