"""Shared PostgreSQL readers for one visible ontology version (FEAT-824)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureRow,
    OntologyContent,
    ParsedConcept,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
)


def _json_object(value: Any) -> dict[str, Any]:
    """Normalize asyncpg's configurable JSONB codec result to a dictionary."""
    return json.loads(value) if isinstance(value, str) else dict(value)


async def read_content(
    conn: asyncpg.Connection[Any], schema: str, ontology_id: str, version: int
) -> tuple[OntologyContent, list[ClosureRow], dict[str, list[float]]]:
    """Read all rows visible for an ontology at one published version.

    Args:
        conn: Open PostgreSQL connection.
        schema: Validated ontology schema name.
        ontology_id: Registered ontology identifier.
        version: Published version to materialize.

    Returns:
        Content, closure rows and concept embeddings at ``version``.
    """
    visible = "since_version <= $2 AND (until_version IS NULL OR $2 < until_version)"
    ontology = await conn.fetchrow(f"SELECT base_iri FROM {schema}.ontology WHERE ontology_id = $1", ontology_id)
    if ontology is None:
        raise ValueError(f"Ontology {ontology_id!r} does not exist")

    concepts = await conn.fetch(
        f"SELECT iri, kind, pref_label, definition, deprecated, replaced_by, extra, embedding "
        f"FROM {schema}.concept WHERE ontology_id = $1 AND {visible} ORDER BY iri",
        ontology_id,
        version,
    )
    labels = await conn.fetch(
        f"SELECT iri, lang, kind, text FROM {schema}.label "
        f"WHERE ontology_id = $1 AND {visible} ORDER BY iri, lang, kind, text",
        ontology_id,
        version,
    )
    relations = await conn.fetch(
        f"SELECT subject_iri, predicate, object_iri, inferred FROM {schema}.relation "
        f"WHERE ontology_id = $1 AND {visible} ORDER BY subject_iri, predicate, object_iri, inferred",
        ontology_id,
        version,
    )
    statements = await conn.fetch(
        f"SELECT subject_iri, predicate, object FROM {schema}.statement "
        f"WHERE ontology_id = $1 AND {visible} ORDER BY subject_iri, predicate, object_hash",
        ontology_id,
        version,
    )
    closure = await conn.fetch(
        f"SELECT family, ancestor_iri, descendant_iri, depth FROM {schema}.closure "
        f"WHERE ontology_id = $1 AND version = $2 ORDER BY family, descendant_iri, ancestor_iri",
        ontology_id,
        version,
    )
    embeddings: dict[str, list[float]] = {}
    parsed_concepts: list[ParsedConcept] = []
    for row in concepts:
        parsed_concepts.append(
            ParsedConcept(
                iri=row["iri"],
                kind=row["kind"],
                pref_label=row["pref_label"],
                definition=row["definition"],
                deprecated=row["deprecated"],
                replaced_by=row["replaced_by"],
                extra=_json_object(row["extra"]),
            )
        )
        if row["embedding"] is not None:
            embeddings[row["iri"]] = [float(value) for value in row["embedding"]]
    return (
        OntologyContent(
            base_iri=ontology["base_iri"],
            concepts=parsed_concepts,
            labels=[ParsedLabel(**dict(row)) for row in labels],
            relations=[ParsedRelation(**dict(row)) for row in relations],
            statements=[
                ParsedStatement(
                    subject_iri=row["subject_iri"], predicate=row["predicate"], object=_json_object(row["object"])
                )
                for row in statements
            ],
        ),
        [ClosureRow(**dict(row)) for row in closure],
        embeddings,
    )


async def visible_iris(conn: asyncpg.Connection[Any], schema: str, ontology_id: str, version: int) -> frozenset[str]:
    """Return concept IRIs visible at one published version."""
    rows = await conn.fetch(
        f"SELECT iri FROM {schema}.concept WHERE ontology_id = $1 "
        "AND since_version <= $2 AND (until_version IS NULL OR $2 < until_version)",
        ontology_id,
        version,
    )
    return frozenset(row["iri"] for row in rows)
