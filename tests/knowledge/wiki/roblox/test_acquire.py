"""Tests for explicit Roblox API acquisition (FEAT-532 TASK-2900).

Mocks every HTTP call — no real network access, matching the spec's
"Mock HTTP acquisition and assert network/LLM paths are unreachable in
build" test-fixture rule. Follows the existing hand-rolled aiohttp
async-context-manager double established in ``test_documents.py`` (no
``aioresponses``-style dependency is installed in this repo), extended
here to route by URL since one acquisition call hits four endpoints.
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
import yaml
from parrot.knowledge.wiki.roblox.acquire import (
    AcquiredApiPayloads,
    RobloxApiAcquisitionError,
    acquire_roblox_api_payloads,
    extract_class_docs,
)

# NOTE: `pytest.ini` sets `asyncio_mode = auto` — every `async def test_*`
# is collected as an asyncio test automatically; no `pytestmark`/per-test
# `@pytest.mark.asyncio` needed (and one would warn on the sync tests below).


# ---------------------------------------------------------------------------
# Fake aiohttp session — routes by URL (extends test_documents.py's pattern)
# ---------------------------------------------------------------------------


class _FakeContentStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, *, status, chunks):
        self.status = status
        self.content = _FakeContentStream(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeGetContextManager:
    def __init__(self, *, response=None, exc=None):
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class RoutedFakeSession:
    """A fake ``aiohttp.ClientSession`` that dispatches ``get()`` by exact
    URL, and records every URL requested (for request-count assertions)."""

    def __init__(self, routes: dict[str, tuple[int, bytes] | Exception]):
        self._routes = routes
        self.requested_urls: list[str] = []

    def get(self, url, **_kwargs):
        self.requested_urls.append(url)
        entry = self._routes.get(url)
        if entry is None:
            return _FakeGetContextManager(exc=AssertionError(f"unexpected request to {url}"))
        if isinstance(entry, Exception):
            return _FakeGetContextManager(exc=entry)
        status, body = entry
        return _FakeGetContextManager(response=_FakeResponse(status=status, chunks=[body]))

    async def close(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


# ---------------------------------------------------------------------------
# Fixtures: a tiny, valid API dump + a tiny, valid creator-docs tarball
# ---------------------------------------------------------------------------

STUDIO_VERSION = "0.123.0.456789"
COMMIT_SHA = "a" * 40

_DUMP = {
    "Classes": [
        {"Name": "Players", "Superclass": "Instance", "Members": []},
        {"Name": "Workspace", "Superclass": "Instance", "Members": []},
    ],
    "Enums": [{"Name": "Material", "Items": [{"Name": "Plastic", "Value": 256}]}],
}


def _make_tarball(members: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        if symlink is not None:
            link_info = tarfile.TarInfo(name=symlink)
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = "/etc/passwd"
            tar.addfile(link_info)
    return buf.getvalue()


def _players_yaml() -> bytes:
    return yaml.safe_dump({"name": "Players", "summary": "Manages players."}).encode("utf-8")


def _standard_routes(tarball: bytes) -> dict:
    return {
        "https://setup.rbxcdn.com/versionQTStudio": (200, STUDIO_VERSION.encode()),
        f"https://setup.rbxcdn.com/{STUDIO_VERSION}-API-Dump.json": (
            200,
            json.dumps(_DUMP).encode(),
        ),
        "https://api.github.com/repos/Roblox/creator-docs/commits/main": (
            200,
            json.dumps({"sha": COMMIT_SHA}).encode(),
        ),
        f"https://codeload.github.com/Roblox/creator-docs/tar.gz/{COMMIT_SHA}": (
            200,
            tarball,
        ),
    }


# ---------------------------------------------------------------------------
# test_sha_pinned_tarball_requests
# ---------------------------------------------------------------------------


async def test_sha_pinned_tarball_requests():
    """One commit-resolution and one tarball request for docs; no raw
    YAML requests — 4 total requests (version, dump, commit, tarball)."""
    tarball = _make_tarball({"creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml()})
    session = RoutedFakeSession(_standard_routes(tarball))

    payloads, reused = await acquire_roblox_api_payloads(session=session)

    assert reused is False
    assert payloads.studio_version == STUDIO_VERSION
    assert payloads.creator_docs_commit == COMMIT_SHA
    assert payloads.class_docs["Players"]["summary"] == "Manages players."
    # Exactly these four URLs, each requested exactly once — no raw
    # per-class YAML file request anywhere (that would be a fifth+ URL
    # under raw.githubusercontent.com, which is never in the route table).
    assert session.requested_urls.count("https://api.github.com/repos/Roblox/creator-docs/commits/main") == 1
    assert session.requested_urls.count(f"https://codeload.github.com/Roblox/creator-docs/tar.gz/{COMMIT_SHA}") == 1
    assert len(session.requested_urls) == 4


async def test_reuse_skips_dump_and_tarball_requests():
    """Unchanged identities: only the two cheap identity checks run."""
    tarball = _make_tarball({})
    session = RoutedFakeSession(_standard_routes(tarball))
    reuse = AcquiredApiPayloads(
        studio_version=STUDIO_VERSION,
        api_dump=_DUMP,
        creator_docs_commit=COMMIT_SHA,
        class_docs={"Players": {"summary": "cached"}},
        source_hashes={"api_dump": "x", "creator_docs_tarball": "y"},
    )

    payloads, reused = await acquire_roblox_api_payloads(session=session, reuse=reuse)

    assert reused is True
    assert payloads is reuse
    assert len(session.requested_urls) == 2  # only version + commit checks
    assert f"https://setup.rbxcdn.com/{STUDIO_VERSION}-API-Dump.json" not in session.requested_urls
    assert f"https://codeload.github.com/Roblox/creator-docs/tar.gz/{COMMIT_SHA}" not in session.requested_urls


# ---------------------------------------------------------------------------
# test_no_archive_extraction_to_disk
# ---------------------------------------------------------------------------


def test_no_archive_extraction_to_disk_symlink_rejected():
    tarball = _make_tarball(
        {"creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml()},
        symlink="creator-docs-aaa/content/en-us/reference/engine/classes/Evil.yaml",
    )
    docs, diagnostics = extract_class_docs(tarball, {"Players", "Evil"})
    assert "Players" in docs
    assert "Evil" not in docs  # symlink member never followed/read


def test_no_archive_extraction_to_disk_path_traversal_skipped():
    tarball = _make_tarball(
        {
            "../../../etc/content/en-us/reference/engine/classes/Evil.yaml": _players_yaml(),
        }
    )
    docs, diagnostics = extract_class_docs(tarball, {"Evil"})
    assert "Evil" not in docs
    assert any("traversal" in d for d in diagnostics)


def test_no_archive_extraction_to_disk_oversize_member_skipped(monkeypatch):
    from parrot.knowledge.wiki.roblox import acquire as acquire_module

    monkeypatch.setattr(acquire_module, "MAX_MEMBER_BYTES", 4)
    tarball = _make_tarball({"creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml()})
    docs, diagnostics = extract_class_docs(tarball, {"Players"})
    assert "Players" not in docs
    assert any("exceeds member limit" in d for d in diagnostics)


def test_no_archive_extraction_to_disk_too_many_members_raises(monkeypatch):
    from parrot.knowledge.wiki.roblox import acquire as acquire_module

    monkeypatch.setattr(acquire_module, "MAX_TARBALL_MEMBERS", 1)
    tarball = _make_tarball(
        {
            "creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml(),
            "creator-docs-aaa/content/en-us/reference/engine/classes/Workspace.yaml": _players_yaml(),
        }
    )
    with pytest.raises(RobloxApiAcquisitionError, match="exceeds"):
        extract_class_docs(tarball, {"Players", "Workspace"})


def test_extraction_ignores_non_class_and_unlisted_files():
    tarball = _make_tarball(
        {
            "creator-docs-aaa/README.md": b"# readme",
            "creator-docs-aaa/content/en-us/reference/engine/classes/Unknown.yaml": _players_yaml(),
        }
    )
    docs, _diag = extract_class_docs(tarball, {"Players"})  # "Unknown" not in dump
    assert docs == {}


# ---------------------------------------------------------------------------
# test_missing_vs_malformed_yaml
# ---------------------------------------------------------------------------


def test_missing_vs_malformed_yaml():
    """Absent class docs are structural-only; invalid present YAML fails
    (per-member, not the whole acquisition)."""
    tarball = _make_tarball(
        {
            "creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml(),
            "creator-docs-aaa/content/en-us/reference/engine/classes/Workspace.yaml": b"{ not: valid: yaml: [",
        }
    )
    docs, diagnostics = extract_class_docs(tarball, {"Players", "Workspace"})

    # Present + valid -> parsed.
    assert docs["Players"]["summary"] == "Manages players."
    # Present + malformed -> explicitly skipped with a diagnostic, not silently absent.
    assert "Workspace" not in docs
    assert any("Workspace" in d and "invalid" in d.lower() for d in diagnostics)


async def test_missing_class_yaml_is_structural_only_not_error():
    """A class the dump declares but the tarball has no YAML for at all
    acquires successfully — no docs key, no error."""
    tarball = _make_tarball({"creator-docs-aaa/content/en-us/reference/engine/classes/Players.yaml": _players_yaml()})
    session = RoutedFakeSession(_standard_routes(tarball))

    payloads, _reused = await acquire_roblox_api_payloads(session=session)

    assert "Players" in payloads.class_docs
    assert "Workspace" not in payloads.class_docs  # structural-only, not an error


# ---------------------------------------------------------------------------
# test_http_failure_no_retry
# ---------------------------------------------------------------------------


async def test_http_failure_no_retry_timeout():
    routes = _standard_routes(_make_tarball({}))
    routes["https://setup.rbxcdn.com/versionQTStudio"] = TimeoutError("simulated timeout")
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="request failed"):
        await acquire_roblox_api_payloads(session=session)

    # Fails once — no retry attempts against the same URL.
    assert session.requested_urls.count("https://setup.rbxcdn.com/versionQTStudio") == 1


async def test_http_failure_no_retry_rate_limited():
    routes = _standard_routes(_make_tarball({}))
    routes["https://api.github.com/repos/Roblox/creator-docs/commits/main"] = (429, b"")
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="429"):
        await acquire_roblox_api_payloads(session=session)
    assert session.requested_urls.count("https://api.github.com/repos/Roblox/creator-docs/commits/main") == 1


async def test_http_failure_invalid_studio_version_identity():
    routes = _standard_routes(_make_tarball({}))
    routes["https://setup.rbxcdn.com/versionQTStudio"] = (200, b"; rm -rf /")
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="invalid Studio version"):
        await acquire_roblox_api_payloads(session=session)


async def test_http_failure_invalid_commit_sha_identity():
    routes = _standard_routes(_make_tarball({}))
    routes["https://api.github.com/repos/Roblox/creator-docs/commits/main"] = (
        200,
        json.dumps({"sha": "not-a-sha"}).encode(),
    )
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="invalid creator-docs commit SHA"):
        await acquire_roblox_api_payloads(session=session)


async def test_http_failure_truncated_dump_data_does_not_publish():
    """A dump missing its 'Classes' list fails the whole acquisition (no
    partial AcquiredApiPayloads is ever returned)."""
    routes = _standard_routes(_make_tarball({}))
    routes[f"https://setup.rbxcdn.com/{STUDIO_VERSION}-API-Dump.json"] = (
        200,
        json.dumps({"nope": True}).encode(),
    )
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="Classes"):
        await acquire_roblox_api_payloads(session=session)


async def test_http_failure_size_cap_enforced(monkeypatch):
    from parrot.knowledge.wiki.roblox import acquire as acquire_module

    monkeypatch.setattr(acquire_module, "MAX_DUMP_BYTES", 4)
    routes = _standard_routes(_make_tarball({}))
    session = RoutedFakeSession(routes)

    with pytest.raises(RobloxApiAcquisitionError, match="exceeded"):
        await acquire_roblox_api_payloads(session=session)
