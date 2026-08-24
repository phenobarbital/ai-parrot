"""Unit tests for `GoogleSheetSink` (FEAT-457, TASK-2425).

Uses a fake Sheets client double — no real Google API calls.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.persistence import GoogleSheetTarget, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import SinkUnavailableError
from parrot_formdesigner.services.sinks.gsheet import GoogleSheetSink
from parrot_formdesigner.services.submissions import FormSubmission


class _FakeSheetsClient:
    def __init__(self, rate_limited: bool = False) -> None:
        self.header: list[str] | None = None
        self.header_written = False
        self.columns_appended = 0
        self.rows: list[list] = []
        self.attempts = 0
        self._rate_limited = rate_limited

    def get_header(self):
        return self.header

    def write_header(self, header):
        self.header = list(header)
        self.header_written = True

    def append_column(self, name):
        self.header = [*(self.header or []), name]
        self.columns_appended += 1

    def append_row(self, row):
        self.attempts += 1
        if self._rate_limited:
            raise RuntimeError("429 Too Many Requests")
        self.rows.append(row)


def _target() -> GoogleSheetTarget:
    return GoogleSheetTarget(
        type="gsheet",
        connection="sheets_alias",
        spreadsheet_id="abc123",
        worksheet="Sheet1",
    )


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
def form_with_extra_field():
    section = FormSection(
        section_id="s1",
        fields=[
            FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
            FormField(field_id="rating", field_type=FieldType.INTEGER, label="Rating"),
        ],
    )
    return FormSchema(form_id="nps", title="NPS", sections=[section])


@pytest.fixture
def submission():
    return _submission()


@pytest.fixture
def fake_client():
    return _FakeSheetsClient()


@pytest.fixture
def gsheet_sink(fake_client):
    return GoogleSheetSink(
        _target(), alias_registry=SinkAliasRegistry(), tenant="navigator", client=fake_client
    )


@pytest.fixture
def gsheet_sink_429():
    client = _FakeSheetsClient(rate_limited=True)
    return GoogleSheetSink(
        _target(), alias_registry=SinkAliasRegistry(), tenant="navigator", client=client
    )


class TestGuardedImport:
    def test_module_imports_without_extra(self, monkeypatch):
        import parrot_formdesigner.services.sinks.gsheet as mod

        monkeypatch.setattr(mod, "build", None)
        assert mod is not None

    async def test_use_without_extra_is_actionable(self, monkeypatch, form):
        import parrot_formdesigner.services.sinks.gsheet as mod

        monkeypatch.setattr(mod, "build", None)
        sink = GoogleSheetSink(
            _target(), alias_registry=SinkAliasRegistry(), tenant="navigator"
        )
        with pytest.raises(SinkUnavailableError, match="gsheet"):
            await sink.ensure_target(form)


class TestProvision:
    async def test_creates_header(self, gsheet_sink, fake_client, form):
        await gsheet_sink.ensure_target(form)
        assert fake_client.header_written
        assert fake_client.header[0] == "submission_id"

    async def test_new_field_appends_column(
        self, gsheet_sink, fake_client, form, form_with_extra_field
    ):
        await gsheet_sink.ensure_target(form)
        fake_client.header_written = False
        await gsheet_sink.ensure_target(form_with_extra_field)
        assert fake_client.columns_appended == 1
        assert "rating" in fake_client.header
        assert "comment" in fake_client.header  # existing column preserved


class TestFailure:
    async def test_rate_limit_maps_unavailable(self, gsheet_sink_429, submission):
        with pytest.raises(SinkUnavailableError):
            await gsheet_sink_429.write(submission, {})

    async def test_no_retry_on_429(self, gsheet_sink_429, submission):
        with pytest.raises(SinkUnavailableError):
            await gsheet_sink_429.write(submission, {})
        client = gsheet_sink_429._client
        assert client.attempts == 1


class TestCapabilities:
    def test_capability_set(self, gsheet_sink):
        assert gsheet_sink.capabilities == frozenset(
            {SinkCapability.WRITE, SinkCapability.PROVISION, SinkCapability.EXTEND}
        )


class TestNoBlockingCall:
    async def test_write_uses_to_thread(self, gsheet_sink, fake_client, submission, monkeypatch):
        calls = []
        real_to_thread = asyncio.to_thread

        async def spy(func, *args, **kwargs):
            calls.append(func)
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy)
        await gsheet_sink.write(submission, {"comment": "great"})
        assert fake_client.append_row in calls
