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
  the ``Retry-After`` header in full.

Retry layering: the installed ``msgraph``/Kiota stack ships its own
``RetryHandler`` middleware (3 retries by default, also honouring
``Retry-After``). The bound configured here therefore counts *this* layer's
attempts, not raw HTTP requests — the two multiply. Set the SDK's
``RetryHandlerOption`` if a single owner of retry policy is required.

Security: continuation links are opaque, but they are still URLs that this
process would send an access token to, and
``DeltaRequestBuilder.with_url()`` replaces the *entire* URL rather than just
its query string. Every ``nextLink`` / ``deltaLink`` — including a
caller-supplied stored cursor — is therefore validated *before* the request
is issued: it must sit on a configured Microsoft Graph origin **and** address
the delta endpoint of the drive being enumerated. A poisoned feed can neither
exfiltrate credentials to a foreign host nor redirect the authenticated
request at another resource.

Scope: this helper is deliberately transport-only. It never commits a delta
cursor, never downloads file content and never ingests documents — those are
the consumer's responsibility.

Reference: https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

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


def _transient_exception_types() -> Tuple[type, ...]:
    """Exception types that mean "the request never got an answer".

    A dropped connection or a timeout carries no HTTP status, so it would
    otherwise skip the retry budget entirely and fail on the first blip.
    ``httpx.TransportError`` (connect/read/write/pool failures) is included
    when available — this is a type lookup for classification only, not an
    HTTP client choice; the transport belongs to the msgraph SDK.
    """
    types: List[type] = [TimeoutError, OSError]
    try:  # pragma: no cover - depends on the installed SDK stack
        import httpx

        types.append(httpx.TransportError)
    except Exception:  # pragma: no cover - httpx is a msgraph dependency
        pass
    return tuple(types)


#: Exception types retried even though they carry no HTTP status code.
TRANSIENT_EXCEPTION_TYPES: Tuple[type, ...] = _transient_exception_types()

#: Default bound on retry attempts per page request.
DEFAULT_MAX_RETRIES: int = 3

#: Default backoff schedule bounds, in seconds.
DEFAULT_INITIAL_BACKOFF: float = 1.0
DEFAULT_MAX_BACKOFF: float = 30.0

