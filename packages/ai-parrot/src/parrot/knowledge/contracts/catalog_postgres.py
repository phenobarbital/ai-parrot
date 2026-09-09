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
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional

from .catalog import (
    AliasConflictError,
    CatalogConflictError,
    CatalogError,
    ContractCatalogStore,
    DuplicateSourceError,
    ExpiringKey,
    ObligationWindow,
    PartyMergeResult,
    SearchHit,
    UnknownAnswerError,
    UnknownContractError,
    UnknownPartyError,
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

__all__ = (
    "PostgresContractCatalog",
    "CONTRACTS_DDL",
    "LOW_CONFIDENCE_THRESHOLD",
    "MAX_SEARCH_TOP_K",
    "MAX_QUEUE_LIMIT",
)

logger = logging.getLogger(__name__)

_ACTIVE_PUBLICATION_POOLS: set[int] = set()

#: Unverified fields below this confidence go to the verification queue.
LOW_CONFIDENCE_THRESHOLD = 0.6

#: Hard upper bounds so a caller (or a model) cannot request unbounded rows.
MAX_SEARCH_TOP_K = 50
MAX_QUEUE_LIMIT = 500

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
    "CREATE UNIQUE INDEX IF NOT EXISTS contracts_source_uri_key " "ON {schema}.contracts (source_uri)",
    "CREATE UNIQUE INDEX IF NOT EXISTS contracts_source_sha_key "
    "ON {schema}.contracts (source_sha256) WHERE source_sha256 <> ''",
    "CREATE INDEX IF NOT EXISTS contracts_search_idx " "ON {schema}.contracts USING GIN (search_vector)",
    "CREATE INDEX IF NOT EXISTS contracts_status_idx ON {schema}.contracts (status)",
    "CREATE INDEX IF NOT EXISTS contracts_verification_idx " "ON {schema}.contracts (verification)",
    "CREATE INDEX IF NOT EXISTS contracts_expiration_idx " "ON {schema}.contracts (expiration_date)",
    "CREATE INDEX IF NOT EXISTS contracts_notice_idx " "ON {schema}.contracts (notice_deadline)",
    "CREATE INDEX IF NOT EXISTS contracts_owner_idx " "ON {schema}.contracts (owner_employee_id)",
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
    "CREATE INDEX IF NOT EXISTS obligations_contract_idx " "ON {schema}.obligations (contract_id)",
    "CREATE INDEX IF NOT EXISTS obligations_kind_idx ON {schema}.obligations (kind)",
    "CREATE INDEX IF NOT EXISTS obligations_standard_idx " "ON {schema}.obligations (standard_id)",
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
    "CREATE INDEX IF NOT EXISTS party_aliases_party_idx " "ON {schema}.party_aliases (party_id)",
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
    "CREATE INDEX IF NOT EXISTS contract_answers_retired_idx " "ON {schema}.contract_answers (retired_at)",
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
    "CREATE INDEX IF NOT EXISTS source_items_source_idx " "ON {schema}.source_items (source)",
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
    "CREATE INDEX IF NOT EXISTS relation_judgements_source_idx " "ON {schema}.relation_judgements (source_contract_id)",
    "CREATE INDEX IF NOT EXISTS relation_judgements_target_idx " "ON {schema}.relation_judgements (target_contract_id)",
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
        self._publication_connection: ContextVar[Any] = ContextVar("contracts_publication_connection", default=None)

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
        connection = self._publication_connection.get()
        if connection is not None:
            return nullcontext(connection)
        pool = await self._ensure_pool()
        if not self._ready:
            await self.setup()
            pool = await self._ensure_pool()
        return pool.acquire()

    @asynccontextmanager
    async def publication_guard(self, *, target: PublicationTarget) -> AsyncIterator[bool]:
        """Avoid pool starvation even when different tenants share a small pool."""
        pool = await self._ensure_pool()
        pool_id = id(pool)
        # No await between checking and reserving: competing tasks cannot both
        # reserve the same pool, and the reservation holds no database slot.
        if pool_id in _ACTIVE_PUBLICATION_POOLS:
            yield False
            return
        _ACTIVE_PUBLICATION_POOLS.add(pool_id)
        try:
            async with self._guard_database_publication(target=target) as acquired:
                yield acquired
        finally:
            _ACTIVE_PUBLICATION_POOLS.discard(pool_id)

    @asynccontextmanager
    async def _guard_database_publication(self, *, target: PublicationTarget) -> AsyncIterator[bool]:
        """Serialize a tenant's drains and reclaim work abandoned by older workers.

        The catalog transaction spans the drain, while GraphIndex commits on
        its own connection. A crash rolls back claims/receipts; the next drain
        validates the existing GraphIndex run before replaying it. A pool shared
        with GraphIndex needs at least two connections.
        """
        pool = await self._ensure_pool()
        if pool.get_max_size() < 2:
            raise CatalogError("Temporal publication requires a pool with at least two connections")
        async with await self._connection() as conn:
            async with conn.transaction():
                acquired = await conn.fetchval(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
                    f"contracts:{self.schema}:{self.tenant_id}:{target}",
                )
                if not acquired:
                    # Never occupy a pool slot waiting for the worker that needs
                    # that same pool to commit its GraphIndex update.
                    yield False
                    return
                await conn.execute(
                    f"UPDATE {self.schema}.publication_outbox SET state = 'pending' "
                    "WHERE tenant_id = $1 AND target = $2 AND state = 'in_flight'",
                    self.tenant_id,
                    target,
                )
                token = self._publication_connection.set(conn)
                try:
                    yield True
                finally:
                    self._publication_connection.reset(token)

    async def _record_administration(self, conn: Any, card: ContractCard, *, now: datetime) -> ContractVersion:
        """Append an administrative snapshot without changing contractual time."""
        row = await conn.fetchrow(
            f"SELECT * FROM {self.schema}.contract_versions WHERE contract_id = $1 "
            "ORDER BY version_n DESC, revision DESC LIMIT 1",
            card.contract_id,
        )
        previous = self._row_to_version(row) if row else ContractVersion(n=1)
        recorded = previous.model_copy(
            update={
                "revision": card.revision,
                "recorded_at": now,
                "card_snapshot": card_snapshot_payload(card),
            }
        )
        await conn.execute(
            f"INSERT INTO {self.schema}.contract_versions "
            "(contract_id, version_n, revision, valid_from, valid_to, kind, amended_by, "
            "source_sha256, card_snapshot, evidence_ref, recorded_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)",
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
        return recorded

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
                    f"SELECT revision FROM {self.schema}.contracts " "WHERE contract_id = $1 FOR UPDATE",
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
                        source_sha256=card.source_sha256 if clash["source_sha256"] == card.source_sha256 else "",
                        source_uri=card.source_uri if clash["source_uri"] == card.source_uri else "",
                    )

                created = current is None
                revision = 1 if created else int(actual) + 1
                previous_row = await conn.fetchrow(
                    f"SELECT * FROM {self.schema}.contract_versions WHERE contract_id = $1 "
                    "ORDER BY version_n DESC, revision DESC LIMIT 1",
                    card.contract_id,
                )
                basis = version or (
                    self._row_to_version(previous_row)
                    if previous_row
                    else ContractVersion(n=1, valid_from=card.term.effective_date)
                )
                stored = card.model_copy(update={"revision": revision, "updated_at": now, "versions": []})
                recorded = basis.model_copy(
                    update={
                        "revision": revision,
                        "recorded_at": now,
                        "source_sha256": basis.source_sha256 or card.source_sha256,
                        "card_snapshot": (version.card_snapshot if version else {}) or card_snapshot_payload(stored),
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
        """Record a new retraction revision, retaining all historical evidence."""
        now = self._now()
        async with await self._connection() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT * FROM {self.schema}.contracts WHERE contract_id = $1 FOR UPDATE", contract_id
                )
                if row is None:
                    raise UnknownContractError(contract_id)
                card = self._row_to_card(row)
                if not card.active:
                    return
                card = card.model_copy(
                    update={
                        "active": False,
                        "revision": card.revision + 1,
                        "updated_at": now,
                        "obligations": [ob.model_copy(update={"active": False}) for ob in card.obligations],
                    }
                )
                await conn.execute(
                    f"UPDATE {self.schema}.contracts SET active = false, card_json = $2::jsonb, "
                    "revision = $3, updated_at = $4 WHERE contract_id = $1",
                    contract_id,
                    self._dumps(card.model_dump(mode="json")),
                    card.revision,
                    now,
                )
                await conn.execute(
                    f"UPDATE {self.schema}.obligations SET active = false WHERE contract_id = $1", contract_id
                )
                recorded = await self._record_administration(conn, card, now=now)
                for target in ("ontology", "temporal"):
                    await self._enqueue(
                        conn,
                        PublicationRecord(
                            tenant_id=self.tenant_id,
                            contract_id=contract_id,
                            version_n=recorded.n,
                            revision=card.revision,
                            target=target,
                            run_id=f"{contract_id}:{recorded.n}:{card.revision}",
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
                f"SELECT * FROM {self.schema}.obligations " "WHERE contract_id = $1 ORDER BY obligation_id",
                contract_id,
            )
        return [self._row_to_obligation(row) for row in rows]

    async def versions(self, contract_id: str) -> list[ContractVersion]:
        """Return the retained version/revision history, oldest first."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.schema}.contract_versions " "WHERE contract_id = $1 ORDER BY version_n, revision",
                contract_id,
            )
        return [self._row_to_version(row) for row in rows]

    # -- outbox primitives (shared by writes) ------------------------------

    async def _enqueue(self, conn: Any, record: PublicationRecord) -> PublicationRecord:
        """Insert one outbox row idempotently inside the caller's transaction."""
        if record.tenant_id != self.tenant_id:
            raise CatalogError("publication record belongs to another tenant")
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
    # Query surface
    # ------------------------------------------------------------------

    async def list_cards(
        self,
        *,
        status: Optional[ContractStatus] = None,
        verification: Optional[VerificationState] = None,
        active_only: bool = True,
    ) -> list[ContractCard]:
        """List cards filtered by status and verification state.

        Args:
            status: Restrict to one contract status.
            verification: Restrict to one verification state.
            active_only: Exclude retracted cards.

        Returns:
            Cards ordered deterministically by ``contract_id``.
        """
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.schema}.contracts
                WHERE ($1::boolean IS NOT TRUE OR active)
                  AND ($2::text IS NULL OR status = $2)
                  AND ($3::text IS NULL OR verification = $3)
                ORDER BY contract_id
                """,
                active_only,
                status,
                verification,
            )
        return [self._row_to_card(row) for row in rows]

    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        """Rank cards with English ``plainto_tsquery`` / ``ts_rank``.

        The query is always a bound parameter — injection payloads are
        tokenised as ordinary search terms, never executed.

        Args:
            query: Free-form user query; blank queries match nothing.
            top_k: Bounded number of hits (1..``MAX_SEARCH_TOP_K``).

        Returns:
            Hits ordered by descending rank, then ``contract_id``.
        """
        if not (query or "").strip():
            return []
        bounded = max(1, min(int(top_k), MAX_SEARCH_TOP_K))
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.*, ts_rank(c.search_vector, q.query) AS rank
                FROM {self.schema}.contracts c,
                     plainto_tsquery('english', $1) AS q(query)
                WHERE c.active
                  AND c.search_vector @@ q.query
                ORDER BY rank DESC, c.contract_id
                LIMIT $2
                """,
                query,
                bounded,
            )
        return [SearchHit(card=self._row_to_card(row), rank=float(row["rank"])) for row in rows]

    async def expiring(
        self,
        *,
        until: date,
        key: ExpiringKey = "notice_deadline",
        since: Optional[date] = None,
    ) -> list[ContractCard]:
        """Return active cards inside an inclusive date window.

        ``notice_deadline`` falls back to ``expiration_date`` for cards
        without a notice period; cards whose driving date is null are
        omitted entirely.

        Args:
            until: Inclusive end of the window.
            key: Which date drives the window.
            since: Inclusive start, or ``None`` for everything up to
                ``until``.

        Raises:
            ValueError: When ``key`` is not a supported window key, or the
                window is inverted.
        """
        if key not in ("notice_deadline", "expiration_date"):
            raise ValueError(f"unsupported expiring key {key!r}")
        if since is not None and since > until:
            raise ValueError("expiring window start must not be after its end")
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT c.*
                FROM {self.schema}.contracts c,
                     LATERAL (
                         SELECT CASE
                             WHEN $3 = 'notice_deadline'
                                 THEN COALESCE(c.notice_deadline, c.expiration_date)
                             ELSE c.expiration_date
                         END AS driver
                     ) AS w
                WHERE c.active
                  AND c.status = 'active'
                  AND w.driver IS NOT NULL
                  AND w.driver <= $1
                  AND ($2::date IS NULL OR w.driver >= $2)
                ORDER BY w.driver, c.contract_id
                """,
                until,
                since,
                key,
            )
        return [self._row_to_card(row) for row in rows]

    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        """Return unverified cards in deterministic priority order.

        Missing evidence first, then unresolved low-confidence fields, then
        remaining stale cards; ``contract_id`` breaks every tie.
        """
        bounded = max(1, min(int(limit), MAX_QUEUE_LIMIT))
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                WITH provenance AS (
                    SELECT
                        c.contract_id,
                        array_remove(array_agg(fp.key ORDER BY fp.key) FILTER (
                            WHERE fp.value ->> 'verification' IS DISTINCT FROM 'verified'
                              AND coalesce(btrim(fp.value ->> 'quote'), '') = ''
                        ), NULL) AS missing_fields,
                        array_remove(array_agg(fp.key ORDER BY fp.key) FILTER (
                            WHERE fp.value ->> 'verification' IS DISTINCT FROM 'verified'
                              AND coalesce(btrim(fp.value ->> 'quote'), '') <> ''
                              AND coalesce((fp.value ->> 'confidence')::double precision, 0) < $1
                        ), NULL) AS low_fields
                    FROM {self.schema}.contracts c
                    LEFT JOIN LATERAL jsonb_each(
                        coalesce(c.card_json -> 'field_provenance', '{{}}'::jsonb)
                    ) AS fp ON true
                    WHERE c.active AND c.verification <> 'verified'
                    GROUP BY c.contract_id
                )
                SELECT
                    c.*,
                    coalesce(p.missing_fields, ARRAY[]::text[]) AS missing_fields,
                    coalesce(p.low_fields, ARRAY[]::text[]) AS low_fields,
                    CASE
                        WHEN coalesce(array_length(p.missing_fields, 1), 0) > 0 THEN 0
                        WHEN coalesce(array_length(p.low_fields, 1), 0) > 0 THEN 1
                        ELSE 2
                    END AS priority
                FROM {self.schema}.contracts c
                JOIN provenance p USING (contract_id)
                WHERE coalesce(array_length(p.missing_fields, 1), 0) > 0
                   OR coalesce(array_length(p.low_fields, 1), 0) > 0
                   OR jsonb_array_length(
                          coalesce(c.card_json -> 'stale_fields', '[]'::jsonb)
                      ) > 0
                ORDER BY priority, c.contract_id
                LIMIT $2
                """,
                LOW_CONFIDENCE_THRESHOLD,
                bounded,
            )

        entries: list[VerificationQueueEntry] = []
        for row in rows:
            card = self._row_to_card(row)
            if row["priority"] == 0:
                reason, fields = "missing_evidence", list(row["missing_fields"])
            elif row["priority"] == 1:
                reason, fields = "low_confidence", list(row["low_fields"])
            else:
                reason, fields = "stale", sorted(card.stale_fields)
            entries.append(VerificationQueueEntry(card=card, reason=reason, fields=fields))  # type: ignore[arg-type]
        return entries

    async def obligations_due(self, window: ObligationWindow) -> list[Obligation]:
        """Return obligations inside a typed due-date window.

        Fixed due dates are selected by an inclusive window. Recurrence is
        returned for review when ``include_recurring`` is set; it is never
        interpreted here.
        """
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT o.*
                FROM {self.schema}.obligations o
                JOIN {self.schema}.contracts c USING (contract_id)
                WHERE o.active
                  AND c.active
                  AND ($1::text[] IS NULL OR o.kind = ANY($1))
                  AND ($2::text IS NULL OR o.standard_id = $2)
                  AND (
                        (o.due_date IS NOT NULL
                         AND o.due_date <= $3
                         AND ($4::date IS NULL OR o.due_date >= $4))
                     OR ($5::boolean AND o.due_date IS NULL AND o.recurrence IS NOT NULL)
                  )
                ORDER BY o.due_date NULLS LAST, o.obligation_id
                LIMIT $6
                """,
                list(window.kinds) if window.kinds else None,
                window.standard_id,
                window.until,
                window.since,
                window.include_recurring,
                window.limit,
            )
        return [self._row_to_obligation(row) for row in rows]

    # ------------------------------------------------------------------
    # Administration surface
    # ------------------------------------------------------------------

    async def merge_parties(
        self,
        keep_party_id: str,
        merge_party_id: str,
        *,
        user: str,
    ) -> PartyMergeResult:
        """Merge two party identities inside one transaction.

        Current cards, signatories, alias mappings and queued projections
        move together; historical snapshots keep the name they were signed
        under.

        Raises:
            ValueError: On an invalid self-merge.
            UnknownPartyError: When either identity is unknown.
        """
        if keep_party_id == merge_party_id:
            raise ValueError("cannot merge a party into itself")

        now = self._now()
        updated: list[str] = []
        remapped: list[str] = []
        queued: list[PublicationRecord] = []

        async with await self._connection() as conn:
            async with conn.transaction():
                known = {row["party_id"] for row in await conn.fetch(f"""
                        SELECT DISTINCT p ->> 'party_id' AS party_id
                        FROM {self.schema}.contracts c,
                             jsonb_array_elements(
                                 coalesce(c.card_json -> 'parties', '[]'::jsonb)
                             ) AS p
                        """)}
                known |= {
                    row["party_id"]
                    for row in await conn.fetch(f"SELECT DISTINCT party_id FROM {self.schema}.party_aliases")
                }
                for party_id in (keep_party_id, merge_party_id):
                    if party_id not in known:
                        raise UnknownPartyError(party_id)

                rows = await conn.fetch(
                    f"""
                    SELECT * FROM {self.schema}.contracts
                    WHERE card_json -> 'parties' @> $1::jsonb
                       OR card_json -> 'signatories' @> $1::jsonb
                    ORDER BY contract_id
                    FOR UPDATE
                    """,
                    self._dumps([{"party_id": merge_party_id}]),
                )
                for row in rows:
                    card = self._row_to_card(row)
                    keeps = [party for party in card.parties if party.party_id == keep_party_id]
                    parties: list[Party] = []
                    for party in card.parties:
                        if party.party_id != merge_party_id:
                            parties.append(party)
                        elif not keeps:
                            parties.append(party.model_copy(update={"party_id": keep_party_id}))
                    signatories = [
                        (
                            signatory.model_copy(update={"party_id": keep_party_id})
                            if signatory.party_id == merge_party_id
                            else signatory
                        )
                        for signatory in card.signatories
                    ]
                    revision = card.revision + 1
                    merged = card.model_copy(
                        update={
                            "parties": parties,
                            "signatories": signatories,
                            "revision": revision,
                            "updated_at": now,
                            "versions": [],
                        }
                    )
                    await conn.execute(
                        f"""
                        UPDATE {self.schema}.contracts
                        SET card_json = $2::jsonb, revision = $3, updated_at = $4
                        WHERE contract_id = $1
                        """,
                        card.contract_id,
                        self._dumps(merged.model_dump(mode="json")),
                        revision,
                        now,
                    )
                    updated.append(card.contract_id)
                    recorded = await self._record_administration(conn, merged, now=now)
                    for target in ("ontology", "temporal"):
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
                                    payload={"party_merge": [merge_party_id, keep_party_id], "actor": user},
                                    created_at=now,
                                ),
                            )
                        )

                alias_rows = await conn.fetch(
                    f"""
                    UPDATE {self.schema}.party_aliases
                    SET party_id = $1, actor = $3, created_at = $4
                    WHERE party_id = $2
                    RETURNING alias
                    """,
                    keep_party_id,
                    merge_party_id,
                    user,
                    now,
                )
                remapped = sorted(row["alias"] for row in alias_rows)

        return PartyMergeResult(
            keep_party_id=keep_party_id,
            merged_party_id=merge_party_id,
            cards_updated=updated,
            aliases_remapped=remapped,
            queued=queued,
        )

    async def party_aliases(self, party_id: str) -> list[PartyAlias]:
        """Return every alias mapped onto one canonical party."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM {self.schema}.party_aliases " "WHERE party_id = $1 ORDER BY alias",
                party_id,
            )
        return [
            PartyAlias(
                alias=row["alias"],
                party_id=row["party_id"],
                actor=row["actor"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def all_party_aliases(self) -> dict[str, list[str]]:
        """Return catalog-wide aliases keyed by canonical ``party_id``."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"SELECT party_id, alias FROM {self.schema}.party_aliases " "ORDER BY party_id, alias"
            )
        mapping: dict[str, list[str]] = {}
        for row in rows:
            mapping.setdefault(row["party_id"], []).append(row["alias"])
        return mapping

    async def add_party_alias(self, alias: str, party_id: str, *, user: str) -> PartyAlias:
        """Map a normalized alias onto a canonical party.

        Raises:
            AliasConflictError: When the alias already maps elsewhere; the
                conflict is surfaced for review instead of being silently
                remapped.
        """
        now = self._now()
        async with await self._connection() as conn:
            async with conn.transaction():
                existing = await conn.fetchval(
                    f"SELECT party_id FROM {self.schema}.party_aliases " "WHERE alias = $1 FOR UPDATE",
                    alias,
                )
                if existing is not None and existing != party_id:
                    raise AliasConflictError(alias, existing, party_id)
                await conn.execute(
                    f"""
                    INSERT INTO {self.schema}.party_aliases (alias, party_id, actor, created_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (alias) DO UPDATE
                        SET actor = EXCLUDED.actor, created_at = EXCLUDED.created_at
                    """,
                    alias,
                    party_id,
                    user,
                    now,
                )
        return PartyAlias(alias=alias, party_id=party_id, actor=user, created_at=now)

    async def resolve_party(self, alias: str) -> Optional[str]:
        """Resolve a normalized alias to its canonical ``party_id``."""
        async with await self._connection() as conn:
            return await conn.fetchval(
                f"SELECT party_id FROM {self.schema}.party_aliases WHERE alias = $1",
                alias,
            )

    async def list_parties(self) -> list[Party]:
        """Return every distinct party across active cards, id-ordered."""
        async with await self._connection() as conn:
            rows = await conn.fetch(f"""
                SELECT DISTINCT ON (p ->> 'party_id')
                       p ->> 'party_id' AS party_id,
                       p ->> 'name'     AS name,
                       p ->> 'role'     AS role,
                       (p ->> 'is_us')::boolean AS is_us
                FROM {self.schema}.contracts c,
                     jsonb_array_elements(
                         coalesce(c.card_json -> 'parties', '[]'::jsonb)
                     ) AS p
                WHERE c.active
                ORDER BY p ->> 'party_id', p ->> 'name'
                """)
        return [
            Party(
                party_id=row["party_id"],
                name=row["name"],
                role=row["role"] or "other",
                is_us=bool(row["is_us"]),
            )
            for row in rows
        ]

    # -- answer audit and retirement --------------------------------------

    async def record_answer(self, record: AnswerRecord) -> None:
        """Persist an audited answer before it is released."""
        async with await self._connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.schema}.contract_answers (
                    answer_id, asked_at, answer_user, question, answer_kind, pattern,
                    answer, citations, authorization_json, retired_by, retired_at,
                    retirement_reason
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12)
                ON CONFLICT (answer_id) DO UPDATE SET
                    answer = EXCLUDED.answer,
                    citations = EXCLUDED.citations,
                    authorization_json = EXCLUDED.authorization_json
                """,
                record.answer_id,
                record.asked_at,
                record.user,
                record.question,
                record.answer_kind,
                record.pattern,
                record.answer,
                self._dumps([c.model_dump(mode="json") for c in record.citations]),
                self._dumps(record.authorization.model_dump(mode="json")),
                record.retired_by,
                record.retired_at,
                record.retirement_reason,
            )

    async def get_answer(self, answer_id: str) -> Optional[AnswerRecord]:
        """Return one audited answer, or ``None`` when unknown."""
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.contract_answers WHERE answer_id = $1",
                answer_id,
            )
        return self._row_to_answer(row) if row else None

    @classmethod
    def _row_to_answer(cls, row: Any) -> AnswerRecord:
        """Rebuild an :class:`AnswerRecord` from an audit row."""
        return AnswerRecord(
            answer_id=row["answer_id"],
            asked_at=row["asked_at"],
            user=row["answer_user"],
            question=row["question"],
            answer_kind=row["answer_kind"],
            pattern=row["pattern"],
            answer=row["answer"],
            citations=cls._loads(row["citations"]) or [],
            authorization=cls._loads(row["authorization_json"]) or {"allowed": False},
            retired_by=row["retired_by"],
            retired_at=row["retired_at"],
            retirement_reason=row["retirement_reason"],
        )

    async def retire_answer(self, answer_id: str, *, user: str, reason: str) -> AnswerRecord:
        """Retire an answer; its cited nodes are suppressed from then on."""
        now = self._now()
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {self.schema}.contract_answers
                SET retired_by = $2, retired_at = $3, retirement_reason = $4
                WHERE answer_id = $1
                RETURNING *
                """,
                answer_id,
                user,
                now,
                reason,
            )
        if row is None:
            raise UnknownAnswerError(answer_id)
        return self._row_to_answer(row)

    async def retired_citations(self) -> set[tuple[str, str]]:
        """Return every suppressed ``(contract_id, node_id)`` pair.

        Suppression is deliberately broad and version-independent: a
        refresh cannot evade it by renumbering an unchanged excerpt.
        """
        async with await self._connection() as conn:
            rows = await conn.fetch(f"""
                SELECT DISTINCT
                    citation ->> 'contract_id' AS contract_id,
                    citation ->> 'node_id'     AS node_id
                FROM {self.schema}.contract_answers a,
                     jsonb_array_elements(coalesce(a.citations, '[]'::jsonb)) AS citation
                WHERE a.retired_at IS NOT NULL
                """)
        return {(row["contract_id"], row["node_id"]) for row in rows}

    # -- source identity and cursors --------------------------------------

    async def get_delta_token(self, source_uri: str) -> Optional[str]:
        """Return the committed opaque delta cursor for a source."""
        async with await self._connection() as conn:
            return await conn.fetchval(
                f"SELECT token FROM {self.schema}.source_delta_tokens WHERE source_uri = $1",
                source_uri,
            )

    async def set_delta_token(self, source_uri: str, token: str) -> None:
        """Commit a delta cursor after the batch is durable."""
        async with await self._connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.schema}.source_delta_tokens (source_uri, token, updated_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (source_uri) DO UPDATE
                    SET token = EXCLUDED.token, updated_at = EXCLUDED.updated_at
                """,
                source_uri,
                token,
                self._now(),
            )

    async def upsert_source_item(self, item: SourceItem) -> None:
        """Record stable remote-item identity for renames and tombstones."""
        async with await self._connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.schema}.source_items (
                    source, drive_id, item_id, current_uri, name, contract_id,
                    sha256, deleted, last_seen_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (drive_id, item_id) DO UPDATE SET
                    source = EXCLUDED.source,
                    current_uri = EXCLUDED.current_uri,
                    name = EXCLUDED.name,
                    contract_id = COALESCE(EXCLUDED.contract_id,
                                           {self.schema}.source_items.contract_id),
                    sha256 = EXCLUDED.sha256,
                    deleted = EXCLUDED.deleted,
                    last_seen_at = EXCLUDED.last_seen_at
                """,
                item.source,
                item.drive_id,
                item.item_id,
                item.current_uri,
                item.name,
                item.contract_id,
                item.sha256,
                item.deleted,
                item.last_seen_at or self._now(),
            )

    async def get_source_item(self, drive_id: str, item_id: str) -> Optional[SourceItem]:
        """Return one recorded source item by its stable identity."""
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.schema}.source_items " "WHERE drive_id = $1 AND item_id = $2",
                drive_id,
                item_id,
            )
        return self._row_to_source_item(row) if row else None

    async def list_source_items(self, source: Optional[str] = None) -> list[SourceItem]:
        """Return recorded source items, for one source or for all of them."""
        async with await self._connection() as conn:
            if source is None:
                rows = await conn.fetch(
                    f"SELECT * FROM {self.schema}.source_items ORDER BY source, drive_id, item_id",
                )
            else:
                rows = await conn.fetch(
                    f"SELECT * FROM {self.schema}.source_items WHERE source = $1 ORDER BY drive_id, item_id",
                    source,
                )
        return [self._row_to_source_item(row) for row in rows]

    @staticmethod
    def _row_to_source_item(row: Any) -> SourceItem:
        """Rebuild a :class:`SourceItem` from a ``source_items`` row."""
        return SourceItem(
            source=row["source"],
            drive_id=row["drive_id"],
            item_id=row["item_id"],
            current_uri=row["current_uri"],
            name=row["name"],
            contract_id=row["contract_id"],
            sha256=row["sha256"],
            deleted=row["deleted"],
            last_seen_at=row["last_seen_at"],
        )

    # -- relation judgements ----------------------------------------------

    async def record_judgement(self, judgement: RelationJudgement) -> None:
        """Append a judgement row, including ``none`` outcomes."""
        async with await self._connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.schema}.relation_judgements (
                    judgement_id, source_contract_id, target_contract_id, outcome,
                    source_sha256, target_sha256, source_obligation_id,
                    target_obligation_id, confidence, rationale, model, origin,
                    active, judged_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (judgement_id) DO NOTHING
                """,
                judgement.judgement_id,
                judgement.source_contract_id,
                judgement.target_contract_id,
                judgement.outcome,
                judgement.source_sha256,
                judgement.target_sha256,
                judgement.source_obligation_id,
                judgement.target_obligation_id,
                judgement.confidence,
                judgement.rationale,
                judgement.model,
                judgement.origin,
                judgement.active,
                judgement.judged_at or self._now(),
            )

    async def judgements_for(self, contract_id: str) -> list[RelationJudgement]:
        """Return judgement history touching one contract, newest last."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.schema}.relation_judgements
                WHERE source_contract_id = $1 OR target_contract_id = $1
                ORDER BY judged_at, judgement_id
                """,
                contract_id,
            )
        return [
            RelationJudgement(
                judgement_id=row["judgement_id"],
                source_contract_id=row["source_contract_id"],
                target_contract_id=row["target_contract_id"],
                outcome=row["outcome"],
                source_sha256=row["source_sha256"],
                target_sha256=row["target_sha256"],
                source_obligation_id=row["source_obligation_id"],
                target_obligation_id=row["target_obligation_id"],
                confidence=row["confidence"],
                rationale=row["rationale"],
                model=row["model"],
                origin=row["origin"],
                active=row["active"],
                judged_at=row["judged_at"],
            )
            for row in rows
        ]

    async def replace_relations(
        self,
        contract_id: str,
        relations: list[ContractRelation],
    ) -> None:
        """Replace the active relations owned by one source contract."""
        async with await self._connection() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"DELETE FROM {self.schema}.contract_relations " "WHERE source_contract_id = $1",
                    contract_id,
                )
                for relation in relations:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.schema}.contract_relations (
                            source_contract_id, target_contract_id, kind,
                            source_obligation_id, target_obligation_id, confidence,
                            rationale, origin, active, judged_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        ON CONFLICT (source_contract_id, target_contract_id, kind)
                        DO UPDATE SET
                            source_obligation_id = EXCLUDED.source_obligation_id,
                            target_obligation_id = EXCLUDED.target_obligation_id,
                            confidence = EXCLUDED.confidence,
                            rationale = EXCLUDED.rationale,
                            origin = EXCLUDED.origin,
                            active = EXCLUDED.active,
                            judged_at = EXCLUDED.judged_at
                        """,
                        relation.source_contract_id,
                        relation.target_contract_id,
                        relation.kind,
                        relation.source_obligation_id,
                        relation.target_obligation_id,
                        relation.confidence,
                        relation.rationale,
                        relation.origin,
                        relation.active,
                        relation.judged_at or self._now(),
                    )

    async def active_relations(
        self,
        contract_id: Optional[str] = None,
    ) -> list[ContractRelation]:
        """Return active judged relations, optionally for one contract."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.schema}.contract_relations
                WHERE active
                  AND ($1::text IS NULL
                       OR source_contract_id = $1
                       OR target_contract_id = $1)
                ORDER BY source_contract_id, target_contract_id, kind
                """,
                contract_id,
            )
        return [
            ContractRelation(
                source_contract_id=row["source_contract_id"],
                target_contract_id=row["target_contract_id"],
                kind=row["kind"],
                source_obligation_id=row["source_obligation_id"],
                target_obligation_id=row["target_obligation_id"],
                confidence=row["confidence"],
                rationale=row["rationale"],
                origin=row["origin"],
                active=row["active"],
                judged_at=row["judged_at"],
            )
            for row in rows
        ]

    async def invalidate_relations(self, contract_id: str, *, source_sha256: str) -> int:
        """Deactivate judgements and relations made against an old hash."""
        async with await self._connection() as conn:
            async with conn.transaction():
                invalidated = await conn.fetch(
                    f"""
                    UPDATE {self.schema}.relation_judgements
                    SET active = false
                    WHERE active
                      AND (
                            (source_contract_id = $1 AND source_sha256 IS DISTINCT FROM $2)
                         OR (target_contract_id = $1 AND target_sha256 IS DISTINCT FROM $2)
                      )
                    RETURNING judgement_id
                    """,
                    contract_id,
                    source_sha256,
                )
                if invalidated:
                    await conn.execute(
                        f"""
                        UPDATE {self.schema}.contract_relations
                        SET active = false
                        WHERE source_contract_id = $1 OR target_contract_id = $1
                        """,
                        contract_id,
                    )
        return len(invalidated)

    # -- durable publication outbox ---------------------------------------

    async def pending_publications(
        self,
        *,
        target: Optional[PublicationTarget] = None,
        limit: int = 50,
    ) -> list[PublicationRecord]:
        """Return queued/failed publication work, oldest first."""
        async with await self._connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.schema}.publication_outbox
                WHERE tenant_id = $3 AND state IN ('pending', 'failed')
                  AND ($1::text IS NULL OR target = $1)
                ORDER BY created_at, contract_id, version_n, revision, target
                LIMIT $2
                """,
                target,
                max(1, int(limit)),
                self.tenant_id,
            )
        return [self._row_to_publication(row) for row in rows]

    async def claim_publication(
        self,
        *,
        target: PublicationTarget,
        limit: int = 1,
    ) -> list[PublicationRecord]:
        """Claim publication work, marking it in flight and counting attempts.

        Uses ``FOR UPDATE SKIP LOCKED`` so publication stays serialized per
        row: a crashed run's claim is recovered on the next pass instead of
        emitting a duplicate logical version.
        """
        async with await self._connection() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    f"""
                    UPDATE {self.schema}.publication_outbox o
                    SET state = 'in_flight', attempts = o.attempts + 1, updated_at = $3
                    FROM (
                        SELECT tenant_id, contract_id, version_n, revision, target
                        FROM {self.schema}.publication_outbox
                        WHERE tenant_id = $4 AND state IN ('pending', 'failed') AND target = $1
                        ORDER BY created_at, contract_id, version_n, revision
                        LIMIT $2
                        FOR UPDATE SKIP LOCKED
                    ) AS claimed
                    WHERE o.tenant_id = claimed.tenant_id
                      AND o.contract_id = claimed.contract_id
                      AND o.version_n = claimed.version_n
                      AND o.revision = claimed.revision
                      AND o.target = claimed.target
                    RETURNING o.*
                    """,
                    target,
                    max(1, int(limit)),
                    self._now(),
                    self.tenant_id,
                )
        return [self._row_to_publication(row) for row in rows]

    async def complete_publication(
        self,
        record: PublicationRecord,
        *,
        receipt: str,
    ) -> PublicationRecord:
        """Record a verified receipt and mark the row published."""
        return await self._set_publication_state(record, state="published", receipt=receipt, error=None)

    async def fail_publication(
        self,
        record: PublicationRecord,
        *,
        error: str,
    ) -> PublicationRecord:
        """Record a retryable failure without losing the queued payload."""
        return await self._set_publication_state(record, state="failed", receipt=None, error=error)

    async def _set_publication_state(
        self,
        record: PublicationRecord,
        *,
        state: str,
        receipt: Optional[str],
        error: Optional[str],
    ) -> PublicationRecord:
        """Update one outbox row's terminal state, keeping its payload."""
        if record.tenant_id != self.tenant_id:
            raise CatalogError("publication record belongs to another tenant")
        async with await self._connection() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE {self.schema}.publication_outbox
                SET state = $6,
                    receipt = COALESCE($7, receipt),
                    last_error = $8,
                    updated_at = $9
                WHERE tenant_id = $1 AND contract_id = $2 AND version_n = $3
                  AND revision = $4 AND target = $5
                RETURNING *
                """,
                record.tenant_id,
                record.contract_id,
                record.version_n,
                record.revision,
                record.target,
                state,
                receipt,
                error,
                self._now(),
            )
        if row is None:
            raise CatalogError(f"unknown publication row {record.key}")
        return self._row_to_publication(row)
