"""Microsoft Graph drive-delta models and helper (FEAT-539 M8).

Drive-level ``/drives/{id}/root/delta`` enumeration with the semantics
Microsoft Graph v1.0 actually specifies:

* follow ``@odata.nextLink`` until an ``@odata.deltaLink`` appears — the
  final link is the cursor a consumer may commit;
* a page may legitimately be **empty** and still carry a next link;
* deleted items arrive as tombstones (``deleted`` facet), not as absences;
* an expired/invalid token answers **410 Gone**, which means "restart
  enumeration", never "everything was deleted".

This module is deliberately **independent of the contracts package**: it
knows nothing about cards, catalogs or cursors being committed. It fetches
pages and reports what it saw; consumers decide what to persist.

Reference: https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, Field

__all__ = (
    "DEFAULT_GRAPH_ORIGINS",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_RETRIES",
    "DeltaError",
    "DeltaTokenExpired",
    "UntrustedContinuation",
    "DeltaItem",
    "DeltaPage",
    "DeltaEnumeration",
    "validate_continuation",
    "DriveDeltaReader",
)

logger = logging.getLogger(__name__)

#: Continuation links are only followed when they point at Microsoft Graph.
DEFAULT_GRAPH_ORIGINS: tuple[str, ...] = (
    "https://graph.microsoft.com",
    "https://graph.microsoft.us",
    "https://dod-graph.microsoft.us",
    "https://microsoftgraph.chinacloudapi.cn",
    "https://graph.microsoft.de",
)

#: Hard bound on pages followed in one enumeration.
DEFAULT_MAX_PAGES = 200

#: Bounded retries for throttling (429) and transient (5xx) failures.
DEFAULT_MAX_RETRIES = 3


class DeltaError(RuntimeError):
    """A drive delta enumeration failed."""


class DeltaTokenExpired(DeltaError):
    """Graph answered 410 Gone: the delta token is no longer usable.

    The correct response is a **full rescan** from scratch. A partial
    listing must never be interpreted as mass deletion.
    """


class UntrustedContinuation(DeltaError):
    """A continuation link pointed somewhere other than Microsoft Graph.

    Raised *before* any request is made, so credentials are never
    forwarded to a foreign host.
    """


class DeltaItem(BaseModel):
    """One item reported by a drive delta page.

    Args:
        item_id: Stable Graph item id (survives renames and moves).
        drive_id: Owning drive id.
        name: Current file name.
        path: Folder path from ``parentReference.path``.
        web_url: Canonical Graph URL of the item.
        size: Size in bytes.
        etag: Item ETag, when Graph supplied one.
        sha256: Content hash when Graph supplied one.
        last_modified: Last modification timestamp.
        is_folder: Whether the item is a folder.
        deleted: Tombstone marker — the item was deleted or moved out.
    """

    item_id: str = Field(..., min_length=1)
    drive_id: str = ""
    name: Optional[str] = None
    path: Optional[str] = None
    web_url: Optional[str] = None
    size: Optional[int] = None
    etag: Optional[str] = None
    sha256: Optional[str] = None
    last_modified: Optional[datetime] = None
    is_folder: bool = False
    deleted: bool = False

    @property
    def full_path(self) -> str:
        """``path/name`` when both are known, else whichever exists."""
        if self.path and self.name:
            return f"{self.path.rstrip('/')}/{self.name}"
        return self.name or self.path or ""

    def in_folder(self, prefix: Optional[str]) -> bool:
        """Whether this item lives under ``prefix`` (no prefix = all)."""
        if not prefix:
            return True
        needle = prefix.strip("/").lower()
        return needle in (self.path or "").strip("/").lower()


class DeltaPage(BaseModel):
    """One page of a drive delta response.

    Args:
        items: Items on this page (possibly empty — that is legal).
        next_link: Opaque continuation link, when more pages follow.
        delta_link: Opaque final cursor, present on the last page only.
    """

    items: list[DeltaItem] = Field(default_factory=list)
    next_link: Optional[str] = None
    delta_link: Optional[str] = None

    @property
    def is_final(self) -> bool:
        """True when this page carried the final delta link."""
        return self.delta_link is not None


class DeltaEnumeration(BaseModel):
    """The result of following a delta enumeration to its end.

    Args:
        items: Every item seen, de-duplicated on ``item_id`` with the
            **last** report winning (Graph may repeat an item across
            pages).
        delta_link: The final cursor — ``None`` when the enumeration was
            truncated, in which case it must NOT be committed.
        pages: How many pages were read.
        complete: Whether the final delta link was reached.
        rescan_required: True when Graph answered 410 and the caller must
            re-enumerate from scratch.
        truncated: True when ``max_pages`` stopped the walk.
    """

    items: list[DeltaItem] = Field(default_factory=list)
    delta_link: Optional[str] = None
    pages: int = 0
    complete: bool = False
    rescan_required: bool = False
    truncated: bool = False

    @property
    def tombstones(self) -> list[DeltaItem]:
        """Items reported as deleted."""
        return [item for item in self.items if item.deleted]


def validate_continuation(
    link: str,
    *,
    allowed_origins: Sequence[str] = DEFAULT_GRAPH_ORIGINS,
) -> str:
    """Validate a continuation link before credentials are forwarded.

    Args:
        link: The opaque ``nextLink``/``deltaLink`` to follow.
        allowed_origins: Permitted Graph origins.

    Returns:
        The validated link.

    Raises:
        UntrustedContinuation: When the link is not an HTTPS URL on a
            configured Microsoft Graph origin.
    """
    parsed = urlparse(link or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise UntrustedContinuation(f"continuation link is not an https URL: {link!r}")
    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    if origin not in {value.lower() for value in allowed_origins}:
        raise UntrustedContinuation(
            f"continuation link points at {origin!r}, which is not a configured "
            "Microsoft Graph endpoint"
        )
    return link


def _status_of(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP status extraction from an SDK/API error."""
    for attribute in ("response_status_code", "status_code", "status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def _retry_after(exc: BaseException) -> Optional[float]:
    """Extract a ``Retry-After`` hint (seconds) when the SDK exposes one."""
    headers = getattr(exc, "response_headers", None) or {}
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:  # pragma: no cover - unusual header container
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):  # pragma: no cover - malformed header
        return None


