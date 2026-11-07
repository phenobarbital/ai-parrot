"""Read-only SQLite snapshots of one ontology version (FEAT-824)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from parrot.knowledge.ontology.vocabulary.contracts import VersionContent

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
            f"Snapshot {final} already exists with checksum {existing_checksum!r}, "
            f"not {content.checksum!r}"
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
            label_rows = [
                (label.iri, label.lang, label.kind, label.text) for label in content.content.labels
            ]
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
                [
                    (row.family, row.ancestor_iri, row.descendant_iri, row.depth)
                    for row in content.closure
                ],
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
