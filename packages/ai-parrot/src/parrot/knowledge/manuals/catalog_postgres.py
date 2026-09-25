"""Postgres implementation of the tenant-bound manual catalog."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from parrot.knowledge.manuals.catalog import (
    AnswerRecord,
    CatalogConflictError,
    CatalogError,
    DuplicateSourceError,
    ManualCatalogStore,
    PublicationRecord,
    SearchHit,
    UpsertResult,
    VerificationQueueEntry,
    queue_entries_for,
)
from parrot.knowledge.manuals.models import ManualCard, ManualVersion, manual_snapshot_payload

if TYPE_CHECKING:
    import asyncpg

__all__ = ("PostgresManualCatalog", "MANUALS_DDL", "MAX_SEARCH_TOP_K", "MAX_QUEUE_LIMIT")

logger = logging.getLogger(__name__)
MAX_SEARCH_TOP_K = 50
MAX_QUEUE_LIMIT = 500

MANUALS_DDL: tuple[str, ...] = (
    "CREATE SCHEMA IF NOT EXISTS {schema}",
    """
    CREATE TABLE IF NOT EXISTS {schema}.manuals (
        manual_id text PRIMARY KEY, card_json jsonb NOT NULL,
        title text NOT NULL DEFAULT '', equipment_text text NOT NULL DEFAULT '',
        procedure_text text NOT NULL DEFAULT '', caption_text text NOT NULL DEFAULT '',
        toc_digest text NOT NULL DEFAULT '', verification text NOT NULL DEFAULT 'extracted',
        source_uri text, source_sha256 text NOT NULL DEFAULT '', active boolean NOT NULL DEFAULT true,
        revision integer NOT NULL DEFAULT 1, added_at timestamptz, updated_at timestamptz,
        search_vector tsvector GENERATED ALWAYS AS (
          to_tsvector('{regconfig}', coalesce(title, '') || ' ' || coalesce(equipment_text, '') || ' '
            || coalesce(procedure_text, '') || ' ' || coalesce(caption_text, '') || ' ' || coalesce(toc_digest, ''))
        ) STORED
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS manuals_source_uri_key ON {schema}.manuals (source_uri) WHERE source_uri IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS manuals_source_sha_key ON {schema}.manuals (source_sha256) WHERE source_sha256 <> ''",
    "CREATE INDEX IF NOT EXISTS manuals_search_idx ON {schema}.manuals USING GIN (search_vector)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.manual_versions (
        manual_id text NOT NULL, n integer NOT NULL, revision text NOT NULL, valid_from date, valid_to date,
        source_sha256 text NOT NULL DEFAULT '', card_snapshot jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        recorded_at timestamptz NOT NULL, evidence_ref text, PRIMARY KEY (manual_id, n)
    )
    """,
    "CREATE INDEX IF NOT EXISTS manual_versions_recorded_idx ON {schema}.manual_versions (manual_id, recorded_at)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.answers (
        answer_id text PRIMARY KEY, asked_at timestamptz NOT NULL, user_id text NOT NULL,
        record_json jsonb NOT NULL DEFAULT '{{}}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.publication_outbox (
        tenant_id text NOT NULL, manual_id text NOT NULL, version_n integer NOT NULL, revision integer NOT NULL,
        target text NOT NULL, run_id text NOT NULL, payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        state text NOT NULL DEFAULT 'pending', receipt text, attempts integer NOT NULL DEFAULT 0, last_error text,
        created_at timestamptz NOT NULL, updated_at timestamptz,
        PRIMARY KEY (tenant_id, manual_id, version_n, revision, target)
    )
    """,
    "CREATE INDEX IF NOT EXISTS publication_outbox_state_idx ON {schema}.publication_outbox (target, state, created_at)",
)


def _utcnow() -> datetime:
    """Return the current UTC time."""
    return datetime.now(tz=timezone.utc)


