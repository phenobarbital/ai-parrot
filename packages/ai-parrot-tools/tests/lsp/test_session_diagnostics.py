"""Unit/integration tests for FEAT-580 M2 document sync and diagnostics.

``PyrightSession`` is started against the scripted, deterministic
``fake_server.py`` fixture (already built for M1/M2) over a real subprocess
pipe for lifecycle/liveness — never a live Pyright install. Because that
fixture's only diagnostics-producing scenario (``happy_path``) always
publishes a single fixed ``textDocument/publishDiagnostics`` notification
for ``file:///scenario.py`` (a URI that never resolves inside a pytest
``tmp_path`` root), freshness/matching/overflow scenarios are exercised by
feeding synthetic notifications through the session's own private
dispatch seam (:meth:`PyrightSession._dispatch_message`) — exactly the
same private-seam testing style already used by
``test_session_lifecycle.py`` (e.g. ``_build_server_response``,
``_notifications``, ``_drain_notifications``).
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import urllib.parse
from pathlib import Path

import pytest

from parrot_tools.lsp.models import LSPConfig, LSPFailure, SourceState
from parrot_tools.lsp.protocol import ParsedMessage
from parrot_tools.lsp.session import PyrightSession

FAKE_SERVER = Path(__file__).parent / "fake_server.py"

#: Generous per-call timeout for a well-behaved exchange.
_TIMEOUT_S = 2.0

_VERSION_OK_COMMAND = [sys.executable, "-c", "print('pyright 1.1.414')"]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _uri(tmp_path: Path, path: str) -> str:
    """Build a ``file://`` URI independently of the session's own encoder."""
    return "file://" + urllib.parse.quote((tmp_path / path).as_posix())


def _publish_diagnostics(
    tmp_path: Path,
    path: str,
    *,
    version: int | None,
    items: list[dict],
) -> ParsedMessage:
    """Build a synthetic ``textDocument/publishDiagnostics`` notification."""
    params: dict = {"uri": _uri(tmp_path, path), "diagnostics": items}
    if version is not None:
        params["version"] = version
    return ParsedMessage(
        kind="notification",
        id=None,
        method="textDocument/publishDiagnostics",
        params=params,
        result=None,
        error=None,
        raw={},
    )


def _diag_item(message: str, *, line: int = 0, start_char: int = 0, end_char: int = 1) -> dict:
    return {
        "range": {"start": {"line": line, "character": start_char}, "end": {"line": line, "character": end_char}},
        "message": message,
    }


def _make_config(
    tmp_path: Path,
    *,
    scenario: str = "happy_path",
    startup_timeout_s: float = 1.0,
    request_timeout_s: float = 1.0,
) -> LSPConfig:
    """Build a deterministic :class:`LSPConfig` pointed at the fake server."""
    return LSPConfig(
        repo_root=tmp_path,
        server_command=[sys.executable, str(FAKE_SERVER), scenario],
        version_command=list(_VERSION_OK_COMMAND),
        expected_server_version="1.1.414",
        environment_id="test-env",
        startup_timeout_s=startup_timeout_s,
        request_timeout_s=request_timeout_s,
        node_heap_mb=256,
    )


