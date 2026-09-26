"""FEAT-602 TASK-3732 — OpenAPIToolkit cookie-session mode."""

import asyncio
from types import SimpleNamespace

import pytest

from parrot.tools.openapitoolkit import OpenAPIToolkit


class FakeTransport:
    """Replace ``HTTPService`` request and response handling with scripted responses."""

    def __init__(self, statuses: list[int]) -> None:
        """Initialize a response script.

        Args:
            statuses: Status codes returned in request order.
        """
        self.statuses = list(statuses)
        self.calls: list[dict] = []
        self.headers: dict[str, str] = {}

    async def _request(self, **kwargs):
        """Record a request and return the next scripted response."""
        self.calls.append(kwargs)
        return SimpleNamespace(status_code=self.statuses.pop(0)), None

    async def process_response(self, response, url: str) -> tuple:
        """Mirror the shared transport's success/error result behavior."""
        if response.status_code >= 400:
            raise ConnectionError(f"HTTP Error {response.status_code}")
        return {"ok": True, "url": url}, None


def _spec() -> dict:
    """Return a minimal spec with GET and POST operations."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Cookie test", "version": "1.0"},
        "servers": [{"url": "https://api.test"}],
        "paths": {
            "/items": {
                "get": {"operationId": "list_items"},
                "post": {"operationId": "create_item"},
            }
        },
    }


def _toolkit(login_hook, **kwargs) -> OpenAPIToolkit:
    """Create a cookie-mode toolkit with the inline test spec."""
    return OpenAPIToolkit(
        spec=_spec(),
        service="cookie",
        auth_type="cookie",
        login_hook=login_hook,
        **kwargs,
    )


def test_cookie_mode_requires_login_hook():
    """Cookie mode rejects construction without a login hook."""
    with pytest.raises(ValueError, match="requires a login_hook"):
        OpenAPIToolkit(spec=_spec(), service="cookie", auth_type="cookie")


async def test_cookie_mode_logs_in_lazily_once():
    """The first requests share one lazy login."""
    login_calls = 0

    async def login_hook(_service) -> dict[str, str]:
        nonlocal login_calls
        login_calls += 1
        return {"sid": "first"}

    toolkit = _toolkit(login_hook)
    transport = FakeTransport([200, 200])
    toolkit.http_service = transport

    assert login_calls == 0
    await toolkit.cookie_get_items()
    await toolkit.cookie_get_items()

    assert login_calls == 1


async def test_cookie_mode_sends_jar_and_extra_headers():
    """Cookie requests include the session jar and configured static headers."""

    async def login_hook(_service) -> dict[str, str]:
        return {"sid": "session"}

    toolkit = _toolkit(login_hook, extra_headers={"X-Hooba-Language": "es"})
    transport = FakeTransport([200])
    transport.headers = dict(toolkit.http_service.headers)
    toolkit.http_service = transport

    await toolkit.cookie_get_items()

    assert transport.calls[0]["cookies"] == {"sid": "session"}
    assert transport.calls[0]["headers"]["X-Hooba-Language"] == "es"
    assert transport.calls[0]["full_response"] is True


async def test_cookie_mode_relogins_once_on_401():
    """A single 401 refreshes the jar once, while a second remains an error."""
    login_calls = 0

    async def login_hook(_service) -> dict[str, str]:
        nonlocal login_calls
        login_calls += 1
        return {"sid": str(login_calls)}

    toolkit = _toolkit(login_hook)
    transport = FakeTransport([401, 200])
    toolkit.http_service = transport

    success = await toolkit.cookie_get_items()

    assert success["status"] == "success"
    assert login_calls == 2
    assert [call["cookies"] for call in transport.calls] == [{"sid": "1"}, {"sid": "2"}]

    second_toolkit = _toolkit(login_hook)
    second_transport = FakeTransport([401, 401])
    second_toolkit.http_service = second_transport

    error = await second_toolkit.cookie_get_items()

    assert error["status"] == "error"
    assert login_calls == 4


async def test_cookie_mode_concurrent_first_use_logs_in_once():
    """Concurrent first callers wait on a single login hook invocation."""
    login_calls = 0

    async def login_hook(_service) -> dict[str, str]:
        nonlocal login_calls
        login_calls += 1
        await asyncio.sleep(0)
        return {"sid": "shared"}

    toolkit = _toolkit(login_hook)
    transport = FakeTransport([200] * 5)
    toolkit.http_service = transport

    await asyncio.gather(*(toolkit.cookie_get_items() for _ in range(5)))

    assert login_calls == 1


async def test_cookie_mode_no_transport_retries_on_writes():
    """Cookie writes disable transport retries, while reads retain the default."""

    async def login_hook(_service) -> dict[str, str]:
        return {"sid": "session"}

    toolkit = _toolkit(login_hook)
    transport = FakeTransport([200, 200])
    toolkit.http_service = transport

    await toolkit.cookie_post_items()
    await toolkit.cookie_get_items()

    assert transport.calls[0]["num_retries"] == 0
    assert "num_retries" not in transport.calls[1]


async def test_set_and_get_cookies_copy():
    """Cookie accessors replace and expose detached jar copies."""

    async def login_hook(_service) -> dict[str, str]:
        return {"sid": "unused"}

    toolkit = _toolkit(login_hook)
    supplied = {"sid": "external"}
    await toolkit.set_cookies(supplied)
    supplied["sid"] = "changed"
    returned = toolkit.get_cookies()
    returned["sid"] = "changed-again"

    assert toolkit.get_cookies() == {"sid": "external"}


async def test_non_cookie_modes_use_original_call():
    """Non-cookie generated methods retain the original request invocation shape."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="bearer", api_key="token")
    transport = FakeTransport([200])
    toolkit.http_service = transport

    await toolkit.bearer_get_items()

    assert transport.calls[0]["full_response"] is False
    assert "cookies" not in transport.calls[0]