#: Longest server-requested ``Retry-After`` this helper will wait out before
#: abandoning the round. A `Retry-After` is honoured in full up to this bound
#: (truncating it would retry while still throttled); beyond it, the throttle
#: is surfaced to the caller instead.
DEFAULT_MAX_RETRY_AFTER: float = 300.0

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

    def __init__(
        self,
        attempts: int,
        last_error: BaseException,
        reason: str = "retries exhausted",
    ) -> None:
        """Initialize the error.

        Args:
            attempts: Number of attempts performed before giving up.
            last_error: The final underlying error.
            reason: Why the helper stopped — distinguishes a genuinely
                exhausted retry budget from a throttle longer than
                ``max_retry_after``, which a caller may want to defer on
                rather than treat as a failure.
        """
        super().__init__(
            f"Microsoft Graph delta request failed after {attempts} " f"attempt(s) ({reason}): {last_error}"
        )
        self.attempts = attempts
        self.last_error = last_error
        self.reason = reason


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
    name: Optional[str] = Field(default=None, description="Item name at the time of this change.")
    deleted: bool = Field(
        default=False,
        description="True when Graph reported the item with the deleted facet.",
    )
    is_folder: bool = Field(default=False, description="True when the item is a folder, not a file.")
    parent_id: Optional[str] = Field(default=None, description="Identifier of the containing folder.")
    parent_path: Optional[str] = Field(
        default=None,
        description=(
            "Drive-relative parent path (Graph's '/drive/root:' prefix removed). "
            "Usually None: the Graph v1.0 delta API documents that "
            "parentReference omits 'path'. Track items by item_id/parent_id."
        ),
    )
    size: Optional[int] = Field(default=None, description="Item size in bytes.")
    etag: Optional[str] = Field(default=None, description="Graph eTag, if reported.")
    ctag: Optional[str] = Field(default=None, description="Graph cTag, if reported.")
    web_url: Optional[str] = Field(default=None, description="Browser URL, if reported.")
    last_modified: Optional[datetime] = Field(default=None, description="Last modification timestamp, if reported.")
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
    items: List[DeltaItem] = Field(default_factory=list, description="Items reported on this page.")
    next_link: Optional[str] = Field(
        default=None,
        description="Opaque '@odata.nextLink' continuation, when more pages follow.",
    )
    delta_link: Optional[str] = Field(
        default=None,
        description="Opaque '@odata.deltaLink' final cursor, when enumeration ended.",
    )
    skipped_entries: int = Field(
        default=0,
        description=(
            "Entries on this page that carried no stable item id and could " "not be reconciled, so were dropped."
        ),
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
            "Changed items, de-duplicated by item_id with the latest occurrence " "winning, in first-seen order."
        ),
    )
    delta_link: Optional[str] = Field(default=None, description="Final cursor, or None if enumeration was truncated.")
    pages_fetched: int = Field(default=0, description="Number of delta pages retrieved.")
    complete: bool = Field(default=False, description="True when the final delta link was reached.")
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
        description=(
            "Drive-relative folder path filter applied locally, if any. Graph "
            "omits parentReference.path from delta responses, so this filter "
            "is best-effort — see unresolved_parent / folder_filter_reliable."
        ),
    )
    folder_id: Optional[str] = Field(
        default=None,
        description=(
            "Stable folder item id filter applied locally, if any. Exact, but " "matches direct children only."
        ),
    )
    filtered_out: int = Field(
        default=0,
        description="Items positively excluded by the local folder filter.",
    )
    skipped_entries: int = Field(
        default=0,
        description=(
            "Entries dropped because Graph reported no stable item id. "
            "Non-zero means this enumeration is incomplete: the cursor "
            "should not be committed without investigating."
        ),
    )
    unresolved_parent: int = Field(
        default=0,
        description=(
            "Items KEPT because their folder membership could not be decided "
            "(Graph reported neither a usable parent path nor a parent id). "
            "Non-zero means the folder filter did not fully apply."
        ),
    )

    @property
    def deleted_items(self) -> List[DeltaItem]:
        """Tombstones present in this enumeration."""
        return [item for item in self.items if item.deleted]

    @property
    def changed_items(self) -> List[DeltaItem]:
        """Non-deleted items present in this enumeration."""
        return [item for item in self.items if not item.deleted]

    @property
    def folder_filter_reliable(self) -> bool:
        """True when every returned item's folder membership was decidable.

        False means at least one item was kept without being able to confirm
        it belongs to the requested folder, so the caller must re-check
        membership by item id before treating the result as folder-scoped.
        """
        return self.unresolved_parent == 0


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
        path = path[idx + len(marker) :]
    return path.strip("/")


