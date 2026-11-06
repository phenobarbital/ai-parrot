"""Models and Protocols of the vocabulary store (FEAT-824 TASK-5253)."""

from __future__ import annotations

import pickle
from typing import Literal

from parrot.knowledge.ontology.exceptions import OntologyError
from parrot.knowledge.ontology.vocabulary import contracts as c
from parrot.knowledge.ontology.vocabulary import exceptions as e


def test_models_roundtrip() -> None:
    """Every model validates, serialises with model_dump/model_validate, and pickles."""
    concept_ref = c.ConceptRef(
        iri="https://example.test/Concept",
        ontology_id="example",
        kind="class",
        version=1,
    )
    parsed_concept = c.ParsedConcept(iri=concept_ref.iri, kind="class")
    parsed_label = c.ParsedLabel(iri=concept_ref.iri, lang="en", kind="pref", text="Concept")
    parsed_relation = c.ParsedRelation(
        subject_iri=concept_ref.iri,
        predicate="https://www.w3.org/2000/01/rdf-schema#subClassOf",
        object_iri="https://example.test/Parent",
    )
    parsed_statement = c.ParsedStatement(
        subject_iri=concept_ref.iri,
        predicate="https://example.test/property",
        object={"value": "example", "datatype": "http://www.w3.org/2001/XMLSchema#string", "lang": "en"},
    )
    content = c.OntologyContent(
        base_iri="https://example.test/",
        concepts=[parsed_concept],
        labels=[parsed_label],
        relations=[parsed_relation],
        statements=[parsed_statement],
    )
    closure_row = c.ClosureRow(
        family="subclass",
        ancestor_iri="https://example.test/Parent",
        descendant_iri=concept_ref.iri,
        depth=1,
    )
    publish_diff = c.PublishDiff(added_iris=[concept_ref.iri])
    models: list[c.BaseModel] = [
        concept_ref,
        c.Resolution(concept=concept_ref, score=1.0, matched_by="exact"),
        c.StoreStatus(ontology_id="example", version=1, backend="postgres"),
        parsed_concept,
        parsed_label,
        parsed_relation,
        parsed_statement,
        content,
        closure_row,
        c.VersionContent(
            ontology_id="example",
            version=1,
            checksum="checksum",
            content=content,
            closure=[closure_row],
            embeddings={concept_ref.iri: [0.1]},
        ),
        publish_diff,
        c.PublishResult(
            ontology_id="example",
            version=1,
            changed=True,
            checksum="checksum",
            diff=publish_diff,
        ),
        c.ValidationIssue(code="IRI_REMOVED", message="IRI was removed", subject=concept_ref.iri),
    ]

    for model in models:
        assert type(model).model_validate(model.model_dump()) == model
        assert pickle.loads(pickle.dumps(model)) == model


def test_validation_error_carries_issues() -> None:
    """Validation errors retain all issue details and inherit the ontology base error."""
    err = e.OntologyValidationError([c.ValidationIssue(code="IRI_REMOVED", message="x")])

    assert isinstance(err, OntologyError)
    assert err.issues[0].code == "IRI_REMOVED"
    assert str(err) == "1 issues: IRI_REMOVED"


def test_protocols_are_runtime_checkable() -> None:
    """A complete read-store implementation satisfies the runtime Protocol."""

    class InMemoryStore:
        async def version(self, ontology_id: str) -> int:
            return 0

        async def status(self, ontology_id: str) -> c.StoreStatus:
            return c.StoreStatus(ontology_id=ontology_id, version=0, backend="memory")

        async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> c.ConceptRef | None:
            return None

        async def resolve(
            self,
            ontology_id: str,
            term: str,
            *,
            lang: str | None = None,
            k: int = 10,
            kinds: c.Sequence[str] | None = None,
            embedding: c.Sequence[float] | None = None,
        ) -> list[c.Resolution]:
            return []

        async def expand(
            self,
            ontology_id: str,
            iris: c.Sequence[str],
            *,
            family: c.ClosureFamily = "subclass",
            direction: Literal["down", "up", "both"] = "down",
            max_depth: int | None = None,
            include_deprecated: bool = False,
            as_of: int | None = None,
        ) -> set[str]:
            return set(iris)

        async def neighbors(
            self,
            ontology_id: str,
            iri: str,
            predicate: str | None = None,
            *,
            as_of: int | None = None,
        ) -> list[tuple[str, str]]:
            return []

        async def canonical(self, ontology_id: str, iris: c.Sequence[str]) -> dict[str, str]:
            return {iri: iri for iri in iris}

        async def export(
            self,
            ontology_id: str,
            fmt: Literal["turtle", "jsonld"] = "turtle",
            *,
            as_of: int | None = None,
        ) -> bytes:
            return b""

        async def close(self) -> None:
            return None

    assert isinstance(InMemoryStore(), c.OntologyStore)
