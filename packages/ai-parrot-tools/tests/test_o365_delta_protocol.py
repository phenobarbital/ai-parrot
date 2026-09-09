"""Unit tests for ``parrot_tools.o365.delta`` (FEAT-539 / TASK-3041).

The Microsoft Graph drive delta helper is exercised entirely against a fake
Graph surface: multipage feeds, empty intermediate pages, final cursors,
duplicate items, tombstones, 410 resets, bounded throttling retries and
continuation-host validation.

No network access, no credentials and no live Graph tenant are involved.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pytest

from parrot_tools.o365 import delta as delta_mod
from parrot_tools.o365.delta import (
    DEFAULT_GRAPH_ORIGINS,
    DeltaEnumeration,
    DeltaItem,
    DeltaLinkValidationError,
    DeltaPage,
    DeltaResetRequiredError,
    DeltaRetryExhaustedError,
    DriveDeltaHelper,
    drive_item_to_delta_item,
    item_in_folder,
    normalize_drive_path,
    validate_continuation_link,
)

GRAPH = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "b!fake-drive-id"


# ============================================================================
# FAKE GRAPH SURFACE
# ============================================================================

class FakeHashes:
    """Stand-in for msgraph ``Hashes``."""

    def __init__(self, quick_xor_hash: Optional[str] = None) -> None:
        self.quick_xor_hash = quick_xor_hash
        self.sha1_hash = None
        self.sha256_hash = None
        self.crc32_hash = None


class FakeFileFacet:
    """Stand-in for the msgraph ``file`` facet."""

    def __init__(self, quick_xor_hash: Optional[str] = None) -> None:
        self.hashes = FakeHashes(quick_xor_hash)


class FakeParentReference:
    """Stand-in for msgraph ``ItemReference``."""

    def __init__(
        self,
        path: Optional[str] = None,
        id: Optional[str] = None,
        drive_id: Optional[str] = None,
    ) -> None:
        self.path = path
        self.id = id
        self.drive_id = drive_id


class FakeDriveItem:
    """Stand-in for msgraph ``DriveItem`` carrying only delta-relevant fields."""

    def __init__(
        self,
        *,
        id: Optional[str],
        name: Optional[str] = None,
        deleted: Any = None,
        folder: Any = None,
        parent_path: Optional[str] = None,
        parent_id: Optional[str] = None,
        drive_id: Optional[str] = None,
        size: Optional[int] = None,
        e_tag: Optional[str] = None,
        c_tag: Optional[str] = None,
        web_url: Optional[str] = None,
        last_modified_date_time: Optional[str] = None,
        quick_xor_hash: Optional[str] = None,
    ) -> None:
        self.id = id
        self.name = name
        self.deleted = deleted
        self.folder = folder
        self.parent_reference = FakeParentReference(
            path=parent_path, id=parent_id, drive_id=drive_id
        )
        self.size = size
        self.e_tag = e_tag
        self.c_tag = c_tag
        self.web_url = web_url
        self.last_modified_date_time = last_modified_date_time
        self.file = FakeFileFacet(quick_xor_hash) if quick_xor_hash else None


class FakeDeltaResponse:
    """Stand-in for msgraph ``DeltaGetResponse``."""

    def __init__(
        self,
        value: Sequence[Any],
        next_link: Optional[str] = None,
        delta_link: Optional[str] = None,
    ) -> None:
        self.value = list(value)
        self.odata_next_link = next_link
        self.odata_delta_link = delta_link


class FakeGraphError(Exception):
    """Stand-in for a kiota ``APIError`` / msgraph ``ODataError``."""

    def __init__(
        self,
        status_code: int,
        retry_after: Optional[str] = None,
        message: str = "fake graph error",
    ) -> None:
        super().__init__(message)
        self.response_status_code = status_code
        self.response_headers = (
            {"retry-after": {retry_after}} if retry_after is not None else {}
        )


class FakeDeltaRequestBuilder:
    """Fake ``DeltaRequestBuilder`` recording every URL it is asked to GET."""

    def __init__(self, graph: "FakeGraph", url: Optional[str] = None) -> None:
        self._graph = graph
        self._url = url

    def with_url(self, raw_url: str) -> "FakeDeltaRequestBuilder":
        return FakeDeltaRequestBuilder(self._graph, raw_url)

    async def get(self) -> Any:
        return await self._graph._respond(self._url)


class _FakeItemsCollection:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    def by_drive_item_id(self, item_id: str) -> "_FakeDriveItemBuilder":
        self._graph.requested_root_ids.append(item_id)
        return _FakeDriveItemBuilder(self._graph)


class _FakeDriveItemBuilder:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def delta(self) -> FakeDeltaRequestBuilder:
        return FakeDeltaRequestBuilder(self._graph)


class _FakeDriveBuilder:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def items(self) -> _FakeItemsCollection:
        return _FakeItemsCollection(self._graph)


class _FakeDrivesCollection:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    def by_drive_id(self, drive_id: str) -> _FakeDriveBuilder:
        self._graph.requested_drive_ids.append(drive_id)
        return _FakeDriveBuilder(self._graph)


class FakeGraph:
    """Minimal fake ``GraphServiceClient`` serving a scripted delta feed.

    ``responses`` maps a requested URL (or ``None`` for the initial,
    URL-less request) to either a :class:`FakeDeltaResponse` or an exception
    instance to raise. A list value is consumed one entry per call, which is
    how throttling-then-success and 410-then-rescan are scripted.
    """

    def __init__(self, responses: Dict[Optional[str], Any]) -> None:
        self.responses = {k: list(v) if isinstance(v, list) else [v]
                          for k, v in responses.items()}
        self.requested_urls: List[Optional[str]] = []
        self.requested_drive_ids: List[str] = []
        self.requested_root_ids: List[str] = []

    @property
    def drives(self) -> _FakeDrivesCollection:
        return _FakeDrivesCollection(self)

    async def _respond(self, url: Optional[str]) -> Any:
        self.requested_urls.append(url)
        if url not in self.responses:
            raise AssertionError(f"Unscripted delta request for URL: {url!r}")
        queue = self.responses[url]
        entry = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(entry, BaseException):
            raise entry
        return entry


class FakeO365Client:
    """Fake authenticated client exposing only ``graph_client``.

    It also exposes download/ingest style attributes so a test can prove the
    delta helper never touches them.
    """

    def __init__(self, graph: FakeGraph) -> None:
        self._graph = graph
        self.download_calls: List[Any] = []

    @property
    def graph_client(self) -> FakeGraph:
        return self._graph

    async def file_download(self, *args: Any, **kwargs: Any) -> Any:
        self.download_calls.append((args, kwargs))
        raise AssertionError("delta helper must not download content")


@pytest.fixture
def sleeps() -> List[float]:
    """Collect the backoff delays a helper would have slept for."""
    return []


@pytest.fixture
def helper(sleeps: List[float]) -> DriveDeltaHelper:
    """A helper with deterministic (recorded, non-blocking) sleeps."""
    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return DriveDeltaHelper(
        max_retries=2,
        initial_backoff=1.0,
        max_backoff=8.0,
        sleep=_sleep,
    )


# ============================================================================
# AC1 — fake Graph pages: multipage, empty page, final cursor, duplicate,
#       deleted marker
# ============================================================================

class TestPageEnumeration:
    """Fake Graph pages cover the full shape of a delta feed."""

    async def test_multipage_with_empty_intermediate_and_final_cursor(
        self, helper: DriveDeltaHelper
    ) -> None:
        """A three-page feed ends on the delta link and keeps page order."""
        page2 = f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta?token=p2"
        page3 = f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta?token=p3"
        final = f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta?token=final"

        graph = FakeGraph({
            None: FakeDeltaResponse(
                [FakeDriveItem(id="item-1", name="a.docx",
                               parent_path="/drive/root:")],
                next_link=page2,
            ),
            # Empty intermediate page: legal in Graph, must not end the walk.
            page2: FakeDeltaResponse([], next_link=page3),
            page3: FakeDeltaResponse(
                [FakeDriveItem(id="item-2", name="b.docx",
                               parent_path="/drive/root:")],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert isinstance(result, DeltaEnumeration)
        assert result.pages_fetched == 3
        assert result.complete is True
        assert result.delta_link == final
        assert result.full_enumeration is True
        assert result.reset_performed is False
        assert [i.item_id for i in result.items] == ["item-1", "item-2"]
        assert graph.requested_urls == [None, page2, page3]
        # Drive-level delta anchored at the drive root.
        assert graph.requested_drive_ids == [DRIVE_ID] * 3
        assert graph.requested_root_ids == ["root"] * 3

    async def test_duplicate_item_across_pages_keeps_latest(
        self, helper: DriveDeltaHelper
    ) -> None:
        """The same item on two pages collapses; the later state wins."""
        page2 = f"{GRAPH}/delta?token=p2"
        final = f"{GRAPH}/delta?token=final"

        graph = FakeGraph({
            None: FakeDeltaResponse(
                [FakeDriveItem(id="dup", name="old-name.docx",
                               parent_path="/drive/root:", size=10)],
                next_link=page2,
            ),
            page2: FakeDeltaResponse(
                [FakeDriveItem(id="dup", name="new-name.docx",
                               parent_path="/drive/root:", size=99)],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert len(result.items) == 1
        assert result.items[0].name == "new-name.docx"
        assert result.items[0].size == 99

    async def test_deleted_marker_is_surfaced_as_tombstone(
        self, helper: DriveDeltaHelper
    ) -> None:
        """Items carrying the deleted facet become tombstones, not drops."""
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: FakeDeltaResponse(
                [
                    FakeDriveItem(id="alive", name="keep.docx",
                                  parent_path="/drive/root:"),
                    FakeDriveItem(id="gone", name="removed.docx",
                                  deleted=object(),
                                  parent_path="/drive/root:"),
                ],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert [i.item_id for i in result.deleted_items] == ["gone"]
        assert [i.item_id for i in result.changed_items] == ["alive"]

    async def test_resume_from_stored_cursor_is_not_a_full_enumeration(
        self, helper: DriveDeltaHelper
    ) -> None:
        """Passing a stored delta link resumes rather than rescans."""
        stored = f"{GRAPH}/delta?token=stored"
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({stored: FakeDeltaResponse([], delta_link=final)})

        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, delta_link=stored
        )

        assert graph.requested_urls == [stored]
        assert result.full_enumeration is False
        assert result.delta_link == final

    async def test_entry_without_stable_id_is_skipped(
        self, helper: DriveDeltaHelper
    ) -> None:
        """An entry Graph reported without an id cannot be reconciled."""
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: FakeDeltaResponse(
                [FakeDriveItem(id=None, name="ghost.docx"),
                 FakeDriveItem(id="real", name="real.docx")],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)
        assert [i.item_id for i in result.items] == ["real"]

    async def test_page_bound_truncates_without_committable_cursor(
        self, helper: DriveDeltaHelper
    ) -> None:
        """Hitting the page bound yields no cursor, forcing idempotent replay."""
        loop_link = f"{GRAPH}/delta?token=loop"
        graph = FakeGraph({
            None: FakeDeltaResponse([FakeDriveItem(id="x")], next_link=loop_link),
            loop_link: FakeDeltaResponse(
                [FakeDriveItem(id="x")], next_link=loop_link
            ),
        })
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, max_pages=3
        )

        assert result.pages_fetched == 3
        assert result.complete is False
        assert result.delta_link is None

    async def test_page_without_any_link_stops_without_cursor(
        self, helper: DriveDeltaHelper
    ) -> None:
        """A page with neither link ends the walk but commits nothing."""
        graph = FakeGraph({None: FakeDeltaResponse([FakeDriveItem(id="only")])})
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.pages_fetched == 1
        assert result.complete is False
        assert result.delta_link is None

    async def test_none_response_yields_empty_page(
        self, helper: DriveDeltaHelper
    ) -> None:
        """A null Graph body degrades to an empty page, not a crash."""
        graph = FakeGraph({None: None})
        page = await helper.fetch_page(FakeO365Client(graph), DRIVE_ID)

        assert isinstance(page, DeltaPage)
        assert page.items == []
        assert page.is_final is False


class TestFolderFiltering:
    """Drive-level delta is scoped locally by folder."""

    async def test_folder_filter_keeps_subtree_and_counts_drops(
        self, helper: DriveDeltaHelper
    ) -> None:
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: FakeDeltaResponse(
                [
                    FakeDriveItem(id="in-root-of-folder", name="a.docx",
                                  parent_path="/drive/root:/Contracts"),
                    FakeDriveItem(id="in-subfolder", name="b.docx",
                                  parent_path="/drive/root:/Contracts/2026"),
                    FakeDriveItem(id="outside", name="c.docx",
                                  parent_path="/drive/root:/Invoices"),
                    FakeDriveItem(id="prefix-trap", name="d.docx",
                                  parent_path="/drive/root:/ContractsArchive"),
                ],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_path="Contracts"
        )

        assert [i.item_id for i in result.items] == [
            "in-root-of-folder", "in-subfolder"
        ]
        assert result.filtered_out == 2
        assert result.folder_path == "Contracts"

    async def test_tombstone_without_parent_path_is_retained(
        self, helper: DriveDeltaHelper
    ) -> None:
        """An unlocatable tombstone is kept so a retraction is never lost."""
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: FakeDeltaResponse(
                [FakeDriveItem(id="gone", deleted=object())],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_path="Contracts"
        )
        assert [i.item_id for i in result.items] == ["gone"]

    def test_item_in_folder_semantics(self) -> None:
        inside = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="Contracts")
        deeper = DeltaItem(drive_id=DRIVE_ID, item_id="i",
                           parent_path="Contracts/2026/Q1")
        sibling = DeltaItem(drive_id=DRIVE_ID, item_id="i",
                            parent_path="ContractsArchive")
        unknown = DeltaItem(drive_id=DRIVE_ID, item_id="i")

        assert item_in_folder(inside, "Contracts") is True
        assert item_in_folder(deeper, "/Contracts/") is True
        assert item_in_folder(sibling, "Contracts") is False
        assert item_in_folder(unknown, "Contracts") is True
        assert item_in_folder(sibling, None) is True
        assert item_in_folder(sibling, "") is True


class TestItemProjection:
    """Graph driveItems project onto stable, typed delta items."""

    def test_full_projection(self) -> None:
        raw = FakeDriveItem(
            id="item-1",
            name="contract.docx",
            parent_path="/drives/b!other/root:/Contracts/2026",
            parent_id="parent-1",
            drive_id="b!other",
            size=1234,
            e_tag="etag-1",
            c_tag="ctag-1",
            web_url="https://contoso.sharepoint.com/x",
            last_modified_date_time="2026-09-09T10:00:00Z",
            quick_xor_hash="QXH",
        )
        item = drive_item_to_delta_item(raw, DRIVE_ID)

        assert item is not None
        assert item.drive_id == "b!other"
        assert item.item_id == "item-1"
        assert item.parent_path == "Contracts/2026"
        assert item.path == "Contracts/2026/contract.docx"
        assert item.deleted is False
        assert item.is_folder is False
        assert item.content_hashes == {"quickXorHash": "QXH"}
        assert item.last_modified is not None
        assert item.last_modified.year == 2026

    def test_folder_projection_and_root_path(self) -> None:
        raw = FakeDriveItem(id="f1", name="Contracts", folder=object(),
                            parent_path="/drive/root:")
        item = drive_item_to_delta_item(raw, DRIVE_ID)

        assert item is not None
        assert item.is_folder is True
        assert item.parent_path == ""
        assert item.path == "Contracts"

    def test_missing_id_returns_none(self) -> None:
        assert drive_item_to_delta_item(FakeDriveItem(id=None), DRIVE_ID) is None

    def test_unparseable_timestamp_is_dropped(self) -> None:
        raw = FakeDriveItem(id="i", last_modified_date_time="not-a-date")
        item = drive_item_to_delta_item(raw, DRIVE_ID)
        assert item is not None and item.last_modified is None

    @pytest.mark.parametrize(
        "raw_path,expected",
        [
            (None, None),
            ("/drive/root:", ""),
            ("/drive/root:/Contracts", "Contracts"),
            ("/drives/b!x/root:/Contracts/2026", "Contracts/2026"),
            ("Contracts/2026", "Contracts/2026"),
        ],
    )
    def test_normalize_drive_path(
        self, raw_path: Optional[str], expected: Optional[str]
    ) -> None:
        assert normalize_drive_path(raw_path) == expected


# ============================================================================
# AC2 — 410 rescan, bounded/throttle-aware retry, foreign-host rejection
# ============================================================================

class TestResetOn410:
    """410 Gone triggers a safe full rescan, never a mass deletion."""

    async def test_410_restarts_enumeration_and_flags_rescan(
        self, helper: DriveDeltaHelper
    ) -> None:
        stored = f"{GRAPH}/delta?token=expired"
        final = f"{GRAPH}/delta?token=fresh"
        graph = FakeGraph({
            stored: FakeGraphError(410),
            None: FakeDeltaResponse(
                [FakeDriveItem(id="a", name="a.docx",
                               parent_path="/drive/root:")],
                delta_link=final,
            ),
        })
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, delta_link=stored
        )

        assert result.reset_performed is True
        assert result.full_enumeration is True
        assert result.complete is True
        assert result.delta_link == final
        # A rescan reports live items, not tombstones.
        assert result.deleted_items == []
        assert graph.requested_urls == [stored, None]

    async def test_410_is_not_retried_as_a_transient_failure(
        self, helper: DriveDeltaHelper, sleeps: List[float]
    ) -> None:
        stored = f"{GRAPH}/delta?token=expired"
        graph = FakeGraph({
            stored: FakeGraphError(410),
            None: FakeDeltaResponse([], delta_link=f"{GRAPH}/delta?token=f"),
        })
        await helper.enumerate(FakeO365Client(graph), DRIVE_ID, delta_link=stored)

        assert sleeps == []  # no backoff burned on a reset

    async def test_fetch_page_propagates_reset_to_caller(
        self, helper: DriveDeltaHelper
    ) -> None:
        stored = f"{GRAPH}/delta?token=expired"
        graph = FakeGraph({stored: FakeGraphError(410)})

        with pytest.raises(DeltaResetRequiredError) as excinfo:
            await helper.fetch_page(FakeO365Client(graph), DRIVE_ID, link=stored)

        assert excinfo.value.drive_id == DRIVE_ID
        assert "mass-deletion" in str(excinfo.value).lower()


class TestBoundedRetry:
    """Throttling and transient failures retry within a hard bound."""

    async def test_throttling_honours_retry_after_then_succeeds(
        self, helper: DriveDeltaHelper, sleeps: List[float]
    ) -> None:
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: [
                FakeGraphError(429, retry_after="5"),
                FakeDeltaResponse([FakeDriveItem(id="a")], delta_link=final),
            ],
        })
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [5.0]  # Retry-After respected, not the default backoff
        assert result.complete is True

    async def test_retry_after_is_capped_by_max_backoff(
        self, sleeps: List[float]
    ) -> None:
        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        capped = DriveDeltaHelper(
            max_retries=1, initial_backoff=1.0, max_backoff=3.0, sleep=_sleep
        )
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: [
                FakeGraphError(503, retry_after="600"),
                FakeDeltaResponse([], delta_link=final),
            ],
        })
        await capped.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [3.0]

    async def test_retries_are_bounded_and_then_raise(
        self, helper: DriveDeltaHelper, sleeps: List[float]
    ) -> None:
        graph = FakeGraph({
            None: [FakeGraphError(503) for _ in range(10)],
        })
        with pytest.raises(DeltaRetryExhaustedError) as excinfo:
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        # max_retries=2 -> 3 attempts total, 2 backoffs, exponential.
        assert excinfo.value.attempts == 3
        assert len(graph.requested_urls) == 3
        assert sleeps == [1.0, 2.0]

    async def test_non_retryable_error_propagates_immediately(
        self, helper: DriveDeltaHelper, sleeps: List[float]
    ) -> None:
        graph = FakeGraph({None: FakeGraphError(403, message="forbidden")})

        with pytest.raises(FakeGraphError):
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert len(graph.requested_urls) == 1
        assert sleeps == []

    async def test_zero_retries_disables_backoff(self, sleeps: List[float]) -> None:
        async def _sleep(seconds: float) -> None:  # pragma: no cover
            sleeps.append(seconds)

        strict = DriveDeltaHelper(max_retries=0, sleep=_sleep)
        graph = FakeGraph({None: [FakeGraphError(429) for _ in range(3)]})

        with pytest.raises(DeltaRetryExhaustedError):
            await strict.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert len(graph.requested_urls) == 1
        assert sleeps == []

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_retries": -1},
            {"initial_backoff": -1.0},
            {"max_backoff": -1.0},
            {"max_pages": 0},
        ],
    )
    def test_invalid_bounds_rejected(self, kwargs: Dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            DriveDeltaHelper(**kwargs)


class TestContinuationHostValidation:
    """Credentials are never forwarded to a foreign continuation host."""

    async def test_malicious_next_link_rejected_before_request(
        self, helper: DriveDeltaHelper
    ) -> None:
        evil = "https://evil.example.com/v1.0/drives/x/items/root/delta?token=steal"
        graph = FakeGraph({
            None: FakeDeltaResponse([FakeDriveItem(id="a")], next_link=evil),
        })
        client = FakeO365Client(graph)

        with pytest.raises(DeltaLinkValidationError) as excinfo:
            await helper.enumerate(client, DRIVE_ID)

        assert "evil.example.com" in str(excinfo.value)
        # The poisoned URL was never dereferenced: only the initial request ran.
        assert graph.requested_urls == [None]

    async def test_malicious_final_delta_link_rejected(
        self, helper: DriveDeltaHelper
    ) -> None:
        evil = "https://evil.example.com/delta?token=steal"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=evil)})

        with pytest.raises(DeltaLinkValidationError):
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

    async def test_untrusted_stored_cursor_rejected_before_request(
        self, helper: DriveDeltaHelper
    ) -> None:
        graph = FakeGraph({})  # any request at all would raise AssertionError

        with pytest.raises(DeltaLinkValidationError):
            await helper.fetch_page(
                FakeO365Client(graph),
                DRIVE_ID,
                link="https://attacker.invalid/delta?token=x",
            )

        assert graph.requested_urls == []

    @pytest.mark.parametrize(
        "link",
        [
            "",
            "   ",
            "http://graph.microsoft.com/delta",          # not https
            "ftp://graph.microsoft.com/delta",
            "https://graph.microsoft.com.evil.tld/delta",  # suffix spoof
            "https://evil.com/https://graph.microsoft.com/delta",
            "https://graph.microsoft.com:8443/delta",    # non-standard port
            "/relative/delta",
        ],
    )
    def test_rejected_links(self, link: str) -> None:
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link)

    @pytest.mark.parametrize("origin", DEFAULT_GRAPH_ORIGINS)
    def test_all_sovereign_graph_origins_accepted(self, origin: str) -> None:
        link = f"{origin}/v1.0/drives/x/items/root/delta?token=abc"
        assert validate_continuation_link(link) == link

    def test_explicit_port_443_accepted(self) -> None:
        link = "https://graph.microsoft.com:443/v1.0/delta?token=a"
        assert validate_continuation_link(link) == link

    def test_custom_allowed_origin(self) -> None:
        link = "https://graph.internal.test/delta"
        assert validate_continuation_link(
            link, allowed_origins=("https://graph.internal.test",)
        ) == link
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link)


# ============================================================================
# AC3 — the helper stays a transport: no contracts import, no cursor commit,
#       no document ingestion
# ============================================================================

class TestHelperBoundaries:
    """The delta module is transport-only and contracts-free."""

    def test_module_imports_no_contracts_or_scheduler_package(self) -> None:
        source = Path(delta_mod.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "parrot.knowledge.contracts",
            "parrot_tools.contracts",
            "parrot.scheduler",
        ):
            assert forbidden not in source, (
                f"delta helper must not reference {forbidden}"
            )

    def test_no_contracts_module_is_imported_at_runtime(self) -> None:
        """Importing the delta module must not drag in any contracts package.

        Checked in a clean subprocess so an unrelated test in the same
        session cannot mask (or fake) the result.
        """
        import subprocess
        import sys

        probe = (
            "import sys;"
            "import parrot_tools.o365.delta;"
            "bad=[n for n in sys.modules if n.startswith("
            "('parrot.knowledge.contracts','parrot_tools.contracts'))];"
            "print('OFFENDERS:'+','.join(sorted(bad)))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=180,
        )
        assert completed.returncode == 0, completed.stderr
        line = next(
            ln for ln in completed.stdout.splitlines()
            if ln.startswith("OFFENDERS:")
        )
        offenders = line.removeprefix("OFFENDERS:").strip()
        assert not offenders, f"delta import pulled in contracts modules: {offenders}"

    def test_helper_exposes_no_cursor_commit_or_ingest_surface(self) -> None:
        public = {
            name for name, _ in inspect.getmembers(DriveDeltaHelper)
            if not name.startswith("_")
        }
        assert public == {"enumerate", "fetch_page", "validate_link"}
        for banned in ("commit", "save", "store", "persist", "ingest",
                       "download", "upload", "set_delta_token"):
            assert not any(banned in name for name in public), (
                f"delta helper must not expose a {banned!r} surface"
            )

    async def test_enumeration_never_downloads_content(
        self, helper: DriveDeltaHelper
    ) -> None:
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({
            None: FakeDeltaResponse(
                [FakeDriveItem(id="a", name="a.docx", quick_xor_hash="H")],
                delta_link=final,
            ),
        })
        client = FakeO365Client(graph)
        await helper.enumerate(client, DRIVE_ID)

        assert client.download_calls == []

    async def test_enumeration_returns_cursor_without_committing_it(
        self, helper: DriveDeltaHelper
    ) -> None:
        """The final cursor is returned to the caller, never stored here."""
        final = f"{GRAPH}/delta?token=final"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=final)})

        first = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)
        # A second call with no cursor still starts from scratch: the helper
        # kept no state between rounds.
        second = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert first.delta_link == final
        assert second.full_enumeration is True
