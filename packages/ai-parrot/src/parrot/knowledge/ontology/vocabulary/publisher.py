"""Serialised, append-only publication of ontology versions to PostgreSQL (FEAT-824)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import json
import logging
from typing import Any, ClassVar

import asyncpg

from parrot.knowledge.ontology.vocabulary._rows import read_content, visible_iris
from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses
from parrot.knowledge.ontology.vocabulary.contracts import (
    EmbedFn,
    OntologyContent,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
    PublishDiff,
    PublishResult,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyValidationError, PublishConflict
from parrot.knowledge.ontology.vocabulary.pg_schema import validate_schema_name, vector_literal
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import (
    canonical_ntriples,
    content_checksum,
    diff_content,
    parse_turtle,
    statement_object_hash,
    validate_content,
)


def _prepare(
    content: OntologyContent, base: OntologyContent | None
) -> tuple[OntologyContent, PublishDiff, list[Any], str, str]:
    """Materialize inferred rows and deterministic publication material off the event loop."""
    inferred = materialise_inverses(content.relations)
    prepared = content.model_copy(update={"relations": [*content.relations, *inferred]})
    diff = diff_content(base, content)
    closure = build_closure(prepared.relations, (concept.iri for concept in prepared.concepts))
    canonical = canonical_ntriples(content).decode("utf-8")
    return prepared, diff, closure, content_checksum(content), canonical


def _has_changes(diff: PublishDiff) -> bool:
    """Return whether a content diff requires a new immutable version."""
    return bool(
        diff.added_iris or diff.changed_iris or diff.deprecated or diff.relations_added or diff.relations_closed
    )


class _RetryPublication(Exception):
    """Abort a transaction whose optimistic base version has changed."""


class PostgresOntologyPublisher:
    """Serialised, append-only publication of ontology versions."""

    MAX_PUBLISH_RETRIES: ClassVar[int] = 3

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        schema: str | None = None,
        embed: EmbedFn | None = None,
        executor: concurrent.futures.Executor | None = None,
    ) -> None:
        """Initialize a publisher over a caller-owned PostgreSQL pool."""
        settings = resolve_ontology_settings(schema=schema)
        validate_schema_name(settings.schema_name)
        self._pool, self._schema, self._embed = pool, settings.schema_name, embed
        self._default_lang = settings.default_lang
        self._executor, self._owns_executor = executor, executor is None
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.publisher")

    def _pool_executor(self) -> concurrent.futures.Executor:
        """Lazily create a single-worker ProcessPoolExecutor when none was injected."""
        if self._executor is None:
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        return self._executor

    async def ensure_ontology(self, ontology_id: str, *, base_iri: str, title: str | None = None) -> None:
        """Register an ontology at version zero, checking immutable base IRI identity."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {self._schema}.ontology (ontology_id, base_iri, title) VALUES ($1, $2, $3) "
                "ON CONFLICT (ontology_id) DO NOTHING",
                ontology_id,
                base_iri,
                title,
            )
            existing = await conn.fetchrow(
                f"SELECT base_iri FROM {self._schema}.ontology WHERE ontology_id = $1", ontology_id
            )
        if existing is None or existing["base_iri"] != base_iri:
            raise ValueError(f"Ontology {ontology_id!r} is already registered with a different base_iri")

    async def publish(
        self, ontology_id: str, turtle: bytes, *, notes: str = "", shapes: bytes | None = None
    ) -> PublishResult:
        """Parse Turtle in the executor and publish the resulting content."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT base_iri FROM {self._schema}.ontology WHERE ontology_id = $1", ontology_id
            )
        if row is None:
            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            self._pool_executor(),
            functools.partial(parse_turtle, turtle, base_iri=row["base_iri"], default_lang=self._default_lang),
        )
        return await self._publish(ontology_id, content, notes=notes, carry_forward_missing=False, shapes=shapes)

    async def publish_content(
        self, ontology_id: str, content: OntologyContent, *, notes: str = "", carry_forward_missing: bool = False
    ) -> PublishResult:
        """Validate, diff against the current version, and append a new version when changed."""
        return await self._publish(
            ontology_id, content, notes=notes, carry_forward_missing=carry_forward_missing, shapes=None
        )

    async def _publish(
        self,
        ontology_id: str,
        content: OntologyContent,
        *,
        notes: str,
        carry_forward_missing: bool,
        shapes: bytes | None,
    ) -> PublishResult:
        """Run the bounded optimistic publication loop."""
        loop = asyncio.get_running_loop()
        for _attempt in range(self.MAX_PUBLISH_RETRIES):
            async with self._pool.acquire() as conn:
                ontology = await conn.fetchrow(
                    f"SELECT base_iri, current_version FROM {self._schema}.ontology WHERE ontology_id = $1", ontology_id
                )
                if ontology is None:
                    raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
                version = ontology["current_version"]
                if content.base_iri != ontology["base_iri"]:
                    raise OntologyValidationError([])
                base, _, _ = await read_content(conn, self._schema, ontology_id, version) if version else (None, [], {})
                candidate = (
                    self._carry_forward(content, base) if carry_forward_missing and base is not None else content
                )
                previous_iris = await visible_iris(conn, self._schema, ontology_id, version) if version else frozenset()

            issues = await loop.run_in_executor(
                self._pool_executor(),
                functools.partial(validate_content, candidate, previous_iris=previous_iris, shapes=shapes),
            )
            if issues:
                raise OntologyValidationError(issues)
            prepared, diff, closure, checksum, canonical = await loop.run_in_executor(
                self._pool_executor(), _prepare, candidate, base
            )
            if not _has_changes(diff):
                return PublishResult(
                    ontology_id=ontology_id, version=version, changed=False, checksum=checksum, diff=diff
                )
            embeddings = await self._embeddings(prepared, diff)
            try:
                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        locked = await conn.fetchrow(
                            f"SELECT current_version FROM {self._schema}.ontology WHERE ontology_id = $1 FOR UPDATE",
                            ontology_id,
                        )
                        if locked is None:
                            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
                        if locked["current_version"] != version:
                            raise _RetryPublication
                        new_version = version + 1
                        await self._write_version(
                            conn,
                            ontology_id,
                            new_version,
                            prepared,
                            base,
                            diff,
                            closure,
                            checksum,
                            canonical,
                            notes,
                            embeddings,
                        )
            except _RetryPublication:
                continue
            self.logger.info("published ontology %s version %d", ontology_id, new_version)
            return PublishResult(
                ontology_id=ontology_id, version=new_version, changed=True, checksum=checksum, diff=diff
            )
        raise PublishConflict(
            f"Ontology {ontology_id!r} changed during {self.MAX_PUBLISH_RETRIES} publication attempts"
        )

    def _carry_forward(self, content: OntologyContent, base: OntologyContent) -> OntologyContent:
        """Keep missing base concepts as deprecated candidates with their labels."""
        present = {concept.iri for concept in content.concepts}
        missing = [concept for concept in base.concepts if concept.iri not in present]
        if not missing:
            return content
        missing_iris = {concept.iri for concept in missing}
        carried = [concept.model_copy(update={"deprecated": True}) for concept in missing]
        labels = [*content.labels, *(label for label in base.labels if label.iri in missing_iris)]
        return content.model_copy(update={"concepts": [*content.concepts, *carried], "labels": labels})

    async def _embeddings(self, content: OntologyContent, diff: PublishDiff) -> dict[str, list[float]]:
        """Compute embeddings for added or changed concept rows before the transaction."""
        if self._embed is None:
            return {}
        changed = set(diff.added_iris) | set(diff.changed_iris)
        concepts = [concept for concept in content.concepts if concept.iri in changed]
        alt_labels: dict[str, list[str]] = {}
        for label in content.labels:
            if label.kind == "alt":
                alt_labels.setdefault(label.iri, []).append(label.text)
        texts = [
            f"{concept.pref_label or ''}\n{concept.definition or ''}\n{', '.join(sorted(alt_labels.get(concept.iri, [])))}"
            for concept in concepts
        ]
        vectors = await self._embed(texts)
        if len(vectors) != len(concepts):
            raise ValueError("EmbedFn returned a vector count different from its input count")
        return {concept.iri: vector for concept, vector in zip(concepts, vectors, strict=True)}

    async def _write_version(
        self,
        conn: asyncpg.Connection[Any],
        ontology_id: str,
        version: int,
        content: OntologyContent,
        base: OntologyContent | None,
        diff: PublishDiff,
        closure: list[Any],
        checksum: str,
        canonical: str,
        notes: str,
        embeddings: dict[str, list[float]],
    ) -> None:
        """Append one version and reconcile every versioned row without destructive writes."""
        await conn.execute(
            f"INSERT INTO {self._schema}.version (ontology_id, version, checksum, turtle_canonical, notes) "
            "VALUES ($1, $2, $3, $4, $5)",
            ontology_id,
            version,
            checksum,
            canonical,
            notes,
        )
        for concept in content.concepts:
            await conn.execute(
                f"INSERT INTO {self._schema}.concept_identity (ontology_id, iri) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                ontology_id,
                concept.iri,
            )
        base_concepts = {concept.iri: concept for concept in base.concepts} if base else {}
        for concept in content.concepts:
            if concept.iri in base_concepts and concept.iri not in diff.changed_iris:
                continue
            if concept.iri in base_concepts:
                await conn.execute(
                    f"UPDATE {self._schema}.concept SET until_version = $3 "
                    "WHERE ontology_id = $1 AND iri = $2 AND until_version IS NULL",
                    ontology_id,
                    concept.iri,
                    version,
                )
            await conn.execute(
                f"INSERT INTO {self._schema}.concept "
                "(ontology_id, iri, kind, pref_label, definition, deprecated, replaced_by, since_version, embedding, extra) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::text::vector, $10::jsonb)",
                ontology_id,
                concept.iri,
                concept.kind,
                concept.pref_label,
                concept.definition,
                concept.deprecated,
                concept.replaced_by,
                version,
                None if (vector := embeddings.get(concept.iri)) is None else vector_literal(vector),
                json.dumps(concept.extra),
            )
        await self._reconcile_labels(conn, ontology_id, version, content.labels, base.labels if base else [])
        await self._reconcile_relations(conn, ontology_id, version, content.relations, base.relations if base else [])
        await self._reconcile_statements(
            conn, ontology_id, version, content.statements, base.statements if base else []
        )
        for row in closure:
            await conn.execute(
                f"INSERT INTO {self._schema}.closure "
                "(ontology_id, version, family, ancestor_iri, descendant_iri, depth) VALUES ($1, $2, $3, $4, $5, $6)",
                ontology_id,
                version,
                row.family,
                row.ancestor_iri,
                row.descendant_iri,
                row.depth,
            )
        await conn.execute(
            f"UPDATE {self._schema}.ontology SET current_version = $2 WHERE ontology_id = $1", ontology_id, version
        )
        await conn.execute(
            f"INSERT INTO {self._schema}.publication_outbox (ontology_id, version, diff) VALUES ($1, $2, $3::jsonb)",
            ontology_id,
            version,
            diff.model_dump_json(),
        )

    async def _reconcile_labels(
        self,
        conn: asyncpg.Connection[Any],
        ontology_id: str,
        version: int,
        current: list[ParsedLabel],
        base: list[ParsedLabel],
    ) -> None:
        """Close removed label rows and append added label rows."""
        old = {(row.iri, row.lang, row.kind, row.text) for row in base}
        new = {(row.iri, row.lang, row.kind, row.text) for row in current}
        for iri, lang, kind, text in old - new:
            await conn.execute(
                f"UPDATE {self._schema}.label SET until_version = $5 WHERE ontology_id = $1 AND iri = $2 "
                "AND lang = $3 AND kind = $4 AND text = $6 AND until_version IS NULL",
                ontology_id,
                iri,
                lang,
                kind,
                version,
                text,
            )
        for iri, lang, kind, text in new - old:
            await conn.execute(
                f"INSERT INTO {self._schema}.label (ontology_id, iri, lang, kind, text, since_version) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                ontology_id,
                iri,
                lang,
                kind,
                text,
                version,
            )

    async def _reconcile_relations(
        self,
        conn: asyncpg.Connection[Any],
        ontology_id: str,
        version: int,
        current: list[ParsedRelation],
        base: list[ParsedRelation],
    ) -> None:
        """Close removed asserted or inferred relation rows and append new rows."""
        old = {(row.subject_iri, row.predicate, row.object_iri, row.inferred) for row in base}
        new = {(row.subject_iri, row.predicate, row.object_iri, row.inferred) for row in current}
        for subject, predicate, object_iri, inferred in old - new:
            await conn.execute(
                f"UPDATE {self._schema}.relation SET until_version = $6 WHERE ontology_id = $1 AND subject_iri = $2 "
                "AND predicate = $3 AND object_iri = $4 AND inferred = $5 AND until_version IS NULL",
                ontology_id,
                subject,
                predicate,
                object_iri,
                inferred,
                version,
            )
        for subject, predicate, object_iri, inferred in new - old:
            await conn.execute(
                f"INSERT INTO {self._schema}.relation "
                "(ontology_id, subject_iri, predicate, object_iri, inferred, since_version) VALUES ($1, $2, $3, $4, $5, $6)",
                ontology_id,
                subject,
                predicate,
                object_iri,
                inferred,
                version,
            )

    async def _reconcile_statements(
        self,
        conn: asyncpg.Connection[Any],
        ontology_id: str,
        version: int,
        current: list[ParsedStatement],
        base: list[ParsedStatement],
    ) -> None:
        """Close removed statement rows and append new rows keyed by canonical object hash."""
        old = {(row.subject_iri, row.predicate, statement_object_hash(row.object)) for row in base}
        new = {(row.subject_iri, row.predicate, statement_object_hash(row.object)) for row in current}
        objects = {(row.subject_iri, row.predicate, statement_object_hash(row.object)): row.object for row in current}
        for subject, predicate, object_hash in old - new:
            await conn.execute(
                f"UPDATE {self._schema}.statement SET until_version = $5 WHERE ontology_id = $1 AND subject_iri = $2 "
                "AND predicate = $3 AND object_hash = $4 AND until_version IS NULL",
                ontology_id,
                subject,
                predicate,
                object_hash,
                version,
            )
        for subject, predicate, object_hash in new - old:
            await conn.execute(
                f"INSERT INTO {self._schema}.statement "
                "(ontology_id, subject_iri, predicate, object, object_hash, since_version) VALUES ($1, $2, $3, $4::jsonb, $5, $6)",
                ontology_id,
                subject,
                predicate,
                json.dumps(objects[(subject, predicate, object_hash)]),
                object_hash,
                version,
            )

    async def close(self) -> None:
        """Shut down the executor this instance created; the pool belongs to the caller."""
        if self._owns_executor and self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
