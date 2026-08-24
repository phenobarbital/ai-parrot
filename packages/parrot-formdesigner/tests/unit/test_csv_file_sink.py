"""Unit tests for `CsvFileSink` (FEAT-457, TASK-2424)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.persistence import CsvFileTarget, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    SinkNotCapableError,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.csv_file import CsvFileSink
from parrot_formdesigner.services.submissions import FormSubmission


@pytest.fixture
def alias_registry(tmp_path):
    reg = SinkAliasRegistry()
    reg.register("exports", tenant="navigator", base_dir=str(tmp_path))
    return reg


@pytest.fixture
def csv_path(tmp_path):
    return tmp_path / "nps.csv"


@pytest.fixture
def csv_sink(alias_registry):
    target = CsvFileTarget(type="csv_file", connection="exports", path="nps.csv")
    return CsvFileSink(target, alias_registry=alias_registry, tenant="navigator")


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


def _make_submission() -> FormSubmission:
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
def submission_factory():
    return _make_submission


@pytest.fixture
def submission():
    return _make_submission()


@pytest.fixture
def readonly_csv_sink(alias_registry, tmp_path):
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    reg = SinkAliasRegistry()
    reg.register("readonly", tenant="navigator", base_dir=str(readonly_dir))
    target = CsvFileTarget(type="csv_file", connection="readonly", path="nps.csv")
    os.chmod(readonly_dir, 0o500)  # read + execute only, no write
    sink = CsvFileSink(target, alias_registry=reg, tenant="navigator")
    yield sink
    os.chmod(readonly_dir, 0o700)  # restore so tmp_path cleanup can remove it


class TestProvision:
    async def test_creates_header(self, csv_sink, csv_path, form):
        await csv_sink.ensure_target(form)
        assert csv_path.read_text().splitlines()[0].startswith("submission_id")

    async def test_existing_header_untouched(
        self, csv_sink, csv_path, form, form_with_extra_field
    ):
        await csv_sink.ensure_target(form)
        header_before = csv_path.read_text().splitlines()[0]
        await csv_sink.ensure_target(form_with_extra_field)
        assert csv_path.read_text().splitlines()[0] == header_before

    async def test_header_drift_logs_warning(
        self, csv_sink, form, form_with_extra_field, caplog
    ):
        caplog.set_level("WARNING")
        await csv_sink.ensure_target(form)
        await csv_sink.ensure_target(form_with_extra_field)
        assert any("existing CSV header" in r.message for r in caplog.records)


class TestWrite:
    async def test_two_submissions_two_lines(
        self, csv_sink, csv_path, form, submission_factory
    ):
        await csv_sink.ensure_target(form)
        await csv_sink.write(submission_factory(), {})
        await csv_sink.write(submission_factory(), {})
        assert len(csv_path.read_text().strip().splitlines()) == 3

    async def test_single_write_call(self, csv_sink, form, submission, monkeypatch):
        calls = []
        monkeypatch.setattr(csv_sink, "_append", lambda line: calls.append(line))
        await csv_sink.write(submission, {})
        assert len(calls) == 1

    async def test_write_returns_submission_id(self, csv_sink, form, submission):
        await csv_sink.ensure_target(form)
        result = await csv_sink.write(submission, {"comment": "great"})
        assert result == submission.submission_id


class TestCapabilities:
    def test_write_only(self, csv_sink):
        assert csv_sink.capabilities == frozenset(
            {SinkCapability.WRITE, SinkCapability.PROVISION}
        )

    async def test_read_not_capable(self, csv_sink):
        with pytest.raises(SinkNotCapableError):
            await csv_sink.read("abc")

    async def test_list_revisions_not_capable(self, csv_sink):
        with pytest.raises(SinkNotCapableError):
            await csv_sink.list_revisions("abc")


class TestSafety:
    async def test_path_escape_rejected(self, alias_registry):
        target = CsvFileTarget(
            type="csv_file", connection="exports", path="safe.csv"
        )
        sink = CsvFileSink(target, alias_registry=alias_registry, tenant="navigator")
        # Simulate an escape attempt post-construction validation by
        # pointing the alias's base dir resolution at a forged path.
        sink._target = CsvFileTarget.model_construct(
            type="csv_file", connection="exports", path="../escape.csv", delimiter=","
        )
        with pytest.raises(ValueError):
            sink._resolve_path()

    async def test_permission_error_maps_unavailable(self, readonly_csv_sink, form):
        with pytest.raises(SinkUnavailableError):
            await readonly_csv_sink.ensure_target(form)
