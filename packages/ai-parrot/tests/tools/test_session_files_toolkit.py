"""Tests for SessionFileToolkit binding, isolation and prefix naming."""
from datetime import datetime, timezone
from itertools import count

import pytest

from parrot.interfaces.file.session import SessionFileRecord, SessionFileStore
from parrot.tools.session_files import NoBoundSession, SessionFileToolkit
from parrot.utils.helpers import RequestContext, _current_ctx


class _FakeStore(SessionFileStore):
    """In-memory stand-in so the toolkit is tested independently of disk writes."""

    def __init__(self, root):
        super().__init__(root=root)
        self._records = {}
        self._ids = count(1)

    async def put_bytes(self, session_id, filename, data, *, origin="upload"):
        rec = SessionFileRecord(
            file_id=f"f{next(self._ids)}", session_id=session_id, filename=filename,
            mime_type="text/plain", size=len(data), origin=origin,
            created_at=datetime.now(timezone.utc),
        )
        self._records.setdefault(session_id, []).append(rec)
        return rec

    async def list_files(self, session_id):
        return list(self._records.get(session_id, []))


@pytest.fixture
def toolkit(tmp_path):
    return SessionFileToolkit(store=_FakeStore(tmp_path))


@pytest.fixture
def bind():
    """Bind a RequestContext for the duration of a test, then reset the ContextVar."""

    def _bind(session_id):
        _current_ctx.set(RequestContext(session_id=session_id))

    yield _bind
    # Tokens cannot be reset across the fixture/test context boundary; clear instead.
    _current_ctx.set(None)


class TestSessionBinding:
    async def test_refuses_without_session(self, toolkit):
        with pytest.raises(NoBoundSession) as exc:
            await toolkit.list_session_files()
        assert exc.value.code == "no_session"

    async def test_refuses_store_without_session(self, toolkit):
        with pytest.raises(NoBoundSession):
            await toolkit.store_generated_file("a.txt", "x")

    async def test_lists_only_current_session(self, toolkit, bind):
        bind("s1")
        await toolkit.store_generated_file("a.txt", "hello")
        bind("s2")
        assert (await toolkit.list_session_files())["files"] == []
        bind("s1")
        files = (await toolkit.list_session_files())["files"]
        assert [f["filename"] for f in files] == ["a.txt"]

    def test_tool_names_carry_the_prefix(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        assert {"sf_list_session_files", "sf_store_generated_file"} <= names

    async def test_output_has_no_path(self, toolkit, bind, tmp_path):
        bind("s1")
        out = await toolkit.store_generated_file("a.txt", "héllo")
        assert out["size"] == len("héllo".encode("utf-8"))
        listing = (await toolkit.list_session_files())["files"]
        assert set(listing[0]) == {"file_id", "filename", "mime_type", "size", "origin"}
        assert listing[0]["origin"] == "generated"
        assert str(tmp_path) not in repr(out) + repr(listing)
