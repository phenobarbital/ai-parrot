"""Scoped user knowledge in independent tables of the configured SQLite database."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.memory.lexical import query_terms

from .models import UserKnowledge, UserKnowledgeCandidate, UserKnowledgeCommand, UserMemoryReceipt

_MAX_QUERY_CHARS = 2_048
_MAX_RESULT_LIMIT = 100
_PROFILE_KIND_ORDER = {"constraint": 0, "preference": 0, "goal": 1, "fact": 1}
_SCHEMA_VERSION = 2
_EPISODE_REF_PREFIXES = ("episode:", "episode/v1/")
EvidenceTenantResolver = Callable[[ChatStorageEvidenceRef], Awaitable[str | None]]
_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_memory_schema (
    component TEXT PRIMARY KEY,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_knowledge (
    knowledge_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    normalized_key TEXT,
    context_key TEXT NOT NULL,
    provenance TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    valid_from TEXT,
    expires_at TEXT,
    searchable_text TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_knowledge_scope_updated
    ON user_knowledge (tenant_id, agent_id, user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_knowledge_active_key
    ON user_knowledge (tenant_id, agent_id, user_id, kind, normalized_key, context_key)
    WHERE status = 'active' AND normalized_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS user_knowledge_events (
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    command_payload TEXT NOT NULL,
    result_status TEXT NOT NULL,
    knowledge_id TEXT,
    revision INTEGER,
    PRIMARY KEY (tenant_id, agent_id, user_id, event_id)
);
CREATE TABLE IF NOT EXISTS user_knowledge_suppressions (
    tenant_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    forgotten_at TEXT NOT NULL,
    blocked_evidence_hashes TEXT NOT NULL,
    PRIMARY KEY (tenant_id, agent_id, user_id, claim_key)
);
CREATE TABLE IF NOT EXISTS user_derivative_forgets (
    tenant_id TEXT NOT NULL,
    source_episode_id TEXT NOT NULL,
    forget_event_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_episode_id)
);
"""


