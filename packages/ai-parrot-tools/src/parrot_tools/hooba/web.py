"""Playwright fallback for Hooba over a PRIVATE action catalog (FEAT-602 M7, U1)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from parrot_tools.browsing import WebBrowsingToolkit
from parrot_tools.scraping.session_actions import CredentialResolverFn

logger = logging.getLogger(__name__)

DEFAULT_SECTIONS: Dict[str, Tuple[str, str, str]] = {
    "hooba-invoices": ("Ir a facturas", "Abrir el listado de facturas.", "/es/sales/invoices"),
    "hooba-purchases": ("Ir a gastos", "Abrir el listado de facturas de compra.", "/es/purchases/purchase-invoices"),
}


class HoobaWebAdapter:
    """Thin wrapper over :class:`WebBrowsingToolkit` for the private Hooba catalog."""

    def __init__(
        self,
        catalog_dir: Union[str, Path],
        credential_resolver: CredentialResolverFn,
        *,
        site: str = "hooba",
        login_action: str = "hooba-login",
        headless: bool = True,
        driver_type: str = "playwright",
        browser: str = "chrome",
        base_url: str = "https://app.hooba.com",
        **kwargs: Any,
    ) -> None:
        self._catalog_dir = Path(catalog_dir)
        self._resolver = credential_resolver
        self.site, self.login_action, self.base_url = site, login_action, base_url
        self._tk_kwargs = dict(headless=headless, driver_type=driver_type, browser=browser, **kwargs)
        self._toolkit: Optional[WebBrowsingToolkit] = None

    @property
    def started(self) -> bool:
        """True once the underlying toolkit exists (the browser may still be lazy)."""
        return self._toolkit is not None

    def _tk(self) -> WebBrowsingToolkit:
        """Return the lazily-created browsing toolkit."""
        if self._toolkit is None:
            self._toolkit = WebBrowsingToolkit(
                catalog_dir=self._catalog_dir,
                credential_resolver=self._resolver,
                confirm_runs=False,
                **self._tk_kwargs,
            )
        return self._toolkit

    async def recover_session(
        self,
        cookie_names: Sequence[str] = ("sid",),
        *,
        api_url: str = "https://api.hooba.com",
    ) -> Dict[str, str]:
        """Log in through the catalog and return requested context cookies.

        Any login, driver, cookie capability, or cookie-shape failure is
        fail-closed and returns an empty mapping.
        """
        try:
            result = await self._tk().run_site_action(self.site, self.login_action)
            if not result.get("success", False):
                logger.warning("Hooba web session recovery login failed")
                return {}
            driver = await self._tk()._ensure_session_driver()
            cookies = await driver.get_cookies([api_url, self.base_url])
            selected = {
                cookie["name"]: cookie["value"]
                for cookie in cookies
                if cookie.get("name") in cookie_names and "value" in cookie
            }
            if "sid" not in selected:
                logger.warning("Hooba web session recovery did not return a sid cookie")
                return {}
            return selected
        except Exception:  # noqa: BLE001
            logger.warning("Hooba web session recovery failed")
            return {}

    async def run_navigation(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a catalog action only when its kind is ``navigation``."""
        toolkit = self._tk()
        meta = await toolkit.get_site_action(self.site, action)
        if meta["kind"] != "navigation":
            return {"status": "error", "error": "only navigation actions are allowed"}
        return await toolkit.run_site_action(self.site, action, params=params)

    async def close(self) -> None:
        """Close the browser if it was started."""
        if self._toolkit is not None:
            await self._toolkit.close_browser()


async def seed_catalog(
    catalog_dir: Union[str, Path],
    *,
    base_url: str = "https://app.hooba.com",
    sections: Optional[Dict[str, Tuple[str, str, str]]] = None,
    username_selector: str = 'input[type="email"]',
    password_selector: str = 'input[type="password"]',
    submit_selector: str = 'button[type="submit"]',
) -> str:
    """Write the private Hooba login and navigation actions to a catalog.

    Returns:
        The registered site slug.
    """
    toolkit = WebBrowsingToolkit(catalog_dir=catalog_dir)
    await toolkit.register_site(
        base_url,
        name="hooba",
        title="Hooba",
        aliases=["hooba", "app.hooba.com"],
    )
    await toolkit.save_site_action(
        "hooba",
        "hooba-login",
        "Iniciar sesión en Hooba.",
        steps=[
            {"action": "navigate", "url": f"{base_url}/es/login?returnUrl=%2Fdashboard"},
            {
                "action": "authenticate",
                "method": "form",
                "credential_provider": "hooba",
                "username_selector": username_selector,
                "password_selector": password_selector,
                "submit_selector": submit_selector,
            },
            {"action": "wait", "condition": "/dashboard", "condition_type": "url_contains"},
        ],
        kind="operation",
        overwrite=True,
    )
    for name, (title, description, path) in (sections or DEFAULT_SECTIONS).items():
        await toolkit.save_site_action(
            "hooba",
            name,
            description,
            steps=[
                {"action": "navigate", "url": f"{base_url}{path}"},
                {"action": "wait", "condition": path, "condition_type": "url_contains"},
            ],
            kind="navigation",
            requires=["hooba-login"],
            title=title,
            overwrite=True,
        )
    return "hooba"
