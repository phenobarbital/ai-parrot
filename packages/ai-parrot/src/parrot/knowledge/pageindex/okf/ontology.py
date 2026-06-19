"""Backwards-compatible re-export shim for OKF ontology types.

The canonical definitions have moved to ``parrot.knowledge.okf.ontology``
(FEAT-239).  This module re-exports everything so that existing import paths:

    from parrot.knowledge.pageindex.okf.ontology import ConceptType
    from parrot.knowledge.pageindex.okf import ConceptType

continue to work without modification.
"""

from parrot.knowledge.okf.ontology import (  # noqa: F401
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)

__all__ = [
    "ConceptType",
    "RelationType",
    "RelatesTo",
    "SourceProvenance",
]
