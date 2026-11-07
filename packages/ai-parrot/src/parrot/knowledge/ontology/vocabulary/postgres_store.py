"""OntologyStore over PostgreSQL versioned rows (FEAT-824)."""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal, Sequence

from parrot.knowledge.ontology.vocabulary._rows import read_content
from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureFamily, ConceptRef, OntologyStore, Resolution, StoreStatus, VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.pg_schema import create_ontology_pg_pool
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, serialize

_VISIBLE = "since_version <= $2 AND (until_version IS NULL OR $2 < until_version)"


class PostgresOntologyStore:
    """OntologyStore over PostgreSQL. Each call captures one version and reads only at it."""

    backend_name: ClassVar[str] = "postgres"
    TRGM_THRESHOLD: ClassVar[float] = 0.45
    RRF_K: ClassVar[int] = 60

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
            f"SELECT current_version FROM {self._schema}.ontology WHERE ontology_id = $1",
            ontology_id
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
                f"SELECT current_version FROM {self._schema}.ontology WHERE ontology_id = $1",
                ontology_id
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
            
            # If version is 0, return None (no published versions)
            if version == 0:
                return None
                
            # Get the concept visible at the specified version
            row = await conn.fetchrow(
                f"SELECT iri, kind, pref_label, definition, deprecated, replaced_by "
                f"FROM {self._schema}.concept WHERE ontology_id = $1 AND iri = $2 AND {_VISIBLE}",
                ontology_id, iri, version
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
                version=version
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
        """Hybrid lookup at the current version with at most `k` live results."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, None)  # Current version
            
            # If version is 0, return empty list (no published versions)
            if version == 0:
                return []
                
            # Build conditions for filtering
            conditions = ["ontology_id = $1"]
            params = [ontology_id, version]
            param_index = 3  # Starting from $3 since $1=ontology_id, $2=version
            
            if lang is not None:
                conditions.append(f"label.lang = ${param_index}")
                params.append(lang)
                param_index += 1
                
            if kinds:
                placeholders = ", ".join(f"${i}" for i in range(param_index, param_index + len(kinds)))
                conditions.append(f"concept.kind IN ({placeholders})")
                params.extend(kinds)
                param_index += len(kinds)
                
            # Exclude deprecated concepts
            conditions.append("concept.deprecated = FALSE")
            
            where_clause = " AND ".join(conditions)
            
            # Collect results from different sources
            results = []
            
            # 1. Exact case-insensitive match on any label
            exact_query = f"""
                SELECT concept.iri, concept.kind, concept.pref_label, concept.definition, 
                       concept.deprecated, concept.replaced_by,
                       1.0 as score, 'exact' as matched_by
                FROM {self._schema}.concept concept
                JOIN {self._schema}.label label ON concept.ontology_id = label.ontology_id 
                    AND concept.iri = label.iri AND concept.since_version <= $2 
                    AND (concept.until_version IS NULL OR $2 < concept.until_version)
                WHERE {where_clause} AND LOWER(label.text) = LOWER($2)
            """
            exact_params = params + [term]
            exact_rows = await conn.fetch(exact_query, *exact_params)
            results.extend(exact_rows)
            
            # 2. Trigram similarity
            trgm_query = f"""
                SELECT concept.iri, concept.kind, concept.pref_label, concept.definition, 
                       concept.deprecated, concept.replaced_by,
                       similarity(label.text, $2) as score, 'trgm' as matched_by
                FROM {self._schema}.concept concept
                JOIN {self._schema}.label label ON concept.ontology_id = label.ontology_id 
                    AND concept.iri = label.iri AND concept.since_version <= $2 
                    AND (concept.until_version IS NULL OR $2 < concept.until_version)
                WHERE {where_clause} AND similarity(label.text, $2) > {self.TRGM_THRESHOLD}
            """
            trgm_rows = await conn.fetch(trgm_query, *(params + [term]))
            results.extend(trgm_rows)
            
            # 3. Vector cosine on concept.embedding when embedding is given
            if embedding is not None:
                vector_query = f"""
                    SELECT concept.iri, concept.kind, concept.pref_label, concept.definition, 
                           concept.deprecated, concept.replaced_by,
                           1 - (concept.embedding <=> $2) as score, 'vector' as matched_by
                    FROM {self._schema}.concept concept
                    WHERE {where_clause} AND concept.embedding IS NOT NULL
                """
                vector_params = params + [embedding]
                vector_rows = await conn.fetch(vector_query, *vector_params)
                results.extend(vector_rows)
            
            # Deduplicate results by IRI, keeping the highest scoring match
            concept_scores = {}
            for row in results:
                iri = row["iri"]
                score = row["score"]
                if iri not in concept_scores or score > concept_scores[iri]["score"]:
                    concept_scores[iri] = row
                    
            # Apply RRF scoring
            scored_concepts = []
            for i, (_iri, row) in enumerate(concept_scores.items()):
                # Simple ranking-based scoring for now
                rrf_score = 1.0 / (self.RRF_K + i + 1) if i < len(concept_scores) else 0
                concept_ref = ConceptRef(
                    iri=row["iri"],
                    ontology_id=ontology_id,
                    kind=row["kind"],
                    pref_label=row["pref_label"],
                    definition=row["definition"],
                    deprecated=row["deprecated"],
                    replaced_by=row["replaced_by"],
                    version=version
                )
                resolution = Resolution(
                    concept=concept_ref,
                    score=rrf_score,
                    matched_by=row["matched_by"]
                )
                scored_concepts.append(resolution)
                
            # Sort by score descending and limit to k results
            scored_concepts.sort(key=lambda x: x.score, reverse=True)
            return scored_concepts[:k]

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
            
            # If version is 0, return only the input IRIs
            if version == 0:
                return set(iris)
                
            # Build the query based on direction
            if direction == "down":
                # Descendants
                query = f"""
                    SELECT DISTINCT descendant_iri 
                    FROM {self._schema}.closure 
                    WHERE ontology_id = $1 AND version = $2 AND family = $3 
                    AND ancestor_iri = ANY($4)
                """
                params = [ontology_id, version, family, list(iris)]
            elif direction == "up":
                # Ancestors
                query = f"""
                    SELECT DISTINCT ancestor_iri 
                    FROM {self._schema}.closure 
                    WHERE ontology_id = $1 AND version = $2 AND family = $3 
                    AND descendant_iri = ANY($4)
                """
                params = [ontology_id, version, family, list(iris)]
            else:  # both
                # Union of ancestors and descendants
                query = f"""
                    SELECT DISTINCT iri FROM (
                        SELECT descendant_iri as iri
                        FROM {self._schema}.closure 
                        WHERE ontology_id = $1 AND version = $2 AND family = $3 
                        AND ancestor_iri = ANY($4)
                        UNION
                        SELECT ancestor_iri as iri
                        FROM {self._schema}.closure 
                        WHERE ontology_id = $1 AND version = $2 AND family = $3 
                        AND descendant_iri = ANY($4)
                    ) combined
                """
                params = [ontology_id, version, family, list(iris)]
                
            # Add depth filter if specified
            if max_depth is not None:
                query = query.replace("FROM", f"FROM {self._schema}.closure WHERE depth <= {max_depth} AND ")
                
            # Exclude deprecated concepts unless asked
            if not include_deprecated:
                query += f" AND iri NOT IN (SELECT iri FROM {self._schema}.concept WHERE ontology_id = $1 AND deprecated = TRUE)"
                
            rows = await conn.fetch(query, *params)
            result_iris = {row["iri"] for row in rows}
            
            # Always include input IRIs
            result_iris.update(iris)
            
            return result_iris

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
            
            # If version is 0, return empty list
            if version == 0:
                return []
                
            # Build query
            query = f"""
                SELECT predicate, object_iri 
                FROM {self._schema}.relation 
                WHERE ontology_id = $1 AND subject_iri = $2 AND {_VISIBLE}
            """
            params = [ontology_id, iri, version]
            
            if predicate is not None:
                query += " AND predicate = $4"
                params.append(predicate)
                
            query += " ORDER BY predicate, object_iri"
                
            rows = await conn.fetch(query, *params)
            return [(row["predicate"], row["object_iri"]) for row in rows]

    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
        """Map each IRI to its live replacement, following replacements safely."""
        if not iris:
            return {}
            
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            version = await self._version_for(conn, ontology_id, None)  # Current version
            
            # If version is 0, return empty dict
            if version == 0:
                return {}
                
            # Get current concepts to check replacements
            query = f"""
                SELECT iri, replaced_by 
                FROM {self._schema}.concept 
                WHERE ontology_id = $1 AND iri = ANY($2) AND {_VISIBLE} AND replaced_by IS NOT NULL
            """
            rows = await conn.fetch(query, ontology_id, list(iris), version)
            
            # Build replacement map
            replacements = {row["iri"]: row["replaced_by"] for row in rows}
            
            # Follow replacements safely (cycle-safe, ≤ 16 hops)
            result = {}
            for iri in iris:
                current = iri
                hops = 0
                while current in replacements and hops < 16:
                    current = replacements[current]
                    hops += 1
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
                embeddings=embeddings
            )
            
            return version_content


def _create_postgres(*, dsn: str | None = None, schema: str | None = None, pool: Any = None,
                     **_: Any) -> OntologyStore:
    """Registry factory for the 'postgres' backend."""
    return PostgresOntologyStore(pool, schema=schema, dsn=dsn)