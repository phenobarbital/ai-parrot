"""Bounded download of remote media URLs to temp files (FEAT-601 M12).

Used by channels that cannot send a remote URL directly (Telegram ``send_photo``) and as the WhatsApp
fallback. Default deny: only hosts in the allowlist are fetched, on every redirect hop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import aiohttp

logger = logging.getLogger(__name__)

MEDIA_HOSTS_ENV = "PARROT_MEDIA_URL_HOSTS"
MAX_REDIRECTS = 3
_CHUNK_SIZE = 65536
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class MediaDownloadRefused(ValueError):
    """Raised when a URL, redirect hop, size or timeout violates the download policy."""


def allowed_media_hosts() -> tuple[str, ...]:
    """Return the lower-cased host allowlist from ``PARROT_MEDIA_URL_HOSTS`` (comma-separated).

    Returns:
        A tuple of lower-cased, non-blank hostnames. Empty when the env var is unset or blank.
    """
    raw = os.environ.get(MEDIA_HOSTS_ENV, "")
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def _check_host(url: str, allowed_hosts: Sequence[str]) -> None:
    """Raise :class:`MediaDownloadRefused` unless ``url`` is http(s) and its host is allowlisted.

    Args:
        url: Absolute URL to validate (initial request or a redirect hop).
        allowed_hosts: Hosts permitted for this request.

    Raises:
        MediaDownloadRefused: The scheme is not http(s), or the host is not in ``allowed_hosts``
            (including the case where ``allowed_hosts`` is empty — default deny).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise MediaDownloadRefused(f"Unsupported scheme for media URL: {url!r}")
    host = (parts.hostname or "").lower()
    allowed = {h.lower() for h in allowed_hosts}
    if not host or not allowed or host not in allowed:
        raise MediaDownloadRefused(f"Host {host!r} is not allowlisted for media URL {url!r}")


async def download_to_temp(
    url: str,
    *,
    allowed_hosts: Sequence[str],
    max_bytes: int = 10 * 1024 * 1024,
    timeout_s: float = 15.0,
) -> Path:
    """Download ``url`` to a new temp file and return its path; the caller removes it.

    Args:
        url: Absolute http(s) URL.
        allowed_hosts: Hosts permitted for the initial request and every redirect hop.
        max_bytes: Hard cap on the body size.
        timeout_s: Total request timeout in seconds.

    Returns:
        Path of the downloaded temp file (suffix guessed from the URL path).

    Raises:
        MediaDownloadRefused: Foreign host, too many redirects, oversize body, non-2xx or timeout.
    """
    _check_host(url, allowed_hosts)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    current_url = url
    tmp_path: Optional[Path] = None
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _hop in range(MAX_REDIRECTS + 1):
                async with session.get(current_url, allow_redirects=False) as resp:
                    if resp.status in _REDIRECT_STATUSES:
                        location = resp.headers.get("Location")
                        if not location:
                            raise MediaDownloadRefused(f"Redirect from {current_url!r} has no Location header")
                        current_url = urljoin(current_url, location)
                        _check_host(current_url, allowed_hosts)
                        continue

                    if resp.status >= 400:
                        raise MediaDownloadRefused(f"Non-2xx status {resp.status} for {current_url!r}")

                    content_length = resp.headers.get("Content-Length")
                    if content_length is not None and int(content_length) > max_bytes:
                        raise MediaDownloadRefused(
                            f"Content-Length {content_length} exceeds max_bytes {max_bytes} for {current_url!r}"
                        )

                    suffix = Path(urlsplit(current_url).path).suffix
                    fd, tmp_name = tempfile.mkstemp(suffix=suffix)
                    tmp_path = Path(tmp_name)
                    downloaded = 0
                    with os.fdopen(fd, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                raise MediaDownloadRefused(
                                    f"Body exceeded max_bytes {max_bytes} while streaming {current_url!r}"
                                )
                            fh.write(chunk)
                    return tmp_path

            raise MediaDownloadRefused(f"Too many redirects (> {MAX_REDIRECTS}) for {url!r}")
    except MediaDownloadRefused:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
        raise MediaDownloadRefused(f"Download failed for {url!r}: {exc}") from exc


@contextlib.asynccontextmanager
async def temp_download(url: str, **kwargs: object) -> AsyncIterator[Path]:
    """Async context manager around :func:`download_to_temp` that always removes the file on exit."""
    path = await download_to_temp(url, **kwargs)  # type: ignore[arg-type]
    try:
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
