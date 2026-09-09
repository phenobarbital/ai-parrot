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
    FOLDER_MATCH,
    FOLDER_MISS,
    FOLDER_UNKNOWN,
    DeltaEnumeration,
    DeltaItem,
    DeltaLinkValidationError,
    DeltaPage,
    DeltaResetRequiredError,
    DeltaRetryExhaustedError,
    DriveDeltaHelper,
    classify_folder_membership,
    drive_item_to_delta_item,
    item_in_folder,
    normalize_drive_path,
    validate_continuation_link,
)

GRAPH = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "b!fake-drive-id"
#: Shape Microsoft Graph actually returns for drive delta continuations.
DELTA = f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta"


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
        self.parent_reference = FakeParentReference(path=parent_path, id=parent_id, drive_id=drive_id)
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
        self.response_headers = {"retry-after": {retry_after}} if retry_after is not None else {}


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
        return _FakeDriveItemBuilder(self._graph, item_id)


class _FakeDriveItemBuilder:
    def __init__(self, graph: "FakeGraph", item_id: str = "root") -> None:
        self._graph = graph
        self._item_id = item_id

    @property
    def delta(self) -> FakeDeltaRequestBuilder:
        return FakeDeltaRequestBuilder(self._graph)

    async def get(self) -> Any:
        """Item lookup, used by folder-ancestry resolution."""
        self._graph.item_lookups.append(self._item_id)
        if self._item_id not in self._graph.items_by_id:
            raise AssertionError(f"Unscripted item lookup: {self._item_id!r}")
        entry = self._graph.items_by_id[self._item_id]
        if isinstance(entry, BaseException):
            raise entry
        return entry


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

    def __init__(
        self,
        responses: Dict[Optional[str], Any],
        items_by_id: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.responses = {k: list(v) if isinstance(v, list) else [v] for k, v in responses.items()}
        self.items_by_id = dict(items_by_id or {})
        self.item_lookups: List[str] = []
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

    async def test_multipage_with_empty_intermediate_and_final_cursor(self, helper: DriveDeltaHelper) -> None:
        """A three-page feed ends on the delta link and keeps page order."""
        page2 = f"{DELTA}?token=p2"
        page3 = f"{DELTA}?token=p3"
        final = f"{DELTA}?token=final"

        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="item-1", name="a.docx", parent_path="/drive/root:")],
                    next_link=page2,
                ),
                # Empty intermediate page: legal in Graph, must not end the walk.
                page2: FakeDeltaResponse([], next_link=page3),
                page3: FakeDeltaResponse(
                    [FakeDriveItem(id="item-2", name="b.docx", parent_path="/drive/root:")],
                    delta_link=final,
                ),
            }
        )
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

    async def test_duplicate_item_across_pages_keeps_latest(self, helper: DriveDeltaHelper) -> None:
        """The same item on two pages collapses; the later state wins."""
        page2 = f"{DELTA}?token=p2"
        final = f"{DELTA}?token=final"

        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="dup", name="old-name.docx", parent_path="/drive/root:", size=10)],
                    next_link=page2,
                ),
                page2: FakeDeltaResponse(
                    [FakeDriveItem(id="dup", name="new-name.docx", parent_path="/drive/root:", size=99)],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert len(result.items) == 1
        assert result.items[0].name == "new-name.docx"
        assert result.items[0].size == 99

    async def test_deleted_marker_is_surfaced_as_tombstone(self, helper: DriveDeltaHelper) -> None:
        """Items carrying the deleted facet become tombstones, not drops."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id="alive", name="keep.docx", parent_path="/drive/root:"),
                        FakeDriveItem(id="gone", name="removed.docx", deleted=object(), parent_path="/drive/root:"),
                    ],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert [i.item_id for i in result.deleted_items] == ["gone"]
        assert [i.item_id for i in result.changed_items] == ["alive"]

    async def test_resume_from_stored_cursor_is_not_a_full_enumeration(self, helper: DriveDeltaHelper) -> None:
        """Passing a stored delta link resumes rather than rescans."""
        stored = f"{DELTA}?token=stored"
        final = f"{DELTA}?token=final"
        graph = FakeGraph({stored: FakeDeltaResponse([], delta_link=final)})

        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, delta_link=stored)

        assert graph.requested_urls == [stored]
        assert result.full_enumeration is False
        assert result.delta_link == final

    async def test_entry_without_stable_id_is_skipped(self, helper: DriveDeltaHelper) -> None:
        """An entry Graph reported without an id cannot be reconciled."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id=None, name="ghost.docx"), FakeDriveItem(id="real", name="real.docx")],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)
        assert [i.item_id for i in result.items] == ["real"]

    async def test_unreconcilable_entries_block_the_cursor(self, helper: DriveDeltaHelper) -> None:
        """An entry with no item id means the picture is incomplete.

        Committing a cursor after silently dropping it would permanently
        lose that change, so completeness is withheld.
        """
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id=None, name="ghost.docx"), FakeDriveItem(id="real", name="real.docx")],
                    delta_link=final,
                )
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert [i.item_id for i in result.items] == ["real"]
        assert result.skipped_entries == 1
        assert result.complete is False
        assert result.delta_link == final  # reported, but not committable

    async def test_page_bound_truncates_without_committable_cursor(self, helper: DriveDeltaHelper) -> None:
        """Hitting the page bound yields no cursor, forcing idempotent replay."""
        loop_link = f"{DELTA}?token=loop"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse([FakeDriveItem(id="x")], next_link=loop_link),
                loop_link: FakeDeltaResponse([FakeDriveItem(id="x")], next_link=loop_link),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, max_pages=3)

        assert result.pages_fetched == 3
        assert result.complete is False
        assert result.delta_link is None

    async def test_page_without_any_link_stops_without_cursor(self, helper: DriveDeltaHelper) -> None:
        """A page with neither link ends the walk but commits nothing."""
        graph = FakeGraph({None: FakeDeltaResponse([FakeDriveItem(id="only")])})
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.pages_fetched == 1
        assert result.complete is False
        assert result.delta_link is None

    async def test_none_response_yields_empty_page(self, helper: DriveDeltaHelper) -> None:
        """A null Graph body degrades to an empty page, not a crash."""
        graph = FakeGraph({None: None})
        page = await helper.fetch_page(FakeO365Client(graph), DRIVE_ID)

        assert isinstance(page, DeltaPage)
        assert page.items == []
        assert page.is_final is False


