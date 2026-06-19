"""Backwards-compatible re-export shim for OKF frontmatter engine.

The canonical definitions have moved to ``parrot.knowledge.okf.frontmatter``
(FEAT-239).  This module re-exports everything so that existing import paths:

    from parrot.knowledge.pageindex.okf.frontmatter import ConceptFrontmatter
    from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter
    from parrot.knowledge.pageindex.okf import ConceptFrontmatter

continue to work without modification.
"""

from parrot.knowledge.okf.frontmatter import (  # noqa: F401
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)

__all__ = [
    "ConceptFrontmatter",
    "project_frontmatter",
    "parse_frontmatter",
]
