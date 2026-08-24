"""Unit tests for `AsyncDBSink` (FEAT-457, TASK-2423).

Uses a fake asyncdb-driver double — no real Mongo/Arango/BigQuery backend
required.
"""

import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.persistence import AsyncDBTarget, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.asyncdb_store import AsyncDBSink
from parrot_formdesigner.services.sinks.base import SinkUnavailableError
from parrot_formdesigner.services.submissions import FormSubmission


class _FakeDriver:
    """Records every write call; implements the real per-driver method
    names verified against the installed `asyncdb` package."""

    def __init__(self) -> None:
        self.written: list[dict] = []
        self._database_name = "testdb"

    async def connection(self):
        return self

    async def close(self) -> None:
        return None

    # mongo
    async def insert(self, collection_name: str, data, **kwargs):
        self.written.append(dict(data))
        return {"ok": True}

    async def list_collections(self, *args, **kwargs):
        return []

    async def create_collection(self, **kwargs):
        return True

    async def fetch_one(self, collection_name, query=None, *args, **kwargs):
        return None

    async def fetch(self, collection_name, query=None, *args, **kwargs):
        return []

    # arango
    async def insert_document(self, collection: str, document, return_new=True):
        self.written.append(dict(document))
        return document

    async def collection_exists(self, name: str) -> bool:
        return False

    async def query(self, sentence: str, bind_vars=None, **kwargs):
        return [], None

    # bigquery
    async def write(self, data, table_id=None, dataset_id=None, **kwargs):
        self.written.append(dict(data[0]))
        return True

    async def create_table(self, dataset_id, table_id, schema):
        return True


class _BrokenDriver:
    async def connection(self):
        raise ConnectionError("simulated driver failure")

    async def close(self) -> None:
        return None


def _target(driver: str, collection: str = "responses") -> AsyncDBTarget:
    return AsyncDBTarget(type="asyncdb", connection="db_alias", driver=driver, collection=collection)


def _submission() -> FormSubmission:
    return FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_uid=uuid.uuid4(),
        form_id="nps",
        form_version="1.0",
        data={"comment": "great"},
        is_valid=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def form():
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
    )
    return FormSchema(form_id="nps", title="NPS", sections=[section])


@pytest.fixture
def form_with_group():
    address = FormField(
        field_id="address",
        field_type=FieldType.GROUP,
        label="Address",
        children=[FormField(field_id="city", field_type=FieldType.TEXT, label="City")],
    )
    section = FormSection(section_id="s1", fields=[address])
    return FormSchema(form_id="nps", title="NPS", sections=[section])


@pytest.fixture
def submission():
    return _submission()


@pytest.fixture
def fake_driver():
    return _FakeDriver()


@pytest.fixture
def mongo_sink(fake_driver, form):
    return AsyncDBSink(
        _target("mongo"),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        driver=fake_driver,
        form=form,
    )


@pytest.fixture
def bigquery_sink(fake_driver, form_with_group):
    return AsyncDBSink(
        _target("bigquery", collection="nps_2026"),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        driver=fake_driver,
        form=form_with_group,
    )


@pytest.fixture
def broken_sink():
    return AsyncDBSink(
        _target("mongo"),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        driver=_BrokenDriver(),
    )


class TestMappingMode:
    async def test_document_driver_nests(self, mongo_sink, fake_driver, form, submission):
        await mongo_sink.write(submission, None)
        payload = fake_driver.written[-1]
        assert payload["data"] == submission.data
        assert not any("__" in k for k in payload)

    async def test_tabular_driver_flattens(self, bigquery_sink, fake_driver, form_with_group, submission):
        submission.data = {"address": {"city": "Tampa"}}
        await bigquery_sink.write(submission, None)
        assert any("__" in k for k in fake_driver.written[-1])


class TestCapabilities:
    def test_document_driver_capability_set(self, mongo_sink):
        assert SinkCapability.WRITE in mongo_sink.capabilities
        assert SinkCapability.EXTEND not in mongo_sink.capabilities

    def test_tabular_driver_has_extend(self, bigquery_sink):
        assert SinkCapability.EXTEND in bigquery_sink.capabilities


class TestFailure:
    async def test_driver_error_maps_unavailable(self, broken_sink, submission):
        with pytest.raises(SinkUnavailableError):
            await broken_sink.write(submission, None)

    async def test_write_without_form_or_payload_raises(self, fake_driver, submission):
        sink = AsyncDBSink(
            _target("mongo"),
            alias_registry=SinkAliasRegistry(),
            tenant="navigator",
            driver=fake_driver,
        )
        with pytest.raises(SinkUnavailableError):
            await sink.write(submission, None)


class TestExplicitPayload:
    async def test_write_accepts_explicit_payload(self, mongo_sink, fake_driver, submission):
        result = await mongo_sink.write(submission, {"submission_id": "abc"})
        assert result == submission.submission_id
        assert fake_driver.written[-1] == {"submission_id": "abc"}


class TestImportGuard:
    def test_module_imports_without_google_cloud_bigquery(self):
        # The module itself never imports google.cloud.bigquery at module
        # level — only inside ensure_target()'s bigquery branch.
        import parrot_formdesigner.services.sinks.asyncdb_store as mod

        assert mod is not None
