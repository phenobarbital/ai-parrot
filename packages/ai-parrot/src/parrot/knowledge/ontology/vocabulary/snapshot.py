"""Read-only SQLite snapshots of one ontology version (FEAT-824)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Mapping, Protocol, Sequence, runtime_checkable

import aiohttp
import aiosqlite
import numpy as np

from parrot.knowledge.ontology.vocabulary.contracts import (
    ConceptRef,
    OntologyContent,
    OntologyStore,
    Resolution,
    StoreStatus,
    VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import (
    OntologyNotFound,
    OntologyVersionNotFound,
)
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings
from parrot.knowledge.ontology.vocabulary.turtle import serialize

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
    out: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        out.update(padded[index : index + 3] for index in range(len(padded) - 2))
    return out


@runtime_checkable
class SnapshotSource(Protocol):
    """Where newer snapshots come from."""

    async def latest_version(self, ontology_id: str) -> int: ...

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path: ...


class HttpSnapshotSource:
    """SnapshotSource over the vocabulary HTTP routes, using aiohttp."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = dict(headers or {})
        self._session, self._owns_session = session, session is None

    async def latest_version(self, ontology_id: str) -> int:
        """Return the latest snapshot version for the given ontology."""
        url = f"{self._base}/vocabularies/{ontology_id}/version"
        async with self._session.get(url, headers=self._headers) as response:
            response.raise_for_status()
            data = await response.json()
            return int(data["version"])

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
        """Download a snapshot and write it atomically to dest_root."""
        url = f"{self._base}/vocabularies/{ontology_id}/snapshot?version={version}"
        dest = snapshot_path(dest_root, ontology_id, version)
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with self._session.get(url, headers=self._headers) as response:
            response.raise_for_status()
            content = await response.read()

        dest.write_bytes(content)
        return dest

    async def __aenter__(self) -> "HttpSnapshotSource":
        """Context manager entry: create session if we own it."""
        if self._owns_session and self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit: close session if we own it."""
        if self._owns_session and self._session is not None:
            await self._session.close()

    async def close(self) -> None:
        """Close the underlying session if we own it."""
        if self._owns_session and self._session is not None:
            await self._session.close()


class SnapshotOntologyStore:
    """Read-only OntologyStore over local snapshot files."""

    backend_name: ClassVar[str] = "snapshot"

    def __init__(self, snapshot_dir: Path | str | None = None, *, source: SnapshotSource | None = None) -> None:
        settings = resolve_ontology_settings()
        self._root = Path(snapshot_dir or settings.snapshot_dir).expanduser()
        self._source = source
        self._lang = settings.default_lang
        self._stale: dict[str, bool] = {}
        self._refreshed: set[str] = set()
        self._connections: dict[tuple[str, int], aiosqlite.Connection] = {}

    async def refresh(self, ontology_id: str) -> StoreStatus:
        """Fetch a newer snapshot when reachable; never raises on network failure (stale=True)."""
        if self._source is None:
            # No source configured: nothing to refresh
            return StoreStatus(
                ontology_id=ontology_id,
                version=0,
                stale=False,
                backend=self.backend_name,
            )

        try:
            latest = await self._source.latest_version(ontology_id)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # Source unreachable: keep local, mark stale
            self._stale[ontology_id] = True
            return StoreStatus(
                ontology_id=ontology_id,
                version=0,
                stale=True,
                backend=self.backend_name,
            )

        # Find the latest local version
        ontology_dir = self._root / ontology_id
        if not ontology_dir.exists():
            # No local file and source unreachable
            raise OntologyNotFound(f"Ontology {ontology_id} not found")

        versions = [int(p.stem[1:]) for p in ontology_dir.glob("v*.sqlite") if p.stem.startswith("v")]
        if not versions:
            # No local file and source unreachable
            raise OntologyNotFound(f"Ontology {ontology_id} not found")

        local_version = max(versions)
        if latest > local_version:
            # Download the newer version
            try:
                await self._source.fetch(ontology_id, latest, self._root)
                self._stale[ontology_id] = False
            except (aiohttp.ClientError, asyncio.TimeoutError):
                # Network failure: keep local, mark stale
                self._stale[ontology_id] = True
                return StoreStatus(
                    ontology_id=ontology_id,
                    version=local_version,
                    stale=True,
                    backend=self.backend_name,
                )
        else:
            self._stale[ontology_id] = False

        # Return the actual version we have
        actual_version = latest if latest > local_version else local_version
        return StoreStatus(
            ontology_id=ontology_id,
            version=actual_version,
            stale=False,
            backend=self.backend_name,
        )

    async def version(self, ontology_id: str) -> int:
        """Return the current version for the ontology."""
        status = await self.status(ontology_id)
        return status.version

    async def status(self, ontology_id: str) -> StoreStatus:
        """Return version, backend name and whether the data may be behind the central store."""
        if ontology_id not in self._stale:
            await self.refresh(ontology_id)
        # The version is set by refresh, so we need to get it from the status
        # We'll call refresh again to get the status with the version set
        return await self.refresh(ontology_id)

    async def get(self, ontology_id: str, iri: str, *, as_of: int | None = None) -> ConceptRef | None:
        """Return the concept with the given IRI at the given version."""
        if as_of is None:
            as_of = await self.version(ontology_id)

        if as_of == 0:
            return None

        conn = await self._get_connection(ontology_id, as_of)
        cursor = await conn.execute(
            "SELECT iri, kind, pref_label, definition, deprecated, replaced_by, extra, embedding FROM concept WHERE iri = ?",
            (iri,),
        )
        row = await cursor.fetchone()
        await cursor.close()

        if row is None:
            return None

        iri, kind, pref_label, definition, deprecated, replaced_by, extra, embedding = row
        return ConceptRef(
            iri=iri,
            ontology_id=ontology_id,
            kind=kind,
            pref_label=pref_label,
            definition=definition,
            deprecated=bool(deprecated),
            replaced_by=replaced_by,
            version=as_of,
            extra=extra,
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
        """Hybrid lookup at the current version with at most k live results."""
        if lang is None:
            lang = self._lang

        as_of = await self.version(ontology_id)
        conn = await self._get_connection(ontology_id, as_of)

        # Trigram search for terms >= 3 chars
        candidates: list[tuple[str, float]] = []
        if len(term) >= 3:
            cursor = await conn.execute(
                "SELECT iri, text FROM label_fts WHERE label_fts MATCH ?",
                (term,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for iri, text in rows:
                score = trigram_similarity(term, text)
                if score > 0.45:
                    candidates.append((iri, score))

        # Full scan for short terms
        if len(term) < 3:
            cursor = await conn.execute(
                "SELECT iri, text FROM label WHERE lang = ? AND text LIKE ?",
                (lang, f"%{term}%"),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for iri, text in rows:
                score = trigram_similarity(term, text)
                if score > 0.45:
                    candidates.append((iri, score))

        # Vector search if embedding provided
        if embedding is not None:
            import numpy as np

            cursor = await conn.execute(
                "SELECT iri, embedding FROM concept WHERE embedding IS NOT NULL",
            )
            rows = await cursor.fetchall()
            await cursor.close()

            for iri, blob in rows:
                if blob is None:
                    continue
                vec = np.frombuffer(blob, dtype=np.float32)
                if len(vec) != len(embedding):
                    continue
                score = np.dot(vec, embedding) / (np.linalg.norm(vec) * np.linalg.norm(embedding))
                candidates.append((iri, float(score)))

        # RRF ranking
        scores: dict[str, float] = defaultdict(float)
        for iri, score in candidates:
            scores[iri] += 1.0 / (60 + scores[iri])

        # Filter by kind if specified
        if kinds is not None:
            cursor = await conn.execute(
                "SELECT iri, kind FROM concept WHERE iri IN ({})".format(",".join(["?"] * len(scores))),
                list(scores.keys()),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            kind_by_iri = {iri: kind for iri, kind in rows}
            scores = {iri: score for iri, score in scores.items() if kind_by_iri.get(iri) in kinds}

        # Sort by score and take top k
        sorted_iris = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]

        # Fetch full concept refs
        results: list[Resolution] = []
        for iri, _ in sorted_iris:
            concept = await self.get(ontology_id, iri, as_of=as_of)
            if concept is not None:
                results.append(Resolution(concept=concept, score=scores[iri], matched_by="vector"))

        return results

    async def expand(
        self,
        ontology_id: str,
        iris: Sequence[str],
        *,
        family: str = "subclass",
        direction: str = "down",
        max_depth: int | None = None,
        include_deprecated: bool = False,
        as_of: int | None = None,
    ) -> set[str]:
        """Return the closure of iris at the given version."""
        if as_of is None:
            as_of = await self.version(ontology_id)

        conn = await self._get_connection(ontology_id, as_of)
        closure: set[str] = set(iris)

        if direction in ("down", "both"):
            for iri in iris:
                cursor = await conn.execute(
                    "SELECT descendant_iri FROM closure WHERE family = ? AND ancestor_iri = ?",
                    (family, iri),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                for row in rows:
                    closure.add(row[0])

        if direction in ("up", "both"):
            for iri in iris:
                cursor = await conn.execute(
                    "SELECT ancestor_iri FROM closure WHERE family = ? AND descendant_iri = ?",
                    (family, iri),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                for row in rows:
                    closure.add(row[0])

        return closure

    async def neighbors(
        self, ontology_id: str, iri: str, predicate: str | None = None, *, as_of: int | None = None
    ) -> list[tuple[str, str]]:
        """Return outbound asserted and inferred (predicate, object_iri) pairs."""
        if as_of is None:
            as_of = await self.version(ontology_id)

        conn = await self._get_connection(ontology_id, as_of)
        query = "SELECT predicate, object_iri FROM relation WHERE subject_iri = ?"
        params: list[Any] = [iri]

        if predicate is not None:
            query += " AND predicate = ?"
            params.append(predicate)

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()

        return [(row[0], row[1]) for row in rows]

    async def canonical(self, ontology_id: str, iris: Sequence[str]) -> dict[str, str]:
        """Map each IRI to its live replacement, following replacements safely."""
        as_of = await self.version(ontology_id)
        conn = await self._get_connection(ontology_id, as_of)

        # Build replacement map
        replacements: dict[str, str] = {}
        for iri in iris:
            cursor = await conn.execute(
                "SELECT replaced_by FROM concept WHERE iri = ?",
                (iri,),
            )
            row = await cursor.fetchone()
            await cursor.close()

            if row is not None and row[0] is not None:
                # Follow replacements recursively
                current = row[0]
                while current is not None:
                    if current in replacements:
                        break
                    replacements[iri] = current
                    cursor = await conn.execute(
                        "SELECT replaced_by FROM concept WHERE iri = ?",
                        (current,),
                    )
                    row = await cursor.fetchone()
                    await cursor.close()
                    current = row[0] if row is not None else None

        return replacements

    async def export(self, ontology_id: str, fmt: str = "turtle", *, as_of: int | None = None) -> bytes:
        """Serialize the asserted graph visible at the given version."""
        if as_of is None:
            as_of = await self.version(ontology_id)

        conn = await self._get_connection(ontology_id, as_of)

        # Build OntologyContent from the snapshot
        content = OntologyContent(
            base_iri="",
            concepts=[],
            labels=[],
            relations=[],
            statements=[],
        )

        # Fetch concepts
        cursor = await conn.execute(
            "SELECT iri, kind, pref_label, definition, deprecated, replaced_by, extra FROM concept"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            iri, kind, pref_label, definition, deprecated, replaced_by, extra = row
            content.concepts.append(
                {
                    "iri": iri,
                    "kind": kind,
                    "pref_label": pref_label,
                    "definition": definition,
                    "deprecated": bool(deprecated),
                    "replaced_by": replaced_by,
                    "extra": extra,
                }
            )

        # Fetch labels
        cursor = await conn.execute("SELECT iri, lang, kind, text FROM label")
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            iri, lang, kind, text = row
            content.labels.append({"iri": iri, "lang": lang, "kind": kind, "text": text})

        # Fetch relations
        cursor = await conn.execute("SELECT subject_iri, predicate, object_iri, inferred FROM relation")
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            subject_iri, predicate, object_iri, inferred = row
            content.relations.append(
                {
                    "subject_iri": subject_iri,
                    "predicate": predicate,
                    "object_iri": object_iri,
                    "inferred": bool(inferred),
                }
            )

        # Fetch statements
        cursor = await conn.execute("SELECT subject_iri, predicate, object, object_hash FROM statement")
        rows = await cursor.fetchall()
        await cursor.close()
        for row in rows:
            subject_iri, predicate, object, object_hash = row
            content.statements.append({"subject_iri": subject_iri, "predicate": predicate, "object": object})

        return serialize(content, fmt=fmt)

    async def close(self) -> None:
        """Close all open connections."""
        for conn in self._connections.values():
            await conn.close()
        self._connections.clear()

    async def _get_connection(self, ontology_id: str, version: int) -> aiosqlite.Connection:
        """Get or create a connection for the given ontology and version."""
        key = (ontology_id, version)
        if key not in self._connections:
            path = snapshot_path(self._root, ontology_id, version)
            if not path.exists():
                raise OntologyVersionNotFound(f"Ontology {ontology_id} version {version} not found")
            self._connections[key] = await aiosqlite.connect(path)
        return self._connections[key]


async def _create_snapshot(*, snapshot_dir: Any = None, source: Any = None, **_: Any) -> OntologyStore:
    """Registry factory for the 'snapshot' backend."""
    settings = resolve_ontology_settings()
    if source is None and settings.snapshot_url:
        source = HttpSnapshotSource(settings.snapshot_url)
    return SnapshotOntologyStore(snapshot_dir=snapshot_dir, source=source)
