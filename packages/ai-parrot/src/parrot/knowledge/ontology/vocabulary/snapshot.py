"""Read-only SQLite snapshots of one ontology version (FEAT-824)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Mapping, Protocol, Sequence, runtime_checkable

from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureFamily,
    ConceptRef,
    OntologyContent,
    OntologyStore,
    ParsedConcept,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
    Resolution,
    StoreStatus,
    VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

if TYPE_CHECKING:
    import aiohttp
    import aiosqlite

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.snapshot")

SNAPSHOT_FORMAT_VERSION = 1
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SNAPSHOT_DDL = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE concept (
    iri TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    pref_label TEXT,
    definition TEXT,
    deprecated INTEGER NOT NULL,
    replaced_by TEXT,
    extra JSON NOT NULL,
    embedding BLOB
);
CREATE TABLE label (
    iri TEXT NOT NULL,
    lang TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (iri, lang, kind, text)
);
CREATE TABLE relation (
    subject_iri TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_iri TEXT NOT NULL,
    inferred INTEGER NOT NULL,
    PRIMARY KEY (subject_iri, predicate, object_iri)
);
CREATE TABLE statement (
    subject_iri TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object JSON NOT NULL,
    object_hash TEXT NOT NULL,
    PRIMARY KEY (subject_iri, predicate, object_hash)
);
CREATE TABLE closure (
    family TEXT NOT NULL,
    ancestor_iri TEXT NOT NULL,
    descendant_iri TEXT NOT NULL,
    depth INTEGER NOT NULL,
    PRIMARY KEY (family, descendant_iri, ancestor_iri)
);
CREATE INDEX relation_by_subject ON relation (predicate, subject_iri);
CREATE INDEX relation_by_object ON relation (predicate, object_iri);
CREATE INDEX closure_by_ancestor ON closure (family, ancestor_iri);
CREATE VIRTUAL TABLE label_fts USING fts5(
    text,
    iri UNINDEXED,
    lang UNINDEXED,
    kind UNINDEXED,
    tokenize='trigram'
);
"""


def snapshot_path(root: Path, ontology_id: str, version: int) -> Path:
    """Return ``{root}/{ontology_id}/v{version}.sqlite``."""
    return Path(root).expanduser() / ontology_id / f"v{version}.sqlite"