class DriveDeltaReader:
    """Read drive-level delta pages through an authenticated Graph client.

    Args:
        graph_client: The authenticated ``GraphServiceClient`` from
            ``O365Client.graph_client``.
        allowed_origins: Graph origins continuation links may point at.
        max_pages: Hard bound on pages followed per enumeration.
        max_retries: Bounded retries for 429/5xx responses.
        base_delay: Base backoff delay in seconds.
        sleep: Injectable sleep (tests pass a no-op).
    """

    def __init__(
        self,
        graph_client: Any,
        *,
        allowed_origins: Sequence[str] = DEFAULT_GRAPH_ORIGINS,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = 1.0,
        sleep: Any = None,
    ) -> None:
        self.graph_client = graph_client
        self.allowed_origins = tuple(allowed_origins)
        self.max_pages = max_pages
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._sleep = sleep or asyncio.sleep

    # -- request builders --------------------------------------------------

    def _root_delta_builder(self, drive_id: str) -> Any:
        """Return the ``/drives/{id}/root/delta`` request builder.

        Verified against the installed ``msgraph`` SDK: drive-level delta
        is the delta of the drive's ``root`` item.
        """
        return (
            self.graph_client.drives.by_drive_id(drive_id)
            .items.by_drive_item_id("root")
            .delta
        )

    def _builder_for(self, drive_id: str, link: Optional[str]) -> Any:
        """Return the builder for a first page or a validated continuation."""
        builder = self._root_delta_builder(drive_id)
        if link is None:
            return builder
        return builder.with_url(validate_continuation(link, allowed_origins=self.allowed_origins))

    # -- parsing -----------------------------------------------------------

    @staticmethod
    def parse_item(raw: Any, drive_id: str) -> DeltaItem:
        """Map one SDK ``DriveItem`` (or dict) onto :class:`DeltaItem`."""
        get = raw.get if isinstance(raw, dict) else lambda name, default=None: getattr(raw, name, default)
        parent = get("parent_reference", None) or get("parentReference", None)
        parent_path = None
        parent_drive = None
        if parent is not None:
            parent_get = (
                parent.get
                if isinstance(parent, dict)
                else lambda name, default=None: getattr(parent, name, default)
            )
            parent_path = parent_get("path", None)
            parent_drive = parent_get("drive_id", None) or parent_get("driveId", None)
        file_facet = get("file", None)
        sha256 = None
        if file_facet is not None:
            file_get = (
                file_facet.get
                if isinstance(file_facet, dict)
                else lambda name, default=None: getattr(file_facet, name, default)
            )
            hashes = file_get("hashes", None)
            if hashes is not None:
                hash_get = (
                    hashes.get
                    if isinstance(hashes, dict)
                    else lambda name, default=None: getattr(hashes, name, default)
                )
                sha256 = hash_get("sha256_hash", None) or hash_get("sha256Hash", None)
        additional = get("additional_data", None) or {}
        deleted = bool(get("deleted", None)) or "deleted" in (additional or {})
        return DeltaItem(
            item_id=str(get("id", "") or ""),
            drive_id=parent_drive or drive_id,
            name=get("name", None),
            path=parent_path,
            web_url=get("web_url", None) or get("webUrl", None),
            size=get("size", None),
            etag=get("e_tag", None) or get("eTag", None),
            sha256=sha256,
            last_modified=get("last_modified_date_time", None)
            or get("lastModifiedDateTime", None),
            is_folder=get("folder", None) is not None,
            deleted=deleted,
        )

    @classmethod
    def parse_page(cls, response: Any, drive_id: str) -> DeltaPage:
        """Map an SDK delta response onto :class:`DeltaPage`."""
        get = (
            response.get
            if isinstance(response, dict)
            else lambda name, default=None: getattr(response, name, default)
        )
        values = get("value", None) or []
        return DeltaPage(
            items=[cls.parse_item(item, drive_id) for item in values],
            next_link=get("odata_next_link", None) or get("@odata.nextLink", None),
            delta_link=get("odata_delta_link", None) or get("@odata.deltaLink", None),
        )

    # -- fetching ----------------------------------------------------------

    async def fetch_page(self, drive_id: str, *, link: Optional[str] = None) -> DeltaPage:
        """Fetch one delta page, retrying throttling/transient failures.

        Args:
            drive_id: The drive to enumerate.
            link: A continuation/delta link, or ``None`` for a fresh walk.

        Returns:
            The parsed :class:`DeltaPage`.

        Raises:
            DeltaTokenExpired: On 410 Gone — the caller must rescan.
            UntrustedContinuation: When ``link`` is not a Graph URL.
            DeltaError: When the retry budget is exhausted.
        """
        builder = self._builder_for(drive_id, link)
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            try:
                response = await builder.get()
            except Exception as exc:  # noqa: BLE001 - status drives the decision
                status = _status_of(exc)
                if status == 410:
                    raise DeltaTokenExpired(
                        "delta token expired (410 Gone); a full rescan is required"
                    ) from exc
                if status is not None and status != 429 and status < 500:
                    raise DeltaError(f"drive delta request failed ({status}): {exc}") from exc
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                delay = _retry_after(exc)
                await self._sleep(delay if delay is not None else self.base_delay * (2**attempt))
                continue
            if response is None:
                return DeltaPage()
            return self.parse_page(response, drive_id)
        raise DeltaError(
            f"drive delta request failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

    async def enumerate(
        self,
        drive_id: str,
        *,
        token: Optional[str] = None,
        folder_prefix: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> DeltaEnumeration:
        """Follow ``nextLink`` pages until the final ``deltaLink``.

        The final cursor is only reported when the walk actually reached
        it: a truncated or interrupted enumeration returns
        ``delta_link=None`` so a consumer cannot commit a cursor it did
        not finish.

        Args:
            drive_id: The drive to enumerate.
            token: A previously committed delta link, or ``None``.
            folder_prefix: Keep only items whose path contains this folder.
            max_pages: Override the page bound for this call.

        Returns:
            A :class:`DeltaEnumeration`. A 410 is reported as
            ``rescan_required`` rather than raised, so the caller can
            re-enumerate without mistaking it for mass deletion.
        """
        limit = max_pages or self.max_pages
        result = DeltaEnumeration()
        seen: dict[str, DeltaItem] = {}
        link = token
        for _ in range(limit):
            try:
                page = await self.fetch_page(drive_id, link=link)
            except DeltaTokenExpired:
                logger.info("Delta token expired for drive %s; rescan required", drive_id)
                return DeltaEnumeration(rescan_required=True, pages=result.pages)
            result.pages += 1
            for item in page.items:
                if item.deleted or item.in_folder(folder_prefix):
                    # Tombstones are always kept: a deleted item no longer
                    # carries a path to filter on.
                    seen[item.item_id] = item
            if page.delta_link:
                result.delta_link = page.delta_link
                result.complete = True
                break
            if not page.next_link:
                # No next link and no delta link: nothing more to read, but
                # there is no cursor to commit either.
                break
            link = page.next_link
        else:
            result.truncated = True

        result.items = [seen[key] for key in sorted(seen)]
        return result
