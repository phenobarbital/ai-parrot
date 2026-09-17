"""Bounded, origin-restricted media downloader for provider result URIs (FEAT-564, spec module M4).

Manually follows redirects (never ``allow_redirects=True``) so scheme, an
SSRF guard, and credential re-attachment can all be re-validated at every
hop — a redirect Location is never trusted blindly.

Evidence gate (spec §8 Q3, "Omni URI download authentication is unverified"):
this module has no live-verified answer for what host(s) an Omni
``VideoContent.uri`` actually resolves to, or whether it requires a bearer
credential at all. ``DEFAULT_CREDENTIAL_ORIGINS`` is a conservative,
publicly-documented Google API hostname set (not an invented allowlist) used
ONLY to decide whether to attach a caller-supplied credential — it is not a
claim that Omni download URIs live there. See this task's Completion Note.
"""

from __future__ import annotations

import ipaddress
import time
from pathlib import Path
from typing import Callable, FrozenSet, Optional
from urllib.parse import urlsplit

import aiohttp

from .errors import DownloadFailure

# Publicly-documented Google API hostnames. Credentials are attached ONLY
# when a request (initial or post-redirect) targets one of these exact
# hostnames — never inferred from a "google" substring anywhere in the URI.
DEFAULT_CREDENTIAL_ORIGINS: FrozenSet[str] = frozenset(
    {
        "generativelanguage.googleapis.com",
        "storage.googleapis.com",
    }
)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_MAX_REDIRECTS = 5
# Response Content-Types that indicate an error/login page rather than media,
# even on a 200 status — rejected outright rather than saved as if it were
# the requested clip.
_REJECTED_CONTENT_TYPE_PREFIXES = ("text/html", "text/plain")


