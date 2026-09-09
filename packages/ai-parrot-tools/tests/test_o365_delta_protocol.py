"""Microsoft Graph drive-delta protocol tests (TASK-3041)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot_tools.o365.delta import (
    DEFAULT_GRAPH_ORIGINS,
    DEFAULT_MAX_RETRIES,
    DeltaError,
    DeltaItem,
    DeltaPage,
    DeltaTokenExpired,
    DriveDeltaReader,
    UntrustedContinuation,
    validate_continuation,
)

GRAPH = "https://graph.microsoft.com"


class GraphError(Exception):
    """Mimics an SDK API error carrying a status and headers."""

    def __init__(self, status: int, retry_after: Optional[str] = None) -> None:
        super().__init__(f"graph error {status}")
        self.response_status_code = status
        self.response_headers = {"Retry-After": retry_after} if retry_after else {}


class FakeResponse:
    """Mimics ``DeltaGetResponse`` (value / odata_next_link / odata_delta_link)."""

    def __init__(self, value, next_link=None, delta_link=None) -> None:
        self.value = value
        self.odata_next_link = next_link
        self.odata_delta_link = delta_link
        self.additional_data = {}


class FakeBuilder:
    """Mimics the SDK delta request builder chain."""

    def __init__(self, graph: "FakeGraph", url: Optional[str] = None) -> None:
        self.graph = graph
        self.url = url

    def with_url(self, raw_url: str) -> "FakeBuilder":
        return FakeBuilder(self.graph, raw_url)

    async def get(self):
        return self.graph.respond(self.url)


class FakeGraph:
    """A fake ``GraphServiceClient`` exposing drives/items/root/delta."""

    def __init__(self, pages: dict[Optional[str], Any]) -> None:
        self.pages = pages
        self.requested: list[Optional[str]] = []
        self.drive_ids: list[str] = []
        self.item_ids: list[str] = []

    # -- builder chain -----------------------------------------------------

    @property
    def drives(self):
        graph = self

        class Drives:
            def by_drive_id(self, drive_id):
                graph.drive_ids.append(drive_id)

                class Drive:
                    @property
                    def items(self):
                        class Items:
                            def by_drive_item_id(self, item_id):
                                graph.item_ids.append(item_id)

                                class Item:
                                    delta = FakeBuilder(graph)

                                return Item()

                        return Items()

                return Drive()

        return Drives()

    def respond(self, url: Optional[str]):
        self.requested.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        if callable(page):
            return page()
        return page


def item(item_id: str, *, path: str = "/drive/root:/legal", **overrides) -> dict[str, Any]:
    """A raw Graph drive item payload."""
    payload = {
        "id": item_id,
        "name": f"{item_id}.pdf",
        "parent_reference": {"path": path, "drive_id": "drive-1"},
        "web_url": f"{GRAPH}/{item_id}",
        "size": 1024,
        "e_tag": f"etag-{item_id}",
        "file": {"hashes": {"sha256_hash": f"sha-{item_id}"}},
    }
    payload.update(overrides)
    return payload


async def no_sleep(_seconds: float) -> None:
    return None


def reader(pages: dict[Optional[str], Any], **kwargs) -> DriveDeltaReader:
    return DriveDeltaReader(FakeGraph(pages), sleep=no_sleep, **kwargs)


# --------------------------------------------------------------------------
# Continuation validation (before any credential is forwarded)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link",
    [
        f"{GRAPH}/v1.0/drives/drive-1/root/delta?token=abc",
        "https://graph.microsoft.us/v1.0/drives/x/root/delta",
    ],
)
def test_graph_continuations_are_accepted(link):
    assert validate_continuation(link) == link


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example.com/v1.0/drives/drive-1/root/delta",
        "http://graph.microsoft.com/v1.0/delta",
        "https://graph.microsoft.com.evil.example/v1.0/delta",
        "ftp://graph.microsoft.com/delta",
        "",
        "not-a-url",
    ],
)
def test_foreign_or_insecure_continuations_are_rejected(link):
    with pytest.raises(UntrustedContinuation):
        validate_continuation(link)


@pytest.mark.asyncio
async def test_a_foreign_continuation_is_rejected_before_the_request():
    graph = FakeGraph({})
    delta = DriveDeltaReader(graph, sleep=no_sleep)
    with pytest.raises(UntrustedContinuation):
        await delta.fetch_page("drive-1", link="https://evil.example.com/delta")
    assert graph.requested == [], "no request was made, so no token was leaked"


def test_configured_origins_are_the_microsoft_clouds():
    assert GRAPH in DEFAULT_GRAPH_ORIGINS
    assert all(origin.startswith("https://") for origin in DEFAULT_GRAPH_ORIGINS)


# --------------------------------------------------------------------------
# 1. Paging semantics
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multipage_enumeration_follows_next_until_the_delta_link():
    delta = reader(
        {
            None: FakeResponse([item("a")], next_link=f"{GRAPH}/page2"),
            f"{GRAPH}/page2": FakeResponse([], next_link=f"{GRAPH}/page3"),
            f"{GRAPH}/page3": FakeResponse([item("b")], delta_link=f"{GRAPH}/final"),
        }
    )
    result = await delta.enumerate("drive-1")

    assert [entry.item_id for entry in result.items] == ["a", "b"]
    assert result.pages == 3, "an empty intermediate page is legal and still followed"
    assert result.delta_link == f"{GRAPH}/final"
    assert result.complete is True
    assert result.truncated is False


@pytest.mark.asyncio
async def test_the_drive_root_delta_endpoint_is_used():
    graph = FakeGraph({None: FakeResponse([], delta_link=f"{GRAPH}/final")})
    delta = DriveDeltaReader(graph, sleep=no_sleep)
    await delta.enumerate("drive-42")

    assert graph.drive_ids == ["drive-42"]
    assert graph.item_ids == ["root"], "drive-level delta is the root item's delta"


@pytest.mark.asyncio
async def test_duplicate_items_across_pages_keep_the_latest_report():
    delta = reader(
        {
            None: FakeResponse([item("a", name="old.pdf")], next_link=f"{GRAPH}/page2"),
            f"{GRAPH}/page2": FakeResponse(
                [item("a", name="new.pdf")], delta_link=f"{GRAPH}/final"
            ),
        }
    )
    result = await delta.enumerate("drive-1")

    assert len(result.items) == 1
    assert result.items[0].name == "new.pdf"


@pytest.mark.asyncio
async def test_tombstones_are_reported_and_never_filtered_away():
    delta = reader(
        {
            None: FakeResponse(
                [
                    item("a"),
                    {"id": "b", "deleted": {"state": "deleted"}},
                ],
                delta_link=f"{GRAPH}/final",
            )
        }
    )
    result = await delta.enumerate("drive-1", folder_prefix="legal")

    assert [entry.item_id for entry in result.items] == ["a", "b"]
    assert [entry.item_id for entry in result.tombstones] == ["b"]
    assert result.items[1].deleted is True


@pytest.mark.asyncio
async def test_folder_filtering_keeps_only_matching_paths():
    delta = reader(
        {
            None: FakeResponse(
                [
                    item("a", path="/drive/root:/legal/contracts"),
                    item("b", path="/drive/root:/marketing"),
                ],
                delta_link=f"{GRAPH}/final",
            )
        }
    )
    result = await delta.enumerate("drive-1", folder_prefix="legal")
    assert [entry.item_id for entry in result.items] == ["a"]


@pytest.mark.asyncio
async def test_an_empty_drive_yields_an_empty_but_complete_enumeration():
    delta = reader({None: FakeResponse([], delta_link=f"{GRAPH}/final")})
    result = await delta.enumerate("drive-1")
    assert result.items == []
    assert result.complete is True
    assert result.delta_link == f"{GRAPH}/final"


@pytest.mark.asyncio
async def test_a_truncated_walk_reports_no_cursor():
    delta = reader(
        {
            None: FakeResponse([item("a")], next_link=f"{GRAPH}/page2"),
            f"{GRAPH}/page2": FakeResponse([item("b")], next_link=f"{GRAPH}/page3"),
            f"{GRAPH}/page3": FakeResponse([item("c")], delta_link=f"{GRAPH}/final"),
        }
    )
    result = await delta.enumerate("drive-1", max_pages=2)

    assert result.truncated is True
    assert result.complete is False
    assert result.delta_link is None, "an unfinished walk must not commit a cursor"
    assert len(result.items) == 2


@pytest.mark.asyncio
async def test_a_committed_token_is_used_as_the_starting_link():
    graph = FakeGraph(
        {f"{GRAPH}/previous": FakeResponse([item("a")], delta_link=f"{GRAPH}/final")}
    )
    delta = DriveDeltaReader(graph, sleep=no_sleep)
    result = await delta.enumerate("drive-1", token=f"{GRAPH}/previous")

    assert graph.requested == [f"{GRAPH}/previous"]
    assert result.delta_link == f"{GRAPH}/final"


# --------------------------------------------------------------------------
# 2. 410 rescan, retries and throttling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_410_requests_a_rescan_instead_of_reporting_deletions():
    delta = reader({f"{GRAPH}/expired": GraphError(410)})
    result = await delta.enumerate("drive-1", token=f"{GRAPH}/expired")

    assert result.rescan_required is True
    assert result.items == [], "a 410 is never mass deletion"
    assert result.delta_link is None
    assert result.complete is False


@pytest.mark.asyncio
async def test_410_raises_from_fetch_page_so_callers_cannot_ignore_it():
    delta = reader({None: GraphError(410)})
    with pytest.raises(DeltaTokenExpired, match="full rescan"):
        await delta.fetch_page("drive-1")


@pytest.mark.asyncio
async def test_throttling_is_retried_within_a_bounded_budget():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise GraphError(429, retry_after="0")
        return FakeResponse([item("a")], delta_link=f"{GRAPH}/final")

    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    graph = FakeGraph({None: flaky})
    delta = DriveDeltaReader(graph, sleep=record_sleep)
    result = await delta.enumerate("drive-1")

    assert attempts["count"] == 3
    assert result.complete is True
    assert delays == [0.0, 0.0], "the Retry-After hint is honoured"


@pytest.mark.asyncio
async def test_transient_failures_use_exponential_backoff_then_give_up():
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    graph = FakeGraph({None: GraphError(503)})
    delta = DriveDeltaReader(graph, sleep=record_sleep, base_delay=2.0)

    with pytest.raises(DeltaError, match="after 3 attempts"):
        await delta.fetch_page("drive-1")
    assert delays == [2.0, 4.0]
    assert DEFAULT_MAX_RETRIES == 3


@pytest.mark.asyncio
async def test_client_errors_are_not_retried():
    attempts = {"count": 0}

    def failing():
        attempts["count"] += 1
        raise GraphError(403)

    delta = reader({None: failing})
    with pytest.raises(DeltaError, match="403"):
        await delta.fetch_page("drive-1")
    assert attempts["count"] == 1


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_items_carry_stable_identity_and_content_metadata():
    parsed = DriveDeltaReader.parse_item(item("a"), "drive-1")
    assert parsed.item_id == "a"
    assert parsed.drive_id == "drive-1"
    assert parsed.sha256 == "sha-a"
    assert parsed.etag == "etag-a"
    assert parsed.path == "/drive/root:/legal"
    assert parsed.full_path.endswith("/a.pdf")
    assert parsed.is_folder is False


def test_folders_are_recognised():
    parsed = DriveDeltaReader.parse_item(item("f", folder={"childCount": 2}), "drive-1")
    assert parsed.is_folder is True


def test_pages_expose_the_opaque_links_verbatim():
    page = DriveDeltaReader.parse_page(
        FakeResponse([item("a")], next_link=f"{GRAPH}/n", delta_link=None), "drive-1"
    )
    assert page.next_link == f"{GRAPH}/n"
    assert page.is_final is False
    assert DeltaPage(delta_link=f"{GRAPH}/final").is_final is True


def test_item_folder_matching():
    entry = DeltaItem(item_id="a", path="/drive/root:/Legal/Contracts")
    assert entry.in_folder(None) is True
    assert entry.in_folder("legal") is True
    assert entry.in_folder("/Legal/") is True
    assert entry.in_folder("marketing") is False


# --------------------------------------------------------------------------
# 3. Boundaries
# --------------------------------------------------------------------------


def test_the_helper_is_independent_of_the_contracts_package():
    source = Path(
        __file__
    ).resolve().parents[1] / "src" / "parrot_tools" / "o365" / "delta.py"
    tree = ast.parse(source.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any("contracts" in name for name in imported)
    assert not any(name.startswith("parrot.knowledge") for name in imported)


def test_the_helper_neither_commits_cursors_nor_ingests_documents():
    """The helper reads pages; persisting is the consumer's decision.

    Checked on executable code only — the module docstring says the word
    "catalog" precisely to state that it does not touch one.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "parrot_tools"
        / "o365"
        / "delta.py"
    ).read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("set_delta_token", "add_contract", "upsert", "record_answer"):
        assert forbidden not in called, forbidden

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "catalog" not in names | attributes
