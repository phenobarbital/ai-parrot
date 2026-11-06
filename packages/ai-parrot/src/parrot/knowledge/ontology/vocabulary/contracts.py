"""Data models and read/write contracts of the ontology vocabulary store (FEAT-824).

Pure types: no driver imports, so importing this module is cheap and the models are picklable.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field

ConceptKind = Literal["class", "object_property", "datatype_property", "individual", "concept_scheme", "skos_concept"]
ClosureFamily = Literal["subclass", "subproperty", "broader", "partof"]
LabelKind = Literal["pref", "alt", "hidden"]


class ConceptRef(BaseModel):
    """A concept as read at one published version."""

    iri: str
    ontology_id: str
    kind: ConceptKind
    pref_label: str | None = None
    definition: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    version: int


class Resolution(BaseModel):
    """A scored concept match from hybrid vocabulary lookup."""

    concept: ConceptRef
    score: float
    matched_by: Literal["exact", "trgm", "vector"]


class StoreStatus(BaseModel):
    """Published-version and backend health information."""

    ontology_id: str
    version: int
    stale: bool = False
    backend: str


class ParsedConcept(BaseModel):
    """A parsed concept awaiting publication."""

    iri: str
    kind: ConceptKind
    pref_label: str | None = None
    definition: str | None = None
    deprecated: bool = False
    replaced_by: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ParsedLabel(BaseModel):
    """A parsed label for a concept."""

    iri: str
    lang: str
    kind: LabelKind
    text: str


class ParsedRelation(BaseModel):
    """A parsed asserted or inferred relation."""

    subject_iri: str
    predicate: str
    object_iri: str
    inferred: bool = False


class ParsedStatement(BaseModel):
    """A parsed RDF-like statement."""

    subject_iri: str
    predicate: str
    object: dict[str, Any]


class OntologyContent(BaseModel):
    """Parsed ontology content ready for a version publication."""

    base_iri: str
    concepts: list[ParsedConcept]
    labels: list[ParsedLabel]
    relations: list[ParsedRelation]
    statements: list[ParsedStatement]


class ClosureRow(BaseModel):
    """One transitive-closure relation."""

    family: ClosureFamily
    ancestor_iri: str
    descendant_iri: str
    depth: int


class VersionContent(BaseModel):
    """The complete materialized content of a published ontology version."""

    ontology_id: str
    version: int
    checksum: str
    content: OntologyContent
    closure: list[ClosureRow]
    embeddings: dict[str, list[float]] = Field(default_factory=dict)


class PublishDiff(BaseModel):
    """Changes made by a publication."""

    added_iris: list[str] = Field(default_factory=list)
    changed_iris: list[str] = Field(default_factory=list)
    deprecated: dict[str, str | None] = Field(default_factory=dict)
    relations_added: int = 0
    relations_closed: int = 0


class PublishResult(BaseModel):
    """The immutable result of a publication attempt."""

    ontology_id: str
    version: int
    changed: bool
    checksum: str
    diff: PublishDiff


class ValidationIssue(BaseModel):
    """One reason an ontology publication was rejected."""

    code: str
    message: str
    subject: str | None = None


EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]


@runtime_checkable
class OntologyStore(Protocol):
    """Read contract of the ontology vocabulary. Every call reads one published version."""

    async def version(self, ontology_id: str) -> int:
        """Current published version; 0 when registered but never published. Raises OntologyNotFound."""
        ...

    async def status(self, ontology_id: str) -> StoreStatus:
        """Version, backend name and whether the data may be behind the central store."""
        ...

    async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None:
        """Concept visible at `as_of` (default: current). None when the IRI is not visible.

        Raises OntologyVersionNotFound.
        """
        ...

    async def resolve(
        self,
        ontology_id: str,
        term: str,
        *,
        lang: str | None = None,
        k: int = 10,
        kinds: Sequence[str] | None = None,
        embedding: Sequence[float] | None = None,
    ) -> list[Resolution]:
        """Hybrid lookup at the current version with at most `k` live results."""
        ...

    async def expand(
        self,
        ontology_id: str,
        iris: Sequence[str],
        *,
        family: ClosureFamily = "subclass",
        direction: Literal["down", "up", "both"] = "down",
        max_depth: int | None = None,
        include_deprecated: bool = False,
        as_of: int | None = None,
    ) -> set[str]:
        """Closure of `iris` at one version; it always contains the input IRIs."""
        ...

    async def neighbors(
        self,
        ontology_id: str,
        iri: str,
        predicate: str | None = None,
        *,
        as_of: int | None = None,
    ) -> list[tuple[str, str]]:
        """Outbound asserted and inferred `(predicate, object_iri)` pairs."""
        ...

    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
        """Map each IRI to its live replacement, following replacements safely."""
        ...

    async def export(
        self,
        ontology_id: str,
        fmt: Literal["turtle", "jsonld"] = "turtle",
        *,
        as_of: int | None = None,
    ) -> bytes:
        """Serialise the asserted graph visible at `as_of`."""
        ...

    async def close(self) -> None:
        """Release connections and file handles."""
        ...


@runtime_checkable
class OntologyPublisher(Protocol):
    """Write contract; implemented only by the PostgreSQL backend."""

    async def ensure_ontology(self, ontology_id: str, *, base_iri: str, title: str | None = None) -> None:
        """Register an ontology when it is not already present."""
        ...

    async def publish(
        self,
        ontology_id: str,
        turtle: bytes,
        *,
        notes: str = "",
        shapes: bytes | None = None,
    ) -> PublishResult:
        """Parse and publish Turtle content."""
        ...

    async def publish_content(
        self,
        ontology_id: str,
        content: OntologyContent,
        *,
        notes: str = "",
        carry_forward_missing: bool = False,
    ) -> PublishResult:
        """Publish already parsed ontology content."""
        ...
