"""BasicAgent.handle_files persists every upload (FEAT-639, TASK-4132)."""

from unittest.mock import MagicMock

import pytest

from parrot.bots.agent import BasicAgent
from parrot.interfaces.file.session import SessionFileStore
from parrot.utils.helpers import RequestContext, _current_ctx


@pytest.fixture
def basic_agent(tmp_path):
    """A BasicAgent shell whose session store lives under tmp_path."""
    agent = BasicAgent.__new__(BasicAgent)
    agent.logger = MagicMock()
    agent.add_dataframe = MagicMock()
    agent._session_file_store = SessionFileStore(tmp_path)
    return agent


@pytest.fixture
def bound_session():
    """Bind a RequestContext carrying a session id for the test."""
    token = _current_ctx.set(RequestContext(session_id="sess-1"))
    yield "sess-1"
    _current_ctx.reset(token)


class _Boom:
    """Upload whose read() fails."""

    def read(self):
        raise OSError("unreadable")


@pytest.mark.asyncio
class TestHandleFilesPersistence:
    async def test_persists_docx(self, basic_agent, bound_session):
        """Spec AC1 - a .docx upload becomes a resolvable handle."""
        result = await basic_agent.handle_files({"report.docx": b"PK\x03\x04"})
        assert result["errors"] == []
        assert result["dataframes"] == []
        file_id = result["files"][0]["file_id"]
        record, path = await basic_agent._session_store().resolve(bound_session, file_id)
        assert record.filename == "report.docx"
        assert path.read_bytes() == b"PK\x03\x04"

    async def test_csv_is_dataframe_and_file(self, basic_agent, bound_session):
        """A tabular upload takes both paths."""
        result = await basic_agent.handle_files({"data.csv": b"a,b\n1,2"})
        assert result["dataframes"] == ["data"]
        assert len(result["files"]) == 1

    async def test_unreadable_file_does_not_abort_others(self, basic_agent, bound_session):
        """One bad file -> one errors entry, the rest still stored."""
        result = await basic_agent.handle_files({"bad.docx": _Boom(), "ok.docx": b"x"})
        assert [e["filename"] for e in result["errors"]] == ["bad.docx"]
        assert [f["filename"] for f in result["files"]] == ["ok.docx"]

    async def test_no_bound_session_reports_error(self, basic_agent):
        """Unbound -> errors, never an exception."""
        result = await basic_agent.handle_files({"report.docx": b"x"})
        assert result["files"] == []
        assert result["errors"][0]["error"] == "no bound session"
