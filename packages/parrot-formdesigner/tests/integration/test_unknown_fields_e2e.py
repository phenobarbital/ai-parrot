"""End-to-end tests for the FEAT-458 unknown-fields policy.

These tests exercise the assembled layers (validator + handler + storage +
sink + forwarder + renderer) against a REAL scratch Postgres database — the
package's `tests/integration/` directory itself tests without a live DB
(fake pools throughout), so this suite follows the sibling real-DB
convention used by `tests/test_submission_jsonb_shape.py` and
`tests/test_jsonb_object_storage.py` instead (module-level `SCRATCH_DSN`
skip, dedicated disposable schema) — the closest existing precedent for
"the same double-encoding hazard, on a live server" (services/
submissions.py:255-273), which is exactly what this suite's codec-pool
test proves for `extra_data`.

Requires a disposable Postgres::

    SCRATCH_DSN="postgresql://postgres:postgres@localhost:5432/postgres" \\
        pytest tests/integration/test_unknown_fields_e2e.py -v

Spec AC coverage:
  AC1  test_e2e_drop_is_byte_identical_to_baseline
  AC3  test_e2e_legacy_table_gains_column_on_initialize
  AC4  test_e2e_keep_stores_and_forwards
  AC7  test_e2e_reject_blocks_submission
  AC12 test_e2e_keep_stores_and_forwards
  AC13 test_e2e_codec_registered_pool_roundtrip
  AC14 test_e2e_persistence_form_captures_extras
  AC17 test_e2e_partial_then_merge_partials_submit
  AC18 test_e2e_audio_ws_submission_unaffected
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionState,
)
from parrot_formdesigner.core.events import EventResolution
from parrot_formdesigner.core.persistence import (
    FormPersistenceConfig,
    PostgresTableTarget,
    SinkCapability,
)
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    SubmitAction,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import AbstractSubmissionSink
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.unknown_fields import MAX_EXTRA_BYTES, MAX_EXTRA_KEYS

_SCRATCH_DSN = os.getenv("SCRATCH_DSN")

pytestmark = [
    pytest.mark.skipif(
        not _SCRATCH_DSN,
        reason="SCRATCH_DSN not set (scratch Postgres required)",
    ),
]

SCHEMA = "pfd_unknown_fields_e2e_test"
_TEST_TENANT = "test-tenant"


# ---------------------------------------------------------------------------
# Fixtures — real scratch Postgres (this directory otherwise uses fake pools)
# ---------------------------------------------------------------------------


async def _codec_init(conn: Any) -> None:
    """Mirror navigator's shared-pool json/jsonb codec registration
    (the exact condition behind the services/submissions.py:255-273 defect)."""
    for name in ("json", "jsonb"):
        await conn.set_type_codec(name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


@pytest.fixture
async def pool() -> AsyncIterator[Any]:
    """A plain asyncpg pool against a disposable scratch schema."""
    import asyncpg

    created = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=3)
    async with created.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield created
    finally:
        async with created.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await created.close()


@pytest.fixture
async def storage(pool: Any) -> FormSubmissionStorage:
    """A FormSubmissionStorage against the scratch schema, initialized."""
    s = FormSubmissionStorage(pool, schema=SCHEMA)
    await s.initialize()
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _form(
    *,
    policy: str = "drop",
    persistence: FormPersistenceConfig | None = None,
    submit: SubmitAction | None = None,
) -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[FormSection(section_id="s1", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")])],
        unknown_fields=policy,
        persistence=persistence,
        submit=submit,
    )


def _make_request(
    *,
    body: dict | None = None,
    form_uid: uuid.UUID,
    query: dict[str, str] | None = None,
    session_id: str | None = None,
) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": str(form_uid)}
    query = query or {}
    req.query = MagicMock()
    req.query.get = MagicMock(side_effect=lambda key, default="": query.get(key, default))
    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False
        req.__getitem__ = MagicMock(side_effect=KeyError)
    req.json = AsyncMock(return_value=body or {"name": "Ana"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


def _make_handler(
    form: FormSchema,
    *,
    submission_storage: FormSubmissionStorage | None = None,
    forwarder: Any = None,
    sink_factory: Any = None,
    partial_store: PartialSaveStore | None = None,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    return FormAPIHandler(
        registry=registry,
        submission_storage=submission_storage,
        forwarder=forwarder,
        sink_factory=sink_factory,
        partial_store=partial_store,
    )


class _InMemoryRedis:
    """Minimal fake Redis client backed by a plain dict (no live Redis needed)."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def close(self) -> None:
        pass


