"""FEAT-602 TASK-3742 — HoobaToolkit composition and READ tools (no HTTP)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.business_automation.models import OperationKind
from parrot_tools.hooba import HoobaSettings, HoobaToolkit


class FakeApi:
    """Small fake for HoobaOpenAPIToolkit used without network access."""

    def __init__(self, generated=None, responses=None):
        self.generated = generated or []
        self.responses = responses or {}
        self._ensure_session = AsyncMock()
        self.set_cookies = AsyncMock()
        self._cookie_request = AsyncMock(side_effect=self._request)
        self.http_service = MagicMock()
        self.http_service.headers = {}
        self._cookies = {"sid": "fake"}

    async def _request(self, method, url, request_kwargs):
        path = url.split(".com", 1)[-1]
        return self.responses.get(path, ([], None))

    def get_tools(self):
        return self.generated

    def operation_kinds(self):
        return {tool.name: OperationKind.READ for tool in self.generated}

    def get_cookies(self):
        return dict(self._cookies)


def make_toolkit(api=None, settings=None, web=None):
    settings = settings or HoobaSettings(account_id=123, catalog_dir=None)
    return HoobaToolkit(settings=settings, api=api or FakeApi(), web=web)


def test_get_tools_merges_without_collision():
    generated = [MagicMock()]
    generated[0].name = "hooba_generated"
    toolkit = make_toolkit(FakeApi(generated=generated))
    names = {tool.name for tool in toolkit.get_tools()}
    assert {"hooba_whoami", "hooba_generated"} <= names

    duplicate = MagicMock()
    duplicate.name = "hooba_whoami"
    with pytest.raises(ValueError, match="collision"):
        make_toolkit(FakeApi(generated=[duplicate])).get_tools()


def test_operation_kinds_covers_every_tool():
    generated = MagicMock()
    generated.name = "hooba_generated"
    toolkit = make_toolkit(FakeApi(generated=[generated]))
    tools = toolkit.get_tools()
    kinds = toolkit.operation_kinds()
    assert {tool.name for tool in tools} == set(kinds)
    assert all(kind in set(OperationKind) for kind in kinds.values())


async def test_open_does_not_start_browser():
    web = MagicMock()
    toolkit = make_toolkit(web=web)
    await toolkit._ensure_open()
    toolkit._api._ensure_session.assert_awaited_once_with()
    assert toolkit._web is web
    assert not web.started


async def test_find_contact_threshold():
    api = FakeApi(
        responses={
            "/accounts/123/contacts": (
                [
                    {"id": 1, "legalName": "Cafe Azul"},
                    {"id": 2, "legalName": "Café Azul y Asociados"},
                ],
                None,
            )
        }
    )
    result = await make_toolkit(api).hooba_find_contact("CAFÉ AZUL", limit=5)
    assert result["status"] == "success"
    assert [match["contact_id"] for match in result["result"]] == [1]


async def test_web_tools_error_without_catalog_dir():
    toolkit = make_toolkit()
    assert (await toolkit.hooba_recover_web_session())["error"] == "HOOBA_CATALOG_DIR not set"
    assert (await toolkit.hooba_run_web_action("navigate"))["error"] == "HOOBA_CATALOG_DIR not set"
    assert toolkit._web is None


async def test_recover_session_injects_sid_or_fails_closed():
    adapter = MagicMock()
    adapter.recover_session = AsyncMock(return_value={})
    api = FakeApi()
    toolkit = make_toolkit(api, HoobaSettings(account_id=123, catalog_dir="/private"), adapter)
    result = await toolkit.hooba_recover_web_session()
    assert result["status"] == "error"
    api.set_cookies.assert_not_awaited()

    adapter.recover_session.return_value = {"sid": "secret"}
    result = await toolkit.hooba_recover_web_session()
    assert result["result"] == {"recovered": True, "cookie_names": ["sid"]}
    api.set_cookies.assert_awaited_once_with({"sid": "secret"})


async def test_download_invoice_pdf_writes_0600(tmp_path):
    toolkit = make_toolkit()
    toolkit._call_raw = AsyncMock(return_value=b"%PDF-fake")
    result = await toolkit.hooba_download_invoice_pdf(42, str(tmp_path))
    path = tmp_path / "invoice-42.pdf"
    assert result["status"] == "success"
    assert path.read_bytes() == b"%PDF-fake"
    assert path.stat().st_mode & 0o777 == 0o600
