"""
Microsoft Graph drive delta support for AI-Parrot O365 tools.

This module owns the *transport* half of drive change tracking:

- Typed, O365-owned models for delta items and delta pages
  (:class:`DeltaItem`, :class:`DeltaPage`, :class:`DeltaEnumeration`).
- A shared, authenticated drive-level enumeration helper
  (:class:`DriveDeltaHelper`) that follows ``@odata.nextLink``
  continuations until the final ``@odata.deltaLink`` is reached.

Microsoft Graph v1.0 semantics implemented here:

- ``GET /drives/{drive-id}/items/root/delta`` starts a full enumeration;
  passing a previously stored ``deltaLink`` resumes from that cursor.
- Responses carry either ``@odata.nextLink`` (more pages) or
  ``@odata.deltaLink`` (final cursor for the next round).
- Deleted items are returned with the ``deleted`` facet (tombstones); they
  are surfaced as :attr:`DeltaItem.deleted` rather than dropped.
- ``410 Gone`` invalidates the supplied cursor and requires restarting the
  enumeration from scratch (a *rescan*). A rescan is explicitly flagged so a
  consumer never mistakes a partial listing for mass deletion.
- ``429`` / ``5xx`` responses are retried with bounded backoff that honours
  the ``Retry-After`` header.

Security: continuation links are opaque, but they are still URLs that this
process would send an access token to. Every ``nextLink`` / ``deltaLink`` is
validated against the configured Microsoft Graph origin *before* the request
is issued, so a poisoned feed cannot exfiltrate credentials to a foreign host.

Scope: this helper is deliberately transport-only. It never commits a delta
cursor, never downloads file content and never ingests documents — those are
the consumer's responsibility.

Reference: https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from navconfig.logging import logging
from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# CONSTANTS
# ============================================================================

#: Microsoft Graph origins credentials may be forwarded to.
DEFAULT_GRAPH_ORIGINS: Tuple[str, ...] = (
    "https://graph.microsoft.com",
    "https://graph.microsoft.us",
    "https://dod-graph.microsoft.us",
    "https://microsoftgraph.chinacloudapi.cn",
    "https://graph.microsoft.de",
)

#: HTTP status that invalidates a stored delta cursor (full rescan required).
RESET_STATUS_CODE: int = 410

#: HTTP statuses worth a bounded retry (throttling / transient failures).
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: Default bound on retry attempts per page request.
DEFAULT_MAX_RETRIES: int = 3

#: Default backoff schedule bounds, in seconds.
DEFAULT_INITIAL_BACKOFF: float = 1.0
DEFAULT_MAX_BACKOFF: float = 30.0

#: Hard bound on the number of pages a single enumeration will follow.
DEFAULT_MAX_PAGES: int = 1000

logger = logging.getLogger("Parrot.Tools.O365.Delta")


# ============================================================================
# ERRORS
# ============================================================================

class DeltaLinkValidationError(ValueError):
    """Raised when a continuation link does not point at the Graph origin.

    The request is rejected *before* it is issued, so the access token is
    never forwarded to the offending host.
    """


class DeltaResetRequiredError(RuntimeError):
    """Raised internally when Graph answers 410 Gone for a delta cursor.

    :meth:`DriveDeltaHelper.enumerate` handles this by restarting a full
    rescan; it only escapes from :meth:`DriveDeltaHelper.fetch_page`, where
    the caller owns the reset decision.
    """

    def __init__(self, drive_id: str) -> None:
        """Initialize the error.

        Args:
            drive_id: Drive whose delta cursor was invalidated.
        """
        super().__init__(
            f"Delta cursor for drive {drive_id!r} is no longer valid (410 Gone); "
            f"a full rescan is required. This is NOT a mass-deletion signal."
        )
        self.drive_id = drive_id


class DeltaRetryExhaustedError(RuntimeError):
    """Raised when throttling/transient retries hit their bound."""

    def __init__(self, attempts: int, last_error: BaseException) -> None:
        """Initialize the error.

        Args:
            attempts: Number of attempts performed before giving up.
            last_error: The final underlying error.
        """
        super().__init__(
            f"Microsoft Graph delta request failed after {attempts} attempt(s): "
            f"{last_error}"
        )
        self.attempts = attempts
        self.last_error = last_error


# ============================================================================
# MODELS
# ============================================================================

class DeltaItem(BaseModel):
    """A single drive item reported by a Microsoft Graph delta page.

    Stable identity is ``(drive_id, item_id)``; ``name``/``parent_path`` may
    change across rounds when the item is renamed or moved, which is exactly
    how a consumer detects those events.
    """

    model_config = ConfigDict(extra="forbid")

    drive_id: str = Field(description="Stable Graph drive identifier.")
    item_id: str = Field(description="Stable Graph driveItem identifier.")
    name: Optional[str] = Field(
        default=None, description="Item name at the time of this change."
    )
    deleted: bool = Field(
        default=False,
        description="True when Graph reported the item with the deleted facet.",
    )
    is_folder: bool = Field(
        default=False, description="True when the item is a folder, not a file."
    )
    parent_id: Optional[str] = Field(
        default=None, description="Identifier of the containing folder."
    )
    parent_path: Optional[str] = Field(
        default=None,
        description=(
            "Drive-relative parent path (Graph's '/drive/root:' prefix removed). "
            "None when Graph did not report it, which is common for tombstones."
        ),
    )
    size: Optional[int] = Field(default=None, description="Item size in bytes.")
    etag: Optional[str] = Field(default=None, description="Graph eTag, if reported.")
    ctag: Optional[str] = Field(default=None, description="Graph cTag, if reported.")
    web_url: Optional[str] = Field(default=None, description="Browser URL, if reported.")
    last_modified: Optional[datetime] = Field(
        default=None, description="Last modification timestamp, if reported."
    )
    content_hashes: Dict[str, str] = Field(
        default_factory=dict,
        description="File content hashes reported by Graph (quickXor, sha256, ...).",
    )

    @property
    def path(self) -> Optional[str]:
        """Drive-relative path of the item, when the parent path is known."""
        if self.parent_path is None or self.name is None:
            return None
        if not self.parent_path:
            return self.name
        return f"{self.parent_path}/{self.name}"


class DeltaPage(BaseModel):
    """One page of a Microsoft Graph delta response."""

    model_config = ConfigDict(extra="forbid")

    drive_id: str = Field(description="Drive the page was enumerated from.")
    items: List[DeltaItem] = Field(
        default_factory=list, description="Items reported on this page."
    )
    next_link: Optional[str] = Field(
        default=None,
        description="Opaque '@odata.nextLink' continuation, when more pages follow.",
    )
    delta_link: Optional[str] = Field(
        default=None,
        description="Opaque '@odata.deltaLink' final cursor, when enumeration ended.",
    )

    @property
    def is_final(self) -> bool:
        """True when this page carries the final delta cursor."""
        return self.delta_link is not None


class DeltaEnumeration(BaseModel):
    """Aggregated result of following a delta feed to its final cursor.

    ``delta_link`` is the cursor the consumer *may* commit — this helper never
    commits it. When :attr:`complete` is False the enumeration stopped early
    (page bound reached) and the previous cursor must be retained for an
    idempotent replay.
    """

    model_config = ConfigDict(extra="forbid")

    drive_id: str = Field(description="Drive that was enumerated.")
    items: List[DeltaItem] = Field(
        default_factory=list,
        description=(
            "Changed items, de-duplicated by item_id with the latest occurrence "
            "winning, in first-seen order."
        ),
    )
    delta_link: Optional[str] = Field(
        default=None, description="Final cursor, or None if enumeration was truncated."
    )
    pages_fetched: int = Field(
        default=0, description="Number of delta pages retrieved."
    )
    complete: bool = Field(
        default=False, description="True when the final delta link was reached."
    )
    reset_performed: bool = Field(
        default=False,
        description=(
            "True when a 410 Gone invalidated the supplied cursor and the drive "
            "was re-enumerated from scratch. The listing is then a full rescan, "
            "NOT a set of deletions."
        ),
    )
    full_enumeration: bool = Field(
        default=False,
        description="True when enumeration started without a stored cursor.",
    )
    folder_path: Optional[str] = Field(
        default=None,
        description="Drive-relative folder filter applied locally, if any.",
    )
    filtered_out: int = Field(
        default=0, description="Items dropped by the local folder filter."
    )

    @property
    def deleted_items(self) -> List[DeltaItem]:
        """Tombstones present in this enumeration."""
        return [item for item in self.items if item.deleted]

    @property
    def changed_items(self) -> List[DeltaItem]:
        """Non-deleted items present in this enumeration."""
        return [item for item in self.items if not item.deleted]


# ============================================================================
# HELPERS
# ============================================================================

def normalize_drive_path(raw_path: Optional[str]) -> Optional[str]:
    """Convert a Graph ``parentReference.path`` into a drive-relative path.

    Graph reports parent paths as ``/drive/root:/Folder/Sub`` or
    ``/drives/{drive-id}/root:/Folder/Sub``. Both collapse to ``Folder/Sub``;
    the drive root collapses to the empty string.

    Args:
        raw_path: Raw ``parentReference.path`` value, possibly None.

    Returns:
        The drive-relative path, ``""`` for the root, or None when unknown.
    """
    if raw_path is None:
        return None
    path = str(raw_path)
    marker = "root:"
    idx = path.find(marker)
    if idx != -1:
        path = path[idx + len(marker):]
    return path.strip("/")


def validate_continuation_link(
    link: str,
    allowed_origins: Sequence[str] = DEFAULT_GRAPH_ORIGINS,
) -> str:
    """Validate an opaque delta continuation link before using it.

    Continuation links come from the remote feed. Because the request carries
    an access token, the link must be proven to point at a configured
    Microsoft Graph origin before it is ever dereferenced.

    Args:
        link: The opaque ``@odata.nextLink`` / ``@odata.deltaLink`` value.
        allowed_origins: Origins credentials may be forwarded to.

    Returns:
        The validated link, unchanged.

    Raises:
        DeltaLinkValidationError: If the link is empty, is not absolute HTTPS,
            or its origin is not in ``allowed_origins``.
    """
    if not link or not str(link).strip():
        raise DeltaLinkValidationError("Delta continuation link is empty.")

    parts = urlsplit(str(link).strip())
    if parts.scheme.lower() != "https":
        raise DeltaLinkValidationError(
            f"Delta continuation link must use https, got scheme "
            f"{parts.scheme or '(none)'!r}."
        )
    if not parts.hostname:
        raise DeltaLinkValidationError(
            "Delta continuation link has no host component."
        )

    origin = f"https://{parts.hostname.lower()}"
    if parts.port is not None and parts.port != 443:
        origin = f"{origin}:{parts.port}"

    permitted = {str(o).rstrip("/").lower() for o in allowed_origins}
    if origin not in permitted:
        raise DeltaLinkValidationError(
            f"Refusing to send Graph credentials to untrusted delta host "
            f"{origin!r}; allowed origins: {sorted(permitted)}."
        )
    return str(link)


def _status_code_of(error: BaseException) -> Optional[int]:
    """Extract an HTTP status code from a Graph/kiota error, if present."""
    code = getattr(error, "response_status_code", None)
    if isinstance(code, int) and code:
        return code
    code = getattr(error, "status_code", None)
    if isinstance(code, int) and code:
        return code
    return None


def _retry_after_seconds(error: BaseException) -> Optional[float]:
    """Extract a ``Retry-After`` delay (seconds) from a Graph/kiota error."""
    headers = getattr(error, "response_headers", None)
    if headers is None:
        return None

    raw: Any = None
    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            raw = getter("Retry-After")
        except TypeError:  # pragma: no cover - defensive
            raw = None
        if not raw:
            try:
                raw = getter("retry-after")
            except TypeError:  # pragma: no cover - defensive
                raw = None

    if isinstance(raw, (set, frozenset, list, tuple)):
        raw = next(iter(sorted(str(v) for v in raw)), None)
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Best-effort conversion of a Graph timestamp into a datetime."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _extract_hashes(drive_item: Any) -> Dict[str, str]:
    """Collect the content hashes Graph reported for a file item."""
    file_facet = getattr(drive_item, "file", None)
    hashes = getattr(file_facet, "hashes", None) if file_facet is not None else None
    if hashes is None:
        return {}
    collected: Dict[str, str] = {}
    for attr, key in (
        ("quick_xor_hash", "quickXorHash"),
        ("sha1_hash", "sha1Hash"),
        ("sha256_hash", "sha256Hash"),
        ("crc32_hash", "crc32Hash"),
    ):
        value = getattr(hashes, attr, None)
        if value:
            collected[key] = str(value)
    return collected


def drive_item_to_delta_item(drive_item: Any, drive_id: str) -> Optional[DeltaItem]:
    """Project a Graph ``driveItem`` onto the typed :class:`DeltaItem` model.

    Args:
        drive_item: A ``msgraph`` ``DriveItem`` (or any object exposing the
            same attributes).
        drive_id: Drive the item belongs to, used when the item's own
            ``parentReference.driveId`` is absent.

    Returns:
        The typed item, or None when Graph reported no stable item id (such
        an entry cannot be reconciled and is skipped).
    """
    item_id = getattr(drive_item, "id", None)
    if not item_id:
        logger.warning("Skipping delta entry without a stable item id.")
        return None

    parent = getattr(drive_item, "parent_reference", None)
    parent_drive_id = getattr(parent, "drive_id", None) if parent is not None else None

    return DeltaItem(
        drive_id=str(parent_drive_id or drive_id),
        item_id=str(item_id),
        name=getattr(drive_item, "name", None),
        deleted=getattr(drive_item, "deleted", None) is not None,
        is_folder=getattr(drive_item, "folder", None) is not None,
        parent_id=getattr(parent, "id", None) if parent is not None else None,
        parent_path=normalize_drive_path(
            getattr(parent, "path", None) if parent is not None else None
        ),
        size=getattr(drive_item, "size", None),
        etag=getattr(drive_item, "e_tag", None),
        ctag=getattr(drive_item, "c_tag", None),
        web_url=getattr(drive_item, "web_url", None),
        last_modified=_coerce_datetime(
            getattr(drive_item, "last_modified_date_time", None)
        ),
        content_hashes=_extract_hashes(drive_item),
    )


def item_in_folder(item: DeltaItem, folder_path: Optional[str]) -> bool:
    """Decide whether an item falls inside a drive-relative folder filter.

    Graph delta is drive-level, so folder scoping is applied locally.

    Args:
        item: The typed delta item.
        folder_path: Drive-relative folder, or None/"" for the whole drive.

    Returns:
        True when the item is inside the folder subtree. Items whose parent
        path Graph did not report (common for tombstones) return True so that
        a retraction is never silently lost; reconciling an unknown id is a
        no-op for the consumer.
    """
    normalized = (folder_path or "").strip("/")
    if not normalized:
        return True
    if item.parent_path is None:
        return True
    parent = item.parent_path
    return parent == normalized or parent.startswith(f"{normalized}/")


# ============================================================================
# DRIVE DELTA HELPER
# ============================================================================

class DriveDeltaHelper:
    """Authenticated, drive-level Microsoft Graph delta enumeration helper.

    The helper is shared by the SharePoint and OneDrive delta tools. It takes
    an already-authenticated client (anything exposing ``graph_client``) and
    walks the delta feed for one drive.

    It is transport-only: it does not persist cursors, does not download file
    content and does not ingest documents.

    Example:
        >>> helper = DriveDeltaHelper()
        >>> result = await helper.enumerate(       # doctest: +SKIP
        ...     client, drive_id="b!abc", delta_link=stored_cursor,
        ...     folder_path="Contracts",
        ... )
        >>> result.complete and result.delta_link  # doctest: +SKIP
    """

    def __init__(
        self,
        *,
        allowed_origins: Sequence[str] = DEFAULT_GRAPH_ORIGINS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
        max_pages: int = DEFAULT_MAX_PAGES,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        logger_instance: Optional[Any] = None,
    ) -> None:
        """Initialize the helper.

        Args:
            allowed_origins: Graph origins credentials may be forwarded to.
            max_retries: Bound on retries per page for throttling/transient
                failures. ``0`` disables retrying.
            initial_backoff: First backoff delay, in seconds.
            max_backoff: Upper bound for any single backoff delay, in seconds.
            max_pages: Hard bound on pages followed in one enumeration.
            sleep: Awaitable sleep function; injectable for deterministic
                tests. Defaults to :func:`asyncio.sleep`.
            logger_instance: Optional logger override.

        Raises:
            ValueError: If a bound is negative or ``max_pages`` is not positive.
        """
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if initial_backoff < 0 or max_backoff < 0:
            raise ValueError("backoff values must be >= 0")
        if max_pages <= 0:
            raise ValueError("max_pages must be > 0")

        self.allowed_origins = tuple(allowed_origins)
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.max_pages = max_pages
        self._sleep = sleep or asyncio.sleep
        self.logger = logger_instance or logger

    # -- link validation ---------------------------------------------------

    def validate_link(self, link: str) -> str:
        """Validate a continuation link against the configured Graph origins.

        Args:
            link: Opaque nextLink/deltaLink value.

        Returns:
            The validated link.

        Raises:
            DeltaLinkValidationError: If the link is not a trusted Graph URL.
        """
        return validate_continuation_link(link, self.allowed_origins)

    # -- single page -------------------------------------------------------

    def _delta_builder(self, client: Any, drive_id: str) -> Any:
        """Build the drive-root delta request builder for ``drive_id``."""
        return (
            client.graph_client
            .drives.by_drive_id(drive_id)
            .items.by_drive_item_id("root")
            .delta
        )

    async def fetch_page(
        self,
        client: Any,
        drive_id: str,
        *,
        link: Optional[str] = None,
    ) -> DeltaPage:
        """Fetch a single delta page, with bounded retry on throttling.

        Args:
            client: Authenticated client exposing ``graph_client``.
            drive_id: Target drive identifier.
            link: Opaque nextLink/deltaLink to resume from. When None a fresh
                enumeration of the drive is started.

        Returns:
            The typed delta page.

        Raises:
            DeltaLinkValidationError: If ``link`` is not a trusted Graph URL.
                Raised before any request is issued.
            DeltaResetRequiredError: If Graph answered 410 Gone.
            DeltaRetryExhaustedError: If retries hit their bound.
        """
        builder = self._delta_builder(client, drive_id)
        if link is not None:
            # Validate BEFORE the token is ever attached to a request.
            validated = self.validate_link(link)
            builder = builder.with_url(validated)

        response = await self._get_with_retry(builder, drive_id)
        return self._build_page(response, drive_id)

    async def _get_with_retry(self, builder: Any, drive_id: str) -> Any:
        """Issue ``builder.get()``, retrying throttling/transient failures."""
        attempt = 0
        backoff = self.initial_backoff
        last_error: Optional[BaseException] = None

        while attempt <= self.max_retries:
            attempt += 1
            try:
                return await builder.get()
            except Exception as exc:  # noqa: BLE001 - re-raised below
                status = _status_code_of(exc)
                if status == RESET_STATUS_CODE:
                    raise DeltaResetRequiredError(drive_id) from exc
                if status not in RETRYABLE_STATUS_CODES:
                    raise
                last_error = exc
                if attempt > self.max_retries:
                    break
                retry_after = _retry_after_seconds(exc)
                delay = retry_after if retry_after is not None else backoff
                delay = min(delay, self.max_backoff)
                self.logger.warning(
                    "Graph delta request for drive %s returned %s; "
                    "retry %s/%s in %.2fs",
                    drive_id, status, attempt, self.max_retries, delay,
                )
                if delay > 0:
                    await self._sleep(delay)
                backoff = min(backoff * 2 if backoff else self.initial_backoff,
                              self.max_backoff)

        raise DeltaRetryExhaustedError(attempt, last_error or RuntimeError("unknown"))

    def _build_page(self, response: Any, drive_id: str) -> DeltaPage:
        """Project a Graph delta response onto :class:`DeltaPage`."""
        if response is None:
            return DeltaPage(drive_id=drive_id)

        raw_items: Iterable[Any] = getattr(response, "value", None) or []
        items: List[DeltaItem] = []
        for raw in raw_items:
            item = drive_item_to_delta_item(raw, drive_id)
            if item is not None:
                items.append(item)

        return DeltaPage(
            drive_id=drive_id,
            items=items,
            next_link=getattr(response, "odata_next_link", None),
            delta_link=getattr(response, "odata_delta_link", None),
        )

    # -- full enumeration --------------------------------------------------

    async def enumerate(
        self,
        client: Any,
        drive_id: str,
        *,
        delta_link: Optional[str] = None,
        folder_path: Optional[str] = None,
        max_pages: Optional[int] = None,
    ) -> DeltaEnumeration:
        """Follow a drive's delta feed until the final cursor is reached.

        On ``410 Gone`` the supplied cursor is discarded and the drive is
        re-enumerated from scratch exactly once; the result is flagged with
        :attr:`DeltaEnumeration.reset_performed` so the consumer treats it as
        a full rescan rather than as mass deletion.

        Args:
            client: Authenticated client exposing ``graph_client``.
            drive_id: Target drive identifier.
            delta_link: Previously committed cursor to resume from, if any.
            folder_path: Drive-relative folder to filter items to, applied
                locally because Graph delta is drive-level.
            max_pages: Per-call override of the page bound.

        Returns:
            The aggregated :class:`DeltaEnumeration`.

        Raises:
            DeltaLinkValidationError: If a continuation link is untrusted.
            DeltaRetryExhaustedError: If retries hit their bound.
        """
        try:
            return await self._enumerate_once(
                client,
                drive_id,
                delta_link=delta_link,
                folder_path=folder_path,
                max_pages=max_pages,
                reset_performed=False,
            )
        except DeltaResetRequiredError:
            self.logger.warning(
                "Delta cursor for drive %s expired (410 Gone); "
                "restarting a full rescan.",
                drive_id,
            )
            return await self._enumerate_once(
                client,
                drive_id,
                delta_link=None,
                folder_path=folder_path,
                max_pages=max_pages,
                reset_performed=True,
            )

    async def _enumerate_once(
        self,
        client: Any,
        drive_id: str,
        *,
        delta_link: Optional[str],
        folder_path: Optional[str],
        max_pages: Optional[int],
        reset_performed: bool,
    ) -> DeltaEnumeration:
        """Walk the feed a single time, without 410 recovery."""
        page_bound = self.max_pages if max_pages is None else max_pages
        if page_bound <= 0:
            raise ValueError("max_pages must be > 0")

        # De-duplicate by item id: a delta feed may report the same item on
        # several pages, and the latest occurrence is authoritative.
        collected: Dict[str, DeltaItem] = {}
        order: List[str] = []
        filtered_out = 0
        pages = 0
        final_link: Optional[str] = None
        link = delta_link

        while pages < page_bound:
            page = await self.fetch_page(client, drive_id, link=link)
            pages += 1

            for item in page.items:
                if not item_in_folder(item, folder_path):
                    filtered_out += 1
                    continue
                if item.item_id not in collected:
                    order.append(item.item_id)
                collected[item.item_id] = item

            if page.delta_link is not None:
                # Validate the cursor we hand back so a poisoned final link is
                # rejected here rather than on the consumer's next round.
                final_link = self.validate_link(page.delta_link)
                break
            if page.next_link is None:
                # No continuation and no cursor: the feed ended without giving
                # us a cursor to commit. Treat as truncated, not complete.
                self.logger.warning(
                    "Delta page %s for drive %s carried neither nextLink nor "
                    "deltaLink; stopping without a committable cursor.",
                    pages, drive_id,
                )
                break
            link = page.next_link
        else:
            self.logger.warning(
                "Delta enumeration for drive %s hit the %s page bound; "
                "no cursor is committable.",
                drive_id, page_bound,
            )

        return DeltaEnumeration(
            drive_id=drive_id,
            items=[collected[item_id] for item_id in order],
            delta_link=final_link,
            pages_fetched=pages,
            complete=final_link is not None,
            reset_performed=reset_performed,
            full_enumeration=delta_link is None,
            folder_path=(folder_path or None),
            filtered_out=filtered_out,
        )


__all__ = (
    "DEFAULT_GRAPH_ORIGINS",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_RETRIES",
    "RESET_STATUS_CODE",
    "RETRYABLE_STATUS_CODES",
    "DeltaEnumeration",
    "DeltaItem",
    "DeltaLinkValidationError",
    "DeltaPage",
    "DeltaResetRequiredError",
    "DeltaRetryExhaustedError",
    "DriveDeltaHelper",
    "drive_item_to_delta_item",
    "item_in_folder",
    "normalize_drive_path",
    "validate_continuation_link",
)
