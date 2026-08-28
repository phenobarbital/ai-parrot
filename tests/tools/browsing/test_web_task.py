"""Tests for the structured WebTaskRequest contract and execute_web_task."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from parrot_tools.browsing.models import WebTaskRequest
from parrot_tools.browsing.toolkit import WebBrowsingToolkit
from parrot_tools.scraping.models import ScrapingResult

pytestmark = pytest.mark.asyncio


def make_result(extracted=None) -> ScrapingResult:
    return ScrapingResult(
        url="https://hooba.es/x",
        content="<html></html>",
        bs_soup=BeautifulSoup("<html></html>", "html.parser"),
        extracted_data=extracted or {},
        metadata={},
        success=True,
    )


@pytest.fixture
async def toolkit(tmp_path):
    tk = WebBrowsingToolkit(
        catalog_dir=tmp_path / "catalog", driver_type="selenium"
    )
    await tk.register_site(
        base_url="https://hooba.es", title="Hooba", aliases=["hooba"]
    )
    await tk.save_site_action(
        site="hooba",
        name="login",
        description="Iniciar sesión",
        steps=[{"action": "navigate", "url": "https://hooba.es/login"}],
    )
    await tk.save_site_action(
        site="hooba",
        name="register-customer",
        description="Dar de alta un cliente en el CRM",
        requires=["login"],
        params={
            "name": {"description": "Razón social"},
            "vat": {"description": "NIF/CIF"},
        },
        steps=[
            {"action": "fill", "selector": "#name", "value": "{{name}}"},
            {"action": "fill", "selector": "#vat", "value": "{{vat}}"},
            {"action": "click", "selector": "#save"},
        ],
    )
    tk._session_driver = MagicMock()
    return tk


class TestWebTaskRequestModel:
    def test_requires_action_or_plan(self):
        with pytest.raises(ValueError, match="exactly one"):
            WebTaskRequest(site="hooba")

    def test_rejects_both_action_and_plan(self):
        with pytest.raises(ValueError, match="exactly one"):
            WebTaskRequest(
                site="hooba",
                action="login",
                plan=[{"action": "login"}],
            )

    def test_single_action_shape(self):
        req = WebTaskRequest(
            site="hooba",
            action="register-customer",
            data={"name": "ACME", "vat": "B123"},
        )
        assert req.data["name"] == "ACME"
        assert req.include_requires is True


class TestExecuteWebTask:
    async def test_single_action_success(self, toolkit):
        executor = AsyncMock(return_value=make_result({"ok": True}))
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            out = await toolkit.execute_web_task(
                {
                    "site": "hooba",
                    "action": "register-customer",
                    "data": {"name": "ACME", "vat": "B123"},
                }
            )
        assert out["status"] == "ok"
        executed = [e["action"] for e in out["result"]["executed"]]
        assert executed == ["login", "register-customer"]
        # Data rendered into the steps
        steps = executor.call_args_list[1].kwargs["steps"]
        assert steps[0]["value"] == "ACME"
        assert steps[1]["value"] == "B123"

    async def test_plan_with_shared_data(self, toolkit):
        executor = AsyncMock(return_value=make_result())
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            out = await toolkit.execute_web_task(
                {
                    "site": "hooba",
                    "plan": [
                        {"action": "login"},
                        {
                            "action": "register-customer",
                            "data": {"vat": "B999"},
                        },
                    ],
                    "data": {"name": "Globex"},
                }
            )
        assert out["status"] == "ok"
        executed = [e["action"] for e in out["result"]["executed"]]
        assert executed == ["login", "register-customer"]

    async def test_invalid_request_shape(self, toolkit):
        out = await toolkit.execute_web_task({"site": "hooba"})
        assert out["status"] == "error"
        assert out["error"]["code"] == "invalid_request"

    async def test_unknown_site_lists_known(self, toolkit):
        out = await toolkit.execute_web_task(
            {"site": "acme-corp", "action": "login"}
        )
        assert out["status"] == "error"
        assert out["error"]["code"] == "unknown_site"
        assert out["error"]["known_sites"][0]["site"] == "hooba-es"

    async def test_unknown_action_lists_catalog(self, toolkit):
        out = await toolkit.execute_web_task(
            {"site": "hooba", "action": "make-coffee"}
        )
        assert out["status"] == "error"
        assert out["error"]["code"] == "unknown_action"
        names = {a["name"] for a in out["error"]["available_actions"]}
        assert names == {"login", "register-customer"}

    async def test_missing_params_returns_spec(self, toolkit):
        out = await toolkit.execute_web_task(
            {
                "site": "hooba",
                "action": "register-customer",
                "data": {"name": "ACME"},
            }
        )
        assert out["status"] == "error"
        assert out["error"]["code"] == "missing_params"
        assert "vat" in out["error"]["message"]
        spec = out["error"]["expected_params"]["register-customer"]
        assert set(spec) == {"name", "vat"}
        assert out["error"]["provided_data"] == ["name"]

    async def test_tool_is_confirmation_gated(self, tmp_path):
        tk = WebBrowsingToolkit(catalog_dir=tmp_path / "c")
        assert "execute_web_task" in tk.confirming_tools
        tk2 = WebBrowsingToolkit(catalog_dir=tmp_path / "c2", confirm_runs=False)
        assert "execute_web_task" not in tk2.confirming_tools