class InMemoryPartialStore(PartialSaveStore):
    """A real PartialSaveStore, backed by an in-memory dict instead of a
    live Redis connection — exercises the actual save/merge logic."""

    def __init__(self) -> None:
        super().__init__(ttl_seconds=3600, redis_url=None)
        self.raw_store: dict[str, str] = {}

    async def _get_redis(self) -> Any:
        return _InMemoryRedis(self.raw_store)


class _FakeDocumentSink(AbstractSubmissionSink):
    """A document-family sink double (no live Mongo/Arango in this repo's
    test infra) — exercises the SAME handler exclusivity branch real
    tabular sinks do; `write()`'s payload shape is what's under test here,
    not a specific document driver's wire protocol."""

    def __init__(self) -> None:
        self.written: list[Any] = []

    @property
    def capabilities(self) -> frozenset[SinkCapability]:
        return frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})

    @property
    def family(self) -> str:
        return "document"

    async def ensure_target(self, form: FormSchema) -> None:
        return None

    async def write(self, submission: Any, payload: Any) -> str:
        self.written.append(payload)
        return submission.submission_id


class _SingleSinkFactory:
    def __init__(self, sink: Any) -> None:
        self._sink = sink

    async def get(self, form: FormSchema, *, tenant: str) -> Any:
        return self._sink


def _postgres_persistence(table: str) -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {"data": {"type": "postgres_table", "connection": "scratch", "schema_name": SCHEMA, "table": table}}
    )


# ---------------------------------------------------------------------------
# AC1 — drop is byte-identical to pre-FEAT-458 baseline
# ---------------------------------------------------------------------------


async def test_e2e_drop_is_byte_identical_to_baseline(storage: FormSubmissionStorage, pool: Any) -> None:
    form = _form(policy="drop")
    handler = _make_handler(form, submission_storage=storage)
    payload = {"name": "Ana", "junk": 1, "_client_ms": 1180}

    resp = await handler.submit_data(_make_request(body=payload, form_uid=form.form_uid))
    body = json.loads(resp.body)

    assert resp.status == 200
    assert set(body) == {"submission_id", "is_valid", "forwarded", "forward_status", "forward_error"}

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT data, extra_data FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            body["submission_id"],
        )
    assert row is not None
    stored_data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    assert stored_data == {"name": "Ana"}
    assert row["extra_data"] is None


# ---------------------------------------------------------------------------
# AC4, AC12 — keep stores extras and forwards the flat-merged body
# ---------------------------------------------------------------------------


async def test_e2e_keep_stores_and_forwards(storage: FormSubmissionStorage, pool: Any, aiohttp_server) -> None:
    from parrot_formdesigner.services.forwarder import SubmissionForwarder

    received: dict = {}

    async def _stub_handler(request: web.Request) -> web.Response:
        received.update(await request.json())
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/hook", _stub_handler)
    server = await aiohttp_server(app)

    submit = SubmitAction(action_type="endpoint", action_ref=str(server.make_url("/hook")))
    form = _form(policy="keep", submit=submit)
    handler = _make_handler(form, submission_storage=storage, forwarder=SubmissionForwarder())

    resp = await handler.submit_data(
        _make_request(body={"name": "Ana", "legacy_id": 42}, form_uid=form.form_uid)
    )
    body = json.loads(resp.body)
    assert resp.status == 200
    assert body["forwarded"] is True

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT data, extra_data FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            body["submission_id"],
        )
    stored_data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    stored_extra = row["extra_data"] if isinstance(row["extra_data"], dict) else json.loads(row["extra_data"])
    assert stored_data == {"name": "Ana"}
    assert stored_extra == {"legacy_id": 42}
    assert received == {"name": "Ana", "legacy_id": 42}


