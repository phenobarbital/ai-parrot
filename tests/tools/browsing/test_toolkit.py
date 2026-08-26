"""Tests for WebBrowsingToolkit — catalog tools + deterministic runs."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from parrot_tools.browsing.toolkit import WebBrowsingToolkit
from parrot_tools.scraping.models import ScrapingResult

pytestmark = pytest.mark.asyncio

NAV = [{"action": "navigate", "url": "https://hooba.es/x"}]


def make_result(extracted=None, success=True, step_errors=None) -> ScrapingResult:
    return ScrapingResult(
        url="https://hooba.es/x",
        content="<html></html>",
        bs_soup=BeautifulSoup("<html></html>", "html.parser"),
        extracted_data=extracted or {},
        metadata={"step_errors": step_errors or []},
        success=success,
    )


@pytest.fixture
async def toolkit(tmp_path):
    tk = WebBrowsingToolkit(
        catalog_dir=tmp_path / "catalog",
        plans_dir=tmp_path / "plans",
        driver_type="selenium",
    )
    await tk.register_site(
        base_url="https://hooba.es", title="Hooba", aliases=["hooba"]
    )
    await tk.save_site_action(
        site="hooba",
        name="login",
        description="Iniciar sesión en Hooba",
        steps=[
            {"action": "navigate", "url": "https://hooba.es/login"},
            {"action": "fill", "selector": "#user", "value": "{{username}}"},
        ],
        params={"username": {"description": "Usuario", "default": "bot"}},
    )
    await tk.save_site_action(
        site="hooba",
        name="search-customer",
        description="Buscar un cliente en el CRM",
        steps=[{"action": "fill", "selector": "#q", "value": "{{customer}}"}],
        params={"customer": {"description": "Cliente"}},
        requires=["login"],
    )
    # Never start a real browser in tests.
    tk._session_driver = MagicMock()
    return tk


class TestCatalogTools:
    async def test_list_sites_and_actions(self, toolkit):
        sites = await toolkit.list_sites()
        assert [s["site"] for s in sites] == ["hooba-es"]
        actions = await toolkit.list_site_actions("hooba")
        assert {a["name"] for a in actions} == {"login", "search-customer"}

    async def test_get_site_action_returns_script(self, toolkit):
        action = await toolkit.get_site_action("hooba", "login")
        assert action["steps"][0]["action"] == "navigate"
        assert action["site"] == "hooba-es"

    async def test_save_rejects_undeclared_placeholder(self, toolkit):
        with pytest.raises(ValueError, match="undeclared placeholder"):
            await toolkit.save_site_action(
                site="hooba",
                name="bad",
                description="x",
                steps=[{"action": "fill", "selector": "#a", "value": "{{oops}}"}],
            )

    async def test_save_rejects_unbounded_loop(self, toolkit):
        with pytest.raises(ValueError, match="exceeds"):
            await toolkit.save_site_action(
                site="hooba",
                name="looping",
                description="x",
                steps=[{"action": "loop", "iterations": 10_000, "actions": NAV}],
            )

    async def test_delete_site_action(self, toolkit):
        out = await toolkit.delete_site_action("hooba", "search-customer")
        assert out["deleted"] is True
        actions = await toolkit.list_site_actions("hooba")
        assert {a["name"] for a in actions} == {"login"}

    async def test_save_rejects_literal_password(self, toolkit):
        with pytest.raises(ValueError, match="literal credentials"):
            await toolkit.save_site_action(
                site="hooba",
                name="bad-auth",
                description="x",
                steps=[{"action": "authenticate", "password": "hunter2"}],
            )

    async def test_composite_rejects_undeclared_binding_placeholder(
        self, toolkit
    ):
        with pytest.raises(ValueError, match="undeclared placeholder"):
            await toolkit.save_site_action(
                site="hooba",
                name="bad-flow",
                description="x",
                kind="composite",
                compose=[
                    {
                        "action": "search-customer",
                        "params": {"customer": "{{typo}}"},
                    }
                ],
            )

    async def test_composite_save_and_listing(self, toolkit):
        out = await toolkit.save_site_action(
            site="hooba",
            name="find-acme",
            description="Login y buscar a ACME",
            kind="composite",
            compose=[
                {"action": "search-customer", "params": {"customer": "ACME"}}
            ],
        )
        assert out["saved"] is True
        assert out["action"]["compose"] == ["search-customer"]


class TestRunTools:
    async def test_run_action_injects_requires_and_renders(self, toolkit):
        executor = AsyncMock(return_value=make_result({"rows": [1]}))
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            result = await toolkit.run_site_action(
                "hooba", "search-customer", params={"customer": "ACME"}
            )
        assert result["success"] is True
        assert [e["action"] for e in result["executed"]] == [
            "login",
            "search-customer",
        ]
        assert result["executed"][0]["injected"] is True
        # Placeholders rendered before execution
        login_steps = executor.call_args_list[0].kwargs["steps"]
        assert login_steps[1]["value"] == "bot"  # default applied
        search_steps = executor.call_args_list[1].kwargs["steps"]
        assert search_steps[0]["value"] == "ACME"
        assert result["extracted_data"] == {"rows": [1]}

    async def test_run_action_stops_on_error(self, toolkit):
        executor = AsyncMock(
            return_value=make_result(
                success=False,
                step_errors=[
                    {"step_index": 0, "action": "navigate", "error": "boom"}
                ],
            )
        )
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            result = await toolkit.run_site_action(
                "hooba", "search-customer", params={"customer": "ACME"}
            )
        assert result["success"] is False
        assert result["stopped_early"] is True
        assert len(result["executed"]) == 1
        assert "boom" in result["executed"][0]["error"]

    async def test_run_sequence_dedupes_prerequisites(self, toolkit):
        executor = AsyncMock(return_value=make_result())
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            result = await toolkit.run_site_sequence(
                "hooba",
                plan=[
                    "login",
                    {
                        "action": "search-customer",
                        "params": {"customer": "ACME"},
                    },
                ],
            )
        assert [e["action"] for e in result["executed"]] == [
            "login",
            "search-customer",
        ]

    async def test_run_unknown_site_raises(self, toolkit):
        with pytest.raises(KeyError, match="No catalogued site"):
            await toolkit.run_site_action("desconocido", "login")

    async def test_merge_later_action_wins_and_preserves_earlier(
        self, toolkit
    ):
        results = iter(
            [
                make_result({"rows": ["from-login"]}),
                make_result({"rows": ["from-search"]}),
            ]
        )
        executor = AsyncMock(side_effect=lambda *a, **k: next(results))
        with patch(
            "parrot_tools.browsing.toolkit.execute_plan_steps", executor
        ):
            result = await toolkit.run_site_action(
                "hooba", "search-customer", params={"customer": "ACME"}
            )
        assert result["extracted_data"]["rows"] == ["from-search"]
        assert result["extracted_data"]["login.rows"] == ["from-login"]


class TestConfiguration:
    async def test_user_data_dir_reaches_driver_config(self, tmp_path):
        tk = WebBrowsingToolkit(
            catalog_dir=tmp_path / "c",
            user_data_dir="/home/user/.config/google-chrome",
            profile_directory="Profile 1",
            browser_channel="chrome",
            driver_type="playwright",
        )
        assert tk._config.user_data_dir == "/home/user/.config/google-chrome"
        assert tk._config.profile_directory == "Profile 1"
        assert tk._config.browser_channel == "chrome"
        assert tk._session_based is True

    async def test_tools_exposed(self, tmp_path):
        tk = WebBrowsingToolkit(catalog_dir=tmp_path / "c")
        names = {t.name for t in tk.get_tools()}
        assert {
            "register_site",
            "list_sites",
            "list_site_actions",
            "get_site_action",
            "save_site_action",
            "delete_site_action",
            "run_site_action",
            "run_site_sequence",
            "close_browser",
        } <= names
        # Inherited scraping tools remain available
        assert {"scrape", "crawl"} <= names

    async def test_run_tools_require_confirmation_by_default(self, tmp_path):
        tk = WebBrowsingToolkit(catalog_dir=tmp_path / "c")
        assert {
            "run_site_action",
            "run_site_sequence",
            "delete_site_action",
        } <= tk.confirming_tools

    async def test_confirm_runs_false_keeps_delete_gated(self, tmp_path):
        tk = WebBrowsingToolkit(catalog_dir=tmp_path / "c", confirm_runs=False)
        assert tk.confirming_tools == frozenset({"delete_site_action"})
        # Class-level default untouched for other instances
        assert "run_site_action" in WebBrowsingToolkit.confirming_tools

    async def test_close_browser(self, tmp_path):
        tk = WebBrowsingToolkit(catalog_dir=tmp_path / "c")
        assert (await tk.close_browser())["closed"] is False
        driver = MagicMock()
        driver.quit = AsyncMock()
        tk._session_driver = driver
        assert (await tk.close_browser())["closed"] is True
        driver.quit.assert_awaited_once()
