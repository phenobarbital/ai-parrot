"""Controlled type and relation vocabulary for the OKF Knowledge Layer.

This is the foundational leaf module. Every other module in FEAT-238 imports
from here. It defines the controlled type vocabulary (ConceptType), the typed
edge vocabulary (RelationType), and the Pydantic v2 data models (SourceProvenance,
RelatesTo) used throughout the layer.

Design notes (from spec §2, D9):
- ``type`` is a controlled ontological vocabulary; ``tags`` remain free namespaces.
- ``RelationType.REFERENCES`` is the default for untyped prose link fallback.
- ``ConceptType.SECTION`` is the structural fallback when LLM classification is
  unavailable.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConceptType(str, Enum):
    """Controlled ontological vocabulary for OKF node types (D9).

    ``SECTION`` is the structural fallback when LLM classification is unavailable.
    """

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
    OTHER = "Other"


class RelationType(str, Enum):
    """Typed edge vocabulary (OKF-superset, D5).

    ``REFERENCES`` is the default for untyped prose link fallback.
    """

    REFERENCES = "references"
    MAPS_TO = "maps_to"
    SATISFIES = "satisfies"
    SATISFIED_BY = "satisfied_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    IMPLEMENTS = "implements"
    PART_OF = "part_of"


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
