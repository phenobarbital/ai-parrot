"""FEAT-603 TASK-3748 — the Graph test harness behaves as manager tests assume."""

from abc import ABC, abstractmethod
from types import SimpleNamespace

import pytest

from ._graph_fakes import (
    FAKE_DOWNLOAD,
    FakeAiohttpSession,
    FakeAPIError,
    FakeDrive,
    FakeGraphClient,
    make_onedrive_client,
    make_probe,
    make_sharepoint_client,
)
from parrot.interfaces.onedrive import OneDriveClient
from parrot.interfaces.sharepoint import SharepointClient


@pytest.fixture
def fake() -> FakeGraphClient:
    """Build a Graph fake with one populated drive."""
    drive = FakeDrive("drive-1")
    drive.put_file("reports/2026/q3.xlsx", b"x" * 10, mime="application/vnd.ms-excel")
    return FakeGraphClient({"drive-1": drive}, me_drive_id="drive-1", user_drives={"u@t.com": "drive-1"})


async def test_path_ref_resolves_and_missing_raises_404(fake: FakeGraphClient) -> None:
    """Colon-separated Graph path references resolve and missing ones return 404."""
    item = await fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root:/reports/2026/q3.xlsx:").get()
    assert item.name == "q3.xlsx"
    with pytest.raises(FakeAPIError) as error:
        await fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root:/missing:").get()
    assert error.value.response_status_code == 404


async def test_children_paginate_with_next_link(fake: FakeGraphClient) -> None:
    """Children pages resume from the Graph next-link URL exactly once."""
    drive = fake.drives_by_id["drive-1"]
    for index in range(5):
        drive.put_file(f"pages/{index}.txt", b"x")
    fake.page_size = 2
    children = fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root:/pages:").children
    first = await children.get()
    second = await children.with_url(first.odata_next_link).get()
    third = await children.with_url(second.odata_next_link).get()
    assert [item.name for page in (first, second, third) for item in page.value] == [
        f"{index}.txt" for index in range(5)
    ]
    assert third.odata_next_link is None


async def test_fail_next_raises_then_recovers(fake: FakeGraphClient) -> None:
    """Injected Graph errors are consumed and preserve Retry-After."""
    fake.fail_next(429, retry_after=1.5, op="get")
    builder = fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root")
    with pytest.raises(FakeAPIError) as error:
        await builder.get()
    assert error.value.response_headers["Retry-After"] == "1.5"
    assert (await builder.get()).id == "drive-1-root"


async def test_copy_returns_202_location_and_monitor_completes(fake: FakeGraphClient) -> None:
    """Native-handler copies return a monitor location and eventually complete."""
    source = fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root:/reports/2026/q3.xlsx:")
    response = await source.copy.post(
        SimpleNamespace(name="q3-copy.xlsx", parent_reference=SimpleNamespace(id="drive-1-root")),
        request_configuration=SimpleNamespace(options=[SimpleNamespace(response_handler=object())]),
    )
    session = FakeAiohttpSession(fake)
    assert response.status_code == 202
    first = session.get(response.headers["Location"])
    second = session.get(response.headers["Location"])
    assert (await first.json())["status"] == "inProgress"
    completed = await second.json()
    assert completed["status"] == "completed"
    assert fake.drives_by_id["drive-1"].by_id[completed["resourceId"]].data == b"x" * 10


async def test_upload_session_assembles_chunks(fake: FakeGraphClient) -> None:
    """Upload sessions append chunks and create their completed file."""
    parent = fake.drives.by_drive_id("drive-1").items.by_drive_item_id("root")
    session_info = await parent.create_upload_session.post(
        SimpleNamespace(
            item=SimpleNamespace(name="upload.bin", additional_data={"@microsoft.graph.conflictBehavior": "replace"})
        )
    )
    session = FakeAiohttpSession(fake)
    first = session.put(session_info.upload_url, data=b"abc", headers={"Content-Range": "bytes 0-2/6"})
    second = session.put(session_info.upload_url, data=b"def", headers={"Content-Range": "bytes 3-5/6"})
    assert first.status == 202
    assert second.status == 201
    assert fake.drives_by_id["drive-1"].lookup("upload.bin").data == b"abcdef"


async def test_download_url_streams_bytes(fake: FakeGraphClient) -> None:
    """Download URLs expose the original bytes through aiohttp chunk streaming."""
    item = fake.drives_by_id["drive-1"].lookup("reports/2026/q3.xlsx")
    response = FakeAiohttpSession(fake).get(FAKE_DOWNLOAD + item.id)
    assert response.status == 200
    assert b"".join([chunk async for chunk in response.content.iter_chunked(4)]) == b"x" * 10


def test_factories_return_real_client_classes_without_init(fake: FakeGraphClient) -> None:
    """Factories preserve real client identity without creating Redis resources."""
    sharepoint = make_sharepoint_client(fake, drive_id="drive-1")
    onedrive = make_onedrive_client(fake)
    assert isinstance(sharepoint, SharepointClient) and isinstance(onedrive, OneDriveClient)
    assert sharepoint.graph_client is fake and sharepoint._srcfiles == []
    assert not hasattr(sharepoint, "redis")
    assert sharepoint.is_app_only is True and make_onedrive_client(fake, app_only=False).is_app_only is False


def test_make_probe_stubs_remaining_abstract_methods() -> None:
    """Probe construction fills unrelated abstract methods with explicit test stubs."""

    class Example(ABC):
        @abstractmethod
        def _build_client(self) -> object:
            """Build a client."""

        @abstractmethod
        async def _resolve_drive_id(self) -> str:
            """Resolve a drive id."""

        @abstractmethod
        async def list_files(self) -> object:
            """List files."""

    probe = make_probe(Example)
    assert probe.__class__.__name__ == "Probe"
    with pytest.raises(AssertionError, match="unimplemented abstract method: list_files"):
        import asyncio

        asyncio.run(probe.list_files())