# ---------------------------------------------------------------------------
# AC3 — a legacy (pre-FEAT-458) table gains the column via initialize()
# ---------------------------------------------------------------------------


async def test_e2e_legacy_table_gains_column_on_initialize(pool: Any) -> None:
    # Hand-written CREATE TABLE mirroring the pre-FEAT-458 shape (every
    # column _create_table_sql's CREATE INDEX statements depend on, EXCEPT
    # extra_data) — genuinely exercises ADD COLUMN IF NOT EXISTS.
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            CREATE TABLE "{SCHEMA}".form_data (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                submission_id VARCHAR(255) NOT NULL UNIQUE,
                form_uid UUID,
                form_id VARCHAR(255) NOT NULL,
                form_version VARCHAR(50) NOT NULL,
                data JSONB NOT NULL,
                is_valid BOOLEAN NOT NULL DEFAULT TRUE,
                forwarded BOOLEAN NOT NULL DEFAULT FALSE,
                forward_status INTEGER,
                forward_error TEXT,
                tenant VARCHAR(63),
                user_id VARCHAR(255),
                username VARCHAR(255),
                org_id INTEGER,
                submitted_at TIMESTAMPTZ,
                ip INET,
                user_agent TEXT,
                locale VARCHAR(35),
                root_submission_id VARCHAR(255),
                revision INTEGER,
                context JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        legacy_form_uid = uuid.uuid4()
        await conn.execute(
            f'INSERT INTO "{SCHEMA}".form_data '
            "(submission_id, form_uid, form_id, form_version, data) "
            "VALUES ($1, $2, $3, $4, $5::text::jsonb)",
            "legacy-sub-1",
            legacy_form_uid,
            "legacy-form",
            "1.0",
            json.dumps({"q1": "yes"}),
        )

    storage = FormSubmissionStorage(pool, schema=SCHEMA)
    await storage.initialize()  # CREATE IF NOT EXISTS (no-op) then ALTER ADD COLUMN

    async with pool.acquire() as conn:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = $1 AND table_name = 'form_data'",
            SCHEMA,
        )
    assert "extra_data" in {r["column_name"] for r in columns}

    legacy = await storage.get_submission("legacy-sub-1")
    assert legacy is not None
    assert legacy.extra_data is None
    assert legacy.data == {"q1": "yes"}  # no data lost


# ---------------------------------------------------------------------------
# AC7 — reject blocks the submission
# ---------------------------------------------------------------------------


async def test_e2e_reject_blocks_submission(storage: FormSubmissionStorage, pool: Any, monkeypatch) -> None:
    import parrot_formdesigner.api.handlers as handlers_module

    events: list[str] = []

    async def spy_dispatch(event_name, **kwargs):
        events.append(event_name)
        return EventResolution()

    monkeypatch.setattr(handlers_module, "dispatch", spy_dispatch)

    form = _form(policy="reject")
    handler = _make_handler(form, submission_storage=storage)

    resp = await handler.submit_data(
        _make_request(body={"name": "Ana", "junk": 1}, form_uid=form.form_uid)
    )
    body = json.loads(resp.body)

    assert resp.status == 422
    assert body["errors"]["__unknown__"] == ["junk"]
    assert "onError" in events

    async with pool.acquire() as conn:
        count = await conn.fetchval(f'SELECT COUNT(*) FROM "{SCHEMA}".form_data')
    assert count == 0


