-- ===========================================================================
-- FEAT-538 — Recoverable Task Memory: durable schema (Delivery B)
-- Migration 001, schema `working_memory`.
-- ===========================================================================
--
-- APPLY THIS EXPLICITLY AT DEPLOYMENT. It is never executed by a tool call.
-- Decision D2 and spec §2 "Persistence and Recovery": PostgreSQL owns the
-- journal, the projection and the artifact index; automatic DDL on a hot
-- path would mean every agent turn could attempt a schema change, which is
-- both a latency and a privilege problem.
--
--     uv run python -m parrot.tools.working_memory.task_memory.store.postgres \
--         --dsn "$TASK_MEMORY_DSN" --apply
--
-- The file is split into an UP and a DOWN section by the fence comments
-- below. `migrations.py` consumers read them by marker, so DO NOT reorder or
-- reword the fences.
--
-- Idempotence: every statement in UP is `IF NOT EXISTS`-guarded, so a repeat
-- apply is a no-op rather than an error. The `schema_migrations` row is the
-- authoritative record; the guards exist so a half-applied migration (a crash
-- between statements) can be completed by re-running rather than by hand.
--
-- ROLLBACK GUIDANCE
-- -----------------
-- The DOWN section drops the whole `working_memory` schema. That is
-- **destructive and irreversible**: it removes every task journal, projection
-- and artifact index row. There is no partial down-migration, because
-- dropping a column from `tasks` or `task_journal` would leave a projection
-- that the reducer can no longer replay — a silently wrong state is worse
-- than an absent one.
--
-- Before running DOWN in an environment with real data:
--   1. Archive the journals you must keep (spec §2 Retention: JSONL archive
--      must succeed and verify BEFORE deletion).
--   2. Confirm no pod is still writing — a live append during the drop would
--      fail mid-transaction.
--   3. Blob storage is NOT touched by this migration. Dropping the schema
--      orphans every stored payload; sweep them separately or they persist
--      indefinitely.
--
-- ===========================================================================

-- >>> UP

CREATE SCHEMA IF NOT EXISTS working_memory;

