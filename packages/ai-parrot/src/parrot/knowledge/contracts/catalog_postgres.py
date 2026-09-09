"""Postgres implementation of the contract catalog (FEAT-539 M2).

The single production :class:`~parrot.knowledge.contracts.catalog.
ContractCatalogStore` backend. Postgres is authoritative for cards,
obligations, verification, versions, aliases, judgements, answer audit and
source cursors.

Tenancy is a **separate configured schema per tenant**: the schema name is
configuration, validated as a plain SQL identifier before it can reach a
statement, and every user- or model-supplied value is a bound parameter.

``asyncpg`` is imported lazily so that importing the contracts package does
not require the ``graphindex-postgres`` extra to be installed.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from .catalog import (
    CatalogConflictError,
    ContractCatalogStore,
    DuplicateSourceError,
    ExpiringKey,
    ObligationWindow,
    PartyMergeResult,
    SearchHit,
    UnknownContractError,
    UpsertResult,
    VerificationQueueEntry,
)
from .models import (
    AnswerRecord,
    ContractCard,
    ContractRelation,
    ContractStatus,
    ContractVersion,
    Obligation,
    Party,
    PartyAlias,
    PublicationRecord,
    PublicationTarget,
    RelationJudgement,
    SourceItem,
    VerificationState,
    card_snapshot_payload,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg

__all__ = ("PostgresContractCatalog", "CONTRACTS_DDL", "LOW_CONFIDENCE_THRESHOLD")

logger = logging.getLogger(__name__)

#: Unverified fields below this confidence go to the verification queue.
LOW_CONFIDENCE_THRESHOLD = 0.6

#: Idempotent DDL for one tenant schema. ``{schema}`` is a validated
#: identifier; no other interpolation happens anywhere in this module.
CONTRACTS_DDL: tuple[str, ...] = (
    "CREATE SCHEMA IF NOT EXISTS {schema}",
    """
    CREATE TABLE IF NOT EXISTS {schema}.contracts (
        contract_id        text PRIMARY KEY,
        card_json          jsonb NOT NULL,
        title              text NOT NULL DEFAULT '',
        summary            text NOT NULL DEFAULT '',
        toc_digest         text NOT NULL DEFAULT '',
        topics             text NOT NULL DEFAULT '',
        contract_type      text NOT NULL DEFAULT 'other',
        status             text NOT NULL DEFAULT 'unknown',
        verification       text NOT NULL DEFAULT 'extracted',
        effective_date     date,
        expiration_date    date,
        notice_deadline    date,
        next_renewal_date  date,
        owner_employee_id  text,
        department         text,
        source_uri         text NOT NULL,
        source_sha256      text NOT NULL DEFAULT '',
        active             boolean NOT NULL DEFAULT true,
        revision           integer NOT NULL DEFAULT 1,
        added_at           timestamptz,
        updated_at         timestamptz,
        search_vector      tsvector GENERATED ALWAYS AS (
            to_tsvector(
                'english',
                coalesce(title, '') || ' ' || coalesce(summary, '') || ' '
                || coalesce(toc_digest, '') || ' ' || coalesce(topics, '')
            )
        ) STORED
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS contracts_source_uri_key "
    "ON {schema}.contracts (source_uri)",
    "CREATE UNIQUE INDEX IF NOT EXISTS contracts_source_sha_key "
    "ON {schema}.contracts (source_sha256) WHERE source_sha256 <> ''",
    "CREATE INDEX IF NOT EXISTS contracts_search_idx "
    "ON {schema}.contracts USING GIN (search_vector)",
    "CREATE INDEX IF NOT EXISTS contracts_status_idx ON {schema}.contracts (status)",
    "CREATE INDEX IF NOT EXISTS contracts_verification_idx "
    "ON {schema}.contracts (verification)",
    "CREATE INDEX IF NOT EXISTS contracts_expiration_idx "
    "ON {schema}.contracts (expiration_date)",
    "CREATE INDEX IF NOT EXISTS contracts_notice_idx "
    "ON {schema}.contracts (notice_deadline)",
    "CREATE INDEX IF NOT EXISTS contracts_owner_idx "
    "ON {schema}.contracts (owner_employee_id)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.obligations (
        obligation_id text PRIMARY KEY,
        contract_id   text NOT NULL REFERENCES {schema}.contracts(contract_id)
                          ON DELETE CASCADE,
        kind          text NOT NULL DEFAULT 'other',
        obligor       text NOT NULL DEFAULT 'counterparty',
        standard_id   text,
        due_date      date,
        recurrence    text,
        verification  text NOT NULL DEFAULT 'extracted',
        text          text NOT NULL,
        node_id       text NOT NULL,
        page          integer,
        provenance    jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        active        boolean NOT NULL DEFAULT true
    )
    """,
    "CREATE INDEX IF NOT EXISTS obligations_contract_idx "
    "ON {schema}.obligations (contract_id)",
    "CREATE INDEX IF NOT EXISTS obligations_kind_idx ON {schema}.obligations (kind)",
    "CREATE INDEX IF NOT EXISTS obligations_standard_idx "
    "ON {schema}.obligations (standard_id)",
    "CREATE INDEX IF NOT EXISTS obligations_due_idx ON {schema}.obligations (due_date)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.contract_versions (
        contract_id    text NOT NULL,
        version_n      integer NOT NULL,
        revision       integer NOT NULL,
        valid_from     date,
        valid_to       date,
        kind           text NOT NULL DEFAULT 'original',
        amended_by     text,
        source_sha256  text NOT NULL DEFAULT '',
        card_snapshot  jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        evidence_ref   text,
        recorded_at    timestamptz NOT NULL,
        PRIMARY KEY (contract_id, version_n, revision)
    )
    """,
    "CREATE INDEX IF NOT EXISTS contract_versions_recorded_idx "
    "ON {schema}.contract_versions (contract_id, recorded_at)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.party_aliases (
        alias      text PRIMARY KEY,
        party_id   text NOT NULL,
        actor      text,
        created_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS party_aliases_party_idx "
    "ON {schema}.party_aliases (party_id)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.contract_answers (
        answer_id         text PRIMARY KEY,
        asked_at          timestamptz NOT NULL,
        answer_user       text NOT NULL,
        question          text NOT NULL,
        answer_kind       text NOT NULL,
        pattern           text,
        answer            text,
        citations         jsonb NOT NULL DEFAULT '[]'::jsonb,
        authorization_json jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        retired_by        text,
        retired_at        timestamptz,
        retirement_reason text
    )
    """,
    "CREATE INDEX IF NOT EXISTS contract_answers_retired_idx "
    "ON {schema}.contract_answers (retired_at)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.source_delta_tokens (
        source_uri text PRIMARY KEY,
        token      text NOT NULL DEFAULT '',
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.source_items (
        source       text NOT NULL,
        drive_id     text NOT NULL,
        item_id      text NOT NULL,
        current_uri  text NOT NULL DEFAULT '',
        name         text,
        contract_id  text,
        sha256       text,
        deleted      boolean NOT NULL DEFAULT false,
        last_seen_at timestamptz,
        PRIMARY KEY (drive_id, item_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS source_items_source_idx "
    "ON {schema}.source_items (source)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.relation_judgements (
        judgement_id          text PRIMARY KEY,
        source_contract_id    text NOT NULL,
        target_contract_id    text NOT NULL,
        outcome               text NOT NULL,
        source_sha256         text NOT NULL DEFAULT '',
        target_sha256         text NOT NULL DEFAULT '',
        source_obligation_id  text,
        target_obligation_id  text,
        confidence            double precision NOT NULL DEFAULT 0,
        rationale             text NOT NULL DEFAULT '',
        model                 text NOT NULL DEFAULT '',
        origin                text NOT NULL DEFAULT 'llm',
        active                boolean NOT NULL DEFAULT true,
        judged_at             timestamptz NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS relation_judgements_source_idx "
    "ON {schema}.relation_judgements (source_contract_id)",
    "CREATE INDEX IF NOT EXISTS relation_judgements_target_idx "
    "ON {schema}.relation_judgements (target_contract_id)",
    """
    CREATE TABLE IF NOT EXISTS {schema}.contract_relations (
        source_contract_id   text NOT NULL,
        target_contract_id   text NOT NULL,
        kind                 text NOT NULL,
        source_obligation_id text,
        target_obligation_id text,
        confidence           double precision NOT NULL DEFAULT 0,
        rationale            text NOT NULL DEFAULT '',
        origin               text NOT NULL DEFAULT 'llm',
        active               boolean NOT NULL DEFAULT true,
        judged_at            timestamptz,
        PRIMARY KEY (source_contract_id, target_contract_id, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS {schema}.publication_outbox (
        tenant_id   text NOT NULL,
        contract_id text NOT NULL,
        version_n   integer NOT NULL,
        revision    integer NOT NULL,
        target      text NOT NULL,
        run_id      text NOT NULL,
        payload     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        state       text NOT NULL DEFAULT 'pending',
        receipt     text,
        attempts    integer NOT NULL DEFAULT 0,
        last_error  text,
        created_at  timestamptz NOT NULL,
        updated_at  timestamptz,
        PRIMARY KEY (tenant_id, contract_id, version_n, revision, target)
    )
    """,
    "CREATE INDEX IF NOT EXISTS publication_outbox_state_idx "
    "ON {schema}.publication_outbox (target, state, created_at)",
)


def _utcnow() -> datetime:
    """Return the current UTC time (injectable for frozen-clock tests)."""
    return datetime.now(tz=timezone.utc)


class PostgresContractCatalog(ContractCatalogStore):
    """Async Postgres catalog bound to one tenant schema.

    Args:
        dsn: Explicit asyncpg DSN. Required unless ``pool`` is supplied —
            this feature deliberately does not fall back to a default DSN.
        pool: An externally owned pool to reuse. It is never closed by
            :meth:`close`.
        tenant_id: Tenant this catalog is bound to.
        schema: Per-tenant SQL schema; validated as a plain identifier.
        principal: Service principal recorded for unattended writes.
        now: Clock used for recorded timestamps.

    Raises:
        ValueError: When neither ``dsn`` nor ``pool`` is supplied, or the
            schema/tenant configuration is invalid.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        pool: Optional["asyncpg.Pool"] = None,
        tenant_id: str,
        schema: str = "contracts",
        principal: Optional[str] = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        super().__init__(tenant_id=tenant_id, schema=schema, principal=principal)
        if dsn is None and pool is None:
            raise ValueError(
                "PostgresContractCatalog requires an explicit dsn or an injected "
                "asyncpg pool; there is no default DSN fallback."
            )
        self._dsn = dsn
        self._external_pool = pool
        self._pool: Optional["asyncpg.Pool"] = pool
        self._owns_pool = pool is None
        self._now = now
        self._ready = False

    # -- infrastructure ----------------------------------------------------

    async def _ensure_pool(self) -> "asyncpg.Pool":
        """Return the pool, creating an owned one on first use.

        Raises:
            RuntimeError: When ``asyncpg`` is not installed.
        """
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg  # noqa: PLC0415 - optional dependency, imported lazily
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError(
                "The contracts Postgres catalog requires asyncpg. Install it with "
                "`pip install 'ai-parrot[graphindex-postgres]'`."
            ) from exc
        self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=10)
        return self._pool

    async def setup(self) -> None:
        """Create this tenant's schema and tables idempotently."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            for statement in CONTRACTS_DDL:
                await conn.execute(statement.format(schema=self.schema))
        self._ready = True
        logger.info("Contracts catalog ready: schema=%s tenant=%s", self.schema, self.tenant_id)

    async def close(self) -> None:
        """Close the pool only when this instance created it."""
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
        self._pool = self._external_pool
        self._ready = False

    async def _connection(self):
        """Acquire a pooled connection, ensuring the schema exists once."""
        pool = await self._ensure_pool()
        if not self._ready:
            await self.setup()
            pool = await self._ensure_pool()
        return pool.acquire()

    # -- serialization -----------------------------------------------------

    @staticmethod
    def _dumps(payload: Any) -> str:
        """Serialise a payload to JSON text for a ``jsonb`` bind."""
        return json.dumps(payload, default=str, sort_keys=True)

    @staticmethod
    def _loads(value: Any) -> Any:
        """Decode a ``jsonb`` column that asyncpg returned as text."""
        if value is None:
            return None
        if isinstance(value, (str, bytes)):
            return json.loads(value)
        return value

    @classmethod
    def _row_to_card(cls, row: Any) -> ContractCard:
        """Rebuild a :class:`ContractCard` from a ``contracts`` row."""
        payload = cls._loads(row["card_json"])
        payload["revision"] = row["revision"]
        payload["active"] = row["active"]
        return ContractCard.model_validate(payload)

    @classmethod
    def _row_to_obligation(cls, row: Any) -> Obligation:
        """Rebuild an :class:`Obligation` from an ``obligations`` row."""
        return Obligation(
            obligation_id=row["obligation_id"],
            contract_id=row["contract_id"],
            kind=row["kind"],
            obligor=row["obligor"],
            text=row["text"],
            node_id=row["node_id"],
            page=row["page"],
            standard_id=row["standard_id"],
            due_date=row["due_date"],
            recurrence=row["recurrence"],
            verification=row["verification"],
            provenance=cls._loads(row["provenance"]) or {},
            active=row["active"],
        )

    @classmethod
    def _row_to_version(cls, row: Any) -> ContractVersion:
        """Rebuild a :class:`ContractVersion` from a history row."""
        return ContractVersion(
            n=row["version_n"],
            revision=row["revision"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            kind=row["kind"],
            amended_by=row["amended_by"],
            source_sha256=row["source_sha256"],
            card_snapshot=cls._loads(row["card_snapshot"]) or {},
            evidence_ref=row["evidence_ref"],
            recorded_at=row["recorded_at"],
        )

    @classmethod
    def _row_to_publication(cls, row: Any) -> PublicationRecord:
        """Rebuild a :class:`PublicationRecord` from an outbox row."""
        return PublicationRecord(
            tenant_id=row["tenant_id"],
            contract_id=row["contract_id"],
            version_n=row["version_n"],
            revision=row["revision"],
            target=row["target"],
            run_id=row["run_id"],
            payload=cls._loads(row["payload"]) or {},
            state=row["state"],
            receipt=row["receipt"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -- writes ------------------------------------------------------------

    async def upsert(
        self,
        card: ContractCard,
        *,
        expected_revision: Optional[int] = None,
        version: Optional[ContractVersion] = None,
        targets: tuple[PublicationTarget, ...] = ("ontology", "temporal"),
    ) -> UpsertResult:
        """Write card, obligations, history and outbox rows in one transaction."""
        import asyncpg  # noqa: PLC0415 - optional dependency, imported lazily

        now = self._now()
        async with await self._connection() as conn:
            async with conn.transaction():
                current = await conn.fetchrow(
                    f"SELECT revision FROM {self.schema}.contracts "
                    "WHERE contract_id = $1 FOR UPDATE",
                    card.contract_id,
                )
                actual = current["revision"] if current else None
                if expected_revision is not None and actual != expected_revision:
                    raise CatalogConflictError(card.contract_id, expected_revision, actual)

                clash = await conn.fetchrow(
                    f"""
                    SELECT contract_id, source_sha256, source_uri
                    FROM {self.schema}.contracts
                    WHERE contract_id <> $1
                      AND (source_uri = $2 OR (source_sha256 = $3 AND $3 <> ''))
                    LIMIT 1
                    """,
                    card.contract_id,
                    card.source_uri,
                    card.source_sha256,
                )
                if clash is not None:
                    raise DuplicateSourceError(
                        clash["contract_id"],
                        source_sha256=card.source_sha256
                        if clash["source_sha256"] == card.source_sha256
                        else "",
                        source_uri=card.source_uri
                        if clash["source_uri"] == card.source_uri
                        else "",
                    )

                created = current is None
                revision = 1 if created else int(actual) + 1
                previous = await conn.fetchval(
                    f"SELECT max(version_n) FROM {self.schema}.contract_versions "
                    "WHERE contract_id = $1",
                    card.contract_id,
                )
                version_n = version.n if version is not None else int(previous or 1)

                stored = card.model_copy(
                    update={"revision": revision, "updated_at": now, "versions": []}
                )
                recorded = (version or ContractVersion(n=version_n)).model_copy(
                    update={
                        "revision": revision,
                        "recorded_at": now,
                        "source_sha256": (version.source_sha256 if version else "")
                        or card.source_sha256,
                        "card_snapshot": (version.card_snapshot if version else {})
                        or card_snapshot_payload(stored),
                    }
                )

                try:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.schema}.contracts (
                            contract_id, card_json, title, summary, toc_digest, topics,
                            contract_type, status, verification, effective_date,
                            expiration_date, notice_deadline, next_renewal_date,
                            owner_employee_id, department, source_uri, source_sha256,
                            active, revision, added_at, updated_at
                        ) VALUES (
                            $1, $2::jsonb, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13, $14, $15, $16, $17, $18, $19, $20, $21
                        )
                        ON CONFLICT (contract_id) DO UPDATE SET
                            card_json = EXCLUDED.card_json,
                            title = EXCLUDED.title,
                            summary = EXCLUDED.summary,
                            toc_digest = EXCLUDED.toc_digest,
                            topics = EXCLUDED.topics,
                            contract_type = EXCLUDED.contract_type,
                            status = EXCLUDED.status,
                            verification = EXCLUDED.verification,
                            effective_date = EXCLUDED.effective_date,
                            expiration_date = EXCLUDED.expiration_date,
                            notice_deadline = EXCLUDED.notice_deadline,
                            next_renewal_date = EXCLUDED.next_renewal_date,
                            owner_employee_id = EXCLUDED.owner_employee_id,
                            department = EXCLUDED.department,
                            source_uri = EXCLUDED.source_uri,
                            source_sha256 = EXCLUDED.source_sha256,
                            active = EXCLUDED.active,
                            revision = EXCLUDED.revision,
                            updated_at = EXCLUDED.updated_at
                        """,
                        stored.contract_id,
                        self._dumps(stored.model_dump(mode="json")),
                        stored.title,
                        stored.summary,
                        stored.toc_digest,
                        " ".join(stored.topics),
                        stored.contract_type,
                        stored.status,
                        stored.verification,
                        stored.term.effective_date,
                        stored.term.expiration_date,
                        stored.term.notice_deadline,
                        stored.term.next_renewal_date,
                        stored.owner_employee_id,
                        stored.department,
                        stored.source_uri,
                        stored.source_sha256,
                        stored.active,
                        revision,
                        stored.added_at or now,
                        now,
                    )
                except asyncpg.UniqueViolationError as exc:  # duplicate race
                    raise DuplicateSourceError(
                        card.contract_id,
                        source_sha256=card.source_sha256,
                        source_uri=card.source_uri,
                    ) from exc

                await conn.execute(
                    f"DELETE FROM {self.schema}.obligations WHERE contract_id = $1",
                    card.contract_id,
                )
                for obligation in card.obligations:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.schema}.obligations (
                            obligation_id, contract_id, kind, obligor, standard_id,
                            due_date, recurrence, verification, text, node_id, page,
                            provenance, active
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13
                        )
                        """,
                        obligation.obligation_id,
                        obligation.contract_id,
                        obligation.kind,
                        obligation.obligor,
                        obligation.standard_id,
                        obligation.due_date,
                        obligation.recurrence,
                        obligation.verification,
                        obligation.text,
                        obligation.node_id,
                        obligation.page,
                        self._dumps(obligation.provenance.model_dump(mode="json")),
                        obligation.active,
                    )

                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.contract_versions (
                        contract_id, version_n, revision, valid_from, valid_to, kind,
                        amended_by, source_sha256, card_snapshot, evidence_ref, recorded_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)
                    ON CONFLICT (contract_id, version_n, revision) DO NOTHING
                    """,
                    card.contract_id,
                    recorded.n,
                    recorded.revision,
                    recorded.valid_from,
                    recorded.valid_to,
                    recorded.kind,
                    recorded.amended_by,
                    recorded.source_sha256,
                    self._dumps(recorded.card_snapshot),
                    recorded.evidence_ref,
                    now,
                )

                queued: list[PublicationRecord] = []
                for target in targets:
                    queued.append(
                        await self._enqueue(
                            conn,
                            PublicationRecord(
                                tenant_id=self.tenant_id,
                                contract_id=card.contract_id,
                                version_n=recorded.n,
                                revision=revision,
                                target=target,
                                run_id=f"{card.contract_id}:{recorded.n}:{revision}",
                                payload={
                                    "contract_id": card.contract_id,
                                    "version_n": recorded.n,
                                    "revision": revision,
                                },
                                created_at=now,
                            ),
                        )
                    )

        return UpsertResult(
            contract_id=card.contract_id,
            revision=revision,
            created=created,
            version_n=recorded.n,
            queued=queued,
        )

    async def remove(self, contract_id: str) -> None:
        """Retract a contract, keeping every historical row."""
        now = self._now()
        async with await self._connection() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT revision FROM {self.schema}.contracts "
                    "WHERE contract_id = $1 FOR UPDATE",
                    contract_id,
                )
                if row is None:
                    raise UnknownContractError(contract_id)
                await conn.execute(
                    f"""
                    UPDATE {self.schema}.contracts
                    SET active = false,
                        card_json = jsonb_set(card_json, '{{active}}', 'false'::jsonb),
                        updated_at = $2
                    WHERE contract_id = $1
                    """,
                    contract_id,
                    now,
                )
                await conn.execute(
                    f"UPDATE {self.schema}.obligations SET active = false "
                    "WHERE contract_id = $1",
                    contract_id,
                )
                version_n = int(
                    await conn.fetchval(
                        f"SELECT max(version_n) FROM {self.schema}.contract_versions "
                        "WHERE contract_id = $1",
                        contract_id,
                    )
                    or 1
                )
                for target in ("ontology", "temporal"):
                    await self._enqueue(
                        conn,
                        PublicationRecord(
                            tenant_id=self.tenant_id,
                            contract_id=contract_id,
                            version_n=version_n,
                            revision=int(row["revision"]),
                            target=target,  # type: ignore[arg-type]
                            run_id=f"{contract_id}:retract:{row['revision']}",
                            payload={"contract_id": contract_id, "tombstone": True},
                            created_at=now,
                        ),
                    )

    # -- point reads -------------------------------------------------------

    async def get(self, contract_id: str) -> Optional[ContractCard]:
        """Return one card by id."""
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.contracts WHERE contract_id = $1",
                contract_id,
            )
        return self._row_to_card(row) if row else None

    async def find_by_sha(self, sha256: str) -> Optional[ContractCard]:
        """Return the card whose current source hashes to ``sha256``."""
        if not sha256:
            return None
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.contracts WHERE source_sha256 = $1",
                sha256,
            )
        return self._row_to_card(row) if row else None

    async def find_by_source_uri(self, uri: str) -> Optional[ContractCard]:
        """Return the card whose canonical source URI is ``uri``."""
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.contracts WHERE source_uri = $1",
                uri,
            )
        return self._row_to_card(row) if row else None

    async def taken_slugs(self) -> set[str]:
        """Return every slug already used (SQL uniqueness is the real guard)."""
        async with await self._connection() as conn:
            rows = await conn.fetch(f"SELECT contract_id FROM {self.schema}.contracts")
        return {row["contract_id"] for row in rows}

    async def obligations_for(self, contract_id: str) -> list[Obligation]:
        """Return one contract's obligation set in stable id order."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.schema}.obligations "
                "WHERE contract_id = $1 ORDER BY obligation_id",
                contract_id,
            )
        return [self._row_to_obligation(row) for row in rows]

    async def versions(self, contract_id: str) -> list[ContractVersion]:
        """Return the retained version/revision history, oldest first."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.schema}.contract_versions "
                "WHERE contract_id = $1 ORDER BY version_n, revision",
                contract_id,
            )
        return [self._row_to_version(row) for row in rows]

    # -- outbox primitives (shared by writes) ------------------------------

    async def _enqueue(self, conn: Any, record: PublicationRecord) -> PublicationRecord:
        """Insert one outbox row idempotently inside the caller's transaction."""
        row = await conn.fetchrow(
            f"""
            INSERT INTO {self.schema}.publication_outbox (
                tenant_id, contract_id, version_n, revision, target, run_id,
                payload, state, receipt, attempts, last_error, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (tenant_id, contract_id, version_n, revision, target)
            DO UPDATE SET run_id = {self.schema}.publication_outbox.run_id
            RETURNING *
            """,
            record.tenant_id,
            record.contract_id,
            record.version_n,
            record.revision,
            record.target,
            record.run_id,
            self._dumps(record.payload),
            record.state,
            record.receipt,
            record.attempts,
            record.last_error,
            record.created_at or self._now(),
            record.updated_at,
        )
        return self._row_to_publication(row)

    async def enqueue_publication(self, record: PublicationRecord) -> PublicationRecord:
        """Queue one publication row idempotently on its durable key."""
        async with await self._connection() as conn:
            return await self._enqueue(conn, record)

    # ------------------------------------------------------------------
    # Query surface — implemented by TASK-3028 (catalog search/windows)
    # ------------------------------------------------------------------

    async def list_cards(
        self,
        *,
        status: Optional[ContractStatus] = None,
        verification: Optional[VerificationState] = None,
        active_only: bool = True,
    ) -> list[ContractCard]:
        """List cards filtered by status/verification (TASK-3028)."""
        raise NotImplementedError("catalog query surface is implemented by TASK-3028")

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """English full-text search (TASK-3028)."""
        raise NotImplementedError("catalog query surface is implemented by TASK-3028")

    async def expiring(
        self,
        *,
        until: date,
        key: ExpiringKey = "notice_deadline",
        since: Optional[date] = None,
    ) -> list[ContractCard]:
        """Inclusive expiry/notice window (TASK-3028)."""
        raise NotImplementedError("catalog query surface is implemented by TASK-3028")

    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        """Prioritised verification queue (TASK-3028)."""
        raise NotImplementedError("catalog query surface is implemented by TASK-3028")

    async def obligations_due(self, window: ObligationWindow) -> list[Obligation]:
        """Typed obligation due-date window (TASK-3028)."""
        raise NotImplementedError("catalog query surface is implemented by TASK-3028")

    # ------------------------------------------------------------------
    # Administration surface — implemented by TASK-3029
    # ------------------------------------------------------------------

    async def merge_parties(
        self,
        keep_party_id: str,
        merge_party_id: str,
        *,
        user: str,
    ) -> PartyMergeResult:
        """Transactional party merge (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def party_aliases(self, party_id: str) -> list[PartyAlias]:
        """Aliases of one canonical party (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def all_party_aliases(self) -> dict[str, list[str]]:
        """Catalog-wide party aliases (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def add_party_alias(self, alias: str, party_id: str, *, user: str) -> PartyAlias:
        """Map an alias onto a canonical party (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def resolve_party(self, alias: str) -> Optional[str]:
        """Resolve an alias to a canonical party (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def list_parties(self) -> list[Party]:
        """Distinct parties across active cards (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audited answer (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        """Return one audited answer (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def retire_answer(self, answer_id: str, *, user: str, reason: str) -> AnswerRecord:
        """Retire an answer and suppress its evidence (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def retired_citations(self) -> set[tuple[str, str]]:
        """Suppressed contract/node pairs (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def get_delta_token(self, source_uri: str) -> Optional[str]:
        """Committed delta cursor (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def set_delta_token(self, source_uri: str, token: str) -> None:
        """Commit a delta cursor (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def upsert_source_item(self, item: SourceItem) -> None:
        """Record remote item identity (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def get_source_item(self, drive_id: str, item_id: str) -> Optional[SourceItem]:
        """Return one recorded source item (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def list_source_items(self, source: str) -> list[SourceItem]:
        """Return recorded items of one source (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def record_judgement(self, judgement: RelationJudgement) -> None:
        """Append a relation judgement (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def judgements_for(self, contract_id: str) -> list[RelationJudgement]:
        """Judgement history for a contract (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def replace_relations(
        self,
        contract_id: str,
        relations: list[ContractRelation],
    ) -> None:
        """Replace active judged relations (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def active_relations(
        self,
        contract_id: Optional[str] = None,
    ) -> list[ContractRelation]:
        """Active judged relations (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def invalidate_relations(self, contract_id: str, *, source_sha256: str) -> int:
        """Invalidate relations on source change (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def pending_publications(
        self,
        *,
        target: Optional[PublicationTarget] = None,
        limit: int = 50,
    ) -> list[PublicationRecord]:
        """Queued/failed publication work (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def claim_publication(
        self,
        *,
        target: PublicationTarget,
        limit: int = 1,
    ) -> list[PublicationRecord]:
        """Claim publication work (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def complete_publication(
        self,
        record: PublicationRecord,
        *,
        receipt: str,
    ) -> PublicationRecord:
        """Record a publication receipt (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")

    async def fail_publication(
        self,
        record: PublicationRecord,
        *,
        error: str,
    ) -> PublicationRecord:
        """Record a retryable publication failure (TASK-3029)."""
        raise NotImplementedError("catalog administration is implemented by TASK-3029")