class TestFolderFiltering:
    """Drive-level delta is scoped locally by folder."""

    async def test_folder_filter_keeps_subtree_and_counts_drops(self, helper: DriveDeltaHelper) -> None:
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id="in-root-of-folder", name="a.docx", parent_path="/drive/root:/Contracts"),
                        FakeDriveItem(id="in-subfolder", name="b.docx", parent_path="/drive/root:/Contracts/2026"),
                        FakeDriveItem(id="outside", name="c.docx", parent_path="/drive/root:/Invoices"),
                        FakeDriveItem(id="prefix-trap", name="d.docx", parent_path="/drive/root:/ContractsArchive"),
                    ],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")

        assert [i.item_id for i in result.items] == ["in-root-of-folder", "in-subfolder"]
        assert result.filtered_out == 2
        assert result.folder_path == "Contracts"

    async def test_tombstone_without_parent_path_is_retained_and_counted(self, helper: DriveDeltaHelper) -> None:
        """An unlocatable tombstone is kept so a retraction is never lost."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="gone", deleted=object())],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")
        assert [i.item_id for i in result.items] == ["gone"]
        # Retention is deliberate policy, not uncertainty, so it does not
        # make the filter "unreliable".
        assert result.unresolved_parent == 0
        assert result.folder_filter_reliable is True

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"folder_path": "Contracts"},
            {"folder_id": "folder-x"},
            {"folder_path": "Contracts", "folder_id": "folder-x"},
        ],
    )
    async def test_tombstones_are_never_excluded_by_a_folder_filter(
        self, helper: DriveDeltaHelper, kwargs: Dict[str, str]
    ) -> None:
        """A tombstone survives the filter even when it points elsewhere.

        An item is often tombstoned *because* it left the folder. Excluding
        it would strand the projection the consumer already indexed —
        dropping a retraction is corruption, whereas retracting something
        nobody indexed is a no-op.
        """
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(
                            id="gone",
                            name="removed.docx",
                            deleted=object(),
                            parent_path="/drive/root:/SomewhereElse",
                            parent_id="another-folder",
                        ),
                        FakeDriveItem(
                            id="live-outside",
                            name="other.docx",
                            parent_path="/drive/root:/SomewhereElse",
                            parent_id="another-folder",
                        ),
                    ],
                    delta_link=final,
                )
            }
        )
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, resolve_ancestry=False, **kwargs
        )

        # The tombstone is kept; the live file outside the folder is not.
        assert [i.item_id for i in result.items] == ["gone"]
        assert result.filtered_out == 1

    async def test_real_graph_shape_reports_the_filter_as_unreliable(self, helper: DriveDeltaHelper) -> None:
        """Graph omits parentReference.path in delta responses.

        Per the v1.0 docs: "The parentReference property on items won't
        include a value for path... When using delta you should always track
        items by id." A path filter therefore cannot decide membership, and
        the enumeration must SAY so rather than silently returning the whole
        drive as if it had been filtered.
        """
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id="a", name="a.docx", parent_id="folder-x"),
                        FakeDriveItem(id="b", name="b.docx", parent_id="folder-y"),
                    ],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")

        assert [i.item_id for i in result.items] == ["a", "b"]
        assert result.filtered_out == 0
        assert result.unresolved_parent == 2
        assert result.folder_filter_reliable is False

    async def test_folder_id_filter_is_exact_and_reliable(self, helper: DriveDeltaHelper) -> None:
        """parentReference.id IS reported by delta, so id filtering decides."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id="in", name="a.docx", parent_id="folder-x"),
                        FakeDriveItem(id="out", name="b.docx", parent_id="folder-y"),
                        FakeDriveItem(id="folder-x", name="Contracts", folder=object(), parent_id="root-id"),
                    ],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_id="folder-x",
            resolve_ancestry=False,
        )

        # Direct children plus the folder itself; the sibling is excluded.
        assert {i.item_id for i in result.items} == {"in", "folder-x"}
        assert result.filtered_out == 1
        assert result.unresolved_parent == 0
        assert result.folder_filter_reliable is True
        assert result.folder_id == "folder-x"

    async def test_no_filter_is_always_reliable(self, helper: DriveDeltaHelper) -> None:
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="a"), FakeDriveItem(id="b")],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.unresolved_parent == 0
        assert result.folder_filter_reliable is True
        assert result.folder_path is None and result.folder_id is None

    async def test_ancestry_walk_includes_nested_descendants(
        self, helper: DriveDeltaHelper
    ) -> None:
        """Graph omits the path, so a subtree is scoped by walking parent ids.

        `nested` sits in Contracts/2026, whose parent is the target folder,
        so a direct-parent comparison would wrongly exclude it.
        """
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id="direct", name="a.docx",
                                      parent_id="folder-x"),
                        FakeDriveItem(id="nested", name="b.docx",
                                      parent_id="folder-2026"),
                        FakeDriveItem(id="outside", name="c.docx",
                                      parent_id="folder-other"),
                    ],
                    delta_link=final,
                )
            },
            items_by_id={
                "folder-2026": FakeDriveItem(id="folder-2026", name="2026",
                                             folder=object(),
                                             parent_id="folder-x"),
                "folder-other": FakeDriveItem(id="folder-other", name="Other",
                                              folder=object(),
                                              parent_id=None),
            },
        )
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_id="folder-x"
        )

        assert {i.item_id for i in result.items} == {"direct", "nested"}
        assert result.filtered_out == 1
        assert result.unresolved_parent == 0
        assert result.folder_filter_reliable is True

    async def test_ancestry_results_are_cached_per_enumeration(
        self, helper: DriveDeltaHelper
    ) -> None:
        """Many files in one folder must cost one lookup, not one each."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [
                        FakeDriveItem(id=f"f{n}", name=f"{n}.docx",
                                      parent_id="folder-2026")
                        for n in range(5)
                    ],
                    delta_link=final,
                )
            },
            items_by_id={
                "folder-2026": FakeDriveItem(id="folder-2026", name="2026",
                                             folder=object(),
                                             parent_id="folder-x"),
            },
        )
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_id="folder-x"
        )

        assert len(result.items) == 5
        assert graph.item_lookups == ["folder-2026"]

    async def test_unresolvable_ancestry_keeps_the_item_and_flags_it(
        self, helper: DriveDeltaHelper
    ) -> None:
        """A parent we cannot read is undecidable, so the item is kept."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="a", name="a.docx",
                                   parent_id="unreadable")],
                    delta_link=final,
                )
            },
            items_by_id={"unreadable": PermissionError("access denied")},
        )
        result = await helper.enumerate(
            FakeO365Client(graph), DRIVE_ID, folder_id="folder-x"
        )

        assert [i.item_id for i in result.items] == ["a"]
        assert result.unresolved_parent == 1
        assert result.folder_filter_reliable is False

    def test_classify_folder_membership(self) -> None:
        pathed = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="Contracts")
        outside = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="ContractsArchive")
        by_id = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_id="folder-x")
        bare = DeltaItem(drive_id=DRIVE_ID, item_id="i")

        assert classify_folder_membership(bare) == FOLDER_MATCH
        assert classify_folder_membership(pathed, "Contracts") == FOLDER_MATCH
        assert classify_folder_membership(outside, "Contracts") == FOLDER_MISS
        assert classify_folder_membership(bare, "Contracts") == FOLDER_UNKNOWN
        assert classify_folder_membership(by_id, folder_id="folder-x") == FOLDER_MATCH
        assert classify_folder_membership(by_id, folder_id="other") == FOLDER_MISS
        assert classify_folder_membership(bare, folder_id="folder-x") == FOLDER_UNKNOWN
        # Either signal matching is enough.
        assert classify_folder_membership(pathed, "Contracts", "other") == FOLDER_MATCH

    async def test_item_moved_out_of_the_folder_does_not_keep_stale_state(self, helper: DriveDeltaHelper) -> None:
        """Graph: "use the last occurrence you see".

        An item that page 1 placed inside the folder and page 2 moved out
        must not be retained with its stale in-folder state.
        """
        page2 = f"{DELTA}?token=p2"
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="mover", name="m.docx", parent_path="/drive/root:/Contracts")],
                    next_link=page2,
                ),
                page2: FakeDeltaResponse(
                    [FakeDriveItem(id="mover", name="m.docx", parent_path="/drive/root:/Archive")],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")

        assert result.items == []
        assert result.filtered_out == 1

    async def test_filtered_out_counts_distinct_items_not_occurrences(self, helper: DriveDeltaHelper) -> None:
        """Every other counter is per distinct item; this one must match."""
        page2 = f"{DELTA}?token=p2"
        final = f"{DELTA}?token=final"
        outside = FakeDriveItem(id="out", name="o.docx", parent_path="/drive/root:/Archive")
        graph = FakeGraph(
            {
                None: FakeDeltaResponse([outside], next_link=page2),
                page2: FakeDeltaResponse([outside], delta_link=final),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")

        assert result.items == []
        assert result.filtered_out == 1

    async def test_item_moved_into_the_folder_is_picked_up(self, helper: DriveDeltaHelper) -> None:
        """The mirror case: a later in-folder occurrence wins over a miss."""
        page2 = f"{DELTA}?token=p2"
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="mover", name="m.docx", parent_path="/drive/root:/Archive")],
                    next_link=page2,
                ),
                page2: FakeDeltaResponse(
                    [FakeDriveItem(id="mover", name="m.docx", parent_path="/drive/root:/Contracts")],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, folder_path="Contracts")

        assert [i.item_id for i in result.items] == ["mover"]
        assert result.items[0].parent_path == "Contracts"

    def test_item_in_folder_semantics(self) -> None:
        inside = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="Contracts")
        deeper = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="Contracts/2026/Q1")
        sibling = DeltaItem(drive_id=DRIVE_ID, item_id="i", parent_path="ContractsArchive")
        unknown = DeltaItem(drive_id=DRIVE_ID, item_id="i")

        assert item_in_folder(inside, "Contracts") is True
        # SharePoint/OneDrive paths are case-insensitive.
        assert item_in_folder(inside, "contracts") is True
        assert item_in_folder(deeper, "CONTRACTS/2026") is True
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
        raw = FakeDriveItem(id="f1", name="Contracts", folder=object(), parent_path="/drive/root:")
        item = drive_item_to_delta_item(raw, DRIVE_ID)

        assert item is not None
        assert item.is_folder is True
        assert item.parent_path == ""
        assert item.path == "Contracts"

    def test_dict_and_camel_case_payloads_are_parsed(self) -> None:
        """Feeds also arrive as raw JSON dicts, not only as SDK objects."""
        raw = {
            "id": "item-1",
            "name": "contract.docx",
            "webUrl": "https://contoso.sharepoint.com/x",
            "eTag": "etag-1",
            "cTag": "ctag-1",
            "size": 99,
            "lastModifiedDateTime": "2026-09-09T10:00:00Z",
            "parentReference": {
                "id": "parent-1",
                "driveId": "b!other",
                "path": "/drive/root:/Contracts",
            },
            "file": {"hashes": {"sha256Hash": "ABC"}},
        }
        item = drive_item_to_delta_item(raw, DRIVE_ID)

        assert item is not None
        assert item.item_id == "item-1"
        assert item.drive_id == "b!other"
        assert item.parent_id == "parent-1"
        assert item.parent_path == "Contracts"
        assert item.web_url.endswith("/x")
        assert item.etag == "etag-1" and item.ctag == "ctag-1"
        assert item.content_hashes == {"sha256Hash": "ABC"}
        assert item.last_modified is not None

    def test_tombstone_reported_only_in_additional_data(self) -> None:
        """Some feeds carry the deleted facet under additional_data."""
        raw = {"id": "gone", "additionalData": {"deleted": {"state": "deleted"}}}
        item = drive_item_to_delta_item(raw, DRIVE_ID)

        assert item is not None and item.deleted is True

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
    def test_normalize_drive_path(self, raw_path: Optional[str], expected: Optional[str]) -> None:
        assert normalize_drive_path(raw_path) == expected


