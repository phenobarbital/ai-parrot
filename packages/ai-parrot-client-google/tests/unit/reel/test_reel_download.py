"""TASK-3325: bounded, origin-restricted media downloader tests.

Mocks `aiohttp.ClientSession` transport (a fake session/response pair
supporting the same async-context-manager protocol) so the REAL
`ProviderMediaDownloader.fetch()` redirect-following, credential-decision,
byte/deadline-bound and cleanup logic is exercised end to end without any
live network call or new test dependency (no `aioresponses`).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from parrot.clients.google.reel.download import DEFAULT_CREDENTIAL_ORIGINS, ProviderMediaDownloader
from parrot.clients.google.reel.errors import DownloadFailure

ALLOWED_HOST = next(iter(DEFAULT_CREDENTIAL_ORIGINS))  # generativelanguage.googleapis.com


class _FakeResponse:
    """Async-context-manager response double matching the aiohttp shape `fetch()` uses."""

    def __init__(
        self,
        *,
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
        content_type: str = "video/mp4",
        chunks: Optional[List[bytes]] = None,
        delay_before_chunk: Optional[Dict[int, float]] = None,
    ):
        self.status = status
        self.headers = headers or {}
        self.content_type = content_type
        self._chunks = chunks or []
        self._delay_before_chunk = delay_before_chunk or {}
        self.content = self

    async def iter_chunked(self, size: int):
        for i, chunk in enumerate(self._chunks):
            if i in self._delay_before_chunk:
                await asyncio.sleep(self._delay_before_chunk[i])
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _CancellingResponse(_FakeResponse):
    """Raises CancelledError partway through iteration."""

    async def iter_chunked(self, size: int):
        yield self._chunks[0]
        raise asyncio.CancelledError()


class _FakeSession:
    """Records every GET and returns the next queued response for its URL."""

    def __init__(self, responses_by_url: Dict[str, Any]):
        self._responses = responses_by_url
        self.requests: List[Dict[str, Any]] = []

    def get(self, url, *, headers=None, allow_redirects=False, timeout=None):
        self.requests.append({"url": url, "headers": dict(headers or {})})
        entry = self._responses[url]
        return entry() if callable(entry) else entry

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def close(self):
        pass


def _patched(responses_by_url: Dict[str, Any]):
    session = _FakeSession(responses_by_url)
    return patch("parrot.clients.google.reel.download.aiohttp.ClientSession", return_value=session), session


FAR_DEADLINE = lambda: time.monotonic() + 30.0  # noqa: E731


class TestSuccessfulFetch:
    async def test_fetches_and_writes_bytes(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/clip.mp4"
        resp = _FakeResponse(chunks=[b"AAAA", b"BBBB"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader(credential_provider=lambda: "tok-123")
            dest = tmp_path / "out.mp4"
            result = await downloader.fetch(url, dest, max_bytes=1000, deadline=FAR_DEADLINE())

        assert result == dest
        assert dest.read_bytes() == b"AAAABBBB"

    async def test_credential_attached_for_allowlisted_origin(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/clip.mp4"
        resp = _FakeResponse(chunks=[b"X"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader(credential_provider=lambda: "tok-123")
            await downloader.fetch(url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

        assert session.requests[0]["headers"].get("Authorization") == "Bearer tok-123"


class TestCredentialScoping:
    async def test_no_credential_for_non_allowlisted_origin(self, tmp_path):
        url = "https://cdn.example.com/signed?sig=abc123"
        resp = _FakeResponse(chunks=[b"X"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader(credential_provider=lambda: "tok-123")
            await downloader.fetch(url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

        assert "Authorization" not in session.requests[0]["headers"]

    async def test_signed_query_string_left_untouched(self, tmp_path):
        url = "https://cdn.example.com/signed?sig=abc123&exp=999"
        resp = _FakeResponse(chunks=[b"X"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader(credential_provider=lambda: "tok-123")
            await downloader.fetch(url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

        assert session.requests[0]["url"] == url

    async def test_credential_revalidated_after_cross_origin_redirect(self, tmp_path):
        """A redirect from an allowlisted origin to a non-allowlisted one must
        NOT carry the credential onto the second hop."""
        start_url = f"https://{ALLOWED_HOST}/op/123"
        redirect_target = "https://cdn.example.com/signed?sig=abc"
        redirect_resp = _FakeResponse(status=302, headers={"Location": redirect_target})
        final_resp = _FakeResponse(chunks=[b"X"])
        patcher, session = _patched({start_url: redirect_resp, redirect_target: final_resp})
        with patcher:
            downloader = ProviderMediaDownloader(credential_provider=lambda: "tok-123")
            await downloader.fetch(start_url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

        assert session.requests[0]["headers"].get("Authorization") == "Bearer tok-123"
        assert "Authorization" not in session.requests[1]["headers"]


class TestRejections:
    async def test_unsupported_scheme_rejected(self, tmp_path):
        downloader = ProviderMediaDownloader()
        with pytest.raises(DownloadFailure):
            await downloader.fetch(
                "http://example.com/clip.mp4", tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE()
            )

    async def test_loopback_ip_rejected(self, tmp_path):
        downloader = ProviderMediaDownloader()
        with pytest.raises(DownloadFailure):
            await downloader.fetch(
                "https://127.0.0.1/clip.mp4", tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE()
            )

    async def test_private_ip_rejected(self, tmp_path):
        downloader = ProviderMediaDownloader()
        with pytest.raises(DownloadFailure):
            await downloader.fetch(
                "https://10.0.0.5/clip.mp4", tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE()
            )

    async def test_redirect_to_insecure_scheme_rejected(self, tmp_path):
        start_url = f"https://{ALLOWED_HOST}/op/1"
        redirect_resp = _FakeResponse(status=302, headers={"Location": "http://evil.example.com/x"})
        patcher, session = _patched({start_url: redirect_resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            with pytest.raises(DownloadFailure):
                await downloader.fetch(start_url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

    async def test_too_many_redirects_raises(self, tmp_path):
        urls = [f"https://{ALLOWED_HOST}/hop{i}" for i in range(10)]
        responses = {
            urls[i]: _FakeResponse(status=302, headers={"Location": urls[i + 1]}) for i in range(len(urls) - 1)
        }
        patcher, session = _patched(responses)
        with patcher:
            downloader = ProviderMediaDownloader(max_redirects=3)
            with pytest.raises(DownloadFailure):
                await downloader.fetch(urls[0], tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

    async def test_non_2xx_status_raises(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/missing"
        resp = _FakeResponse(status=404)
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())

    async def test_html_error_page_content_type_rejected(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/oops"
        resp = _FakeResponse(status=200, content_type="text/html", chunks=[b"<html>error</html>"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            dest = tmp_path / "out.mp4"
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, dest, max_bytes=1000, deadline=FAR_DEADLINE())
        assert not dest.exists()

    async def test_declared_content_length_over_limit_rejected(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/big"
        resp = _FakeResponse(headers={"Content-Length": "10000"})
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            dest = tmp_path / "out.mp4"
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, dest, max_bytes=100, deadline=FAR_DEADLINE())
        assert not dest.exists()

    async def test_actual_bytes_over_limit_cleans_partial_file(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/big"
        resp = _FakeResponse(chunks=[b"A" * 60, b"B" * 60])  # 120 bytes total
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            dest = tmp_path / "out.mp4"
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, dest, max_bytes=100, deadline=FAR_DEADLINE())
        assert not dest.exists()

    async def test_malformed_uri_missing_host_rejected(self, tmp_path):
        downloader = ProviderMediaDownloader()
        with pytest.raises(DownloadFailure):
            await downloader.fetch("https:///no-host", tmp_path / "out.mp4", max_bytes=1000, deadline=FAR_DEADLINE())


class TestDeadlineAndCancellation:
    async def test_already_expired_deadline_raises_without_request(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/clip.mp4"
        resp = _FakeResponse(chunks=[b"X"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, tmp_path / "out.mp4", max_bytes=1000, deadline=time.monotonic() - 1.0)
        assert session.requests == []

    async def test_deadline_exceeded_mid_stream_cleans_partial_file(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/clip.mp4"
        resp = _FakeResponse(chunks=[b"A", b"B"], delay_before_chunk={1: 0.15})
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            dest = tmp_path / "out.mp4"
            with pytest.raises(DownloadFailure):
                await downloader.fetch(url, dest, max_bytes=1000, deadline=time.monotonic() + 0.05)
        assert not dest.exists()

    async def test_cancellation_propagates_and_cleans_partial_file(self, tmp_path):
        url = f"https://{ALLOWED_HOST}/clip.mp4"
        resp = _CancellingResponse(chunks=[b"A"])
        patcher, session = _patched({url: resp})
        with patcher:
            downloader = ProviderMediaDownloader()
            dest = tmp_path / "out.mp4"
            with pytest.raises(asyncio.CancelledError):
                await downloader.fetch(url, dest, max_bytes=1000, deadline=FAR_DEADLINE())
        assert not dest.exists()
