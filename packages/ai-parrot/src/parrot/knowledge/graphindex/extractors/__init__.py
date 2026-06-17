"""GraphIndex extractors sub-package.

Four parallel extractors feed UniversalNode/UniversalEdge instances
into the pipeline:

- ``code.CodeExtractor``         — tree-sitter Python parsing
- ``odoo_code.OdooCodeExtractor`` — Odoo-aware extension of CodeExtractor (FEAT-240)
- ``loader.LoaderExtractor``     — ai-parrot-loaders + PageIndex integration
- ``skill.SkillExtractor``       — SKILL.md frontmatter parsing
"""

from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor
from parrot.knowledge.graphindex.extractors.skill import SkillExtractor

__all__ = [
    "CodeExtractor",
    "LoaderExtractor",
    "OdooCodeExtractor",
    "SkillExtractor",
]
