"""GraphIndex extractors sub-package.

Five extractors feed UniversalNode/UniversalEdge instances into the
pipeline:

- ``code.CodeExtractor``         — tree-sitter Python parsing
- ``odoo_code.OdooCodeExtractor`` — Odoo-aware extension of CodeExtractor (FEAT-240)
- ``loader.LoaderExtractor``     — ai-parrot-loaders + PageIndex integration
- ``skill.SkillExtractor``       — SKILL.md frontmatter parsing
- ``llm.LLMGraphExtractor``      — schema-constrained LLM extraction of
  typed entities/relations from free text (imported lazily below — it
  is the only extractor with no heavyweight parser dependency, but its
  publish path pulls the persistence stack).
"""

from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.loader import (
    LoaderExtractor,
    PlainTextLoader,
)
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor
from parrot.knowledge.graphindex.extractors.skill import SkillExtractor

__all__ = [
    "CodeExtractor",
    "LoaderExtractor",
    "OdooCodeExtractor",
    "PlainTextLoader",
    "SkillExtractor",
    "LLMGraphExtractor",
    "ExtractedGraph",
    "ExtractedEntity",
    "ExtractedRelation",
]

_LAZY_ATTRS = {
    "LLMGraphExtractor": "parrot.knowledge.graphindex.extractors.llm",
    "ExtractedGraph": "parrot.knowledge.graphindex.extractors.llm",
    "ExtractedEntity": "parrot.knowledge.graphindex.extractors.llm",
    "ExtractedRelation": "parrot.knowledge.graphindex.extractors.llm",
}


def __getattr__(name: str):
    """Resolve lazily-exported attributes on first access (PEP 562)."""
    module_path = _LAZY_ATTRS.get(name)
    if module_path is not None:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