class UserMemoryStore:
    """Manage revisioned cross-session facts without constructing an episodic store."""

    def __init__(self, path: Path, *, evidence_tenant_resolver: EvidenceTenantResolver | None = None) -> None:
        """Retain SQLite configuration; user-only mode acquires only its own resources.

        Args:
            path: Configured SQLite database shared safely with other memory planes.
            evidence_tenant_resolver: Optional metadata-only ChatStorage resolver. It returns the
                stored tenant for a live turn, or ``None`` for missing/tombstoned evidence.
        """
        self.path = Path(path)
        self._evidence_tenant_resolver = evidence_tenant_resolver
        self.logger = logging.getLogger(__name__)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def configure(self) -> None:
        """Open this store's connection and create only its owned tables."""
        async with self._lock:
            await self._configure_locked()

    async def close(self) -> None:
        """Release this store's connection without affecting sibling stores."""
        async with self._lock:
            database = self._db
            self._db = None
            if database is not None:
                close_task = asyncio.create_task(database.close())
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    await asyncio.shield(close_task)
                    raise

    async def __aenter__(self) -> UserMemoryStore:
        """Configure and return the store for an asynchronous context manager."""
        await self.configure()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the store after an asynchronous context manager exits."""
        await self.close()

    async def profile(
        self,
        *,
        scope: MemoryRequestScope,
        query: str = "",
        limit: int = 20,
    ) -> list[UserKnowledge]:
        """Return active, valid scoped knowledge in globally ranked delivery order.

        Args:
            scope: Trusted identity used before any database access.
            query: Optional question used only to rank profile entries.
            limit: Maximum number of facts to return.

        Returns:
            Active valid facts ordered by kind group, overlap, recency, and identifier.

        Raises:
            ValueError: If identity or query arguments are invalid.
        """
        identity = self._require_identity(scope)
        normalized_query = self._validate_query(query)
        self._validate_limit(limit)
        if limit == 0:
            return []

        terms = query_terms(normalized_query)
        async with self._lock:
            database = await self._configure_locked()
            now = datetime.now(timezone.utc).isoformat()
            cursor = await database.execute(
                "SELECT payload, searchable_text FROM user_knowledge "
                "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND status = 'active' "
                "AND (valid_from IS NULL OR valid_from <= ?) AND (expires_at IS NULL OR expires_at > ?)",
                (*identity, now, now),
            )
            winners: list[tuple[UserKnowledge, int]] = []
            try:
                while rows := await cursor.fetchmany(100):
                    for row in rows:
                        knowledge = UserKnowledge.model_validate_json(row[0])
                        searchable_text = str(row[1]).casefold()
                        overlap = sum(term in searchable_text for term in terms)
                        self._insert_profile_winner(winners, knowledge, overlap, limit)
            finally:
                await self._close_cursor(cursor)
        return [knowledge for knowledge, _ in winners]

    async def recall(
        self,
        query: str,
        *,
        scope: MemoryRequestScope,
        limit: int = 5,
    ) -> list[UserKnowledge]:
        """Return any-term matches ranked across all active, valid records of the trusted user.

        Args:
            query: Literal text matched against normalized keys and values.
            scope: Trusted identity used before any database access.
            limit: Maximum number of facts to return.

        Returns:
            Active facts ordered by matched terms, recency, and stable identifier.

        Raises:
            ValueError: If identity or query arguments are invalid.
        """
        identity = self._require_identity(scope)
        normalized_query = self._validate_query(query)
        self._validate_limit(limit)
        if limit == 0:
            return []

        terms = query_terms(normalized_query)
        if not terms:
            return await self._recall_literal(normalized_query, identity, limit)

        async with self._lock:
            database = await self._configure_locked()
            now = datetime.now(timezone.utc).isoformat()
            cursor = await database.execute(
                "SELECT payload, searchable_text FROM user_knowledge "
                "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND status = 'active' "
                "AND (valid_from IS NULL OR valid_from <= ?) AND (expires_at IS NULL OR expires_at > ?)"
                " ORDER BY updated_at DESC, knowledge_id DESC",
                (*identity, now, now),
            )
            winners: list[tuple[UserKnowledge, int]] = []
            try:
                while rows := await cursor.fetchmany(100):
                    for row in rows:
                        knowledge = UserKnowledge.model_validate_json(row[0])
                        searchable_text = str(row[1]).casefold()
                        overlap = sum(term in searchable_text for term in terms)
                        self._insert_recall_winner(winners, knowledge, overlap, limit)
            finally:
                await self._close_cursor(cursor)
        return [knowledge for knowledge, _ in winners]

    async def _recall_literal(
        self,
        normalized_query: str,
        identity: tuple[str, str, str],
        limit: int,
    ) -> list[UserKnowledge]:
        """Preserve blank and short-query literal matching semantics."""
        async with self._lock:
            database = await self._configure_locked()
            now = datetime.now(timezone.utc).isoformat()
            parameters: list[object] = [*identity, now, now]
            predicate = ""
            if normalized_query:
                escaped = self._escape_like(normalized_query.casefold())
                predicate = " AND lower(searchable_text) LIKE ? ESCAPE '\\'"
                parameters.append(f"%{escaped}%")
            parameters.append(limit)
            cursor = await database.execute(
                "SELECT payload FROM user_knowledge "
                "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND status = 'active' "
                "AND (valid_from IS NULL OR valid_from <= ?) AND (expires_at IS NULL OR expires_at > ?)"
                f"{predicate} ORDER BY updated_at DESC, knowledge_id DESC LIMIT ?",
                parameters,
            )
            try:
                rows: list[tuple[str]] = []
                while batch := await cursor.fetchmany(100):
                    rows.extend(batch)
            finally:
                await self._close_cursor(cursor)
        return [UserKnowledge.model_validate_json(row[0]) for row in rows]

    @staticmethod
    async def _close_cursor(cursor: aiosqlite.Cursor) -> None:
        """Close a cursor even when its caller is cancelled during cleanup."""
        close_task = asyncio.create_task(cursor.close())
        try:
            await asyncio.shield(close_task)
        except asyncio.CancelledError:
            await asyncio.shield(close_task)
            raise

    @classmethod
    def _insert_profile_winner(
        cls,
        winners: list[tuple[UserKnowledge, int]],
        knowledge: UserKnowledge,
        overlap: int,
        limit: int,
    ) -> None:
        """Keep a bounded profile winner list in final delivery order."""
        cls._insert_ranked_winner(winners, knowledge, overlap, limit, profile=True)

    @classmethod
    def _insert_recall_winner(
        cls,
        winners: list[tuple[UserKnowledge, int]],
        knowledge: UserKnowledge,
        overlap: int,
        limit: int,
    ) -> None:
        """Keep matching recall winners in final delivery order."""
        if overlap:
            cls._insert_ranked_winner(winners, knowledge, overlap, limit, profile=False)

    @classmethod
    def _insert_ranked_winner(
        cls,
        winners: list[tuple[UserKnowledge, int]],
        knowledge: UserKnowledge,
        overlap: int,
        limit: int,
        *,
        profile: bool,
    ) -> None:
        """Insert one candidate without retaining more than the requested winner count."""
        for index, (current, current_overlap) in enumerate(winners):
            if cls._ranks_before(knowledge, overlap, current, current_overlap, profile=profile):
                if len(winners) == limit:
                    winners.pop()
                winners.insert(index, (knowledge, overlap))
                return
        if len(winners) < limit:
            winners.append((knowledge, overlap))

    @staticmethod
    def _ranks_before(
        candidate: UserKnowledge,
        candidate_overlap: int,
        current: UserKnowledge,
        current_overlap: int,
        *,
        profile: bool,
    ) -> bool:
        """Return whether one record precedes another under the applicable stable order."""
        if profile:
            candidate_group = _PROFILE_KIND_ORDER[candidate.kind]
            current_group = _PROFILE_KIND_ORDER[current.kind]
            if candidate_group != current_group:
                return candidate_group < current_group
        if candidate_overlap != current_overlap:
            return candidate_overlap > current_overlap
        if candidate.updated_at != current.updated_at:
            return candidate.updated_at > current.updated_at
        return candidate.knowledge_id > current.knowledge_id

    async def list(
        self,
        *,
        scope: MemoryRequestScope,
        limit: int = 100,
    ) -> list[UserKnowledge]:
        """List authorized facts with their status and provenance.

        Args:
            scope: Trusted identity used before any database access.
            limit: Maximum number of history rows to return.

        Returns:
            Scoped facts, including pending and superseded history.

        Raises:
            ValueError: If identity or limit arguments are invalid.
        """
        identity = self._require_identity(scope)
        self._validate_limit(limit)
        if limit == 0:
            return []
        async with self._lock:
            database = await self._configure_locked()
            cursor = await database.execute(
                "SELECT payload FROM user_knowledge "
                "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? "
                "ORDER BY updated_at DESC, knowledge_id DESC LIMIT ?",
                (*identity, limit),
            )
            rows = await cursor.fetchall()
        return [UserKnowledge.model_validate_json(row[0]) for row in rows]

    async def upsert(
        self,
        command: UserKnowledgeCommand,
        *,
        scope: MemoryRequestScope,
    ) -> UserMemoryReceipt:
        """Apply an idempotent CAS candidate, keeping inference pending.

        Args:
            command: Validated upsert command and retry-stable event identity.
            scope: Trusted principal; candidate data cannot override it.

        Returns:
            A receipt for the committed mutation, duplicate, or conflict.

        Raises:
            ValueError: If identity is missing or the command is not an upsert.
        """
        identity = self._require_identity(scope)
        if command.operation != "upsert" or command.candidate is None:
            raise ValueError("invalid_parameters: upsert requires an upsert command")
        command_payload = self._command_payload(command)
        evidence_available = await self._evidence_available(command, scope)
        async with self._lock:
            database = await self._configure_locked()
            await database.execute("BEGIN IMMEDIATE")
            try:
                replay = await self._event_replay(database, identity, command.event_id, command_payload)
                if replay is not None:
                    await database.execute("COMMIT")
                    return replay

                if not evidence_available:
                    receipt = UserMemoryReceipt(status="ignored")
                    await self._record_event(database, identity, command, command_payload, receipt)
                    await database.execute("COMMIT")
                    return receipt

                candidate = command.candidate
                suppression = await self._suppression(database, identity, self._candidate_claim_key(candidate))
                if suppression is not None:
                    if candidate.provenance != "explicit" or not self._has_new_evidence(command, suppression):
                        receipt = UserMemoryReceipt(status="ignored")
                        await self._record_event(database, identity, command, command_payload, receipt)
                        await database.execute("COMMIT")
                        return receipt
                    await database.execute(
                        "DELETE FROM user_knowledge_suppressions "
                        "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND claim_key = ?",
                        (*identity, self._candidate_claim_key(candidate)),
                    )
                current = await self._matching_active(database, identity, candidate)
                if candidate.provenance == "inferred" and command.expected_revision is not None:
                    receipt = UserMemoryReceipt(status="conflict")
                    await self._record_event(database, identity, command, command_payload, receipt)
                    await database.execute("COMMIT")
                    return receipt
                if command.expected_revision is not None:
                    current_revision = current.revision if current is not None else 0
                    if current_revision != command.expected_revision:
                        receipt = UserMemoryReceipt(
                            knowledge_id=current.knowledge_id if current is not None else None,
                            revision=current.revision if current is not None else None,
                            status="conflict",
                        )
                        await self._record_event(database, identity, command, command_payload, receipt)
                        await database.execute("COMMIT")
                        return receipt

                now = datetime.now(timezone.utc)
                knowledge = self._make_knowledge(
                    command,
                    scope,
                    revision=current.revision + 1 if current is not None else 0,
                    supersedes_id=current.knowledge_id if current is not None else None,
                    now=now,
                )
                if current is not None:
                    await self._supersede(database, current, now)
                await self._insert_knowledge(database, knowledge)
                receipt = UserMemoryReceipt(
                    knowledge_id=knowledge.knowledge_id,
                    revision=knowledge.revision,
                    status="applied",
                )
                await self._record_event(database, identity, command, command_payload, receipt)
                await database.execute("COMMIT")
                return receipt
            except BaseException:
                await self._rollback(database)
                raise

    async def correct(
        self,
        command: UserKnowledgeCommand,
        *,
        scope: MemoryRequestScope,
    ) -> UserMemoryReceipt:
        """Keep superseded history while making the latest valid explicit correction active.

        Args:
            command: Explicit correction with target ID and expected revision.
            scope: Trusted principal used for the target lookup.

        Returns:
            A receipt for the committed correction, duplicate, conflict, or ignored target.

        Raises:
            ValueError: If identity is missing or the command is not a correction.
        """
        identity = self._require_identity(scope)
        if command.operation != "correct" or command.candidate is None:
            raise ValueError("invalid_parameters: correct requires a correction command")
        command_payload = self._command_payload(command)
        evidence_available = await self._evidence_available(command, scope)
        async with self._lock:
            database = await self._configure_locked()
            await database.execute("BEGIN IMMEDIATE")
            try:
                replay = await self._event_replay(database, identity, command.event_id, command_payload)
                if replay is not None:
                    await database.execute("COMMIT")
                    return replay

                current = await self._knowledge_by_id(database, identity, command.knowledge_id or "")
                if not evidence_available:
                    receipt = UserMemoryReceipt(status="ignored")
                elif current is None:
                    receipt = UserMemoryReceipt(status="ignored")
                elif current.status not in ("active", "pending") or current.revision != command.expected_revision:
                    receipt = UserMemoryReceipt(
                        knowledge_id=current.knowledge_id,
                        revision=current.revision,
                        status="conflict",
                    )
                elif not self._same_claim_context(current, command):
                    receipt = UserMemoryReceipt(
                        knowledge_id=current.knowledge_id,
                        revision=current.revision,
                        status="conflict",
                    )
                else:
                    now = datetime.now(timezone.utc)
                    knowledge = self._make_knowledge(
                        command,
                        scope,
                        revision=current.revision + 1,
                        supersedes_id=current.knowledge_id,
                        now=now,
                    )
                    await self._supersede(database, current, now)
                    await self._insert_knowledge(database, knowledge)
                    receipt = UserMemoryReceipt(
                        knowledge_id=knowledge.knowledge_id,
                        revision=knowledge.revision,
                        status="applied",
                    )
                await self._record_event(database, identity, command, command_payload, receipt)
                await database.execute("COMMIT")
                return receipt
            except BaseException:
                await self._rollback(database)
                raise

    async def forget(
        self,
        command: UserKnowledgeCommand,
        *,
        scope: MemoryRequestScope,
    ) -> UserMemoryReceipt:
        """Delete a fact, suppress stale replay, and retain derivative invalidation work.

        Args:
            command: Revision-checked forget command with a retry-stable event identity.
            scope: Trusted principal used before target lookup or mutation.

        Returns:
            A receipt for the committed erasure, duplicate, conflict, or unknown target.

        Raises:
            ValueError: If identity is missing or the command is not a forget operation.
        """
        identity = self._require_identity(scope)
        if command.operation != "forget":
            raise ValueError("invalid_parameters: forget requires a forget command")
        command_payload = self._command_payload(command)
        async with self._lock:
            database = await self._configure_locked()
            await database.execute("BEGIN IMMEDIATE")
            try:
                replay = await self._event_replay(database, identity, command.event_id, command_payload)
                if replay is not None:
                    await database.execute("COMMIT")
                    return replay

                current = await self._knowledge_by_id(database, identity, command.knowledge_id or "")
                if current is None:
                    receipt = UserMemoryReceipt(status="ignored")
                elif current.status not in ("active", "pending") or current.revision != command.expected_revision:
                    receipt = UserMemoryReceipt(
                        knowledge_id=current.knowledge_id,
                        revision=current.revision,
                        status="conflict",
                    )
                else:
                    now = datetime.now(timezone.utc)
                    claim_key = self._knowledge_claim_key(current)
                    related = await self._knowledge_for_claim(database, identity, claim_key)
                    evidence_refs = tuple(
                        dict.fromkeys(ref for knowledge in related for ref in knowledge.evidence_refs)
                    )
                    evidence_refs = tuple(dict.fromkeys((*evidence_refs, *command.evidence_refs)))
                    blocked_hashes = json.dumps(
                        sorted(self._evidence_hash(ref) for ref in evidence_refs),
                        separators=(",", ":"),
                    )
                    await database.execute(
                        "INSERT INTO user_knowledge_suppressions "
                        "(tenant_id, agent_id, user_id, claim_key, forgotten_at, blocked_evidence_hashes) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(tenant_id, agent_id, user_id, claim_key) DO UPDATE SET "
                        "forgotten_at = excluded.forgotten_at, blocked_evidence_hashes = excluded.blocked_evidence_hashes",
                        (*identity, claim_key, now.isoformat(), blocked_hashes),
                    )
                    related_ids = tuple(knowledge.knowledge_id for knowledge in related)
                    if related_ids:
                        placeholders = ", ".join("?" for _ in related_ids)
                        await database.execute(
                            f"DELETE FROM user_knowledge_events WHERE tenant_id = ? AND agent_id = ? AND user_id = ? "
                            f"AND knowledge_id IN ({placeholders})",
                            (*identity, *related_ids),
                        )
                        await database.execute(
                            f"DELETE FROM user_knowledge WHERE tenant_id = ? AND agent_id = ? AND user_id = ? "
                            f"AND knowledge_id IN ({placeholders})",
                            (*identity, *related_ids),
                        )
                    for episode_id in self._source_episode_ids(evidence_refs):
                        await database.execute(
                            "INSERT INTO user_derivative_forgets "
                            "(tenant_id, source_episode_id, forget_event_id, created_at) VALUES (?, ?, ?, ?) "
                            "ON CONFLICT(tenant_id, source_episode_id) DO UPDATE SET "
                            "forget_event_id = excluded.forget_event_id, created_at = excluded.created_at",
                            (scope.tenant_id, episode_id, command.event_id, now.isoformat()),
                        )
                    receipt = UserMemoryReceipt(
                        knowledge_id=current.knowledge_id,
                        revision=current.revision,
                        status="applied",
                    )
                await self._record_event(database, identity, command, command_payload, receipt)
                await database.execute("COMMIT")
                return receipt
            except BaseException:
                await self._rollback(database)
                raise

    async def _configure_locked(self) -> aiosqlite.Connection:
        """Open and migrate the user-owned schema while the lifecycle lock is held."""
        if self._db is not None:
            return self._db
        database = await aiosqlite.connect(str(self.path), isolation_level=None, timeout=5.0)
        try:
            await database.execute("PRAGMA journal_mode=WAL")
            await database.execute("PRAGMA busy_timeout=5000")
            await database.execute("PRAGMA synchronous=NORMAL")
            await database.execute("PRAGMA secure_delete=ON")
            await database.executescript(_SCHEMA)
            cursor = await database.execute("SELECT version FROM user_memory_schema WHERE component = 'user_knowledge'")
            row = await cursor.fetchone()
            if row is not None and int(row[0]) > _SCHEMA_VERSION:
                raise ValueError(f"unsupported user memory schema version: {row[0]}")
            await database.execute(
                "INSERT INTO user_memory_schema (component, version) VALUES ('user_knowledge', ?) "
                "ON CONFLICT(component) DO UPDATE SET version = excluded.version "
                "WHERE user_memory_schema.version < excluded.version",
                (_SCHEMA_VERSION,),
            )
        except BaseException:
            await database.close()
            raise
        self._db = database
        return database

    @staticmethod
    def _require_identity(scope: MemoryRequestScope) -> tuple[str, str, str]:
        """Return the trusted profile identity or fail before touching storage."""
        if scope.user_id is None:
            raise ValueError("missing_user_identity")
        return scope.tenant_id, scope.agent_id, scope.user_id

    @staticmethod
    def _validate_query(query: str) -> str:
        """Normalize a bounded literal query."""
        normalized = " ".join(query.strip().split())
        if len(normalized) > _MAX_QUERY_CHARS:
            raise ValueError(f"invalid_parameters: query exceeds {_MAX_QUERY_CHARS} characters")
        return normalized

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Require a bounded non-negative result count."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= _MAX_RESULT_LIMIT:
            raise ValueError(f"invalid_parameters: limit must be between 0 and {_MAX_RESULT_LIMIT}")

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape a literal for a SQLite LIKE predicate."""
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _payload_digest(command_payload: str) -> str:
        """Return the content-free identity stored for events that produced no fact."""
        return "sha256:" + hashlib.sha256(command_payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _command_payload(command: UserKnowledgeCommand) -> str:
        """Return canonical JSON used to detect conflicting event reuse."""
        return json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _context_key(context: dict[str, str]) -> str:
        """Return a stable context identity independent of mapping insertion order."""
        return json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _knowledge_id(scope: MemoryRequestScope, event_id: str) -> str:
        """Derive a stable ID from the scoped retry identity."""
        digest = hashlib.sha256()
        for value in (scope.tenant_id, scope.agent_id, scope.user_id or "", event_id):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return f"uk-{digest.hexdigest()}"

    @staticmethod
    def _claim_key(*, kind: str, normalized_key: str | None, value: object, context: dict[str, str]) -> str:
        """Hash claim identity without retaining forgotten fact content."""
        material = {
            "kind": kind,
            "normalized_key": normalized_key,
            "context": context,
            "unkeyed_value": value if normalized_key is None else None,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"uks-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @classmethod
    def _candidate_claim_key(cls, candidate: UserKnowledgeCandidate) -> str:
        """Return the suppression identity for a validated candidate."""
        return cls._claim_key(
            kind=candidate.kind,
            normalized_key=candidate.normalized_key,
            value=candidate.value,
            context=candidate.context,
        )

    @classmethod
    def _knowledge_claim_key(cls, knowledge: UserKnowledge) -> str:
        """Return the suppression identity for persisted knowledge."""
        return cls._claim_key(
            kind=knowledge.kind,
            normalized_key=knowledge.normalized_key,
            value=knowledge.value,
            context=knowledge.context,
        )

    @staticmethod
    def _evidence_hash(reference: str) -> str:
        """Hash evidence identity so suppression never retains source content."""
        return hashlib.sha256(reference.encode("utf-8")).hexdigest()

    @classmethod
    def _has_new_evidence(cls, command: UserKnowledgeCommand, blocked_hashes_json: str) -> bool:
        """Return whether an explicit declaration carries evidence newer than the forgotten claim."""
        candidate = command.candidate
        if candidate is None:
            return False
        blocked_hashes = set(json.loads(blocked_hashes_json))
        evidence_refs = tuple(dict.fromkeys((*candidate.evidence_refs, *command.evidence_refs)))
        return any(cls._evidence_hash(reference) not in blocked_hashes for reference in evidence_refs)

    async def _evidence_available(self, command: UserKnowledgeCommand, scope: MemoryRequestScope) -> bool:
        """Fail closed for malformed, cross-scope, tombstoned, or tenant-mismatched ChatStorage evidence."""
        candidate = command.candidate
        references = command.evidence_refs
        if candidate is not None:
            references = tuple(dict.fromkeys((*candidate.evidence_refs, *references)))
        for reference in references:
            if not reference.startswith("chatstorage/"):
                continue
            try:
                evidence = ChatStorageEvidenceRef.parse(reference)
            except ValueError:
                return False
            if (
                evidence.tenant_id != scope.tenant_id
                or evidence.agent_name != scope.agent_id
                or evidence.user_id != scope.user_id
                or evidence.session_id != scope.session_id
            ):
                return False
            if self._evidence_tenant_resolver is None:
                return False
            stored_tenant = await self._evidence_tenant_resolver(evidence)
            if stored_tenant is None or stored_tenant != scope.tenant_id:
                return False
        return True

    @staticmethod
    def _source_episode_ids(references: tuple[str, ...]) -> tuple[str, ...]:
        """Extract explicit source-episode lineage without importing brain internals."""
        episode_ids: list[str] = []
        for reference in references:
            for prefix in _EPISODE_REF_PREFIXES:
                if reference.startswith(prefix):
                    episode_id = reference[len(prefix) :]
                    if episode_id:
                        episode_ids.append(episode_id)
                    break
        return tuple(dict.fromkeys(episode_ids))

    async def _suppression(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        claim_key: str,
    ) -> str | None:
        """Return hashed blocked evidence for a suppressed claim."""
        cursor = await database.execute(
            "SELECT blocked_evidence_hashes FROM user_knowledge_suppressions "
            "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND claim_key = ?",
            (*identity, claim_key),
        )
        row = await cursor.fetchone()
        return str(row[0]) if row is not None else None

    async def _knowledge_for_claim(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        claim_key: str,
    ) -> list[UserKnowledge]:
        """Load scoped history rows matching a claim before their physical erasure."""
        cursor = await database.execute(
            "SELECT payload FROM user_knowledge WHERE tenant_id = ? AND agent_id = ? AND user_id = ?",
            identity,
        )
        rows = await cursor.fetchall()
        knowledge = [UserKnowledge.model_validate_json(row[0]) for row in rows]
        return [item for item in knowledge if self._knowledge_claim_key(item) == claim_key]

    async def _event_replay(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        event_id: str,
        command_payload: str,
    ) -> UserMemoryReceipt | None:
        """Resolve an existing event as a duplicate or conflicting reuse."""
        cursor = await database.execute(
            "SELECT command_payload, knowledge_id, revision FROM user_knowledge_events "
            "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND event_id = ?",
            (*identity, event_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if row[0] not in (command_payload, self._payload_digest(command_payload)):
            return UserMemoryReceipt(status="conflict")
        return UserMemoryReceipt(knowledge_id=row[1], revision=row[2], status="duplicate")

    async def _record_event(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        command: UserKnowledgeCommand,
        command_payload: str,
        receipt: UserMemoryReceipt,
    ) -> None:
        """Persist a command outcome in the same transaction as its mutation.

        An event tied to a stored fact keeps its canonical payload: ``forget`` deletes it with the fact. An event that
        never produced a fact (ignored, suppressed or unavailable evidence) has no knowledge id for ``forget`` to find,
        so it keeps only a digest and can never retain the content of a claim the user later erases.
        """
        stored_payload = command_payload if receipt.knowledge_id is not None else self._payload_digest(command_payload)
        await database.execute(
            "INSERT INTO user_knowledge_events "
            "(tenant_id, agent_id, user_id, event_id, command_payload, result_status, knowledge_id, revision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*identity, command.event_id, stored_payload, receipt.status, receipt.knowledge_id, receipt.revision),
        )

    async def _matching_active(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        candidate: object,
    ) -> UserKnowledge | None:
        """Return the active explicit claim with the same key and context, if any."""
        normalized_key = candidate.normalized_key
        provenance = candidate.provenance
        if normalized_key is None or provenance != "explicit":
            return None
        cursor = await database.execute(
            "SELECT payload FROM user_knowledge WHERE tenant_id = ? AND agent_id = ? AND user_id = ? "
            "AND kind = ? AND normalized_key = ? AND context_key = ? AND status = 'active' "
            "ORDER BY updated_at DESC, knowledge_id DESC LIMIT 1",
            (
                *identity,
                candidate.kind,
                normalized_key,
                self._context_key(candidate.context),
            ),
        )
        row = await cursor.fetchone()
        return UserKnowledge.model_validate_json(row[0]) if row is not None else None

    async def _knowledge_by_id(
        self,
        database: aiosqlite.Connection,
        identity: tuple[str, str, str],
        knowledge_id: str,
    ) -> UserKnowledge | None:
        """Look up a target only within the trusted identity scope."""
        cursor = await database.execute(
            "SELECT payload FROM user_knowledge "
            "WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND knowledge_id = ?",
            (*identity, knowledge_id),
        )
        row = await cursor.fetchone()
        return UserKnowledge.model_validate_json(row[0]) if row is not None else None

    def _make_knowledge(
        self,
        command: UserKnowledgeCommand,
        scope: MemoryRequestScope,
        *,
        revision: int,
        supersedes_id: str | None,
        now: datetime,
    ) -> UserKnowledge:
        """Build one scoped record from a validated candidate and trusted principal."""
        candidate = command.candidate
        if candidate is None:
            raise ValueError("invalid_parameters: knowledge mutation requires a candidate")
        evidence_refs = tuple(dict.fromkeys((*candidate.evidence_refs, *command.evidence_refs)))
        status = candidate.initial_status
        return UserKnowledge(
            knowledge_id=self._knowledge_id(scope, command.event_id),
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            user_id=scope.user_id or "",
            kind=candidate.kind,
            normalized_key=candidate.normalized_key,
            value=candidate.value,
            context=candidate.context,
            provenance=candidate.provenance,
            evidence_refs=evidence_refs,
            status=status,
            created_at=now,
            updated_at=now,
            confirmed_at=now if candidate.provenance == "explicit" else None,
            valid_from=candidate.valid_from or now,
            expires_at=candidate.expires_at,
            revision=revision,
            supersedes_id=supersedes_id,
        )

    @staticmethod
    def _same_claim_context(current: UserKnowledge, command: UserKnowledgeCommand) -> bool:
        """Keep corrections inside the original kind, key, and context boundary."""
        candidate = command.candidate
        return bool(
            candidate is not None
            and candidate.provenance == "explicit"
            and candidate.kind == current.kind
            and candidate.normalized_key == current.normalized_key
            and candidate.context == current.context
        )

    async def _insert_knowledge(self, database: aiosqlite.Connection, knowledge: UserKnowledge) -> None:
        """Insert a fully validated knowledge record."""
        searchable_text = f"{knowledge.normalized_key or ''} {json.dumps(knowledge.value, ensure_ascii=False)}"
        await database.execute(
            "INSERT INTO user_knowledge "
            "(knowledge_id, tenant_id, agent_id, user_id, kind, normalized_key, context_key, provenance, status, "
            "updated_at, valid_from, expires_at, searchable_text, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                knowledge.knowledge_id,
                knowledge.tenant_id,
                knowledge.agent_id,
                knowledge.user_id,
                knowledge.kind,
                knowledge.normalized_key,
                self._context_key(knowledge.context),
                knowledge.provenance,
                knowledge.status,
                knowledge.updated_at.isoformat(),
                knowledge.valid_from.isoformat() if knowledge.valid_from is not None else None,
                knowledge.expires_at.isoformat() if knowledge.expires_at is not None else None,
                searchable_text,
                knowledge.model_dump_json(),
            ),
        )

    async def _supersede(
        self,
        database: aiosqlite.Connection,
        current: UserKnowledge,
        now: datetime,
    ) -> None:
        """Retain an old record as non-served history."""
        superseded = current.model_copy(update={"status": "superseded", "updated_at": now})
        await database.execute(
            "UPDATE user_knowledge SET status = 'superseded', updated_at = ?, payload = ? WHERE knowledge_id = ?",
            (now.isoformat(), superseded.model_dump_json(), current.knowledge_id),
        )

    async def _rollback(self, database: aiosqlite.Connection) -> None:
        """Roll back atomically while preserving cancellation and the original failure."""
        try:
            await asyncio.shield(database.execute("ROLLBACK"))
        except Exception:
            self.logger.exception("user memory SQLite rollback failed")