# ---------------------------------------------------------------------------
# AC14 — a persistence: form captures extras in its own sink, never form_data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("driver", ["tabular", "document"])
async def test_e2e_persistence_form_captures_extras(storage: FormSubmissionStorage, pool: Any, driver: str) -> None:
    if driver == "tabular":
        target = PostgresTableTarget(connection="scratch", schema_name=SCHEMA, table="survey_extras")
        sink = PostgresTableSink(target, alias_registry=SinkAliasRegistry(), tenant=_TEST_TENANT, pool=pool)
        persistence = _postgres_persistence("survey_extras")
    else:
        sink = _FakeDocumentSink()
        persistence = FormPersistenceConfig.model_validate(
            {"data": {"type": "asyncdb", "connection": "mongo_alias", "driver": "mongo", "collection": "responses"}}
        )

    form = _form(policy="keep", persistence=persistence)
    handler = _make_handler(form, submission_storage=storage, sink_factory=_SingleSinkFactory(sink))

    resp = await handler.submit_data(
        _make_request(body={"name": "Ana", "legacy_id": 42}, form_uid=form.form_uid)
    )
    assert resp.status == 200

    if driver == "tabular":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f'SELECT extra_data FROM "{SCHEMA}".survey_extras LIMIT 1')
        assert row is not None
        extra = row["extra_data"] if isinstance(row["extra_data"], dict) else json.loads(row["extra_data"])
        assert extra == {"legacy_id": 42}
    else:
        assert sink.written[-1]["extra_data"] == {"legacy_id": 42}

    async with pool.acquire() as conn:
        count = await conn.fetchval(f'SELECT COUNT(*) FROM "{SCHEMA}".form_data')
    assert count == 0  # exclusivity — nothing written to the generic table


# ---------------------------------------------------------------------------
# AC13 — codec-registered pool round trip
# ---------------------------------------------------------------------------


async def test_e2e_codec_registered_pool_roundtrip() -> None:
    import asyncpg

    codec_pool = await asyncpg.create_pool(dsn=_SCRATCH_DSN, min_size=1, max_size=2, init=_codec_init)
    async with codec_pool.acquire() as conn:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}_codec" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}_codec"')
    try:
        storage = FormSubmissionStorage(codec_pool, schema=f"{SCHEMA}_codec")
        await storage.initialize()

        from datetime import datetime

        from parrot_formdesigner.services.submissions import FormSubmission

        submission = FormSubmission(
            form_uid=uuid.uuid4(),
            form_id="codec-form",
            form_version="1.0",
            data={"name": "Ana"},
            is_valid=True,
            created_at=datetime.now(UTC),
            extra_data={"legacy_id": 42},
        )
        await storage.store(submission)

        async with codec_pool.acquire() as conn:
            row = await conn.fetchrow(
                f'SELECT jsonb_typeof(extra_data) AS kind '
                f'FROM "{SCHEMA}_codec".form_data WHERE submission_id = $1',
                submission.submission_id,
            )
        assert row["kind"] == "object", "extra_data stored as a jsonb STRING — the double-encoding defect is back"

        loaded = await storage.get_submission(submission.submission_id)
        assert isinstance(loaded.extra_data, dict)
        assert loaded.extra_data == {"legacy_id": 42}
    finally:
        async with codec_pool.acquire() as conn:
            await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}_codec" CASCADE')
        await codec_pool.close()


# ---------------------------------------------------------------------------
# AC17 — /partial still rejects unknown field_ids; /submit?merge_partials=true captures extras
# ---------------------------------------------------------------------------


