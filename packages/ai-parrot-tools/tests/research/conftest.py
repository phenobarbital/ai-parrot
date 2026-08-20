"""Shared fixtures for FEAT-426 research toolkit tests.

Provides recorded-response fixture loading and an aiohttp session stub so
`BaseResearchToolkit._make_api_request()` (and everything built on top of
it) can be exercised offline — no network access in CI (spec goal G6).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import pytest
from parrot_tools.research.base import BaseResearchToolkit

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Skip `live`-marked tests unless explicitly selected via `-m live`.

    Goal G6 requires fixtures-only runs by default: `pytest
    packages/ai-parrot-tools/tests/research/ -v` must pass without ever
    touching the network.
    """
    markexpr = config.getoption("-m", default="")
    if "live" in markexpr:
        return
    skip_live = pytest.mark.skip(reason="Live test — opt-in only, run with `-m live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    """Load a recorded API response from `tests/research/fixtures/`.

    Returns:
        A callable ``(filename) -> str | Any`` — ``.json`` files are
        parsed into Python objects, everything else (``.xml``, ...) is
        returned as raw text.
    """

    def _load(name: str) -> Any:
        path = FIXTURES_DIR / name
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        return text

    return _load


class _FakeResponse:
    """Minimal async-context-manager stand-in for `aiohttp.ClientResponse`."""

    def __init__(
        self,
        status: int,
        json_body: Any | None = None,
        text_body: str = "",
    ):
        self.status = status
        self.request_info = None
        self.history = ()
        self._json_body = json_body
        self._text_body = text_body

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self, content_type: str | None = None) -> Any:
        return self._json_body

    async def text(self) -> str:
        return self._text_body


class _FakeClientSession:
    """Stub `aiohttp.ClientSession` keyed off the request URL.

    `.get(url)` looks up ``url`` in an explicit ``responses`` mapping
    first; failing that, it infers the HTTP status from a trailing
    numeric path segment (e.g. ``http://x/500`` -> 500), defaulting to
    200 with an empty JSON body otherwise.
    """

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}

    def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        if url in self.responses:
            status, json_body = self.responses[url]
            return _FakeResponse(status, json_body=json_body)
        tail = url.rsplit("/", 1)[-1]
        if tail.isdigit():
            status = int(tail)
            return _FakeResponse(status, json_body=None, text_body=f"status {status}")
        return _FakeResponse(200, json_body={})

    async def close(self) -> None:
        return None


@pytest.fixture
def mock_aiohttp_session(monkeypatch) -> Callable[..., None]:
    """Patch `BaseResearchToolkit._open()` to install a stub aiohttp session.

    Usage::

        async def test_x(mock_aiohttp_session):
            payload, err = await toolkit._make_api_request("http://x/500")
            assert payload is None and err

        async def test_y(mock_aiohttp_session):
            mock_aiohttp_session(responses={"http://x/ok": (200, {"a": 1})})
            payload, err = await toolkit._make_api_request("http://x/ok")

    Returns:
        A configuration callable ``(responses: dict | None) -> None``.
        Any toolkit whose `_open()` runs after this fixture is applied
        (including the automatic call inside `_make_api_request()` via
        `_ensure_open()`) receives the stub session.
    """
    state: dict = {"responses": {}}

    async def _fake_open(self) -> None:
        self._session = _FakeClientSession(responses=state["responses"])

    monkeypatch.setattr(BaseResearchToolkit, "_open", _fake_open)

    def _configure(responses: dict | None = None) -> None:
        state["responses"] = responses or {}

    return _configure