class PostgresManualCatalog(ManualCatalogStore):
    """Production Postgres backend for one manual-catalog tenant."""

    def __init__(self, dsn: Optional[str] = None, *, pool: Any = None, tenant_id: str, schema: str = "manuals",
                 principal: Optional[str] = None, search_regconfig: str = "english",
                 now: Callable[[], datetime] = _utcnow) -> None:
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal, search_regconfig=search_regconfig)
        if dsn is None and pool is None:
            raise ValueError("PostgresManualCatalog requires an explicit dsn or an injected asyncpg pool; there is no default DSN fallback.")
        self._dsn, self._external_pool, self._pool = dsn, pool, pool
        self._owns_pool, self._now, self._ready = pool is None, now, False

    def ddl(self) -> list[str]:
        """Render identifier-safe tenant DDL."""
        return [statement.format(schema=self.schema, regconfig=self.search_regconfig) for statement in MANUALS_DDL]

    async def _ensure_pool(self) -> "asyncpg.Pool":
        """Return an injected pool or lazily create an owned pool."""
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as exc:
                raise RuntimeError("The manuals Postgres catalog requires asyncpg. Install it with `pip install 'ai-parrot[graphindex-postgres]'`.") from exc
            self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=10)
        return self._pool

    async def setup(self) -> None:
        """Create catalog storage idempotently."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for statement in self.ddl():
                await conn.execute(statement)
        self._ready = True

    async def close(self) -> None:
        """Close only a pool this catalog owns."""
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
        self._pool, self._ready = self._external_pool, False

    async def _connection(self) -> Any:
        """Acquire a configured connection."""
        pool = await self._ensure_pool()
        if not self._ready:
            await self.setup()
        return pool.acquire()

    @staticmethod
    def _dumps(value: Any) -> str:
        return json.dumps(value, default=str, sort_keys=True)

    @staticmethod
    def _loads(value: Any) -> Any:
        return json.loads(value) if isinstance(value, (str, bytes)) else value

    @classmethod
    def _row_to_card(cls, row: Any) -> ManualCard:
        payload = cls._loads(row["card_json"])
        payload["revision"] = str(row["revision"])
        return ManualCard.model_validate(payload)

    @classmethod
    def _row_to_version(cls, row: Any) -> ManualVersion:
        return ManualVersion(n=row["n"], revision=row["revision"], valid_from=row["valid_from"], valid_to=row["valid_to"], source_sha256=row["source_sha256"], card_snapshot=cls._loads(row["card_snapshot"]) or {}, recorded_at=row["recorded_at"], evidence_ref=row["evidence_ref"])

    @classmethod
    def _row_to_publication(cls, row: Any) -> PublicationRecord:
        return PublicationRecord(tenant_id=row["tenant_id"], manual_id=row["manual_id"], version_n=row["version_n"], revision=row["revision"], target=row["target"], run_id=row["run_id"], payload=cls._loads(row["payload"]) or {}, state=row["state"], receipt=row["receipt"], attempts=row["attempts"], last_error=row["last_error"], created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _text(card: ManualCard) -> tuple[str, str, str, str]:
        equipment = " ".join(item.model for item in card.equipment)
        procedures = " ".join(item.title.value for item in card.procedures)
        return (
            " ".join(value for value in (equipment, procedures) if value),
            equipment,
            procedures,
            " ".join(item.caption or "" for item in card.figures),
        )

    async def upsert(self, card: ManualCard, *, expected_revision: Optional[int] = None,
                     version: Optional[ManualVersion] = None) -> UpsertResult:
        """Atomically store a card, immutable version, and publication record."""
        now = self._now()
        async with await self._connection() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(f"SELECT revision FROM {self.schema}.manuals WHERE manual_id = $1 FOR UPDATE", card.manual_id)
                actual = current["revision"] if current else None
                if expected_revision is not None and actual != expected_revision:
                    raise CatalogConflictError(card.manual_id, expected_revision, actual)
                clash = await conn.fetchrow(f"SELECT manual_id, source_sha256, source_uri FROM {self.schema}.manuals WHERE manual_id <> $1 AND (source_uri = $2 OR (source_sha256 = $3 AND $3 <> '')) LIMIT 1", card.manual_id, card.source_uri, card.source_sha256)
                if clash:
                    raise DuplicateSourceError(clash["manual_id"], source_sha256=card.source_sha256 if clash["source_sha256"] == card.source_sha256 else "", source_uri=card.source_uri if clash["source_uri"] == card.source_uri else "")
                revision = 1 if current is None else int(actual) + 1
                title, equipment, procedures, captions = self._text(card)
                stored = card.model_copy(update={"revision": str(revision), "versions": []})
                await conn.execute(f"""INSERT INTO {self.schema}.manuals (manual_id,card_json,title,equipment_text,procedure_text,caption_text,toc_digest,verification,source_uri,source_sha256,active,revision,added_at,updated_at) VALUES ($1,$2::jsonb,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) ON CONFLICT (manual_id) DO UPDATE SET card_json=EXCLUDED.card_json,title=EXCLUDED.title,equipment_text=EXCLUDED.equipment_text,procedure_text=EXCLUDED.procedure_text,caption_text=EXCLUDED.caption_text,toc_digest=EXCLUDED.toc_digest,verification=EXCLUDED.verification,source_uri=EXCLUDED.source_uri,source_sha256=EXCLUDED.source_sha256,revision=EXCLUDED.revision,updated_at=EXCLUDED.updated_at""", card.manual_id, self._dumps(stored.model_dump(mode="json")), title, equipment, procedures, captions, card.toc_digest, card.verification, card.source_uri, card.source_sha256, True, revision, now, now)
                prior = await conn.fetchrow(f"SELECT COALESCE(MAX(n), 0) AS n FROM {self.schema}.manual_versions WHERE manual_id = $1", card.manual_id)
                recorded = version or ManualVersion(n=int(prior["n"]) + 1, revision=str(revision), source_sha256=card.source_sha256, card_snapshot=manual_snapshot_payload(stored), recorded_at=now)
                await conn.execute(f"INSERT INTO {self.schema}.manual_versions (manual_id,n,revision,valid_from,valid_to,source_sha256,card_snapshot,recorded_at,evidence_ref) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)", card.manual_id, recorded.n, recorded.revision, recorded.valid_from, recorded.valid_to, recorded.source_sha256, self._dumps(recorded.card_snapshot), now, recorded.evidence_ref)
                record = PublicationRecord(tenant_id=self.tenant_id, manual_id=card.manual_id, version_n=recorded.n, revision=revision, run_id=uuid.uuid4().hex, payload={"manual_id": card.manual_id})
                await self._enqueue(conn, record)
        return UpsertResult(manual_id=card.manual_id, revision=revision, created=current is None, version_n=recorded.n, queued=[record])

    async def get(self, manual_id: str) -> Optional[ManualCard]:
        async with await self._connection() as conn:
            row = await conn.fetchrow(f"SELECT * FROM {self.schema}.manuals WHERE manual_id = $1", manual_id)
        return self._row_to_card(row) if row else None

    async def find_by_sha(self, sha256: str) -> Optional[ManualCard]:
        async with await self._connection() as conn:
            row = await conn.fetchrow(f"SELECT * FROM {self.schema}.manuals WHERE source_sha256 = $1", sha256)
        return self._row_to_card(row) if row else None

    async def find_by_source_uri(self, uri: str) -> Optional[ManualCard]:
        async with await self._connection() as conn:
            row = await conn.fetchrow(f"SELECT * FROM {self.schema}.manuals WHERE source_uri = $1", uri)
        return self._row_to_card(row) if row else None

    async def list_cards(self, *, verification: Optional[str] = None, active_only: bool = True) -> list[ManualCard]:
        sql = f"SELECT * FROM {self.schema}.manuals WHERE ($1::text IS NULL OR verification = $1) AND ($2::boolean = false OR active = true) ORDER BY manual_id"
        async with await self._connection() as conn:
            rows = await conn.fetch(sql, verification, active_only)
        return [self._row_to_card(row) for row in rows]

    async def versions(self, manual_id: str) -> list[ManualVersion]:
        async with await self._connection() as conn:
            rows = await conn.fetch(f"SELECT * FROM {self.schema}.manual_versions WHERE manual_id = $1 ORDER BY n", manual_id)
        return [self._row_to_version(row) for row in rows]

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        if not query.strip() or top_k <= 0:
            return []
        limit = min(top_k, MAX_SEARCH_TOP_K)
        sql = f"SELECT *, ts_rank(search_vector, plainto_tsquery('{self.search_regconfig}', $1)) AS rank FROM {self.schema}.manuals WHERE active AND search_vector @@ plainto_tsquery('{self.search_regconfig}', $1) ORDER BY rank DESC, manual_id LIMIT $2"
        async with await self._connection() as conn:
            rows = await conn.fetch(sql, query, limit)
        tokens = query.casefold().split()
        hits = []
        for row in rows:
            matched = "manual"
            for name, value in (("procedure", row["procedure_text"]), ("equipment", row["equipment_text"]), ("caption", row["caption_text"])):
                if any(token in (value or "").casefold() for token in tokens):
                    matched = name
                    break
            hits.append(SearchHit(card=self._row_to_card(row), rank=float(row["rank"]), matched=matched))
        return hits

    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        entries = [entry for card in await self.list_cards(active_only=True) for entry in queue_entries_for(card)]
        return sorted(entries, key=lambda item: (item.priority, item.card.manual_id))[:min(max(limit, 0), MAX_QUEUE_LIMIT)]

    async def record_answer(self, record: AnswerRecord) -> None:
        async with await self._connection() as conn:
            await conn.execute(f"INSERT INTO {self.schema}.answers (answer_id,asked_at,user_id,record_json) VALUES ($1,$2,$3,$4::jsonb)", record.answer_id, record.asked_at, record.user, self._dumps(record.model_dump(mode="json")))

    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        async with await self._connection() as conn:
            row = await conn.fetchrow(f"SELECT record_json FROM {self.schema}.answers WHERE answer_id = $1", answer_id)
        return AnswerRecord.model_validate(self._loads(row["record_json"])) if row else None

    async def _enqueue(self, conn: Any, record: PublicationRecord) -> PublicationRecord:
        await conn.execute(f"INSERT INTO {self.schema}.publication_outbox (tenant_id,manual_id,version_n,revision,target,run_id,payload,state,receipt,attempts,last_error,created_at,updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12,$13) ON CONFLICT (tenant_id,manual_id,version_n,revision,target) DO NOTHING", record.tenant_id, record.manual_id, record.version_n, record.revision, record.target, record.run_id, self._dumps(record.payload), record.state, record.receipt, record.attempts, record.last_error, record.created_at or self._now(), record.updated_at)
        return record

    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        if record.tenant_id != self.tenant_id:
            raise CatalogError("publication record belongs to another tenant")
        async with await self._connection() as conn:
            return await self._enqueue(conn, record)

    async def pending_publications(self, *, limit: int = 50) -> list[PublicationRecord]:
        async with await self._connection() as conn:
            rows = await conn.fetch(f"SELECT * FROM {self.schema}.publication_outbox WHERE tenant_id = $1 AND state IN ('pending', 'failed') ORDER BY created_at, manual_id LIMIT $2", self.tenant_id, min(max(limit, 0), MAX_QUEUE_LIMIT))
        return [self._row_to_publication(row) for row in rows]

    async def claim_publication(self, *, limit: int = 1) -> list[PublicationRecord]:
        async with await self._connection() as conn:
            async with conn.transaction():
                rows = await conn.fetch(f"WITH claimed AS (SELECT tenant_id,manual_id,version_n,revision,target FROM {self.schema}.publication_outbox WHERE tenant_id=$1 AND state IN ('pending','failed') ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT $2) UPDATE {self.schema}.publication_outbox o SET state='in_flight', attempts=o.attempts+1, updated_at=$3 FROM claimed WHERE (o.tenant_id,o.manual_id,o.version_n,o.revision,o.target)=(claimed.tenant_id,claimed.manual_id,claimed.version_n,claimed.revision,claimed.target) RETURNING o.*", self.tenant_id, min(max(limit, 0), MAX_QUEUE_LIMIT), self._now())
        return [self._row_to_publication(row) for row in rows]

    async def complete_publication(self, record: PublicationRecord, *, receipt: str) -> PublicationRecord:
        return await self._set_publication_state(record, state="published", receipt=receipt, error=None)

    async def fail_publication(self, record: PublicationRecord, *, error: str) -> PublicationRecord:
        return await self._set_publication_state(record, state="failed", receipt=None, error=error)

    async def _set_publication_state(self, record: PublicationRecord, *, state: str, receipt: Optional[str], error: Optional[str]) -> PublicationRecord:
        if record.tenant_id != self.tenant_id:
            raise CatalogError("publication record belongs to another tenant")
        async with await self._connection() as conn:
            row = await conn.fetchrow(f"UPDATE {self.schema}.publication_outbox SET state=$6, receipt=COALESCE($7,receipt), last_error=$8, updated_at=$9 WHERE tenant_id=$1 AND manual_id=$2 AND version_n=$3 AND revision=$4 AND target=$5 RETURNING *", record.tenant_id, record.manual_id, record.version_n, record.revision, record.target, state, receipt, error, self._now())
        if row is None:
            raise CatalogError(f"unknown publication row {record.key}")
        return self._row_to_publication(row)