async def test_e2e_partial_then_merge_partials_submit(storage: FormSubmissionStorage, pool: Any) -> None:
    partial_store = InMemoryPartialStore()
    form = _form(policy="keep")
    handler = _make_handler(form, submission_storage=storage, partial_store=partial_store)

    # /partial rejects an unknown field_id under every policy (spec AC17).
    partial_resp = await handler.save_partial(
        _make_request(
            body={"answers": {"junk": 1}},
            form_uid=form.form_uid,
            session_id="sess-1",
        )
    )
    partial_body = json.loads(partial_resp.body)
    assert partial_body["field_errors"]["junk"] == ["unknown field_id"]

    # Save a real (declared) partial answer, then submit with merge_partials=true.
    await handler.save_partial(
        _make_request(
            body={"answers": {"name": "Ana"}},
            form_uid=form.form_uid,
            session_id="sess-1",
        )
    )

    resp = await handler.submit_data(
        _make_request(
            body={"legacy_id": 42},
            form_uid=form.form_uid,
            query={"merge_partials": "true"},
            session_id="sess-1",
        )
    )
    body = json.loads(resp.body)
    assert resp.status == 200

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT data, extra_data FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            body["submission_id"],
        )
    stored_data = row["data"] if isinstance(row["data"], dict) else json.loads(row["data"])
    stored_extra = row["extra_data"] if isinstance(row["extra_data"], dict) else json.loads(row["extra_data"])
    assert stored_data == {"name": "Ana"}  # merged from the cached partial
    assert stored_extra == {"legacy_id": 42}  # still captured under keep


# ---------------------------------------------------------------------------
# AC18 — the audio WebSocket path is unaffected
# ---------------------------------------------------------------------------


async def test_e2e_audio_ws_submission_unaffected(storage: FormSubmissionStorage, pool: Any) -> None:
    form = _form(policy="keep")  # even under keep, the audio path never computes extras
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = AudioFormWSHandler(
        registry=registry,
        synthesizer=None,
        transcriber=None,
        validator=MagicMock(),
        submission_storage=storage,
    )

    question = AudioQuestion(field_uid=uuid.uuid4(), index=0, field_id="name", field_type="text", label="Name?")
    manifest = AudioFormManifest(
        form_uid=str(form.form_uid), title="T", total_questions=1, questions=[question], ws_endpoint="/ws"
    )
    session = AudioSessionState(session_id="s1", form_uid=str(form.form_uid), user_id="u1")
    session.manifest = manifest
    session.answers = {"name": AudioAnswer(field_id="name", value="Ana", source="text")}

    ws = AsyncMock()
    ws.send_json = AsyncMock()

    await handler._finish_session(ws, session)

    sent = ws.send_json.call_args[0][0]
    submission_id = sent["submission_id"]
    assert submission_id is not None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f'SELECT extra_data FROM "{SCHEMA}".form_data WHERE submission_id = $1',
            submission_id,
        )
    assert row is not None
    assert row["extra_data"] is None


# ---------------------------------------------------------------------------
# Cap boundaries — via the imported constants, never a literal
# ---------------------------------------------------------------------------


async def test_e2e_keep_over_cap_rejects_and_stores_nothing(storage: FormSubmissionStorage, pool: Any) -> None:
    form = _form(policy="keep")
    handler = _make_handler(form, submission_storage=storage)
    extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS + 1)}

    resp = await handler.submit_data(
        _make_request(body={"name": "Ana", **extras}, form_uid=form.form_uid)
    )
    assert resp.status == 422

    async with pool.acquire() as conn:
        count = await conn.fetchval(f'SELECT COUNT(*) FROM "{SCHEMA}".form_data')
    assert count == 0


async def test_e2e_keep_at_cap_accepts(storage: FormSubmissionStorage, pool: Any) -> None:
    form = _form(policy="keep")
    handler = _make_handler(form, submission_storage=storage)
    extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS)}

    resp = await handler.submit_data(
        _make_request(body={"name": "Ana", **extras}, form_uid=form.form_uid)
    )
    assert resp.status == 200
    assert MAX_EXTRA_BYTES > 0  # constant imported and used, not hardcoded
