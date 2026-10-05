"""FEAT-608 TASK-3806 — Google Drive fake-harness self-tests."""

import datetime as dt

import pytest

from ._gdrive_fakes import FakeDrive, FakeDriveClient, FakeHTTPError, UPLOAD_URL, make_google_client


async def test_fake_drive_paths_and_duplicates() -> None:
    """Files create parents and duplicate names sort by newest modification time."""
    drive = FakeDrive()
    client = FakeDriveClient(drive)
    older = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    newer = dt.datetime(2025, 1, 2, tzinfo=dt.timezone.utc)
    first = drive.put_file("reports/daily.txt", b"old", modified=older)
    second = drive.duplicate("reports/daily.txt", b"new", modified=newer)

    parent_id = first.parents[0]
    page = await client.files_list(
        q=f"'{parent_id}' in parents and name = 'daily.txt' and trashed = false",
        fields="files(id)",
        order_by="modifiedTime desc",
    )

    assert [item["id"] for item in page["files"]] == [second.id, first.id]
    assert drive.by_id[parent_id].name == "reports"
    assert page["files"][0]["size"] == "3"


async def test_fake_client_pagination_and_fail_next() -> None:
    """Listings page at the fake cap and scripted failures are consumed once."""
    drive = FakeDrive()
    client = FakeDriveClient(drive, page_size=2)
    for number in range(5):
        drive.put_file(f"files/{number}.txt", str(number).encode())
    parent_id = drive.put_folder("files").id
    query = f"'{parent_id}' in parents and trashed = false"

    client.fail_next(503, method="files.list")
    with pytest.raises(FakeHTTPError) as error:
        await client.files_list(q=query, fields="files(id)")
    assert error.value.res.status_code == 503

    first = await client.files_list(q=query, fields="files(id)", page_size=10)
    second = await client.files_list(q=query, fields="files(id)", page_size=10, page_token=first["nextPageToken"])
    third = await client.files_list(q=query, fields="files(id)", page_size=10, page_token=second["nextPageToken"])

    assert [len(page["files"]) for page in (first, second, third)] == [2, 2, 1]
    assert "nextPageToken" not in third


async def test_fake_resumable_session_308_then_200() -> None:
    """Resumable uploads acknowledge intermediate chunks then create an item."""
    drive = FakeDrive()
    client = FakeDriveClient(drive)
    start = SimpleRequest("POST", UPLOAD_URL, json={"name": "resumable.bin"})

    session = await client.send_raw(start)
    location = session.headers["Location"]
    partial = await client.send_raw(
        SimpleRequest("PUT", location, headers={"Content-Range": "bytes 0-2/6"}, data=b"abc"),
        raise_for_status=False,
    )
    complete = await client.send_raw(
        SimpleRequest("PUT", location, headers={"Content-Range": "bytes 3-5/6"}, data=b"def"),
        raise_for_status=False,
    )

    assert partial.status_code == 308
    assert partial.headers["Range"] == "bytes=0-2"
    assert complete.status_code == 200
    assert complete.json["name"] == "resumable.bin"
    assert complete.json["size"] == "6"


def test_make_google_client_is_authenticated_without_init() -> None:
    """The bare Google client reports service-account authentication."""
    client = make_google_client(FakeDriveClient(FakeDrive()))

    assert client.is_authenticated is True
    assert client.using_service_account() is True


class SimpleRequest:
    """Small Request-shaped object for fake raw-upload tests."""

    def __init__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes = b"",
        json: dict[str, str] | None = None,
    ) -> None:
        self.method = method
        self.url = url
        self.headers = headers or {}
        self.data = data
        self.json = json
