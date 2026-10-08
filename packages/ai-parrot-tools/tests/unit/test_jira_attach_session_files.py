"""Tests for JiraToolkit._attach_session_files (TASK-4139)."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from jira.exceptions import JIRAError

from parrot.interfaces.file.session import SessionFileStore
from parrot_tools import jiratoolkit as jt
from parrot_tools.jiratoolkit import JiraToolkit


@pytest.fixture
def store(tmp_path):
    return SessionFileStore(root=tmp_path / "sessions")


@pytest.fixture
def toolkit(store, monkeypatch):
    monkeypatch.delenv("JIRA_MAX_ATTACHMENT_BYTES", raising=False)
    monkeypatch.setattr(jt, "nav_config", None)
    tk = JiraToolkit.__new__(JiraToolkit)
    tk.logger = logging.getLogger("test_attach")
    tk.jira = MagicMock()
    tk.jira.add_attachment.side_effect = lambda issue, attachment: SimpleNamespace(
        id="900", filename="x", size=3
    )
    tk._session_file_store = store

    async def _limit():
        return 100

    tk._max_attachment_bytes = _limit
    return tk


@pytest.fixture
def bound_session(monkeypatch):
    monkeypatch.setattr(jt, "current_context", lambda: SimpleNamespace(session_id="s1"))


async def test_one_result_per_handle_in_order(toolkit, store, bound_session):
    a = await store.put_bytes("s1", "a.docx", b"aaa")
    b = await store.put_bytes("s1", "b.docx", b"bbb")
    res = await toolkit._attach_session_files("A-1", [b.file_id, a.file_id])
    assert [r.file_id for r in res] == [b.file_id, a.file_id]
    assert all(r.ok for r in res)


async def test_empty_file_not_uploaded(toolkit, store, bound_session):
    e = await store.put_bytes("s1", "e.docx", b"")
    res = await toolkit._attach_session_files("A-1", [e.file_id])
    assert res[0].error_code == "empty_file"
    toolkit.jira.add_attachment.assert_not_called()


async def test_oversize_not_uploaded(toolkit, store, bound_session):
    big = await store.put_bytes("s1", "big.docx", b"x" * 101)
    res = await toolkit._attach_session_files("A-1", [big.file_id])
    assert res[0].error_code == "too_large"
    assert "100" in res[0].detail
    toolkit.jira.add_attachment.assert_not_called()


async def test_unknown_and_traversal_handles(toolkit, bound_session):
    res = await toolkit._attach_session_files("A-1", ["nope", "../../etc/passwd"])
    assert res[0].error_code == "unknown_handle"
    assert res[1].error_code == "outside_sandbox"


async def test_no_session_marks_every_input(toolkit, monkeypatch):
    monkeypatch.setattr(jt, "current_context", lambda: None)
    res = await toolkit._attach_session_files("A-1", ["a", "b"])
    assert [r.error_code for r in res] == ["no_session", "no_session"]


async def test_jira_403_maps_to_forbidden_with_bounded_detail(toolkit, store, bound_session):
    f = await store.put_bytes("s1", "a.docx", b"aaa")
    toolkit.jira.add_attachment.side_effect = JIRAError(
        status_code=403, text="<html>" + "x" * 50000
    )
    res = await toolkit._attach_session_files("A-1", [f.file_id])
    assert res[0].error_code == "forbidden"
    assert len(res[0].detail) <= 500


async def test_other_4xx_rejected_and_5xx_transport(toolkit, store, bound_session):
    f = await store.put_bytes("s1", "a.docx", b"aaa")
    toolkit.jira.add_attachment.side_effect = JIRAError(status_code=413, text="big")
    assert (await toolkit._attach_session_files("A-1", [f.file_id]))[0].error_code == "rejected"
    toolkit.jira.add_attachment.side_effect = JIRAError(status_code=502, text="bad")
    assert (await toolkit._attach_session_files("A-1", [f.file_id]))[0].error_code == "transport_error"


async def test_mixed_handles_are_best_effort(toolkit, store, bound_session):
    f = await store.put_bytes("s1", "a.docx", b"aaa")
    res = await toolkit._attach_session_files("A-1", [f.file_id, "bogus"])
    assert res[0].ok and res[0].attachment_id == "900"
    assert not res[1].ok and res[1].error_code == "unknown_handle"
