"""OntologyStore over PostgreSQL versioned rows (FEAT-824)."""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal, Sequence

from parrot.knowledge.ontology.vocabulary._rows import read_content
from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureFamily,
    ConceptRef,
    OntologyStore,
    Resolution,
    StoreStatus,
    VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, serialize

_VISIBLE = "since_version <= $2 AND (until_version IS NULL OR $2 < until_version)"


def _visible(alias: str) -> str:
    """Version-visibility predicate for a table alias; the version is always bound as ``$2``."""
    return f"{alias}.since_version <= $2 AND ({alias}.until_version IS NULL OR $2 < {alias}.until_version)"


def _vector_literal(embedding: Sequence[float]) -> str:
    """pgvector text form (``[1,2,3]``), usable with ``$n::vector`` on a pool without the vector codec."""
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


class PostgresOntologyStore:
    """OntologyStore over PostgreSQL. Each call captures one version and reads only at it."""

    backend_name: ClassVar[str] = "postgres"
    TRGM_THRESHOLD: ClassVar[float] = 0.45
    RRF_K: ClassVar[int] = 60
    MAX_HOPS: ClassVar[int] = 16

    def __init__(self, pool: Any, *, schema: str | None = None, dsn: str | None = None) -> None:
        settings = resolve_ontology_settings(schema=schema, dsn=dsn)
        self._pool, self._owns_pool = pool, pool is None
        self._dsn, self._schema, self._lang = settings.dsn, settings.schema_name, settings.default_lang
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.postgres_store")

    async def _get_pool(self) -> Any:
        """Return the pool, creating (and owning) one from the DSN on first use."""
        if self._pool is None:
            self._pool = await create_ontology_pg_pool(self._dsn, schema=self._schema)
        return self._pool

    async def _version_for(self, conn: Any, ontology_id: str, as_of: int | None) -> int:
        """Current version (as_of=None) or as_of validated against 1..current_version."""
        # Get the current version of the ontology
        row = await conn.fetchrow(
            f"SELECT current_version FROM {self._schema}.ontology WHERE ontology_id = $1", ontology_id
        )

        if row is None:
            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")

        current_version = row["current_version"]

        # If as_of is None, return the current version
        if as_of is None:
            return current_version

        # Validate that as_of is within valid range
        if as_of < 1 or as_of > current_version:
            raise OntologyVersionNotFound(
                f"Version {as_of} of ontology {ontology_id!r} was never published "
                f"(valid range: 1..{current_version})"
            )

        return as_of

    async def version(self, ontology_id: str) -> int:
        """Current published version; 0 when registered but never published. Raises OntologyNotFound."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT current_version FROM {self._schema}.ontology WHERE ontology_id = $1", ontology_id
            )
            if row is None:
                raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
            return row["current_version"]

    async def status(self, ontology_id: str) -> StoreStatus:
        """Version, backend name and whether the data may be behind the central store."""
        version = await self.version(ontology_id)
        return StoreStatus(ontology_id=ontology_id, version=version, stale=False, backend="postgres")

    async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None:
        """Concept visible at `as_of` (default: current). None when the IRI is not visible.

        Raises OntologyVersionNotFound.
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, as_of)
            if version == 0:
                return None
            row = await conn.fetchrow(
                f"SELECT iri, kind, pref_label, definition, deprecated, replaced_by "
                f"FROM {self._schema}.concept WHERE ontology_id = $1 AND {_VISIBLE} AND iri = $3",
                ontology_id,
                version,
                iri,
            )
            if row is None:
                return None
            return ConceptRef(
                iri=row["iri"],
                ontology_id=ontology_id,
                kind=row["kind"],
                pref_label=row["pref_label"],
                definition=row["definition"],
                deprecated=row["deprecated"],
                replaced_by=row["replaced_by"],
                version=version,
            )

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
        """Hybrid lookup (exact, trigram, vector) fused with RRF; deprecated concepts are excluded."""
        term = term.strip()
        if not term or k <= 0:
            return []
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, None)
            if version == 0:
                return []
            schema = self._schema

            # $1 ontology_id, $2 version, $3 term, then optional lang / kinds.
            args: list[Any] = [ontology_id, version, term]
            filters = ""
            if lang is not None:
                args.append(lang)
                filters += f" AND l.lang = ${len(args)}"
            if kinds:
                args.append(list(kinds))
                filters += f" AND c.kind = ANY(${len(args)}::text[])"
            label_rows = await conn.fetch(
                f"""SELECT c.iri, c.kind, c.pref_label, c.definition, c.replaced_by,
                           bool_or(lower(l.text) = lower($3)) AS is_exact,
                           max(similarity(l.text, $3)) AS sim
                    FROM {schema}.label l
                    JOIN {schema}.concept c ON c.ontology_id = l.ontology_id AND c.iri = l.iri
                    WHERE l.ontology_id = $1 AND {_visible('l')} AND {_visible('c')}
                      AND NOT c.deprecated{filters}
                      AND (lower(l.text) = lower($3) OR similarity(l.text, $3) > {self.TRGM_THRESHOLD})
                    GROUP BY c.iri, c.kind, c.pref_label, c.definition, c.replaced_by""",
                *args,
            )

            rows_by_iri: dict[str, Any] = {row["iri"]: row for row in label_rows}
            exact = sorted(row["iri"] for row in label_rows if row["is_exact"])
            trgm_rows = [row for row in label_rows if row["sim"] is not None and row["sim"] > self.TRGM_THRESHOLD]
            trgm = [row["iri"] for row in sorted(trgm_rows, key=lambda r: (-r["sim"], r["iri"]))]

            vector: list[str] = []
            if embedding is not None:
                vec_args: list[Any] = [ontology_id, version, _vector_literal(embedding)]
                vec_filter = ""
                if kinds:
                    vec_args.append(list(kinds))
                    vec_filter = f" AND c.kind = ANY(${len(vec_args)}::text[])"
                vec_args.append(max(k * 5, 50))
                vector_rows = await conn.fetch(
                    f"""SELECT c.iri, c.kind, c.pref_label, c.definition, c.replaced_by
                        FROM {schema}.concept c
                        WHERE c.ontology_id = $1 AND {_visible('c')} AND NOT c.deprecated
                          AND c.embedding IS NOT NULL{vec_filter}
                        ORDER BY c.embedding <=> $3::vector, c.iri
                        LIMIT ${len(vec_args)}""",
                    *vec_args,
                )
                for row in vector_rows:
                    rows_by_iri.setdefault(row["iri"], row)
                    vector.append(row["iri"])

            fused: dict[str, float] = {}
            matched_by: dict[str, Literal["exact", "trgm", "vector"]] = {}
            for name, ranking in (("exact", exact), ("trgm", trgm), ("vector", vector)):
                for rank, iri in enumerate(ranking, start=1):
                    fused[iri] = fused.get(iri, 0.0) + 1.0 / (self.RRF_K + rank)
                    matched_by.setdefault(iri, name)  # type: ignore[arg-type]

            results: list[Resolution] = []
            for iri in sorted(fused, key=lambda item: (-fused[item], item))[:k]:
                row = rows_by_iri[iri]
                ref = ConceptRef(
                    iri=iri,
                    ontology_id=ontology_id,
                    kind=row["kind"],
                    pref_label=row["pref_label"],
                    definition=row["definition"],
                    deprecated=False,
                    replaced_by=row["replaced_by"],
                    version=version,
                )
                results.append(Resolution(concept=ref, score=fused[iri], matched_by=matched_by[iri]))
            return results

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
        if not iris:
            return set()

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, as_of)
            if version == 0:
                return set(iris)

            # $1 ontology_id, $2 version, $3 family, $4 iris, optional $5 max_depth.
            args: list[Any] = [ontology_id, version, family, list(iris)]
            depth_sql = ""
            if max_depth is not None:
                args.append(int(max_depth))
                depth_sql = f" AND depth <= ${len(args)}"
            base = f"FROM {self._schema}.closure WHERE ontology_id = $1 AND version = $2 AND family = $3{depth_sql}"
            down = f"SELECT descendant_iri AS iri {base} AND ancestor_iri = ANY($4::text[])"
            up = f"SELECT ancestor_iri AS iri {base} AND descendant_iri = ANY($4::text[])"
            query = {"down": down, "up": up}.get(direction, f"{down} UNION {up}")

            found = {row["iri"] for row in await conn.fetch(query, *args)}

            if not include_deprecated and found:
                deprecated = await conn.fetch(
                    f"SELECT iri FROM {self._schema}.concept "
                    f"WHERE ontology_id = $1 AND {_VISIBLE} AND deprecated AND iri = ANY($3::text[])",
                    ontology_id,
                    version,
                    list(found),
                )
                found.difference_update(row["iri"] for row in deprecated)

            return found | set(iris)

    async def neighbors(
        self,
        ontology_id: str,
        iri: str,
        predicate: str | None = None,
        *,
        as_of: int | None = None,
    ) -> list[tuple[str, str]]:
        """Outbound asserted and inferred `(predicate, object_iri)` pairs."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, as_of)
            if version == 0:
                return []

            query = (
                f"SELECT predicate, object_iri FROM {self._schema}.relation "
                f"WHERE ontology_id = $1 AND {_VISIBLE} AND subject_iri = $3"
            )
            args: list[Any] = [ontology_id, version, iri]
            if predicate is not None:
                args.append(predicate)
                query += f" AND predicate = ${len(args)}"
            rows = await conn.fetch(query + " ORDER BY predicate, object_iri", *args)
            return [(row["predicate"], row["object_iri"]) for row in rows]

    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
        """Map each IRI to its live replacement (cycle-safe, at most 16 hops); unchanged IRIs are omitted."""
        if not iris:
            return {}

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, None)
            if version == 0:
                return {}

            rows = await conn.fetch(
                f"SELECT iri, replaced_by FROM {self._schema}.concept "
                f"WHERE ontology_id = $1 AND {_VISIBLE} AND replaced_by IS NOT NULL",
                ontology_id,
                version,
            )
            replacements = {row["iri"]: row["replaced_by"] for row in rows}

            result: dict[str, str] = {}
            for iri in iris:
                current, seen = iri, {iri}
                for _ in range(self.MAX_HOPS):
                    following = replacements.get(current)
                    if following is None or following in seen:
                        break
                    current = following
                    seen.add(current)
                if current != iri:
                    result[iri] = current
            return result

    async def export(
        self,
        ontology_id: str,
        fmt: Literal["turtle", "jsonld"] = "turtle",
        *,
        as_of: int | None = None,
    ) -> bytes:
        """Serialise the asserted graph visible at `as_of`."""
        # Load the complete version content
        content = await self.load_version(ontology_id, as_of)
        # Serialize using the turtle module
        return serialize(content.content, fmt)

    async def close(self) -> None:
        """Release connections and file handles."""
        if self._owns_pool and self._pool is not None:
            await self._pool.close()

    async def load_version(self, ontology_id: str, version: int | None = None) -> VersionContent:
        """Everything visible at one version — rows, closure, embeddings — for build_snapshot."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Determine the version to load
            target_version = await self._version_for(conn, ontology_id, version)

            # Read content using the shared function
            content, closure, embeddings = await read_content(conn, self._schema, ontology_id, target_version)

            # Create VersionContent
            version_content = VersionContent(
                ontology_id=ontology_id,
                version=target_version,
                checksum=content_checksum(content),
                content=content,
                closure=closure,
                embeddings=embeddings,
            )

            return version_content


def _create_postgres(*, dsn: str | None = None, schema: str | None = None, pool: Any = None, **_: Any) -> OntologyStore:
    """Registry factory for the 'postgres' backend."""
    return PostgresOntologyStore(pool, schema=schema, dsn=dsn)
