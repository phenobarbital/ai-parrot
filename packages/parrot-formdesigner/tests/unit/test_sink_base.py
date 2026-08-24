"""Unit tests for `parrot_formdesigner.services.sinks.base` (FEAT-457, TASK-2419)."""

import pytest
from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkNotCapableError,
    SinkTargetMismatchError,
    SinkUnavailableError,
)


class WriteOnlySink(AbstractSubmissionSink):
    @property
    def capabilities(self):
        return frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})

    async def ensure_target(self, form):
        return None

    async def write(self, submission, payload):
        return submission.submission_id


class TestSinkABC:
    def test_write_only_sink_instantiates(self):
        assert WriteOnlySink() is not None

    @pytest.mark.asyncio
    async def test_read_raises_not_capable(self):
        with pytest.raises(SinkNotCapableError):
            await WriteOnlySink().read("abc")

    @pytest.mark.asyncio
    async def test_list_revisions_raises_not_capable(self):
        with pytest.raises(SinkNotCapableError):
            await WriteOnlySink().list_revisions("abc")

    def test_require_rejects_missing_capability(self):
        with pytest.raises(SinkNotCapableError):
            WriteOnlySink().require(SinkCapability.READ)

    def test_require_allows_declared_capability(self):
        WriteOnlySink().require(SinkCapability.WRITE)  # does not raise

    @pytest.mark.asyncio
    async def test_close_default_noop(self):
        await WriteOnlySink().close()  # does not raise

    def test_capabilities_is_frozenset(self):
        assert isinstance(WriteOnlySink().capabilities, frozenset)

    def test_error_hierarchy(self):
        assert issubclass(SinkUnavailableError, Exception)
        assert issubclass(SinkNotCapableError, Exception)
        assert issubclass(SinkTargetMismatchError, Exception)

    def test_error_docstrings_name_http_status(self):
        assert "503" in SinkUnavailableError.__doc__
        assert "501" in SinkNotCapableError.__doc__
        assert "422" in SinkTargetMismatchError.__doc__

    def test_cannot_instantiate_missing_abstract_methods(self):
        with pytest.raises(TypeError):
            AbstractSubmissionSink()  # type: ignore[abstract]