# ============================================================================
# AC2 — 410 rescan, bounded/throttle-aware retry, foreign-host rejection
# ============================================================================


class TestResetOn410:
    """410 Gone triggers a safe full rescan, never a mass deletion."""

    async def test_410_restarts_enumeration_and_flags_rescan(self, helper: DriveDeltaHelper) -> None:
        stored = f"{DELTA}?token=expired"
        final = f"{DELTA}?token=fresh"
        graph = FakeGraph(
            {
                stored: FakeGraphError(410),
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="a", name="a.docx", parent_path="/drive/root:")],
                    delta_link=final,
                ),
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID, delta_link=stored)

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
        stored = f"{DELTA}?token=expired"
        graph = FakeGraph(
            {
                stored: FakeGraphError(410),
                None: FakeDeltaResponse([], delta_link=f"{DELTA}?token=f"),
            }
        )
        await helper.enumerate(FakeO365Client(graph), DRIVE_ID, delta_link=stored)

        assert sleeps == []  # no backoff burned on a reset

    async def test_fetch_page_propagates_reset_to_caller(self, helper: DriveDeltaHelper) -> None:
        stored = f"{DELTA}?token=expired"
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
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [
                    FakeGraphError(429, retry_after="5"),
                    FakeDeltaResponse([FakeDriveItem(id="a")], delta_link=final),
                ],
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [5.0]  # Retry-After respected, not the default backoff
        assert result.complete is True

    async def test_retry_after_is_honoured_in_full_not_truncated(self, sleeps: List[float]) -> None:
        """max_backoff bounds our own backoff, never a server-set interval.

        Truncating Retry-After would retry while the throttle is still in
        force, which is exactly what Microsoft tells clients not to do.
        """

        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        helper = DriveDeltaHelper(
            max_retries=1,
            initial_backoff=1.0,
            max_backoff=3.0,
            max_retry_after=300.0,
            sleep=_sleep,
        )
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [
                    FakeGraphError(503, retry_after="120"),
                    FakeDeltaResponse([], delta_link=final),
                ],
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [120.0]
        assert result.complete is True

    async def test_retry_after_beyond_budget_abandons_the_round(self, sleeps: List[float]) -> None:
        """A throttle longer than max_retry_after is surfaced, not slept off."""

        async def _sleep(seconds: float) -> None:  # pragma: no cover
            sleeps.append(seconds)

        helper = DriveDeltaHelper(max_retries=3, max_retry_after=60.0, sleep=_sleep)
        graph = FakeGraph({None: [FakeGraphError(429, retry_after="600") for _ in range(5)]})

        with pytest.raises(DeltaRetryExhaustedError) as excinfo:
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == []
        assert len(graph.requested_urls) == 1
        # The caller can tell "still throttled, defer" from "gave up trying".
        assert "beyond the" in excinfo.value.reason
        assert excinfo.value.reason != "retries exhausted"

    async def test_self_computed_backoff_is_capped_by_max_backoff(self, sleeps: List[float]) -> None:
        """Without a Retry-After header our own backoff respects the cap."""

        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        helper = DriveDeltaHelper(max_retries=3, initial_backoff=4.0, max_backoff=5.0, sleep=_sleep)
        graph = FakeGraph({None: [FakeGraphError(500) for _ in range(6)]})

        with pytest.raises(DeltaRetryExhaustedError):
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [4.0, 5.0, 5.0]

    async def test_retries_are_bounded_and_then_raise(self, helper: DriveDeltaHelper, sleeps: List[float]) -> None:
        graph = FakeGraph(
            {
                None: [FakeGraphError(503) for _ in range(10)],
            }
        )
        with pytest.raises(DeltaRetryExhaustedError) as excinfo:
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        # max_retries=2 -> 3 attempts total, 2 backoffs, exponential.
        assert excinfo.value.attempts == 3
        assert excinfo.value.reason == "retries exhausted"
        assert len(graph.requested_urls) == 3
        assert sleeps == [1.0, 2.0]

    @pytest.mark.parametrize(
        "exc",
        [
            TimeoutError("read timed out"),
            ConnectionResetError("peer reset"),
            OSError("network unreachable"),
        ],
    )
    async def test_status_less_transient_failures_are_retried(
        self, helper: DriveDeltaHelper, sleeps: List[float], exc: Exception
    ) -> None:
        """A dropped connection carries no HTTP status but is still transient."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [exc, FakeDeltaResponse([], delta_link=final)],
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.complete is True
        assert len(graph.requested_urls) == 2
        assert sleeps == [1.0]

    async def test_httpx_transport_errors_are_retried(self, helper: DriveDeltaHelper) -> None:
        """The SDK's transport failures reach us without a status code."""
        import httpx

        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [httpx.ConnectError("connection refused"), FakeDeltaResponse([], delta_link=final)],
            }
        )
        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.complete is True
        assert len(graph.requested_urls) == 2

    async def test_transient_failures_stay_bounded(self, helper: DriveDeltaHelper) -> None:
        graph = FakeGraph({None: [TimeoutError("nope") for _ in range(10)]})

        with pytest.raises(DeltaRetryExhaustedError) as excinfo:
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert excinfo.value.attempts == 3
        assert len(graph.requested_urls) == 3

    async def test_retry_after_http_date_is_understood(self, sleeps: List[float]) -> None:
        """RFC 7231 allows an HTTP-date instead of delta-seconds."""
        from datetime import datetime, timedelta, timezone
        from email.utils import format_datetime

        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        when = datetime.now(timezone.utc) + timedelta(seconds=45)
        helper = DriveDeltaHelper(max_retries=1, sleep=_sleep)
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [
                    FakeGraphError(429, retry_after=format_datetime(when)),
                    FakeDeltaResponse([], delta_link=final),
                ],
            }
        )
        await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert len(sleeps) == 1
        # ~45s, allowing for the clock moving during the test.
        assert 40 <= sleeps[0] <= 46

    async def test_unparseable_retry_after_falls_back_to_backoff(
        self, helper: DriveDeltaHelper, sleeps: List[float]
    ) -> None:
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: [
                    FakeGraphError(429, retry_after="soon-ish"),
                    FakeDeltaResponse([], delta_link=final),
                ],
            }
        )
        await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert sleeps == [1.0]

    @pytest.mark.parametrize("attribute", ["response_status_code", "status_code", "status", "code"])
    async def test_status_is_read_from_any_of_the_sdk_attribute_names(
        self, helper: DriveDeltaHelper, attribute: str
    ) -> None:
        """Different SDK error types expose the status under different names."""

        class OddError(Exception):
            pass

        exc = OddError("throttled")
        setattr(exc, attribute, 429)
        final = f"{DELTA}?token=final"
        graph = FakeGraph({None: [exc, FakeDeltaResponse([], delta_link=final)]})

        result = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert result.complete is True
        assert len(graph.requested_urls) == 2

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
            {"max_retry_after": -1.0},
            {"max_pages": 0},
        ],
    )
    def test_invalid_bounds_rejected(self, kwargs: Dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            DriveDeltaHelper(**kwargs)


class TestContinuationHostValidation:
    """Credentials are never forwarded to a foreign continuation host."""

    async def test_malicious_next_link_rejected_before_request(self, helper: DriveDeltaHelper) -> None:
        evil = "https://evil.example.com/v1.0/drives/x/items/root/delta?token=steal"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse([FakeDriveItem(id="a")], next_link=evil),
            }
        )
        client = FakeO365Client(graph)

        with pytest.raises(DeltaLinkValidationError) as excinfo:
            await helper.enumerate(client, DRIVE_ID)

        assert "evil.example.com" in str(excinfo.value)
        # The poisoned URL was never dereferenced: only the initial request ran.
        assert graph.requested_urls == [None]

    async def test_malicious_final_delta_link_rejected(self, helper: DriveDeltaHelper) -> None:
        evil = "https://evil.example.com/delta?token=steal"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=evil)})

        with pytest.raises(DeltaLinkValidationError):
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert graph.requested_urls == [None]

    async def test_untrusted_stored_cursor_rejected_before_request(self, helper: DriveDeltaHelper) -> None:
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
            "http://graph.microsoft.com/delta",  # not https
            "ftp://graph.microsoft.com/delta",
            "https://graph.microsoft.com.evil.tld/delta",  # suffix spoof
            "https://evil.com/https://graph.microsoft.com/delta",
            "https://graph.microsoft.com:8443/delta",  # non-standard port
            "/relative/delta",
        ],
    )
    def test_rejected_links(self, link: str) -> None:
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link, DRIVE_ID)

    async def test_cursor_pointing_at_another_drive_is_rejected(self, helper: DriveDeltaHelper) -> None:
        """with_url() replaces the whole URL, so the path must be confined.

        Origin validation alone would happily send the access token to a
        different resource on the same trusted host.
        """
        graph = FakeGraph({})
        other = f"{GRAPH}/drives/b!someone-elses-drive/items/root/delta?token=x"

        with pytest.raises(DeltaLinkValidationError) as excinfo:
            await helper.fetch_page(FakeO365Client(graph), DRIVE_ID, link=other)

        assert "does not address drive" in str(excinfo.value)
        assert graph.requested_urls == []

    async def test_cursor_pointing_at_a_non_delta_endpoint_is_rejected(self, helper: DriveDeltaHelper) -> None:
        """A trusted-origin, right-drive URL still must be a delta endpoint."""
        graph = FakeGraph({})
        content = f"{GRAPH}/drives/{DRIVE_ID}/items/secret-item/content"

        with pytest.raises(DeltaLinkValidationError) as excinfo:
            await helper.fetch_page(FakeO365Client(graph), DRIVE_ID, link=content)

        assert "not a delta endpoint" in str(excinfo.value)
        assert graph.requested_urls == []

    async def test_poisoned_final_cursor_for_another_drive_is_rejected(self, helper: DriveDeltaHelper) -> None:
        """The cursor handed back to the caller is confined too."""
        evil = f"{GRAPH}/drives/b!other/items/root/delta?token=x"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=evil)})

        with pytest.raises(DeltaLinkValidationError):
            await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert graph.requested_urls == [None]

    @pytest.mark.parametrize(
        "link",
        [
            # Traversal out of the delta endpoint.
            f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta/../../../users",
            f"{GRAPH}/drives/{DRIVE_ID}/items/root/delta/%2e%2e/users",
            # "delta" present, but the endpoint is /content.
            f"{GRAPH}/delta/drives/{DRIVE_ID}/items/x/content",
            f"{GRAPH}/drives/{DRIVE_ID}/items/x/content",
            # Drive id present, but not as the drives/ segment's target.
            f"{GRAPH}/{DRIVE_ID}/delta",
            f"{GRAPH}/drives/other/drives/{DRIVE_ID}/delta",
            # Sibling drive, and a prefix-extended drive id.
            f"{GRAPH}/drives/b!other/items/root/delta",
            f"{GRAPH}/drives/{DRIVE_ID}XX/items/root/delta",
            # Trusted host smuggled into userinfo.
            f"https://graph.microsoft.com@evil.example.com/v1.0/drives/" f"{DRIVE_ID}/items/root/delta",
            # A different-drive path smuggled through the query string.
            f"{GRAPH}/drives/b!other/items/x/content" f"?p=/drives/{DRIVE_ID}/items/root/delta",
        ],
    )
    def test_confinement_cannot_be_bypassed(self, link: str) -> None:
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link, DRIVE_ID)

    @pytest.mark.parametrize(
        "shape",
        [
            "{graph}/drives/{drive}/root/delta?token=abc",
            "{graph}/drives/{drive}/items/root/delta?token=abc",
            "{graph}/drives/{drive}/items/01ABC/delta()?token=abc",
        ],
    )
    def test_real_graph_continuation_shapes_are_accepted(self, shape: str) -> None:
        link = shape.format(graph=GRAPH, drive=DRIVE_ID)
        assert validate_continuation_link(link, DRIVE_ID) == link

    def test_percent_encoded_drive_id_is_accepted(self) -> None:
        from urllib.parse import quote

        encoded = quote(DRIVE_ID, safe="")
        link = f"{GRAPH}/drives/{encoded}/items/root/delta?token=abc"
        assert validate_continuation_link(link, DRIVE_ID) == link

    @pytest.mark.parametrize("origin", DEFAULT_GRAPH_ORIGINS)
    def test_all_sovereign_graph_origins_accepted(self, origin: str) -> None:
        link = f"{origin}/v1.0/drives/{DRIVE_ID}/items/root/delta?token=abc"
        assert validate_continuation_link(link, DRIVE_ID) == link

    def test_explicit_port_443_accepted(self) -> None:
        link = f"https://graph.microsoft.com:443/v1.0/drives/{DRIVE_ID}" "/items/root/delta?token=a"
        assert validate_continuation_link(link, DRIVE_ID) == link

    def test_custom_allowed_origin(self) -> None:
        link = f"https://graph.internal.test/v1.0/drives/{DRIVE_ID}/root/delta"
        assert validate_continuation_link(link, DRIVE_ID, allowed_origins=("https://graph.internal.test",)) == link
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link, DRIVE_ID)

    def test_drive_confinement_cannot_be_skipped(self) -> None:
        """Origin-only checking is the weakness this closes: no opt-out."""
        link = f"{GRAPH}/drives/{DRIVE_ID}/items/x/content"

        with pytest.raises(TypeError):
            validate_continuation_link(link)  # type: ignore[call-arg]
        with pytest.raises(DeltaLinkValidationError):
            validate_continuation_link(link, "")


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
            assert forbidden not in source, f"delta helper must not reference {forbidden}"

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
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr
        line = next(ln for ln in completed.stdout.splitlines() if ln.startswith("OFFENDERS:"))
        offenders = line.removeprefix("OFFENDERS:").strip()
        assert not offenders, f"delta import pulled in contracts modules: {offenders}"

    def test_helper_exposes_no_cursor_commit_or_ingest_surface(self) -> None:
        public = {name for name, _ in inspect.getmembers(DriveDeltaHelper) if not name.startswith("_")}
        assert public == {"enumerate", "fetch_page", "validate_link"}
        for banned in ("commit", "save", "store", "persist", "ingest", "download", "upload", "set_delta_token"):
            assert not any(banned in name for name in public), f"delta helper must not expose a {banned!r} surface"

    async def test_enumeration_never_downloads_content(self, helper: DriveDeltaHelper) -> None:
        final = f"{DELTA}?token=final"
        graph = FakeGraph(
            {
                None: FakeDeltaResponse(
                    [FakeDriveItem(id="a", name="a.docx", quick_xor_hash="H")],
                    delta_link=final,
                ),
            }
        )
        client = FakeO365Client(graph)
        await helper.enumerate(client, DRIVE_ID)

        assert client.download_calls == []

    async def test_enumeration_returns_cursor_without_committing_it(self, helper: DriveDeltaHelper) -> None:
        """The final cursor is returned to the caller, never stored here."""
        final = f"{DELTA}?token=final"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=final)})

        first = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)
        # A second call with no cursor still starts from scratch: the helper
        # kept no state between rounds.
        second = await helper.enumerate(FakeO365Client(graph), DRIVE_ID)

        assert first.delta_link == final
        assert second.full_enumeration is True