def validate_continuation_link(
    link: str,
    drive_id: str,
    allowed_origins: Sequence[str] = DEFAULT_GRAPH_ORIGINS,
) -> str:
    """Validate an opaque delta continuation link before using it.

    Continuation links come from the remote feed (or, for a stored cursor,
    from the caller). Because the request carries an access token, and
    because ``DeltaRequestBuilder.with_url()`` replaces the *entire* URL —
    not just its query string — the link must be proven to be a delta
    endpoint on the intended drive at a configured Microsoft Graph origin
    before it is ever dereferenced.

    Origin validation alone is not enough: a link such as
    ``https://graph.microsoft.com/v1.0/drives/<other>/items/<x>/content``
    passes an origin check yet points the authenticated request at an
    entirely different resource. When ``drive_id`` is supplied the path is
    therefore confined to that drive's delta operation as well.

    Args:
        link: The opaque ``@odata.nextLink`` / ``@odata.deltaLink`` value.
        drive_id: Drive the enumeration is confined to. The link's path must
            name this drive and a ``delta`` operation. It is deliberately a
            required argument: an origin-only check is the very weakness this
            function exists to close, so it must not be reachable by omission.
        allowed_origins: Origins credentials may be forwarded to.

    Returns:
        The validated link, unchanged.

    Raises:
        DeltaLinkValidationError: If the link is empty, is not absolute
            HTTPS, its origin is not in ``allowed_origins``, or it does not
            address the ``drive_id`` delta endpoint.
    """
    if not drive_id:
        raise DeltaLinkValidationError("A drive_id is required to validate a delta continuation link.")
    if not link or not str(link).strip():
        raise DeltaLinkValidationError("Delta continuation link is empty.")

    parts = urlsplit(str(link).strip())
    if parts.scheme.lower() != "https":
        raise DeltaLinkValidationError(
            f"Delta continuation link must use https, got scheme " f"{parts.scheme or '(none)'!r}."
        )
    if not parts.hostname:
        raise DeltaLinkValidationError("Delta continuation link has no host component.")

    origin = f"https://{parts.hostname.lower()}"
    if parts.port is not None and parts.port != 443:
        origin = f"{origin}:{parts.port}"

    permitted = {str(o).rstrip("/").lower() for o in allowed_origins}
    if origin not in permitted:
        raise DeltaLinkValidationError(
            f"Refusing to send Graph credentials to untrusted delta host "
            f"{origin!r}; allowed origins: {sorted(permitted)}."
        )

    # Graph returns e.g. /v1.0/drives/{drive-id}/root/delta?token=...
    # or /v1.0/drives/{drive-id}/items/{item-id}/delta()?token=...
    # The match must be STRUCTURAL: merely containing the drive id and a
    # "delta" segment somewhere would accept
    # /v1.0/delta/drives/{drive-id}/items/x/content.
    # Decode BEFORE splitting: splitting first lets an encoded separator
    # such as %2e%2e%2f smuggle a traversal past a per-segment ".." check
    # and re-anchor the request on another drive once the server decodes it.
    # Backslash is treated as a separator too, for the same reason.
    decoded_path = unquote(parts.path).replace("\\", "/")
    segments = [seg for seg in decoded_path.split("/") if seg]

    if any(seg in ("..", ".") for seg in segments):
        raise DeltaLinkValidationError(
            f"Delta continuation link must not contain relative path " f"segments: {parts.path!r}."
        )

    if any(":" in seg for seg in segments):
        # Colon segments are Graph's path-addressing syntax
        # (`/drives/{id}/root:/Folder/file.docx`). A delta continuation never
        # uses it, and allowing it would let `/drives/{id}/root:/delta` — the
        # *item literally named "delta"* — pass the endpoint check below.
        raise DeltaLinkValidationError(
            f"Delta continuation link must not use path addressing: {parts.path!r}."
        )

    last = segments[-1] if segments else ""
    if not (last == "delta" or last.startswith("delta(")):
        raise DeltaLinkValidationError(f"Delta continuation link is not a delta endpoint: " f"{parts.path!r}.")

    try:
        drives_at = segments.index("drives")
    except ValueError:
        drives_at = -1
    if drives_at < 0 or drives_at + 1 >= len(segments) or segments[drives_at + 1] != str(drive_id):
        raise DeltaLinkValidationError(
            f"Delta continuation link does not address drive " f"{drive_id!r}: {parts.path!r}."
        )

    return str(link)


