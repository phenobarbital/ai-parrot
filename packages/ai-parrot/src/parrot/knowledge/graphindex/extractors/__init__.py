"""GraphIndex extractors sub-package.

Three parallel extractors feed UniversalNode/UniversalEdge instances
into the pipeline:

- ``code.CodeExtractor``   — tree-sitter Python parsing
- ``loader.LoaderExtractor`` — ai-parrot-loaders + PageIndex integration
- ``skill.SkillExtractor`` — SKILL.md frontmatter parsing
"""

from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.extractors.skill import SkillExtractor

__all__ = [
    "CodeExtractor",
    "LoaderExtractor",
    "SkillExtractor",
]