-- ---------------------------------------------------------------------------
-- schema_migrations — which migrations this database has had applied.
-- Consulted before any read/write path runs, so a store never assumes a shape
-- the database does not have.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.schema_migrations (
    version      INTEGER     NOT NULL PRIMARY KEY,
    name         TEXT        NOT NULL,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Reversibility is a property of the migration, recorded so an operator
    -- can tell from the database alone whether a DOWN exists.
    reversible   BOOLEAN     NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------------
-- tasks — one row per task, carrying the reducer projection.
--
-- The projection is a CACHE of the journal, never the source of truth (D6).
-- `reducer_version` is what makes a lazy projection migration possible: a row
-- written by an older reducer is replayed under the task lock, and a row
-- written by a NEWER one is rejected explicitly rather than misinterpreted.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.tasks (
    task_id         TEXT        NOT NULL PRIMARY KEY,

    -- Scope is stored as three columns, not one composite string: it is
    -- queried and indexed, and a delimiter-joined key would be forgeable by
    -- a component containing the delimiter.
    chatbot_id      TEXT        NOT NULL,
    user_id         TEXT        NOT NULL,
    session_id      TEXT        NOT NULL,

    status          TEXT        NOT NULL,
    goal            TEXT        NOT NULL,

    revision        BIGINT      NOT NULL DEFAULT 0,
    last_event_seq  BIGINT      NOT NULL DEFAULT 0,

    projection      JSONB       NOT NULL,
    reducer_version INTEGER     NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL for a live task; set exactly once when the task reaches a terminal
    -- status. Retention measures the 90-day window from here.
    terminal_at     TIMESTAMPTZ,

    CONSTRAINT tasks_status_valid CHECK (
        status IN ('active', 'blocked', 'paused', 'completed', 'failed', 'cancelled')
    ),
    CONSTRAINT tasks_revision_nonneg CHECK (revision >= 0),
    CONSTRAINT tasks_last_seq_nonneg CHECK (last_event_seq >= 0),
    -- A terminal status and a terminal timestamp must agree. Without this a
    -- retention sweep could either skip a finished task forever or expire a
    -- live one.
    CONSTRAINT tasks_terminal_consistent CHECK (
        (status IN ('completed', 'failed', 'cancelled')) = (terminal_at IS NOT NULL)
    )
);

-- Scope + status: the task listing query, and the open-task-per-scope limit.
CREATE INDEX IF NOT EXISTS tasks_scope_status_idx
    ON working_memory.tasks (chatbot_id, user_id, session_id, status);

-- Retention scans terminal tasks by age.
CREATE INDEX IF NOT EXISTS tasks_terminal_at_idx
    ON working_memory.tasks (terminal_at)
    WHERE terminal_at IS NOT NULL;

-- Nonterminal activity: drives both the "newest activity first" listing and
-- the 7-day inactivity pause. PARTIAL on purpose — the sweeper and the
-- listing only ever care about live tasks, and terminal rows dominate the
-- table over time.
CREATE INDEX IF NOT EXISTS tasks_nonterminal_activity_idx
    ON working_memory.tasks (chatbot_id, user_id, session_id, updated_at DESC)
    WHERE terminal_at IS NULL;

-- ---------------------------------------------------------------------------
-- task_journal — the source of truth (D6). Append-only.
--
-- `(task_id, seq)` is the primary key, so sequences are unique per task by
-- construction. `event_id` is globally unique, which is what makes redelivery
-- detectable: the store classifies duplicates BEFORE allocating a sequence,
-- so deduplication leaves no gap in `seq`.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.task_journal (
    task_id     TEXT        NOT NULL,
    seq         BIGINT      NOT NULL,

    -- Globally unique, not merely unique per task: an event id identifies one
    -- append attempt anywhere in the system, which is what lets a retry be
    -- recognised as a retry.
    event_id    TEXT        NOT NULL,

    event_type  TEXT        NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    actor       TEXT        NOT NULL,

    turn_id       TEXT,
    step_id       TEXT,
    call_id       TEXT,
    parent_call_id TEXT,
    attribution   TEXT      NOT NULL DEFAULT 'none',
    plan_revision BIGINT    NOT NULL DEFAULT 0,

    -- The full serialized JournalEvent. Redacted before it gets here.
    payload     JSONB       NOT NULL,

    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT task_journal_pkey PRIMARY KEY (task_id, seq),
    CONSTRAINT task_journal_seq_positive CHECK (seq >= 1),
    CONSTRAINT task_journal_task_fk FOREIGN KEY (task_id)
        REFERENCES working_memory.tasks (task_id) ON DELETE CASCADE
);

-- The idempotency index. An append that would reuse an id fails here even if
-- application-level classification were bypassed.
CREATE UNIQUE INDEX IF NOT EXISTS task_journal_event_id_key
    ON working_memory.task_journal (event_id);

CREATE INDEX IF NOT EXISTS task_journal_type_idx
    ON working_memory.task_journal (task_id, event_type, seq);

-- ---------------------------------------------------------------------------
-- artifacts — one row per immutable (artifact_id, version).
--
-- A version is never updated in place except to record invalidation. An
-- overwrite of an alias creates a NEW version row; the old one stays valid
-- and resolvable, which is what makes older evidence survive an overwrite
-- (AC5).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.artifacts (
    artifact_id     TEXT        NOT NULL,
    version         INTEGER     NOT NULL,

    chatbot_id      TEXT        NOT NULL,
    user_id         TEXT        NOT NULL,
    session_id      TEXT        NOT NULL,

    -- NULL when the artifact is not associated with a task. Unlike
    -- artifact_aliases (below) there is no unique constraint over this
    -- column, so NULL is safe and honest here.
    task_id         TEXT,
    producer_call_id TEXT,
    attribution     TEXT        NOT NULL DEFAULT 'none',

    alias           TEXT,
    kind            TEXT        NOT NULL,
    availability    TEXT        NOT NULL,

    fingerprint_algorithm TEXT,
    fingerprint           TEXT,
    -- Whether the fingerprint actually PROVES content integrity. FALSE for
    -- nested-mutable or unsupported values even when a fingerprint was
    -- computable (TASK-2970 finding: pandas repr-hashes unhashable cells).
    evidence_verifiable   BOOLEAN NOT NULL DEFAULT FALSE,

    storage_ref     TEXT,
    byte_size       BIGINT,
    shape           JSONB,
    schema_summary  JSONB,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated     BOOLEAN     NOT NULL DEFAULT FALSE,
    invalidated_at  TIMESTAMPTZ,
    invalidated_reason TEXT,

    CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_id, version),
    CONSTRAINT artifacts_version_positive CHECK (version >= 1),
    CONSTRAINT artifacts_kind_valid CHECK (
        kind IN ('dataframe', 'json', 'text', 'binary', 'object')
    ),
    CONSTRAINT artifacts_availability_valid CHECK (
        availability IN ('memory', 'persisted', 'missing', 'expired')
    ),
    CONSTRAINT artifacts_byte_size_nonneg CHECK (byte_size IS NULL OR byte_size >= 0),
    -- Cannot claim verifiable evidence without the means to prove it. Mirrors
    -- ArtifactDescriptor's model validator, enforced again at the storage
    -- layer so a direct SQL writer cannot bypass it.
    CONSTRAINT artifacts_verifiable_needs_fingerprint CHECK (
        NOT evidence_verifiable OR (fingerprint IS NOT NULL AND kind IN ('dataframe', 'json', 'text'))
    ),
    CONSTRAINT artifacts_invalidated_consistent CHECK (
        invalidated = (invalidated_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS artifacts_scope_task_idx
    ON working_memory.artifacts (chatbot_id, user_id, session_id, task_id);

CREATE INDEX IF NOT EXISTS artifacts_alias_idx
    ON working_memory.artifacts (chatbot_id, user_id, session_id, alias);

-- Retention sweeps unpinned noncurrent versions by age.
CREATE INDEX IF NOT EXISTS artifacts_created_at_idx
    ON working_memory.artifacts (created_at);

-- ---------------------------------------------------------------------------
-- artifact_aliases — the mutable name -> current version mapping.
--
-- THE NON-NULL NAMESPACE MATTERS. `task_ns` is NOT NULL with an empty-string
-- sentinel for unassociated entries, because in SQL `NULL <> NULL`: a UNIQUE
-- constraint over a nullable `task_id` would permit unlimited duplicate rows
-- for the unassociated namespace, and two concurrent writers would each
-- happily allocate version 1 for the same key. The sentinel is what makes the
-- constraint actually constrain.
--
-- This row is also the LOCK POINT for version allocation: a writer takes
-- `SELECT ... FOR UPDATE` on the alias row before computing the next version,
-- so concurrent overwrites of the same alias serialize and cannot both
-- allocate the same version number.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.artifact_aliases (
    chatbot_id      TEXT        NOT NULL,
    user_id         TEXT        NOT NULL,
    session_id      TEXT        NOT NULL,
    -- '' means "not associated with a task". NEVER NULL — see above.
    task_ns         TEXT        NOT NULL DEFAULT '',
    alias_key       TEXT        NOT NULL,

    artifact_id     TEXT        NOT NULL,
    -- The version the alias currently points at. NULL only while tombstoned.
    current_version INTEGER,
    -- Highest version ever allocated for this identity. Retained across a
    -- tombstone so drop/recreate CONTINUES the counter rather than reusing a
    -- version number a pinned snapshot still refers to.
    latest_version  INTEGER     NOT NULL DEFAULT 0,

    -- The alias was dropped but the identity is retained until retention
    -- permits removal.
    tombstoned      BOOLEAN     NOT NULL DEFAULT FALSE,
    tombstoned_at   TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT artifact_aliases_pkey
        PRIMARY KEY (chatbot_id, user_id, session_id, task_ns, alias_key),
    CONSTRAINT artifact_aliases_versions_nonneg CHECK (
        latest_version >= 0 AND (current_version IS NULL OR current_version >= 1)
    ),
    CONSTRAINT artifact_aliases_current_le_latest CHECK (
        current_version IS NULL OR current_version <= latest_version
    ),
    CONSTRAINT artifact_aliases_tombstone_consistent CHECK (
        tombstoned = (tombstoned_at IS NOT NULL)
    )
);

-- Reverse lookup: which alias currently points at a given identity.
CREATE INDEX IF NOT EXISTS artifact_aliases_artifact_idx
    ON working_memory.artifact_aliases (artifact_id);

-- ---------------------------------------------------------------------------
-- artifact_evidence — which (task, step) references which artifact version.
--
-- PINNING IS DERIVED FROM THIS TABLE, not from a boolean on `artifacts`. A
-- version is pinned while ANY nonterminal task references it — including a
-- task other than the one that produced it. A single mutable `pinned` flag
-- could not express "two tasks reference this, one finished", and consulting
-- only the producing task would let a cross-task reference be swept away
-- underneath its holder.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS working_memory.artifact_evidence (
    task_id     TEXT        NOT NULL,
    step_id     TEXT        NOT NULL,
    artifact_id TEXT        NOT NULL,
    version     INTEGER     NOT NULL,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT artifact_evidence_pkey PRIMARY KEY (task_id, step_id, artifact_id, version),
    CONSTRAINT artifact_evidence_version_positive CHECK (version >= 1),
    CONSTRAINT artifact_evidence_task_fk FOREIGN KEY (task_id)
        REFERENCES working_memory.tasks (task_id) ON DELETE CASCADE,
    CONSTRAINT artifact_evidence_artifact_fk FOREIGN KEY (artifact_id, version)
        REFERENCES working_memory.artifacts (artifact_id, version) ON DELETE CASCADE
);

-- The pin query: "is any nonterminal task still referencing this version?"
CREATE INDEX IF NOT EXISTS artifact_evidence_artifact_idx
    ON working_memory.artifact_evidence (artifact_id, version);

CREATE INDEX IF NOT EXISTS artifact_evidence_task_idx
    ON working_memory.artifact_evidence (task_id, step_id);

-- Record the migration last, so a crash part-way through leaves the version
-- unrecorded and the re-run completes it.
INSERT INTO working_memory.schema_migrations (version, name, reversible)
VALUES (1, '001_task_memory', TRUE)
ON CONFLICT (version) DO NOTHING;

-- <<< UP

-- >>> DOWN
--
-- DESTRUCTIVE AND IRREVERSIBLE. Read the ROLLBACK GUIDANCE at the top of this
-- file first: this removes every journal, projection and artifact index row,
-- and orphans every blob in external storage.

DROP SCHEMA IF EXISTS working_memory CASCADE;

-- <<< DOWN
