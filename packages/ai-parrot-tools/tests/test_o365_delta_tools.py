"""Unit tests for the O365 delta tools (FEAT-539 / TASK-3042).

Covers ``DeltaSharePointFilesTool`` and ``DeltaOneDriveFilesTool``:

- both preserve the ``O365Tool`` authentication and error-wrapping lifecycle;
- both produce equivalent typed continuation / deletion outcomes;
- both resolve drive identity from configured identifiers and refuse
  model-supplied endpoint expansion;
- the SharePoint/OneDrive bundles keep every pre-existing tool and gain the
  delta tool, without importing anything from contracts or the scheduler.

Everything runs against a fake Graph surface — no network, no credentials.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock

import pytest

from parrot_tools.o365 import (
    DeltaOneDriveFilesTool,
    DeltaSharePointFilesTool,
    DriveDeltaHelper,
)
from parrot_tools.o365.bundle import (
    OneDriveToolkit,
    Office365FileManagementToolkit,
    SharePointToolkit,
)
from parrot_tools.o365.onedrive import (
    DownloadOneDriveFileTool,
    ListOneDriveFilesTool,
    SearchOneDriveFilesTool,
    UploadOneDriveFileTool,
)
from parrot_tools.o365.sharepoint import (
    DownloadSharePointFileTool,
    ListSharePointFilesTool,
    SearchSharePointFilesTool,
    UploadSharePointFileTool,
)

GRAPH = "https://graph.microsoft.com/v1.0"
DRIVE_ID = "b!library-drive-id"
SITE_ID = "contoso.sharepoint.com:/sites/Legal"
CREDENTIALS = {
    "client_id": "fake-client-id",
    "client_secret": "fake-secret",
    "tenant_id": "fake-tenant-id",
}


# ============================================================================
# FAKE GRAPH SURFACE
# ============================================================================

class FakeDeleted:
    """Stand-in for the msgraph ``deleted`` facet."""

    state = "deleted"


class FakeParentReference:
    def __init__(self, path: Optional[str] = None, drive_id: Optional[str] = None):
        self.path = path
        self.id = "parent-id"
        self.drive_id = drive_id


class FakeDriveItem:
    def __init__(
        self,
        *,
        id: str,
        name: Optional[str] = None,
        deleted: Any = None,
        parent_path: Optional[str] = "/drive/root:",
    ) -> None:
        self.id = id
        self.name = name
        self.deleted = deleted
        self.folder = None
        self.file = None
        self.parent_reference = FakeParentReference(parent_path)
        self.size = 10
        self.e_tag = f"etag-{id}"
        self.c_tag = f"ctag-{id}"
        self.web_url = f"https://contoso.sharepoint.com/{id}"
        self.last_modified_date_time = "2026-09-09T10:00:00Z"


class FakeDeltaResponse:
    def __init__(
        self,
        value: Sequence[Any],
        next_link: Optional[str] = None,
        delta_link: Optional[str] = None,
    ) -> None:
        self.value = list(value)
        self.odata_next_link = next_link
        self.odata_delta_link = delta_link


class FakeDrive:
    def __init__(self, id: str, name: str) -> None:
        self.id = id
        self.name = name


class FakeDrivesPage:
    def __init__(self, drives: Sequence[FakeDrive]) -> None:
        self.value = list(drives)


class FakeDeltaRequestBuilder:
    def __init__(self, graph: "FakeGraph", url: Optional[str] = None) -> None:
        self._graph = graph
        self._url = url

    def with_url(self, raw_url: str) -> "FakeDeltaRequestBuilder":
        return FakeDeltaRequestBuilder(self._graph, raw_url)

    async def get(self) -> Any:
        return await self._graph._delta(self._url)


class _FakeDriveItemBuilder:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def delta(self) -> FakeDeltaRequestBuilder:
        return FakeDeltaRequestBuilder(self._graph)


class _FakeItemsCollection:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    def by_drive_item_id(self, item_id: str) -> _FakeDriveItemBuilder:
        self._graph.requested_root_ids.append(item_id)
        return _FakeDriveItemBuilder(self._graph)


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


class _FakeSiteBuilder:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def drives(self) -> "_FakeSiteDrives":
        return _FakeSiteDrives(self._graph)


class _FakeSiteDrives:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    async def get(self) -> FakeDrivesPage:
        return FakeDrivesPage(self._graph.site_drives)


class _FakeSitesCollection:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    def by_site_id(self, site_id: str) -> _FakeSiteBuilder:
        self._graph.requested_site_ids.append(site_id)
        return _FakeSiteBuilder(self._graph)


class _FakeDriveEndpoint:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    async def get(self) -> Any:
        return self._graph.owner_drive


class _FakeMe:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def drive(self) -> _FakeDriveEndpoint:
        self._graph.me_drive_lookups += 1
        return _FakeDriveEndpoint(self._graph)


class _FakeUsersCollection:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    def by_user_id(self, user_id: str) -> "_FakeUser":
        self._graph.requested_user_ids.append(user_id)
        return _FakeUser(self._graph)


class _FakeUser:
    def __init__(self, graph: "FakeGraph") -> None:
        self._graph = graph

    @property
    def drive(self) -> _FakeDriveEndpoint:
        return _FakeDriveEndpoint(self._graph)


class FakeGraph:
    """Minimal fake ``GraphServiceClient`` for both delta tools."""

    def __init__(
        self,
        delta_responses: Dict[Optional[str], Any],
        site_drives: Optional[Sequence[FakeDrive]] = None,
        owner_drive: Optional[FakeDrive] = None,
    ) -> None:
        self.delta_responses = {
            k: list(v) if isinstance(v, list) else [v]
            for k, v in delta_responses.items()
        }
        self.site_drives = list(site_drives or [])
        self.owner_drive = owner_drive
        self.requested_urls: List[Optional[str]] = []
        self.requested_drive_ids: List[str] = []
        self.requested_root_ids: List[str] = []
        self.requested_site_ids: List[str] = []
        self.requested_user_ids: List[str] = []
        self.me_drive_lookups = 0

    @property
    def drives(self) -> _FakeDrivesCollection:
        return _FakeDrivesCollection(self)

    @property
    def sites(self) -> _FakeSitesCollection:
        return _FakeSitesCollection(self)

    @property
    def users(self) -> _FakeUsersCollection:
        return _FakeUsersCollection(self)

    @property
    def me(self) -> _FakeMe:
        return _FakeMe(self)

    async def _delta(self, url: Optional[str]) -> Any:
        self.requested_urls.append(url)
        if url not in self.delta_responses:
            raise AssertionError(f"Unscripted delta request for URL: {url!r}")
        queue = self.delta_responses[url]
        entry = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(entry, BaseException):
            raise entry
        return entry


class FakeO365Client:
    """Fake authenticated O365 client exposing only ``graph_client``."""

    def __init__(self, graph: FakeGraph) -> None:
        self._graph = graph

    @property
    def graph_client(self) -> FakeGraph:
        return self._graph


def bind_client(tool: Any, graph: FakeGraph) -> AsyncMock:
    """Replace the tool's authentication step with a fake client.

    Everything else in :meth:`O365Tool._execute` — auth-mode selection, the
    ToolResult wrapper, error capture and metadata — is left untouched.
    """
    mock = AsyncMock(return_value=FakeO365Client(graph))
    tool._get_client = mock  # type: ignore[method-assign]
    return mock


def two_page_feed(prefix: str) -> Dict[Optional[str], Any]:
    """A two-page delta feed with a rename, a tombstone and a duplicate."""
    page2 = f"{GRAPH}/{prefix}/delta?token=p2"
    final = f"{GRAPH}/{prefix}/delta?token=final"
    return {
        None: FakeDeltaResponse(
            [
                FakeDriveItem(id="doc-1", name="old.docx",
                              parent_path="/drive/root:/Contracts"),
                FakeDriveItem(id="doc-2", name="gone.docx",
                              deleted=FakeDeleted(),
                              parent_path="/drive/root:/Contracts"),
            ],
            next_link=page2,
        ),
        page2: FakeDeltaResponse(
            [
                FakeDriveItem(id="doc-1", name="renamed.docx",
                              parent_path="/drive/root:/Contracts"),
                FakeDriveItem(id="doc-3", name="new.docx",
                              parent_path="/drive/root:/Other"),
            ],
            delta_link=final,
        ),
    }


FINAL_SP = f"{GRAPH}/sp/delta?token=final"
FINAL_OD = f"{GRAPH}/od/delta?token=final"


@pytest.fixture
def sharepoint_tool() -> DeltaSharePointFilesTool:
    return DeltaSharePointFilesTool(credentials=dict(CREDENTIALS))


@pytest.fixture
def onedrive_tool() -> DeltaOneDriveFilesTool:
    return DeltaOneDriveFilesTool(credentials=dict(CREDENTIALS))


# ============================================================================
# AC1 — auth/error wrapping preserved, equivalent typed outcomes
# ============================================================================

class TestAuthenticationLifecycle:
    """Both tools go through the standard O365 auth + ToolResult lifecycle."""

    async def test_sharepoint_uses_o365_auth_and_wraps_success(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph(
            {None: FakeDeltaResponse([FakeDriveItem(id="a", name="a.docx")],
                                     delta_link=FINAL_SP)},
        )
        get_client = bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(drive_id=DRIVE_ID)

        assert result.status == "success"
        assert result.error is None
        assert result.metadata["tool"] == "delta_sharepoint_files"
        assert result.metadata["auth_mode"] == "direct"
        get_client.assert_awaited_once()
        assert get_client.await_args.kwargs["auth_mode"] == "direct"

    async def test_onedrive_uses_o365_auth_and_wraps_success(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph(
            {None: FakeDeltaResponse([FakeDriveItem(id="a", name="a.docx")],
                                     delta_link=FINAL_OD)},
        )
        get_client = bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute(drive_id=DRIVE_ID)

        assert result.status == "success"
        assert result.metadata["tool"] == "delta_onedrive_files"
        get_client.assert_awaited_once()

    async def test_explicit_auth_mode_is_honoured(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=FINAL_OD)})
        get_client = bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute(
            drive_id=DRIVE_ID, auth_mode="on_behalf_of", user_assertion="tok"
        )

        assert result.status == "success"
        assert result.metadata["auth_mode"] == "on_behalf_of"
        assert get_client.await_args.kwargs["user_assertion"] == "tok"

    @pytest.mark.parametrize("tool_name", ["sharepoint", "onedrive"])
    async def test_authentication_failure_is_wrapped_not_raised(
        self,
        tool_name: str,
        sharepoint_tool: DeltaSharePointFilesTool,
        onedrive_tool: DeltaOneDriveFilesTool,
    ) -> None:
        tool = sharepoint_tool if tool_name == "sharepoint" else onedrive_tool
        tool._get_client = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("token acquisition failed")
        )

        result = await tool._execute(drive_id=DRIVE_ID)

        assert result.status == "error"
        assert result.result is None
        assert "token acquisition failed" in result.error

    @pytest.mark.parametrize("tool_name", ["sharepoint", "onedrive"])
    async def test_graph_failure_is_wrapped_as_tool_error(
        self,
        tool_name: str,
        sharepoint_tool: DeltaSharePointFilesTool,
        onedrive_tool: DeltaOneDriveFilesTool,
    ) -> None:
        tool = sharepoint_tool if tool_name == "sharepoint" else onedrive_tool
        graph = FakeGraph({None: PermissionError("Access denied")})
        bind_client(tool, graph)

        result = await tool._execute(drive_id=DRIVE_ID)

        assert result.status == "error"
        assert "Access denied" in result.error
        assert "execution_time" in result.metadata


class TestEquivalentDeltaOutcomes:
    """The two tools produce the same typed continuation/deletion shape."""

    async def test_sharepoint_and_onedrive_payloads_are_equivalent(
        self,
        sharepoint_tool: DeltaSharePointFilesTool,
        onedrive_tool: DeltaOneDriveFilesTool,
    ) -> None:
        sp_graph = FakeGraph(two_page_feed("sp"))
        od_graph = FakeGraph(two_page_feed("od"))
        bind_client(sharepoint_tool, sp_graph)
        bind_client(onedrive_tool, od_graph)

        sp = (await sharepoint_tool._execute(drive_id=DRIVE_ID)).result
        od = (await onedrive_tool._execute(drive_id=DRIVE_ID)).result

        shared = {
            "drive_id", "items", "delta_link", "pages_fetched", "complete",
            "reset_performed", "full_enumeration", "folder_path",
            "filtered_out", "total_items", "changed_count", "deleted_count",
            "source",
        }
        assert shared <= set(sp)
        assert shared <= set(od)

        # Same feed shape in, same outcome out (bar the source-specific keys).
        comparable = shared - {"source", "delta_link"}
        assert {k: sp[k] for k in comparable} == {k: od[k] for k in comparable}
        assert sp["source"] == "sharepoint"
        assert od["source"] == "onedrive"

    async def test_typed_continuation_and_tombstones(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph(two_page_feed("sp"))
        bind_client(sharepoint_tool, graph)

        payload = (await sharepoint_tool._execute(drive_id=DRIVE_ID)).result

        assert payload["pages_fetched"] == 2
        assert payload["complete"] is True
        assert payload["delta_link"] == f"{GRAPH}/sp/delta?token=final"
        assert payload["full_enumeration"] is True
        assert payload["reset_performed"] is False

        by_id = {item["item_id"]: item for item in payload["items"]}
        assert set(by_id) == {"doc-1", "doc-2", "doc-3"}
        # Duplicate collapsed, latest state (the rename) won.
        assert by_id["doc-1"]["name"] == "renamed.docx"
        # Tombstone surfaced, not dropped.
        assert by_id["doc-2"]["deleted"] is True
        assert payload["deleted_count"] == 1
        assert payload["changed_count"] == 2
        assert payload["total_items"] == 3

    async def test_incremental_round_uses_stored_cursor(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        stored = f"{GRAPH}/od/delta?token=stored"
        graph = FakeGraph({stored: FakeDeltaResponse([], delta_link=FINAL_OD)})
        bind_client(onedrive_tool, graph)

        payload = (await onedrive_tool._execute(
            drive_id=DRIVE_ID, delta_link=stored
        )).result

        assert graph.requested_urls == [stored]
        assert payload["full_enumeration"] is False
        assert payload["delta_link"] == FINAL_OD

    async def test_expired_cursor_produces_flagged_rescan(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        class Gone(Exception):
            response_status_code = 410
            response_headers: Dict[str, str] = {}

        stored = f"{GRAPH}/sp/delta?token=expired"
        graph = FakeGraph({
            stored: Gone("cursor expired"),
            None: FakeDeltaResponse([FakeDriveItem(id="a", name="a.docx")],
                                    delta_link=FINAL_SP),
        })
        bind_client(sharepoint_tool, graph)

        payload = (await sharepoint_tool._execute(
            drive_id=DRIVE_ID, delta_link=stored
        )).result

        assert payload["reset_performed"] is True
        assert payload["full_enumeration"] is True
        assert payload["deleted_count"] == 0

    async def test_folder_filter_is_applied_locally(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph(two_page_feed("od"))
        bind_client(onedrive_tool, graph)

        payload = (await onedrive_tool._execute(
            drive_id=DRIVE_ID, folder_path="Contracts"
        )).result

        assert payload["folder_path"] == "Contracts"
        assert {i["item_id"] for i in payload["items"]} == {"doc-1", "doc-2"}
        assert payload["filtered_out"] == 1

    async def test_max_pages_bound_yields_no_committable_cursor(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        loop = f"{GRAPH}/od/delta?token=loop"
        graph = FakeGraph({
            None: FakeDeltaResponse([FakeDriveItem(id="a")], next_link=loop),
            loop: FakeDeltaResponse([FakeDriveItem(id="a")], next_link=loop),
        })
        bind_client(onedrive_tool, graph)

        payload = (await onedrive_tool._execute(
            drive_id=DRIVE_ID, max_pages=2
        )).result

        assert payload["pages_fetched"] == 2
        assert payload["complete"] is False
        assert payload["delta_link"] is None


class TestDriveIdentityResolution:
    """Drive identity comes from configuration, never from an expanded URL."""

    async def test_sharepoint_resolves_library_to_drive_id(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph(
            {None: FakeDeltaResponse([], delta_link=FINAL_SP)},
            site_drives=[FakeDrive("b!other", "Archive"),
                         FakeDrive(DRIVE_ID, "Documents")],
        )
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(
            site_id=SITE_ID, library="documents"
        )

        assert result.status == "success"
        assert graph.requested_site_ids == [SITE_ID]
        assert graph.requested_drive_ids == [DRIVE_ID]
        assert graph.requested_root_ids == ["root"]

    async def test_sharepoint_unknown_library_is_an_error(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph({}, site_drives=[FakeDrive(DRIVE_ID, "Documents")])
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(site_id=SITE_ID, library="Nope")

        assert result.status == "error"
        assert "not found" in result.error
        assert graph.requested_urls == []

    async def test_sharepoint_site_without_drives_is_an_error(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph({}, site_drives=[])
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(site_id=SITE_ID)

        assert result.status == "error"
        assert "no drives" in result.error

    async def test_sharepoint_requires_site_or_drive(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph({})
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute()

        assert result.status == "error"
        assert "site_id or drive_id" in result.error

    async def test_onedrive_resolves_signed_in_user_drive(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph(
            {None: FakeDeltaResponse([], delta_link=FINAL_OD)},
            owner_drive=FakeDrive(DRIVE_ID, "OneDrive"),
        )
        bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute()

        assert result.status == "success"
        assert graph.me_drive_lookups == 1
        assert graph.requested_drive_ids == [DRIVE_ID]

    async def test_onedrive_resolves_target_user_drive(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph(
            {None: FakeDeltaResponse([], delta_link=FINAL_OD)},
            owner_drive=FakeDrive(DRIVE_ID, "OneDrive"),
        )
        bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute(user_id="jane@contoso.com")

        assert result.status == "success"
        assert graph.requested_user_ids == ["jane@contoso.com"]
        assert graph.me_drive_lookups == 0

    async def test_onedrive_unresolvable_drive_is_an_error(
        self, onedrive_tool: DeltaOneDriveFilesTool
    ) -> None:
        graph = FakeGraph({}, owner_drive=FakeDrive(None, "OneDrive"))
        bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute()

        assert result.status == "error"
        assert "Could not resolve" in result.error

    @pytest.mark.parametrize(
        "bad_id",
        [
            "https://evil.example.com/v1.0/drives/x",
            "//evil.example.com/drives/x",
            "drive id with spaces",
            "drive\nid",
            "",
            "   ",
        ],
    )
    async def test_model_supplied_endpoint_expansion_is_rejected(
        self, onedrive_tool: DeltaOneDriveFilesTool, bad_id: str
    ) -> None:
        graph = FakeGraph({}, owner_drive=FakeDrive(DRIVE_ID, "OneDrive"))
        bind_client(onedrive_tool, graph)

        result = await onedrive_tool._execute(drive_id=bad_id)

        if bad_id == "":
            # An absent drive_id falls through to normal drive resolution.
            assert graph.requested_drive_ids == [DRIVE_ID]
        else:
            # Anything present but not a plain Graph id is refused, and no
            # delta request is issued.
            assert result.status == "error"
            assert graph.requested_urls == []

    async def test_sharepoint_site_id_url_is_rejected(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph({}, site_drives=[FakeDrive(DRIVE_ID, "Documents")])
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(
            site_id="https://evil.example.com/sites/Legal"
        )

        assert result.status == "error"
        assert "not a URL" in result.error
        assert graph.requested_site_ids == []

    async def test_untrusted_delta_cursor_is_rejected_before_request(
        self, sharepoint_tool: DeltaSharePointFilesTool
    ) -> None:
        graph = FakeGraph({})
        bind_client(sharepoint_tool, graph)

        result = await sharepoint_tool._execute(
            drive_id=DRIVE_ID,
            delta_link="https://evil.example.com/delta?token=steal",
        )

        assert result.status == "error"
        assert "evil.example.com" in result.error
        assert graph.requested_urls == []


class TestHelperInjection:
    """The shared delta helper is used and can be configured per tool."""

    def test_default_helper_is_the_shared_drive_delta_helper(
        self,
        sharepoint_tool: DeltaSharePointFilesTool,
        onedrive_tool: DeltaOneDriveFilesTool,
    ) -> None:
        assert isinstance(sharepoint_tool._delta_helper, DriveDeltaHelper)
        assert isinstance(onedrive_tool._delta_helper, DriveDeltaHelper)

    async def test_injected_helper_is_used(self) -> None:
        custom = DriveDeltaHelper(
            allowed_origins=("https://graph.internal.test",), max_retries=0
        )
        tool = DeltaOneDriveFilesTool(
            credentials=dict(CREDENTIALS), delta_helper=custom
        )
        assert tool._delta_helper is custom

        internal_final = "https://graph.internal.test/delta?token=final"
        graph = FakeGraph({None: FakeDeltaResponse([], delta_link=internal_final)})
        bind_client(tool, graph)

        result = await tool._execute(drive_id=DRIVE_ID)

        assert result.status == "success"
        assert result.result["delta_link"] == internal_final


# ============================================================================
# AC2 — bundle regression: prior tools kept, delta tools added, no contracts
# ============================================================================

class TestBundleRegistration:
    """Bundles gain the delta tools without losing anything."""

    def test_sharepoint_toolkit_keeps_prior_tools_and_adds_delta(self) -> None:
        toolkit = SharePointToolkit(**CREDENTIALS)
        types = {type(t) for t in toolkit.get_tools()}

        assert {
            ListSharePointFilesTool,
            SearchSharePointFilesTool,
            DownloadSharePointFileTool,
            UploadSharePointFileTool,
            DeltaSharePointFilesTool,
        } == types
        assert toolkit.get_tool_by_name("delta_sharepoint_files") is not None
        assert toolkit.get_tool_by_name("list_sharepoint_files") is not None

    def test_onedrive_toolkit_keeps_prior_tools_and_adds_delta(self) -> None:
        toolkit = OneDriveToolkit(**CREDENTIALS)
        types = {type(t) for t in toolkit.get_tools()}

        assert {
            ListOneDriveFilesTool,
            SearchOneDriveFilesTool,
            DownloadOneDriveFileTool,
            UploadOneDriveFileTool,
            DeltaOneDriveFilesTool,
        } == types
        assert toolkit.get_tool_by_name("delta_onedrive_files") is not None
        assert toolkit.get_tool_by_name("upload_onedrive_file") is not None

    def test_file_management_toolkit_bundles_both_delta_tools(self) -> None:
        toolkit = Office365FileManagementToolkit(**CREDENTIALS)
        names = {t.name for t in toolkit.get_tools()}

        assert {"delta_sharepoint_files", "delta_onedrive_files"} <= names
        assert len(toolkit.get_tools()) == 10

    def test_sub_selection_helpers_include_the_delta_tools(self) -> None:
        toolkit = Office365FileManagementToolkit(**CREDENTIALS)

        sp_names = {t.name for t in toolkit.get_sharepoint_tools()}
        od_names = {t.name for t in toolkit.get_onedrive_tools()}

        assert "delta_sharepoint_files" in sp_names
        assert "delta_onedrive_files" in od_names
        assert len(sp_names) == 5
        assert len(od_names) == 5

    def test_delta_tools_are_exported_from_the_o365_package(self) -> None:
        import parrot_tools.o365 as pkg

        for symbol in (
            "DeltaSharePointFilesTool", "DeltaOneDriveFilesTool",
            "DriveDeltaHelper", "DeltaItem", "DeltaPage", "DeltaEnumeration",
        ):
            assert symbol in pkg.__all__
            assert hasattr(pkg, symbol)

        # Pre-existing exports survive.
        for symbol in (
            "ListOneDriveFilesTool", "SearchOneDriveFilesTool",
            "DownloadOneDriveFileTool", "UploadOneDriveFileTool",
            "SendEmailTool", "ListEventsTool",
        ):
            assert symbol in pkg.__all__

    def test_tool_args_schemas_hide_no_auth_surface_but_expose_delta_inputs(
        self,
    ) -> None:
        sp_fields = set(DeltaSharePointFilesTool.args_schema.model_fields)
        od_fields = set(DeltaOneDriveFilesTool.args_schema.model_fields)

        assert {"site_id", "library", "drive_id", "folder_path",
                "delta_link", "max_pages"} <= sp_fields
        assert {"drive_id", "folder_path", "delta_link",
                "max_pages"} <= od_fields
        # Inherited O365 auth arguments are still available.
        assert {"auth_mode", "user_assertion", "user_id"} <= sp_fields
        assert {"auth_mode", "user_assertion", "user_id"} <= od_fields


class TestNoContractsOrSchedulerCoupling:
    """The O365 lane stays independent of contracts and the scheduler."""

    @pytest.mark.parametrize(
        "module_name",
        ["delta.py", "sharepoint.py", "onedrive.py", "bundle.py", "__init__.py"],
    )
    def test_o365_modules_reference_no_contracts_or_scheduler(
        self, module_name: str
    ) -> None:
        import parrot_tools.o365 as pkg

        source = (Path(pkg.__file__).parent / module_name).read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "parrot.knowledge.contracts",
            "parrot_tools.contracts",
            "parrot.scheduler",
        ):
            assert forbidden not in source, (
                f"{module_name} must not reference {forbidden}"
            )

    def test_importing_the_bundle_pulls_in_no_contracts_module(self) -> None:
        """Verified in a clean subprocess so session state cannot mask it."""
        import subprocess
        import sys

        probe = (
            "import sys;"
            "import parrot_tools.o365.bundle;"
            "bad=[n for n in sys.modules if n.startswith("
            "('parrot.knowledge.contracts','parrot_tools.contracts',"
            "'parrot.scheduler'))];"
            "print('OFFENDERS:'+','.join(sorted(bad)))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        line = next(
            ln for ln in completed.stdout.splitlines()
            if ln.startswith("OFFENDERS:")
        )
        offenders = line.removeprefix("OFFENDERS:").strip()
        assert not offenders, f"bundle import pulled in: {offenders}"