async def _wait_until(predicate, *, timeout: float = 2.0, interval: float = 0.01) -> None:
    """Poll ``predicate`` until truthy, or raise once ``timeout`` elapses.

    Used only to observe that the session's reader loop has reached a
    certain point — the fake server's script blindly treats "the next
    stdin frame" after its ``workspace/configuration`` request as our
    answer, so every test below waits for the two notifications it sends
    only once that exchange truly settled before writing anything else to
    stdin (``sync_documents``), to avoid racing our own reader task.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(interval)


async def _start_settled_session(tmp_path: Path) -> PyrightSession:
    """Start a session against ``happy_path`` and wait for its exchange to settle."""
    session = PyrightSession()
    await session.start(_make_config(tmp_path), generation=1)
    await _wait_until(lambda: len(session._notifications) >= 2)
    return session


# ---------------------------------------------------------------------------
# test_document_open_change_close_versions
# ---------------------------------------------------------------------------


class TestDocumentOpenChangeCloseVersions:
    @pytest.mark.asyncio
    async def test_open_change_noop_and_close(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text_v1 = "x = 1\n"
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text_v1), document_version=1)],
                {"a.py": text_v1},
            )
            assert session._open_documents == {"a.py": 1}
            assert session._open_document_sha["a.py"] == _sha256(text_v1)
            assert session._open_document_text["a.py"] == text_v1

            # Repeating the same (version, sha256) is a no-op.
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text_v1), document_version=1)],
                {"a.py": text_v1},
            )
            assert session._open_documents == {"a.py": 1}

            # A strictly higher version with new content is a didChange.
            text_v2 = "x = 2\n"
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text_v2), document_version=2)],
                {"a.py": text_v2},
            )
            assert session._open_documents == {"a.py": 2}
            assert session._open_document_text["a.py"] == text_v2

            # Dropping "a.py" from the requested set closes it and opens "b.py".
            text_b = "y = 1\n"
            await session.sync_documents(
                [SourceState(path="b.py", sha256=_sha256(text_b), document_version=1)],
                {"b.py": text_b},
            )
            assert "a.py" not in session._open_documents
            assert "a.py" not in session._open_document_sha
            assert "a.py" not in session._open_document_text
            assert session._open_documents == {"b.py": 1}

            # URI round-trip sanity: a repository-relative path survives.
            assert session._path_for_uri(session._uri_for_path("b.py")) == "b.py"
            # A foreign URI outside repo_root never resolves to a local path.
            assert session._path_for_uri("file:///scenario.py") is None
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_same_version_different_content_is_rejected(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "x = 1\n"
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text), document_version=1)], {"a.py": text}
            )
            with pytest.raises(LSPFailure) as excinfo:
                await session.sync_documents(
                    [SourceState(path="a.py", sha256=_sha256("different"), document_version=1)],
                    {"a.py": "different"},
                )
            assert excinfo.value.code == "invalid_request"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_regressing_version_is_rejected(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text_v2 = "x = 2\n"
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text_v2), document_version=2)], {"a.py": text_v2}
            )
            with pytest.raises(LSPFailure) as excinfo:
                await session.sync_documents(
                    [SourceState(path="a.py", sha256=_sha256("x = 1\n"), document_version=1)],
                    {"a.py": "x = 1\n"},
                )
            assert excinfo.value.code == "invalid_request"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_missing_text_is_rejected(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            with pytest.raises(LSPFailure) as excinfo:
                await session.sync_documents([SourceState(path="a.py", sha256=_sha256("x"), document_version=1)], {})
            assert excinfo.value.code == "invalid_request"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_more_than_twenty_documents_is_rejected(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            sources = [SourceState(path=f"f{i}.py", sha256=_sha256(str(i)), document_version=1) for i in range(21)]
            texts = {f"f{i}.py": str(i) for i in range(21)}
            with pytest.raises(LSPFailure) as excinfo:
                await session.sync_documents(sources, texts)
            assert excinfo.value.code == "resource_limit"
            assert session._open_documents == {}
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_sync_documents_before_start_raises_server_crashed(self) -> None:
        session = PyrightSession()
        with pytest.raises(LSPFailure) as excinfo:
            await session.sync_documents([], {})
        assert excinfo.value.code == "server_crashed"


# ---------------------------------------------------------------------------
# test_diagnostic_freshness
# ---------------------------------------------------------------------------


class TestDiagnosticFreshness:
    @pytest.mark.asyncio
    async def test_stale_version_is_ignored_then_fresh_version_matches(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "x = 1\n"
            await session.sync_documents(
                [SourceState(path="a.py", sha256=_sha256(text), document_version=1)], {"a.py": text}
            )

            # A publication for an older/mismatched version is ignored.
            await session._dispatch_message(
                _publish_diagnostics(tmp_path, "a.py", version=0, items=[_diag_item("stale")])
            )
            assert "a.py" not in session._diagnostic_cache

            # A malformed item alongside a well-formed one never crashes the
            # publication; only the well-formed item survives.
            await session._dispatch_message(
                _publish_diagnostics(
                    tmp_path,
                    "a.py",
                    version=1,
                    items=[_diag_item("real problem"), {"range": {}}],
                )
            )

            batch = await session.diagnostics(
                [SourceState(path="a.py", sha256=_sha256(text), document_version=1)], timeout_s=_TIMEOUT_S
            )
            assert batch.complete is True
            assert batch.matched_versions == {"a.py": 1}
            assert len(batch.diagnostics["a.py"]) == 1
            assert batch.diagnostics["a.py"][0].full_message == "real problem"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_diagnostics_waits_for_a_later_matching_publication(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "y = 1\n"
            await session.sync_documents(
                [SourceState(path="c.py", sha256=_sha256(text), document_version=2)], {"c.py": text}
            )

            async def _inject_after_delay() -> None:
                await asyncio.sleep(0.05)
                await session._dispatch_message(
                    _publish_diagnostics(tmp_path, "c.py", version=2, items=[_diag_item("late arrival")])
                )

            injector = asyncio.ensure_future(_inject_after_delay())
            batch = await session.diagnostics(
                [SourceState(path="c.py", sha256=_sha256(text), document_version=2)], timeout_s=_TIMEOUT_S
            )
            await injector
            assert batch.complete is True
            assert batch.diagnostics["c.py"][0].full_message == "late arrival"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_warm_reuse_of_unchanged_source_state_is_instant(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "z = 1\n"
            source = SourceState(path="d.py", sha256=_sha256(text), document_version=1)
            await session.sync_documents([source], {"d.py": text})
            await session._dispatch_message(
                _publish_diagnostics(tmp_path, "d.py", version=1, items=[_diag_item("one")])
            )

            first = await session.diagnostics([source], timeout_s=_TIMEOUT_S)
            assert first.complete is True

            loop = asyncio.get_running_loop()
            started = loop.time()
            second = await session.diagnostics([source], timeout_s=5.0)
            elapsed = loop.time() - started
            assert second.complete is True
            assert second.diagnostics["d.py"][0].full_message == "one"
            assert elapsed < 0.5  # resolved from the warm per-path cache, never waited
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_diagnostics_before_start_raises_server_crashed(self) -> None:
        session = PyrightSession()
        with pytest.raises(LSPFailure) as excinfo:
            await session.diagnostics([], timeout_s=1.0)
        assert excinfo.value.code == "server_crashed"


# ---------------------------------------------------------------------------
# test_matching_empty_publication_clears_diagnostics
# ---------------------------------------------------------------------------


class TestMatchingEmptyPublicationClearsDiagnostics:
    @pytest.mark.asyncio
    async def test_empty_publication_for_new_version_clears_prior_findings(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text_v1 = "x = 1\n"
            source_v1 = SourceState(path="a.py", sha256=_sha256(text_v1), document_version=1)
            await session.sync_documents([source_v1], {"a.py": text_v1})
            await session._dispatch_message(
                _publish_diagnostics(
                    tmp_path, "a.py", version=1, items=[_diag_item("problem-1"), _diag_item("problem-2")]
                )
            )
            first = await session.diagnostics([source_v1], timeout_s=_TIMEOUT_S)
            assert len(first.diagnostics["a.py"]) == 2

            text_v2 = "x = 2\n"
            source_v2 = SourceState(path="a.py", sha256=_sha256(text_v2), document_version=2)
            await session.sync_documents([source_v2], {"a.py": text_v2})
            await session._dispatch_message(_publish_diagnostics(tmp_path, "a.py", version=2, items=[]))

            second = await session.diagnostics([source_v2], timeout_s=_TIMEOUT_S)
            assert second.complete is True
            assert second.diagnostics["a.py"] == []
            assert second.matched_versions == {"a.py": 2}
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# test_unversioned_missing_and_overflow_are_incomplete
# ---------------------------------------------------------------------------


class TestUnversionedMissingAndOverflowAreIncomplete:
    @pytest.mark.asyncio
    async def test_unversioned_publication_is_reported_and_never_matched(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "x = 1\n"
            source = SourceState(path="a.py", sha256=_sha256(text), document_version=1)
            await session.sync_documents([source], {"a.py": text})
            await session._dispatch_message(
                _publish_diagnostics(tmp_path, "a.py", version=None, items=[_diag_item("no version")])
            )

            batch = await session.diagnostics([source], timeout_s=0.2)
            assert batch.complete is False
            assert batch.unversioned_paths == ["a.py"]
            assert batch.missing_paths == []
            assert batch.diagnostics == {}
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_never_published_path_is_reported_missing_at_deadline(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            text = "x = 1\n"
            source = SourceState(path="never.py", sha256=_sha256(text), document_version=1)
            await session.sync_documents([source], {"never.py": text})

            batch = await session.diagnostics([source], timeout_s=0.2)
            assert batch.complete is False
            assert batch.missing_paths == ["never.py"]
            assert batch.unversioned_paths == []
            assert batch.diagnostics == {}
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_raw_diagnostic_cap_demotes_oversized_path_to_missing(self, tmp_path: Path) -> None:
        session = await _start_settled_session(tmp_path)
        try:
            big_text = "x = 1\n"
            small_text = "y = 1\n"
            big_source = SourceState(path="a_big.py", sha256=_sha256(big_text), document_version=1)
            small_source = SourceState(path="b_small.py", sha256=_sha256(small_text), document_version=1)
            await session.sync_documents([big_source, small_source], {"a_big.py": big_text, "b_small.py": small_text})

            big_items = [_diag_item(f"issue-{i}") for i in range(2001)]
            await session._dispatch_message(_publish_diagnostics(tmp_path, "a_big.py", version=1, items=big_items))
            await session._dispatch_message(
                _publish_diagnostics(tmp_path, "b_small.py", version=1, items=[_diag_item("kept")])
            )

            batch = await session.diagnostics([big_source, small_source], timeout_s=_TIMEOUT_S)
            assert batch.complete is False
            assert batch.missing_paths == ["a_big.py"]
            assert "a_big.py" not in batch.diagnostics
            assert "a_big.py" not in batch.matched_versions
            assert batch.diagnostics["b_small.py"][0].full_message == "kept"
            total = sum(len(items) for items in batch.diagnostics.values())
            assert total <= 2000
        finally:
            await session.close()