def _status_code_of(error: BaseException) -> Optional[int]:
    """Extract an HTTP status code from a Graph/kiota error, if present."""
    code = getattr(error, "response_status_code", None)
    if isinstance(code, int) and code:
        return code
    for attribute in ("status_code", "status", "code"):
        code = getattr(error, attribute, None)
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

    text = str(raw).strip()
    try:
        value = float(text)
    except (TypeError, ValueError):
        # RFC 7231 also allows an HTTP-date instead of a delta-seconds value.
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        value = (when - datetime.now(timezone.utc)).total_seconds()
    return value if value >= 0 else None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """Best-effort conversion of a Graph timestamp into a datetime."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _field(source: Any, *names: str) -> Any:
    """Read the first present field from an SDK object *or* a plain dict.

    Graph payloads reach this module either as ``msgraph`` model objects
    (snake_case attributes) or, in tests and cached/serialized feeds, as raw
    JSON dicts (camelCase keys). Accepting both keeps one parser instead of
    two subtly different ones.

    Args:
        source: The object or mapping to read from.
        *names: Candidate field names, tried in order.

    Returns:
        The first non-None value found, else None.
    """
    if source is None:
        return None
    for name in names:
        value = source.get(name) if isinstance(source, dict) else getattr(source, name, None)
        if value is not None:
            return value
    return None


def _extract_hashes(drive_item: Any) -> Dict[str, str]:
    """Collect the content hashes Graph reported for a file item."""
    file_facet = _field(drive_item, "file")
    hashes = _field(file_facet, "hashes") if file_facet is not None else None
    if hashes is None:
        return {}
    collected: Dict[str, str] = {}
    for attr, camel, key in (
        ("quick_xor_hash", "quickXorHash", "quickXorHash"),
        ("sha1_hash", "sha1Hash", "sha1Hash"),
        ("sha256_hash", "sha256Hash", "sha256Hash"),
        ("crc32_hash", "crc32Hash", "crc32Hash"),
    ):
        value = _field(hashes, attr, camel)
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
    item_id = _field(drive_item, "id")
    if not item_id:
        logger.warning("Skipping delta entry without a stable item id.")
        return None

    parent = _field(drive_item, "parent_reference", "parentReference")
    parent_drive_id = _field(parent, "drive_id", "driveId")

    additional = _field(drive_item, "additional_data", "additionalData") or {}
    deleted = _field(drive_item, "deleted") is not None or (isinstance(additional, dict) and "deleted" in additional)

    return DeltaItem(
        drive_id=str(parent_drive_id or drive_id),
        item_id=str(item_id),
        name=_field(drive_item, "name"),
        deleted=deleted,
        is_folder=_field(drive_item, "folder") is not None,
        parent_id=_field(parent, "id"),
        parent_path=normalize_drive_path(_field(parent, "path")),
        size=_field(drive_item, "size"),
        etag=_field(drive_item, "e_tag", "eTag"),
        ctag=_field(drive_item, "c_tag", "cTag"),
        web_url=_field(drive_item, "web_url", "webUrl"),
        last_modified=_coerce_datetime(_field(drive_item, "last_modified_date_time", "lastModifiedDateTime")),
        content_hashes=_extract_hashes(drive_item),
    )


#: Classification returned by :func:`classify_folder_membership`.
FOLDER_MATCH: str = "match"
FOLDER_MISS: str = "miss"
FOLDER_UNKNOWN: str = "unknown"


def classify_folder_membership(
    item: DeltaItem,
    folder_path: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> str:
    """Classify an item against a folder filter as match / miss / unknown.

    Graph delta is drive-level, so folder scoping has to be applied locally —
    but the two available signals are not equally trustworthy:

    - ``folder_id`` compares against ``parentReference.id``, which delta does
      report. It is exact, but only identifies **direct children** of that
      folder; deeper descendants must be reconciled by the consumer, which
      Microsoft's guidance ("always track items by id") expects anyway.
    - ``folder_path`` compares against ``parentReference.path``, which the
      Graph v1.0 delta API documents as **omitted**: *"The parentReference
      property on items won't include a value for path."* Against real Graph
      this therefore usually classifies as ``unknown``, not as a match. It
      remains useful for feeds that do carry a path (and for tests), but it
      must never be relied on alone.

    Args:
        item: The typed delta item.
        folder_path: Drive-relative folder path filter, if any.
        folder_id: Stable folder item id filter, if any.

    Returns:
        ``FOLDER_MATCH`` when the item is known to be inside the folder,
        ``FOLDER_MISS`` when it is known to be outside, and
        ``FOLDER_UNKNOWN`` when Graph reported nothing to decide with.
        With no filter configured every item is a match.
    """
    normalized_path = (folder_path or "").strip("/")
    if not normalized_path and not folder_id:
        return FOLDER_MATCH

    if item.deleted:
        # A tombstone is retained whatever the filter says. Graph reports a
        # deletion with little metadata, and an item may be tombstoned
        # precisely because it left the folder — excluding it would strand
        # the projection the consumer already indexed. Dropping a retraction
        # is corruption; keeping one for an item nobody indexed is a no-op.
        return FOLDER_MATCH

    decidable = False

    if folder_id:
        if item.parent_id is not None:
            decidable = True
            if item.parent_id == folder_id or item.item_id == folder_id:
                return FOLDER_MATCH

    if normalized_path:
        if item.parent_path is not None:
            decidable = True
            # SharePoint/OneDrive paths are case-insensitive, so the filter
            # must be too — otherwise "legal" misses "/Legal/Contracts".
            # Matching stays on segment boundaries: "Contracts" must not
            # match "ContractsArchive".
            parent = item.parent_path.casefold()
            wanted = normalized_path.casefold()
            if parent == wanted or parent.startswith(f"{wanted}/"):
                return FOLDER_MATCH

    return FOLDER_MISS if decidable else FOLDER_UNKNOWN


def item_in_folder(
    item: DeltaItem,
    folder_path: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> bool:
    """Decide whether an item should be kept under a folder filter.

    Undecidable items are **kept**, not dropped: Graph omits
    ``parentReference.path`` from delta responses and may report a tombstone
    with no locatable parent, so dropping them would silently lose a
    retraction. Reconciling an item the consumer never indexed is a no-op,
    whereas losing one is data corruption.

    Use :func:`classify_folder_membership` when the distinction between a
    genuine match and an undecidable item matters —
    :attr:`DeltaEnumeration.unresolved_parent` reports exactly that count.

    Args:
        item: The typed delta item.
        folder_path: Drive-relative folder path filter, if any.
        folder_id: Stable folder item id filter, if any.

    Returns:
        True when the item is inside the folder or its membership is unknown.
    """
    return classify_folder_membership(item, folder_path, folder_id) != FOLDER_MISS


#: Bound on how far up the folder chain an ancestry walk will climb.
DEFAULT_MAX_ANCESTRY_DEPTH: int = 32


class FolderAncestryResolver:
    """Decide subtree membership by walking ``parentReference.id`` upwards.

    Graph's delta feed omits ``parentReference.path`` but *does* report
    ``parentReference.id``, so the only exact way to scope a delta round to a
    folder **subtree** is to follow each item's parent chain until the target
    folder or the drive root is reached. Microsoft's own guidance for delta
    is "always track items by id"; this is that, applied to folder scoping.

    Results are cached per instance — one resolver per enumeration — so a
    change set with many files in a handful of folders costs a handful of
    lookups, not one per file.
    """

    def __init__(
        self,
        client: Any,
        drive_id: str,
        folder_id: str,
        *,
        max_depth: int = DEFAULT_MAX_ANCESTRY_DEPTH,
        logger_instance: Optional[Any] = None,
    ) -> None:
        """Initialize the resolver.

        Args:
            client: Authenticated client exposing ``graph_client``.
            drive_id: Drive the enumeration is confined to.
            folder_id: Stable item id of the folder being scoped to.
            max_depth: Bound on the upward walk, so a cycle or a pathological
                hierarchy cannot loop forever.
            logger_instance: Optional logger override.
        """
        self.client = client
        self.drive_id = drive_id
        self.folder_id = folder_id
        self.max_depth = max_depth
        self.logger = logger_instance or logger
        self._cache: Dict[str, Optional[bool]] = {folder_id: True}

    async def is_within(self, parent_id: Optional[str]) -> Optional[bool]:
        """Whether ``parent_id`` sits at or beneath the target folder.

        Args:
            parent_id: The item's immediate parent id, if Graph reported one.

        Returns:
            True/False when the chain could be walked, or None when it could
            not be decided (unknown parent, depth bound, or a failed lookup).
            None is deliberately distinct from False: the caller keeps
            undecidable items rather than dropping them.
        """
        if not parent_id:
            return None
        if parent_id in self._cache:
            return self._cache[parent_id]

        chain: List[str] = []
        current: Optional[str] = parent_id
        verdict: Optional[bool] = None

        for _ in range(self.max_depth):
            if current is None:
                verdict = False  # walked off the top: not under the folder
                break
            if current in self._cache:
                verdict = self._cache[current]
                break
            if current == self.folder_id:
                verdict = True
                break
            chain.append(current)
            try:
                item = await (
                    self.client.graph_client.drives.by_drive_id(self.drive_id)
                    .items.by_drive_item_id(current)
                    .get()
                )
            except Exception as exc:  # noqa: BLE001 - undecidable, not fatal
                self.logger.warning(
                    "Could not resolve ancestry of item %s on drive %s: %s",
                    current, self.drive_id, exc,
                )
                verdict = None
                break
            parent = _field(item, "parent_reference", "parentReference")
            current = _field(parent, "id")
        else:
            self.logger.warning(
                "Ancestry walk for drive %s exceeded %s levels; membership "
                "left undecided.",
                self.drive_id, self.max_depth,
            )

        for seen in chain:
            self._cache[seen] = verdict
        return verdict


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
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER,
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
            max_backoff: Upper bound for a *self-computed* backoff delay, in
                seconds. It never truncates a server-supplied ``Retry-After``.
            max_retry_after: Longest server-requested ``Retry-After`` to wait
                out. A larger interval abandons the round instead of retrying
                early.
            max_pages: Hard bound on pages followed in one enumeration.
            sleep: Awaitable sleep function; injectable for deterministic
                tests. Defaults to :func:`asyncio.sleep`.
            logger_instance: Optional logger override.

        Raises:
            ValueError: If a bound is negative or ``max_pages`` is not positive.
        """
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if initial_backoff < 0 or max_backoff < 0 or max_retry_after < 0:
            raise ValueError("backoff values must be >= 0")
        if max_pages <= 0:
            raise ValueError("max_pages must be > 0")

        self.allowed_origins = tuple(allowed_origins)
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.max_retry_after = max_retry_after
        self.max_pages = max_pages
        self._sleep = sleep or asyncio.sleep
        self.logger = logger_instance or logger

    # -- link validation ---------------------------------------------------

    def validate_link(self, link: str, drive_id: str) -> str:
        """Validate a continuation link before it is dereferenced.

        Args:
            link: Opaque nextLink/deltaLink value.
            drive_id: Drive the enumeration is confined to. The link must
                address that drive's delta endpoint, not merely a trusted
                Graph origin.

        Returns:
            The validated link.

        Raises:
            DeltaLinkValidationError: If the link is not a trusted Graph
                delta URL for ``drive_id``.
        """
        return validate_continuation_link(link, drive_id, self.allowed_origins)

    # -- single page -------------------------------------------------------

    def _delta_builder(self, client: Any, drive_id: str) -> Any:
        """Build the drive-root delta request builder for ``drive_id``."""
        return client.graph_client.drives.by_drive_id(drive_id).items.by_drive_item_id("root").delta

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
            DeltaLinkValidationError: If ``link`` is not this drive's delta
                endpoint on a trusted Graph origin. Raised before any
                request is issued.
            DeltaResetRequiredError: If Graph answered 410 Gone.
            DeltaRetryExhaustedError: If retries hit their bound.
        """
        builder = self._delta_builder(client, drive_id)
        if link is not None:
            # ``with_url`` replaces the whole URL, so validate the path — not
            # just the origin — BEFORE the token is attached to a request.
            validated = self.validate_link(link, drive_id)
            builder = builder.with_url(validated)

        response = await self._get_with_retry(builder, drive_id)
        return self._build_page(response, drive_id)

    async def _get_with_retry(self, builder: Any, drive_id: str) -> Any:
        """Issue ``builder.get()``, retrying throttling/transient failures."""
        attempt = 0
        backoff = self.initial_backoff
        last_error: Optional[BaseException] = None
        reason = "retries exhausted"

        while attempt <= self.max_retries:
            attempt += 1
            try:
                return await builder.get()
            except Exception as exc:  # noqa: BLE001 - re-raised below
                status = _status_code_of(exc)
                if status == RESET_STATUS_CODE:
                    raise DeltaResetRequiredError(drive_id) from exc
                retryable = status in RETRYABLE_STATUS_CODES or (
                    status is None and isinstance(exc, TRANSIENT_EXCEPTION_TYPES)
                )
                if not retryable:
                    raise
                last_error = exc
                if attempt > self.max_retries:
                    break

                retry_after = _retry_after_seconds(exc)
                if retry_after is not None:
                    # Microsoft requires clients to wait the full interval the
                    # service asked for. Truncating it to our own backoff cap
                    # would retry while still throttled, so instead we honour
                    # it up to `max_retry_after` and give up beyond that —
                    # surfacing the throttle rather than hammering Graph.
                    if retry_after > self.max_retry_after:
                        self.logger.warning(
                            "Graph asked drive %s to wait %.0fs (> " "max_retry_after=%.0fs); abandoning this round.",
                            drive_id,
                            retry_after,
                            self.max_retry_after,
                        )
                        reason = (
                            f"server asked for a {retry_after:.0f}s wait, "
                            f"beyond the {self.max_retry_after:.0f}s budget"
                        )
                        break
                    delay = retry_after
                else:
                    delay = min(backoff, self.max_backoff)

                self.logger.warning(
                    "Graph delta request for drive %s returned %s; " "retry %s/%s in %.2fs",
                    drive_id,
                    status,
                    attempt,
                    self.max_retries,
                    delay,
                )
                if delay > 0:
                    await self._sleep(delay)
                backoff = min(backoff * 2 if backoff else self.initial_backoff, self.max_backoff)

        raise DeltaRetryExhaustedError(attempt, last_error or RuntimeError("unknown"), reason)

    def _build_page(self, response: Any, drive_id: str) -> DeltaPage:
        """Project a Graph delta response onto :class:`DeltaPage`."""
        if response is None:
            return DeltaPage(drive_id=drive_id)

        raw_items: Iterable[Any] = _field(response, "value") or []
        items: List[DeltaItem] = []
        skipped = 0
        for raw in raw_items:
            item = drive_item_to_delta_item(raw, drive_id)
            if item is None:
                skipped += 1
                continue
            items.append(item)

        # Validate here rather than only at follow-time, so a DeltaPage
        # obtained through the public fetch_page() never carries a link a
        # caller could dereference unchecked.
        next_link = _field(response, "odata_next_link", "@odata.nextLink")
        delta_link = _field(response, "odata_delta_link", "@odata.deltaLink")
        if next_link is not None:
            next_link = self.validate_link(next_link, drive_id)
        if delta_link is not None:
            delta_link = self.validate_link(delta_link, drive_id)

        return DeltaPage(
            drive_id=drive_id,
            items=items,
            next_link=next_link,
            delta_link=delta_link,
            skipped_entries=skipped,
        )

    # -- full enumeration --------------------------------------------------

    async def enumerate(
        self,
        client: Any,
        drive_id: str,
        *,
        delta_link: Optional[str] = None,
        folder_path: Optional[str] = None,
        folder_id: Optional[str] = None,
        resolve_ancestry: bool = True,
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
            folder_path: Drive-relative folder path to filter items to,
                applied locally because Graph delta is drive-level. Graph
                omits parentReference.path from delta responses, so prefer
                ``folder_id``; see :attr:`DeltaEnumeration.unresolved_parent`.
            folder_id: Stable folder item id to filter items to. With
                ``resolve_ancestry`` this scopes to the whole subtree.
            resolve_ancestry: When a ``folder_id`` is given, walk each
                unmatched item's parent chain through Graph (cached) so
                nested descendants are included, not just direct children.
                Disable to stay offline and match direct children only.
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
                folder_id=folder_id,
                resolve_ancestry=resolve_ancestry,
                max_pages=max_pages,
                reset_performed=False,
            )
        except DeltaResetRequiredError:
            self.logger.warning(
                "Delta cursor for drive %s expired (410 Gone); " "restarting a full rescan.",
                drive_id,
            )
            return await self._enumerate_once(
                client,
                drive_id,
                delta_link=None,
                folder_path=folder_path,
                folder_id=folder_id,
                resolve_ancestry=resolve_ancestry,
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
        folder_id: Optional[str],
        resolve_ancestry: bool,
        max_pages: Optional[int],
        reset_performed: bool,
    ) -> DeltaEnumeration:
        """Walk the feed a single time, without 410 recovery."""
        page_bound = self.max_pages if max_pages is None else max_pages
        if page_bound <= 0:
            raise ValueError("max_pages must be > 0")

        # De-duplicate by item id: a delta feed may report the same item on
        # several pages, and the latest occurrence is authoritative.
        ancestry: Optional[FolderAncestryResolver] = None
        if folder_id and resolve_ancestry:
            ancestry = FolderAncestryResolver(
                client, drive_id, folder_id, logger_instance=self.logger
            )

        collected: Dict[str, DeltaItem] = {}
        order: List[str] = []
        unresolved: set[str] = set()
        excluded: set[str] = set()
        skipped = 0
        pages = 0
        final_link: Optional[str] = None
        link = delta_link

        while pages < page_bound:
            page = await self.fetch_page(client, drive_id, link=link)
            pages += 1
            skipped += page.skipped_entries

            for item in page.items:
                membership = classify_folder_membership(item, folder_path, folder_id)
                if membership != FOLDER_MATCH and ancestry is not None:
                    # A direct-parent mismatch does not mean "outside": the
                    # item may sit deeper in the subtree. Ask Graph.
                    within = await ancestry.is_within(item.parent_id)
                    if within is True:
                        membership = FOLDER_MATCH
                    elif within is False:
                        membership = FOLDER_MISS
                    else:
                        membership = FOLDER_UNKNOWN
                if membership == FOLDER_MISS:
                    # Counted per distinct item, like every other counter on
                    # DeltaEnumeration — an item reported outside the folder
                    # on two pages is one exclusion, not two.
                    excluded.add(item.item_id)
                    unresolved.discard(item.item_id)
                    # Graph: "the same item may appear more than once... use
                    # the last occurrence". If an earlier page placed this
                    # item inside the folder and a later one moved it out,
                    # the later state wins — keeping the stale in-folder copy
                    # would report a location the item no longer has.
                    if item.item_id in collected:
                        del collected[item.item_id]
                        order.remove(item.item_id)
                    continue
                excluded.discard(item.item_id)
                if membership == FOLDER_UNKNOWN:
                    unresolved.add(item.item_id)
                else:
                    unresolved.discard(item.item_id)
                if item.item_id not in collected:
                    order.append(item.item_id)
                collected[item.item_id] = item

            if page.delta_link is not None:
                # Validate the cursor we hand back so a poisoned final link is
                # rejected here rather than on the consumer's next round.
                final_link = self.validate_link(page.delta_link, drive_id)
                break
            if page.next_link is None:
                # No continuation and no cursor: the feed ended without giving
                # us a cursor to commit. Treat as truncated, not complete.
                self.logger.warning(
                    "Delta page %s for drive %s carried neither nextLink nor "
                    "deltaLink; stopping without a committable cursor.",
                    pages,
                    drive_id,
                )
                break
            link = page.next_link
        else:
            self.logger.warning(
                "Delta enumeration for drive %s hit the %s page bound; " "no cursor is committable.",
                drive_id,
                page_bound,
            )

        return DeltaEnumeration(
            drive_id=drive_id,
            items=[collected[item_id] for item_id in order],
            delta_link=final_link,
            pages_fetched=pages,
            # An enumeration that dropped unreconcilable entries is not a
            # complete picture, so it must not authorise a cursor commit.
            complete=final_link is not None and skipped == 0,
            reset_performed=reset_performed,
            full_enumeration=delta_link is None,
            folder_path=(folder_path or None),
            folder_id=(folder_id or None),
            filtered_out=len(excluded),
            skipped_entries=skipped,
            unresolved_parent=len(unresolved),
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
    "DEFAULT_MAX_RETRY_AFTER",
    "FOLDER_MATCH",
    "FOLDER_MISS",
    "FOLDER_UNKNOWN",
    "DEFAULT_MAX_ANCESTRY_DEPTH",
    "DriveDeltaHelper",
    "FolderAncestryResolver",
    "classify_folder_membership",
    "drive_item_to_delta_item",
    "item_in_folder",
    "normalize_drive_path",
    "validate_continuation_link",
)
