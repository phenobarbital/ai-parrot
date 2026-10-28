"""Human-facing Jira site URL resolution.

API calls may go through the Atlassian gateway
(``https://api.atlassian.com/ex/jira/<cloud_id>``): service-account scoped
tokens and OAuth 2.0 (3LO) only authenticate there. Browser links must
still point at the site (``https://<tenant>.atlassian.net/browse/KEY``),
because ``/browse/`` on the gateway does not open in a browser.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_GATEWAY_RE = re.compile(r"^https?://api\.atlassian\.com/ex/jira/[^/]+/?$", re.IGNORECASE)

logger = logging.getLogger(__name__)


def is_gateway_url(url: str | None) -> bool:
    """Return True when ``url`` is an Atlassian API gateway base URL."""
    return bool(url) and bool(_GATEWAY_RE.match(url.strip()))


def fetch_site_url(client: Any) -> str | None:
    """Read the site base URL from Jira's ``serverInfo`` (blocking call).

    Args:
        client: A ``jira.JIRA`` client, typically pointed at the gateway.

    Returns:
        The site URL without a trailing slash (e.g.
        ``https://acme.atlassian.net``), or ``None`` when it cannot be read.
    """
    if client is None:
        return None
    try:
        info = client.server_info()
    except Exception as exc:  # noqa: BLE001 -- link resolution is best-effort
        logger.warning("Could not read Jira serverInfo to resolve the site URL: %s", exc)
        return None
    base = info.get("baseUrl") if isinstance(info, dict) else None
    if not isinstance(base, str) or not base.strip() or is_gateway_url(base):
        return None
    return base.strip().rstrip("/")


class SiteUrlResolver:
    """Resolve and cache the browser-facing site URL for a Jira client.

    Resolution order:

    1. an explicit site URL (constructor argument / ``JIRA_SITE_URL``);
    2. the API base itself when it is not a gateway URL;
    3. ``serverInfo.baseUrl`` read through the client, cached per API base;
    4. the API base as a last resort (a gateway link beats no link).
    """

    def __init__(self, explicit: str | None = None) -> None:
        self.explicit = (explicit or "").strip().rstrip("/")
        self._cache: dict[str, str] = {}

    def resolve(self, client: Any, api_base: str | None) -> str:
        """Return the site URL for ``api_base`` (``""`` when unknown)."""
        if self.explicit:
            return self.explicit
        base = (api_base or "").strip().rstrip("/")
        if not base or not is_gateway_url(base):
            return base
        cached = self._cache.get(base)
        if cached:
            return cached
        site = fetch_site_url(client)
        if site:
            self._cache[base] = site
            return site
        return base

    @staticmethod
    def browse_url(site_url: str, key: str | None) -> str:
        """``<site>/browse/<key>``, or ``""`` when either part is missing."""
        if not site_url or not key:
            return ""
        return f"{site_url.rstrip('/')}/browse/{key}"