class ProviderMediaDownloader:
    """Downloads one provider-hosted media URI to a local path, bounded and origin-aware.

    Args:
        credential_provider: Optional zero-arg callable returning a bearer
            token to attach as ``Authorization: Bearer <token>`` — called
            fresh for every hop, only when that hop's host is in
            ``credential_origins``.
        credential_origins: Hostnames credentials may be attached to.
            Defaults to :data:`DEFAULT_CREDENTIAL_ORIGINS`.
        max_redirects: Maximum number of redirect hops followed before
            failing.
    """

    def __init__(
        self,
        *,
        credential_provider: Optional[Callable[[], Optional[str]]] = None,
        credential_origins: FrozenSet[str] = DEFAULT_CREDENTIAL_ORIGINS,
        max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    ) -> None:
        self._credential_provider = credential_provider
        self._credential_origins = credential_origins
        self._max_redirects = max_redirects

    async def fetch(self, uri: str, dest: Path, *, max_bytes: int, deadline: float) -> Path:
        """Downloads ``uri`` to ``dest``, bounded by byte count and an absolute deadline.

        Args:
            uri: The media URI to download. Must be ``https``.
            dest: The local destination path. Only removed by this call if
                THIS call created it (a pre-existing file at ``dest`` is
                never touched on failure).
            max_bytes: Maximum response body size accepted, in bytes.
            deadline: An absolute ``time.monotonic()``-comparable deadline
                (e.g. ``time.monotonic() + remaining_seconds``) — checked
                before every chunk read and every redirect hop, so this call
                shares a job-wide time budget rather than its own relative
                timeout.

        Returns:
            ``dest``, once the full body has been written.

        Raises:
            DownloadFailure: Unsupported scheme, an unauthorized/SSRF-guarded
                destination, too many redirects, a non-2xx status, a
                rejected response content type, or an oversized/expired
                download.
            asyncio.CancelledError: Propagated unchanged; any partial file
                created by this call is removed first.
        """
        current_uri = uri
        created_dest = False
        try:
            async with aiohttp.ClientSession() as session:
                for hop in range(self._max_redirects + 1):
                    self._validate_destination(current_uri)
                    if time.monotonic() > deadline:
                        raise DownloadFailure(f"Download deadline exceeded before hop {hop} ({current_uri}).")

                    headers = self._headers_for(current_uri)
                    remaining = max(0.0, deadline - time.monotonic())
                    timeout = aiohttp.ClientTimeout(total=remaining if remaining > 0 else 0.001)
                    async with session.get(
                        current_uri, headers=headers, allow_redirects=False, timeout=timeout
                    ) as response:
                        if response.status in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                raise DownloadFailure(f"Redirect from {current_uri} carried no Location header.")
                            current_uri = location
                            continue

                        if response.status < 200 or response.status >= 300:
                            raise DownloadFailure(f"Unexpected status {response.status} fetching {current_uri}.")

                        content_type = (response.content_type or "").lower()
                        if any(content_type.startswith(p) for p in _REJECTED_CONTENT_TYPE_PREFIXES):
                            raise DownloadFailure(
                                f"Rejected response content type {content_type!r} from {current_uri}."
                            )

                        content_length = response.headers.get("Content-Length")
                        if content_length is not None and int(content_length) > max_bytes:
                            raise DownloadFailure(
                                f"Declared Content-Length {content_length} exceeds the {max_bytes}-byte limit."
                            )

                        created_dest = True
                        written = 0
                        with dest.open("wb") as fh:
                            async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                                if time.monotonic() > deadline:
                                    raise DownloadFailure(f"Download deadline exceeded while fetching {current_uri}.")
                                written += len(chunk)
                                if written > max_bytes:
                                    raise DownloadFailure(
                                        f"Download exceeded the {max_bytes}-byte limit fetching {current_uri}."
                                    )
                                fh.write(chunk)
                        return dest
                raise DownloadFailure(f"Exceeded {self._max_redirects} redirects fetching {uri}.")
        except DownloadFailure:
            self._cleanup(dest, created_dest)
            raise
        except aiohttp.ClientError as exc:
            self._cleanup(dest, created_dest)
            raise DownloadFailure(f"Transport error fetching {current_uri}: {exc}") from exc
        except TimeoutError as exc:
            self._cleanup(dest, created_dest)
            raise DownloadFailure(f"Timed out fetching {current_uri}: {exc}") from exc
        except BaseException:
            # Includes asyncio.CancelledError — clean up, then propagate unchanged.
            self._cleanup(dest, created_dest)
            raise

    def _headers_for(self, uri: str) -> dict:
        """Builds request headers, attaching a credential only for an allowlisted host.

        A signed query parameter (e.g. a GCS signed URL) is left untouched
        either way — this method never mutates the URI, only decides whether
        to add an ``Authorization`` header alongside it.
        """
        if self._credential_provider is None:
            return {}
        host = (urlsplit(uri).hostname or "").lower()
        if host not in self._credential_origins:
            return {}
        token = self._credential_provider()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _validate_destination(uri: str) -> None:
        """Rejects unsupported schemes and obvious SSRF targets before any request.

        Args:
            uri: The URI about to be requested (initial or post-redirect).

        Raises:
            DownloadFailure: Non-``https`` scheme, missing host, or a host
                that is a literal loopback/private/link-local/unspecified IP
                address.
        """
        parts = urlsplit(uri)
        if parts.scheme != "https":
            raise DownloadFailure(f"Unsupported URI scheme {parts.scheme!r} (only https is accepted): {uri}")
        host = parts.hostname
        if not host:
            raise DownloadFailure(f"URI has no host: {uri}")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return  # A hostname, not a literal IP; DNS-level SSRF is out of scope here.
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved:
            raise DownloadFailure(f"Refusing to fetch from a non-public address: {uri}")

    @staticmethod
    def _cleanup(dest: Path, created: bool) -> None:
        """Removes ``dest`` only if THIS call created it (never a pre-existing file)."""
        if created and dest.exists():
            dest.unlink(missing_ok=True)