async def build_snapshot(content: VersionContent, dest_root: Path) -> Path:
    """Write the snapshot atomically and return its path.

    An existing snapshot is reused only when its checksum matches. The complete
    replacement database is committed and closed before it is atomically moved
    into place, so readers never observe a partial transaction.

    Args:
        content: Fully materialized rows for one published ontology version.
        dest_root: Root directory for ontology snapshot files.

    Returns:
        Path to the completed snapshot.

    Raises:
        ValueError: If the destination exists with a different checksum.
    """
    import aiosqlite
    import numpy as np

    final = snapshot_path(dest_root, content.ontology_id, content.version)
    if final.exists():
        existing_checksum = await _read_checksum(final)
        if existing_checksum == content.checksum:
            return final
        raise ValueError(
            f"Snapshot {final} already exists with checksum {existing_checksum!r}, " f"not {content.checksum!r}"
        )

    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(f"{final}.tmp")
    if temporary.exists():
        temporary.unlink()

    try:
        async with aiosqlite.connect(temporary) as database:
            await database.executescript(_SNAPSHOT_DDL)
            await database.executemany(
                """INSERT INTO concept
                   (iri, kind, pref_label, definition, deprecated, replaced_by, extra, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        concept.iri,
                        concept.kind,
                        concept.pref_label,
                        concept.definition,
                        int(concept.deprecated),
                        concept.replaced_by,
                        _canonical_json(concept.extra),
                        (
                            np.asarray(content.embeddings[concept.iri], dtype=np.float32).tobytes()
                            if concept.iri in content.embeddings
                            else None
                        ),
                    )
                    for concept in content.content.concepts
                ],
            )
            label_rows = [(label.iri, label.lang, label.kind, label.text) for label in content.content.labels]
            await database.executemany(
                "INSERT INTO label (iri, lang, kind, text) VALUES (?, ?, ?, ?)",
                label_rows,
            )
            await database.executemany(
                "INSERT INTO label_fts (iri, lang, kind, text) VALUES (?, ?, ?, ?)",
                label_rows,
            )
            await database.executemany(
                """INSERT INTO relation
                   (subject_iri, predicate, object_iri, inferred) VALUES (?, ?, ?, ?)""",
                [
                    (relation.subject_iri, relation.predicate, relation.object_iri, int(relation.inferred))
                    for relation in content.content.relations
                ],
            )
            await database.executemany(
                """INSERT INTO statement
                   (subject_iri, predicate, object, object_hash) VALUES (?, ?, ?, ?)""",
                [
                    (
                        statement.subject_iri,
                        statement.predicate,
                        _canonical_json(statement.object),
                        _object_hash(statement.object),
                    )
                    for statement in content.content.statements
                ],
            )
            await database.executemany(
                """INSERT INTO closure
                   (family, ancestor_iri, descendant_iri, depth) VALUES (?, ?, ?, ?)""",
                [(row.family, row.ancestor_iri, row.descendant_iri, row.depth) for row in content.closure],
            )
            await database.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [
                    ("format_version", str(SNAPSHOT_FORMAT_VERSION)),
                    ("ontology_id", content.ontology_id),
                    ("version", str(content.version)),
                    ("checksum", content.checksum),
                    ("base_iri", content.content.base_iri),
                    ("built_at", datetime.now(timezone.utc).isoformat()),
                ],
            )
            await database.commit()
        os.replace(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    logger.info(
        "Built ontology snapshot %s version %s at %s",
        content.ontology_id,
        content.version,
        final,
    )
    return final


async def _read_checksum(path: Path) -> str | None:
    """Read a completed snapshot's checksum without changing the file."""
    import aiosqlite

    try:
        async with aiosqlite.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as database:
            cursor = await database.execute("SELECT value FROM meta WHERE key = 'checksum'")
            row = await cursor.fetchone()
            await cursor.close()
    except aiosqlite.Error as exc:
        raise ValueError(f"Existing snapshot {path} is not a valid snapshot") from exc
    return None if row is None else str(row[0])


def _canonical_json(value: object) -> str:
    """Serialize a snapshot JSON value deterministically."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _object_hash(value: object) -> str:
    """Return the stable SHA-256 hash used in the statement primary key."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def trigram_similarity(a: str, b: str) -> float:
    """Return pg_trgm-compatible lower-cased, word-padded set similarity."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _trigrams(text: str) -> set[str]:
    """Return trigrams of every word padded as ``'  word '``."""
    out: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        out.update(padded[index : index + 3] for index in range(len(padded) - 2))
    return out


@runtime_checkable
class SnapshotSource(Protocol):
    """Where newer snapshots come from."""

    async def latest_version(self, ontology_id: str) -> int:
        """Return the newest snapshot version the source offers."""
        ...

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
        """Download one snapshot into ``dest_root`` and return its path."""
        ...


class HttpSnapshotSource:
    """SnapshotSource over the vocabulary HTTP routes, using aiohttp."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        session: "aiohttp.ClientSession | None" = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self._session, self._owns_session = session, session is None

    async def _get_session(self) -> "aiohttp.ClientSession":
        """Return the session, creating (and owning) one on first use."""
        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self._session

    async def latest_version(self, ontology_id: str) -> int:
        """Return ``version`` from ``GET {base}/vocabularies/{id}/version``.

        Raises:
            aiohttp.ClientError: On transport, HTTP status or malformed-payload errors.
        """
        import aiohttp

        session = await self._get_session()
        async with session.get(f"{self._base}/vocabularies/{ontology_id}/version", headers=self._headers) as response:
            response.raise_for_status()
            payload = await response.json()
        try:
            return int(payload["version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise aiohttp.ClientPayloadError(f"Malformed version payload for {ontology_id!r}: {payload!r}") from exc

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
        """Stream ``GET {base}/vocabularies/{id}/snapshot?version=N`` to a temp file, then move it into place."""
        session = await self._get_session()
        final = snapshot_path(dest_root, ontology_id, version)
        await asyncio.to_thread(final.parent.mkdir, parents=True, exist_ok=True)
        temporary = Path(f"{final}.download")
        try:
            async with session.get(
                f"{self._base}/vocabularies/{ontology_id}/snapshot",
                params={"version": str(version)},
                headers=self._headers,
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:  # noqa: ASYNC230 - chunked, offloaded writes below
                    async for chunk in response.content.iter_chunked(1 << 16):
                        await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(os.replace, temporary, final)
        except BaseException:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
            raise
        return final

    async def close(self) -> None:
        """Close the session only when this source created it."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None


class SnapshotOntologyStore:
    """Read-only OntologyStore over local snapshot files.

    The newest ``{snapshot_dir}/{ontology_id}/v*.sqlite`` is the current version. With a source
    configured the store refreshes once per ontology; when the source is unreachable it keeps
    serving the newest local file and reports ``stale=True``.
    """

    backend_name: ClassVar[str] = "snapshot"
    TRGM_THRESHOLD: ClassVar[float] = 0.45
    RRF_K: ClassVar[int] = 60
    _CHUNK: ClassVar[int] = 500
    _MAX_HOPS: ClassVar[int] = 16

    def __init__(self, snapshot_dir: Path | str | None = None, *, source: SnapshotSource | None = None) -> None:
        settings = resolve_ontology_settings()
        self._root = Path(snapshot_dir or settings.snapshot_dir).expanduser()
        self._source, self._owns_source = source, False
        self._lang = settings.default_lang
        self._stale: dict[str, bool] = {}
        self._refreshed: set[str] = set()
        self._connections: dict[tuple[str, int], "aiosqlite.Connection"] = {}
        self.logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.snapshot_store")

    # ------------------------------------------------------------------ files / refresh

    def _scan(self, ontology_id: str) -> list[int]:
        """Return the ascending local snapshot versions of one ontology."""
        directory = self._root / ontology_id
        if not directory.is_dir():
            return []
        versions: list[int] = []
        for path in directory.glob("v*.sqlite"):
            digits = path.stem[1:]
            if digits.isdigit():
                versions.append(int(digits))
        return sorted(versions)

    async def refresh(self, ontology_id: str) -> StoreStatus:
        """Fetch a newer snapshot when reachable; network failure keeps the local file with ``stale=True``.

        Raises:
            OntologyNotFound: When no local snapshot exists after the attempt.
        """
        import aiohttp

        self._refreshed.add(ontology_id)
        stale = False
        if self._source is not None:
            try:
                latest = await self._source.latest_version(ontology_id)
                local = await asyncio.to_thread(self._scan, ontology_id)
                if latest > (local[-1] if local else 0):
                    await self._source.fetch(ontology_id, latest, self._root)
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                stale = True
                self.logger.warning("Snapshot source unreachable for %s: %s", ontology_id, exc)
        self._stale[ontology_id] = stale
        versions = await asyncio.to_thread(self._scan, ontology_id)
        if not versions:
            raise OntologyNotFound(f"Ontology {ontology_id!r} not found: no local snapshot and no reachable source")
        return StoreStatus(ontology_id=ontology_id, version=versions[-1], stale=stale, backend=self.backend_name)

    async def _current(self, ontology_id: str) -> int:
        """Current local version, refreshing once per ontology when a source is configured."""
        if self._source is not None and ontology_id not in self._refreshed:
            return (await self.refresh(ontology_id)).version
        versions = await asyncio.to_thread(self._scan, ontology_id)
        if not versions:
            raise OntologyNotFound(f"Ontology {ontology_id!r} not found in {self._root}")
        return versions[-1]

    async def _version_for(self, ontology_id: str, as_of: int | None) -> int:
        """The snapshot's own version; any other ``as_of`` is rejected."""
        current = await self._current(ontology_id)
        if as_of is not None and as_of != current:
            raise OntologyVersionNotFound(
                f"Snapshot of {ontology_id!r} holds version {current} only; version {as_of} is not available"
            )
        return current

    async def _connection(self, ontology_id: str, version: int) -> "aiosqlite.Connection":
        """Open (and cache) a read-only connection to one snapshot file."""
        import aiosqlite

        key = (ontology_id, version)
        if key not in self._connections:
            path = snapshot_path(self._root, ontology_id, version)
            self._connections[key] = await aiosqlite.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        return self._connections[key]

    # ------------------------------------------------------------------ OntologyStore

    async def version(self, ontology_id: str) -> int:
        """Current snapshot version. Raises OntologyNotFound."""
        return await self._current(ontology_id)

    async def status(self, ontology_id: str) -> StoreStatus:
        """Version, backend name and whether a configured source was unreachable on the last refresh."""
        version = await self._current(ontology_id)
        return StoreStatus(
            ontology_id=ontology_id,
            version=version,
            stale=self._stale.get(ontology_id, False),
            backend=self.backend_name,
        )

    async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None:
        """Concept at the snapshot version, or None when the IRI is not in it."""
        version = await self._version_for(ontology_id, as_of)
        conn = await self._connection(ontology_id, version)
        cursor = await conn.execute(
            "SELECT iri, kind, pref_label, definition, deprecated, replaced_by FROM concept WHERE iri = ?", (iri,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return None if row is None else self._concept_ref(ontology_id, version, row)

    @staticmethod
    def _concept_ref(ontology_id: str, version: int, row: Any) -> ConceptRef:
        """Build a ConceptRef from an ``(iri, kind, pref_label, definition, deprecated, replaced_by)`` row."""
        return ConceptRef(
            iri=row[0],
            ontology_id=ontology_id,
            kind=row[1],
            pref_label=row[2],
            definition=row[3],
            deprecated=bool(row[4]),
            replaced_by=row[5],
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
        version = await self._version_for(ontology_id, None)
        conn = await self._connection(ontology_id, version)
        term = term.strip()
        if not term or k <= 0:
            return []

        live = await self._live_concepts(conn, kinds)
        folded = term.casefold()
        grams = self._match_grams(term)
        lang_sql, lang_args = ("", ()) if lang is None else (" AND lang = ?", (lang,))
        if grams:
            match = " OR ".join('"' + gram.replace('"', '""') + '"' for gram in grams)
            cursor = await conn.execute(
                f"SELECT iri, text FROM label_fts WHERE label_fts MATCH ?{lang_sql}", (match, *lang_args)
            )
        else:
            cursor = await conn.execute(f"SELECT iri, text FROM label WHERE 1 = 1{lang_sql}", lang_args)
        label_rows = await cursor.fetchall()
        await cursor.close()

        exact: set[str] = set()
        trgm: dict[str, float] = {}
        for iri, text in label_rows:
            if iri not in live:
                continue
            if text.casefold() == folded:
                exact.add(iri)
            similarity = trigram_similarity(term, text)
            if similarity > self.TRGM_THRESHOLD:
                trgm[iri] = max(similarity, trgm.get(iri, 0.0))

        vector: dict[str, float] = {}
        if embedding is not None:
            vector = await self._vector_scores(conn, live, embedding)

        rankings = {
            "exact": sorted(exact),
            "trgm": sorted(trgm, key=lambda iri: (-trgm[iri], iri)),
            "vector": sorted(vector, key=lambda iri: (-vector[iri], iri)),
        }
        fused: dict[str, float] = {}
        matched_by: dict[str, Literal["exact", "trgm", "vector"]] = {}
        for name in ("exact", "trgm", "vector"):
            for rank, iri in enumerate(rankings[name], start=1):
                fused[iri] = fused.get(iri, 0.0) + 1.0 / (self.RRF_K + rank)
                matched_by.setdefault(iri, name)  # type: ignore[arg-type]

        results: list[Resolution] = []
        for iri in sorted(fused, key=lambda item: (-fused[item], item))[:k]:
            kind, pref_label, definition, replaced_by = live[iri]
            ref = ConceptRef(
                iri=iri,
                ontology_id=ontology_id,
                kind=kind,
                pref_label=pref_label,
                definition=definition,
                deprecated=False,
                replaced_by=replaced_by,
                version=version,
            )
            results.append(Resolution(concept=ref, score=fused[iri], matched_by=matched_by[iri]))
        return results

    @staticmethod
    def _match_grams(term: str, limit: int = 64) -> list[str]:
        """Distinct raw character trigrams of the term's words (FTS5 trigram candidates); empty below 3 chars."""
        grams: list[str] = []
        for word in _WORD.findall(term.lower()):
            for index in range(len(word) - 2):
                gram = word[index : index + 3]
                if gram not in grams:
                    grams.append(gram)
        return grams[:limit]

    async def _live_concepts(
        self, conn: "aiosqlite.Connection", kinds: Sequence[str] | None
    ) -> dict[str, tuple[str, str | None, str | None, str | None]]:
        """Non-deprecated concepts (optionally of the given kinds): iri -> (kind, label, definition, replaced_by)."""
        query = "SELECT iri, kind, pref_label, definition, replaced_by FROM concept WHERE deprecated = 0"
        args: list[Any] = []
        if kinds:
            query += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        cursor = await conn.execute(query, args)
        rows = await cursor.fetchall()
        await cursor.close()
        return {row[0]: (row[1], row[2], row[3], row[4]) for row in rows}

    @staticmethod
    async def _vector_scores(
        conn: "aiosqlite.Connection", live: Mapping[str, Any], embedding: Sequence[float]
    ) -> dict[str, float]:
        """Cosine similarity between the query embedding and each live concept's stored embedding."""
        import numpy as np

        query = np.asarray(embedding, dtype=np.float32)
        query_norm = float(np.linalg.norm(query))
        if query_norm == 0.0:
            return {}
        cursor = await conn.execute("SELECT iri, embedding FROM concept WHERE embedding IS NOT NULL")
        rows = await cursor.fetchall()
        await cursor.close()
        scores: dict[str, float] = {}
        for iri, blob in rows:
            if iri not in live:
                continue
            vector = np.frombuffer(blob, dtype=np.float32)
            norm = float(np.linalg.norm(vector))
            if vector.shape != query.shape or norm == 0.0:
                continue
            scores[iri] = float(np.dot(vector, query) / (norm * query_norm))
        return scores

    async def _fetch_in(
        self, conn: "aiosqlite.Connection", template: str, values: Sequence[str], extra: Sequence[Any] = ()
    ) -> list[Any]:
        """Run ``template`` (containing one ``{marks}`` placeholder) over ``values`` in SQLite-safe chunks."""
        rows: list[Any] = []
        for start in range(0, len(values), self._CHUNK):
            chunk = list(values[start : start + self._CHUNK])
            cursor = await conn.execute(template.format(marks=",".join("?" * len(chunk))), (*extra, *chunk))
            rows.extend(await cursor.fetchall())
            await cursor.close()
        return rows

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
        """Closure of ``iris`` at the snapshot version; it always contains the input IRIs."""
        version = await self._version_for(ontology_id, as_of)
        if not iris:
            return set()
        conn = await self._connection(ontology_id, version)
        depth_sql = "" if max_depth is None else " AND depth <= ?"
        depth_args: tuple[Any, ...] = () if max_depth is None else (max_depth,)
        found: set[str] = set()
        if direction in ("down", "both"):
            rows = await self._fetch_in(
                conn,
                f"SELECT descendant_iri FROM closure WHERE family = ?{depth_sql} AND ancestor_iri IN ({{marks}})",
                list(iris),
                (family, *depth_args),
            )
            found.update(row[0] for row in rows)
        if direction in ("up", "both"):
            rows = await self._fetch_in(
                conn,
                f"SELECT ancestor_iri FROM closure WHERE family = ?{depth_sql} AND descendant_iri IN ({{marks}})",
                list(iris),
                (family, *depth_args),
            )
            found.update(row[0] for row in rows)
        if not include_deprecated and found:
            rows = await self._fetch_in(
                conn, "SELECT iri FROM concept WHERE deprecated = 1 AND iri IN ({marks})", sorted(found)
            )
            found.difference_update(row[0] for row in rows)
        return found | set(iris)

    async def neighbors(
        self, ontology_id: str, iri: str, predicate: str | None = None, *, as_of: int | None = None
    ) -> list[tuple[str, str]]:
        """Outbound asserted and inferred ``(predicate, object_iri)`` pairs."""
        version = await self._version_for(ontology_id, as_of)
        conn = await self._connection(ontology_id, version)
        query = "SELECT predicate, object_iri FROM relation WHERE subject_iri = ?"
        args: list[Any] = [iri]
        if predicate is not None:
            query += " AND predicate = ?"
            args.append(predicate)
        cursor = await conn.execute(query + " ORDER BY predicate, object_iri", args)
        rows = await cursor.fetchall()
        await cursor.close()
        return [(row[0], row[1]) for row in rows]

    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
        """Map each IRI to its live replacement (cycle-safe, at most 16 hops); unchanged IRIs are omitted."""
        version = await self._version_for(ontology_id, None)
        if not iris:
            return {}
        conn = await self._connection(ontology_id, version)
        cursor = await conn.execute("SELECT iri, replaced_by FROM concept WHERE replaced_by IS NOT NULL")
        replacements = {row[0]: row[1] for row in await cursor.fetchall()}
        await cursor.close()
        result: dict[str, str] = {}
        for iri in iris:
            current, seen = iri, {iri}
            for _ in range(self._MAX_HOPS):
                following = replacements.get(current)
                if following is None or following in seen:
                    break
                current = following
                seen.add(current)
            if current != iri:
                result[iri] = current
        return result

    async def export(
        self, ontology_id: str, fmt: Literal["turtle", "jsonld"] = "turtle", *, as_of: int | None = None
    ) -> bytes:
        """Serialise the asserted graph (inferred relations are not exported) at the snapshot version."""
        from parrot.knowledge.ontology.vocabulary.turtle import serialize

        version = await self._version_for(ontology_id, as_of)
        conn = await self._connection(ontology_id, version)

        async def rows(query: str) -> list[Any]:
            cursor = await conn.execute(query)
            data = await cursor.fetchall()
            await cursor.close()
            return list(data)

        base_iri = (await rows("SELECT value FROM meta WHERE key = 'base_iri'"))[0][0]
        content = OntologyContent(
            base_iri=base_iri,
            concepts=[
                ParsedConcept(
                    iri=r[0],
                    kind=r[1],
                    pref_label=r[2],
                    definition=r[3],
                    deprecated=bool(r[4]),
                    replaced_by=r[5],
                    extra=json.loads(r[6]),
                )
                for r in await rows(
                    "SELECT iri, kind, pref_label, definition, deprecated, replaced_by, extra FROM concept ORDER BY iri"
                )
            ],
            labels=[
                ParsedLabel(iri=r[0], lang=r[1], kind=r[2], text=r[3])
                for r in await rows("SELECT iri, lang, kind, text FROM label ORDER BY iri, lang, kind, text")
            ],
            relations=[
                ParsedRelation(subject_iri=r[0], predicate=r[1], object_iri=r[2], inferred=False)
                for r in await rows(
                    "SELECT subject_iri, predicate, object_iri FROM relation WHERE inferred = 0 "
                    "ORDER BY subject_iri, predicate, object_iri"
                )
            ],
            statements=[
                ParsedStatement(subject_iri=r[0], predicate=r[1], object=json.loads(r[2]))
                for r in await rows(
                    "SELECT subject_iri, predicate, object FROM statement ORDER BY subject_iri, predicate, object_hash"
                )
            ],
        )
        return serialize(content, fmt)

    async def close(self) -> None:
        """Close open connections, and the source only when this store created it."""
        for connection in self._connections.values():
            await connection.close()
        self._connections.clear()
        if self._owns_source and self._source is not None:
            closer = getattr(self._source, "close", None)
            if closer is not None:
                await closer()


def _create_snapshot(*, snapshot_dir: Any = None, source: Any = None, **_: Any) -> OntologyStore:
    """Registry factory for the 'snapshot' backend."""
    created_source = False
    if source is None:
        url = resolve_ontology_settings().snapshot_url
        if url:
            source, created_source = HttpSnapshotSource(str(url)), True
    store = SnapshotOntologyStore(snapshot_dir, source=source)
    store._owns_source = created_source
    return store
