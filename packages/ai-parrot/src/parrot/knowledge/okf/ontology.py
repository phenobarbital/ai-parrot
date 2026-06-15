"""Shared OKF type vocabulary — single source of truth for all indexes.

This module is the canonical home for the OKF controlled type vocabulary,
previously resident in ``pageindex/okf/ontology.py``.  Both PageIndex and
GraphIndex import from here, avoiding an inverted dependency between sibling
packages.

FEAT-239: Extended with 5 graph-native ``ConceptType`` values and 4 graph
edge kinds for ``RelationType``.

Design notes:
- ``ConceptType`` values for existing members MUST remain identical strings
  (e.g. ``"Section"``, ``"Policy"``) to avoid breaking YAML frontmatter parsing.
- New graph-native type values use title-case: ``"Symbol"``, ``"Rationale"``, etc.
- ``RelationType.REFERENCES`` is the default for untyped prose link fallback.
- ``ConceptType.SECTION`` is the structural fallback when LLM classification is
  unavailable — and is directly reusable for both PageIndex sections and GraphIndex
  SECTION nodes because both use the same string value ``"Section"``.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConceptType(str, Enum):
    """Controlled ontological vocabulary for OKF node types.

    Existing PageIndex values are unchanged.  FEAT-239 adds 5 graph-native
    values: SYMBOL, RATIONALE, SKILL, CONCEPT_NODE, DOCUMENT_NODE.

    ``SECTION`` is the structural fallback for both PageIndex sections and
    GraphIndex SECTION nodes — same string value, zero ambiguity.
    """

    # --- Existing PageIndex types (values unchanged) ---
    SECTION = "Section"
    POLICY = "Policy"
    CONTROL = "Control"
    SAFEGUARD = "Safeguard"
    EVIDENCE = "Evidence"
    PLAYBOOK = "Playbook"
    PROCEDURE = "Procedure"
    STANDARD = "Standard"
    FRAMEWORK = "Framework"
    REGULATION = "Regulation"
    GUIDELINE = "Guideline"

    # --- New graph-native types (FEAT-239) ---
    SYMBOL = "Symbol"
    RATIONALE = "Rationale"
    SKILL = "Skill"
    CONCEPT_NODE = "Concept"
    DOCUMENT_NODE = "Document"


class RelationType(str, Enum):
    """Typed edge vocabulary (OKF-superset).

    Existing PageIndex values are unchanged.  FEAT-239 adds 4 graph edge kinds:
    DEFINES, MENTIONS, EXPLAINS, CONTAINS.

    ``REFERENCES`` is the default for untyped prose link fallback.
    """

    # --- Existing relation types ---
    REFERENCES = "references"
    MAPS_TO = "maps_to"
    SATISFIES = "satisfies"
    SATISFIED_BY = "satisfied_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    IMPLEMENTS = "implements"
    PART_OF = "part_of"

    # --- New graph edge kinds (FEAT-239) ---
    DEFINES = "defines"
    MENTIONS = "mentions"
    EXPLAINS = "explains"
    CONTAINS = "contains"


class RelatesTo(BaseModel):
    """A typed edge in the knowledge graph.

    Attributes:
        concept: Target concept_id (stable identity).
        rel: Relation type. Defaults to ``references`` for untyped prose links.
    """

    concept: str = Field(..., description="Target concept_id")
    rel: RelationType = Field(
        default=RelationType.REFERENCES,
        description="Typed relation between source and target concept.",
    )


class SourceProvenance(BaseModel):
    """Per-node provenance, citable.

    Attributes:
        document: Source document filename (e.g. ``AICPA_SOC2.pdf``).
        pages: Optional list of page numbers (``[start_page, end_page]``).
        url: Optional source URL if available.
    """

    document: str = Field(..., description="Source document filename")
    pages: Optional[list[int]] = Field(
        default=None,
        description="[start_page, end_page] from node start_index/end_index",
    )
    url: Optional[str] = Field(default=None, description="Source URL if available")


__all__ = [
    "ConceptType",
    "RelationType",
    "RelatesTo",
    "SourceProvenance",
]
