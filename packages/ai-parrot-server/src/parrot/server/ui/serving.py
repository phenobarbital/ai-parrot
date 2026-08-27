"""Embedded Admin UI serving.

Mounts the compiled Admin UI single-page application (Svelte 5 + Vite)
under ``/admin`` when the ``dist/`` build output is present in the
installed package. Gracefully degrades (registers nothing, logs a single
warning) when the UI was not built — e.g. an install-from-git without
running the Node build pipeline.

Library-owned: :func:`setup_admin_ui` is called from
``BotManager.setup()`` (see ``parrot.manager.manager``), following the
same ``setup_*_routes(app)`` pattern as
``parrot.handlers.credentials.setup_credentials_routes``.
"""
from __future__ import annotations

from pathlib import Path

from aiohttp import web
from navconfig.logging import logging

from .status import AdminStatusHandler

try:
    from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY
except ImportError:  # pragma: no cover - navigator_auth is a core dependency
    AUTH_EXCLUDE_LIST_KEY = None

logger = logging.getLogger(__name__)

#: URL prefix the Admin UI is served under.
DEFAULT_PREFIX = "/admin"

# Only warn once per process, even if setup_admin_ui() is called more than
# once (e.g. tests instantiating multiple BotManagers).
_warned_missing_dist = False


def _dist_dir() -> Path:
    """Resolve the compiled Admin UI ``dist/`` directory.

    Package-relative resolution (mirrors the Telegram static-mount
    precedent in the repo-root ``app.py``): the built assets live next to
    this module inside the installed wheel. Kept as a standalone function
    (not inlined) so tests can monkeypatch it.

    Returns:
        Path to ``parrot/server/ui/dist`` (may not exist).
    """
    return Path(__file__).parent / "dist"


def _register_auth_exclusion(app: web.Application, pattern: str) -> None:
    """Best-effort registration of ``pattern`` in navigator-auth's exclude list.

    Safe when navigator-auth's ``AuthHandler`` was never installed on
    ``app`` (no ``AUTH_EXCLUDE_LIST_KEY`` entry) — degrades to a debug log
    instead of raising, matching the precedent in
    ``parrot.handlers.web_hitl``.

    Args:
        app: The aiohttp application.
        pattern: fnmatch-style URL pattern to exclude from auth enforcement.
    """
    if AUTH_EXCLUDE_LIST_KEY is None:
        logger.debug(
            "navigator_auth not available: skipping exclude-list "
            "registration for %s",
            pattern,
        )
        return
    exclude_list = app.get(AUTH_EXCLUDE_LIST_KEY)
    if exclude_list is None:
        logger.debug(
            "AuthHandler not installed on this app (no %s key): skipping "
            "exclude-list registration for %s",
            AUTH_EXCLUDE_LIST_KEY,
            pattern,
        )
        return
    if pattern not in exclude_list:
        exclude_list.append(pattern)


def _index_response(index_html: Path) -> web.FileResponse:
    """Build the SPA index response with no-cache headers.

    Args:
        index_html: Path to the built ``index.html``.

    Returns:
        A :class:`web.FileResponse` serving ``index_html`` with
        ``Cache-Control: no-cache`` so browsers always revalidate the
        SPA shell (the shell references hashed, long-cached assets).
    """
    response = web.FileResponse(index_html)
    response.headers["Cache-Control"] = "no-cache"
    return response


def setup_admin_ui(app: web.Application, *, prefix: str = DEFAULT_PREFIX) -> bool:
    """Mount the embedded Admin UI if the compiled ``dist/`` is present.

    Registers:
      - A static mount for hashed assets at ``{prefix}/assets/`` with
        long-cache/immutable headers (handled by the client via hashed
        filenames; aiohttp serves them as-is).
      - A catch-all ``GET {prefix}{{tail:.*}}`` route returning
        ``index.html`` (SPA history-mode router fallback) so deep links
        survive a hard refresh.
      - ``{prefix}*`` in navigator-auth's exclude list, so the HTML shell
        is reachable pre-login (auth enforcement lives entirely in the
        JSON API, not in the SPA shell route).

    Args:
        app: The aiohttp :class:`web.Application` to mount routes on.
        prefix: URL prefix the UI is served under. Defaults to ``/admin``.

    Returns:
        ``True`` when the SPA routes were registered, ``False`` when
        ``dist/`` is absent (a single WARNING is logged; the SPA mount is
        skipped but the JSON API below is registered either way — it is
        UI-agnostic).
    """
    global _warned_missing_dist

    # JSON API: registers unconditionally, independent of dist/ — the
    # status endpoint is UI-agnostic and useful even on an install-from-git
    # that never ran the Node build.
    app.router.add_view("/api/v1/admin/status", AdminStatusHandler)

    dist = _dist_dir()
    index_html = dist / "index.html"
    if not index_html.exists():
        if not _warned_missing_dist:
            logger.warning(
                "Admin UI dist/ not found at %s: the compiled UI was not "
                "built (install-from-git without the Node build step, or "
                "a UI-less wheel). Registering no %s routes; the JSON API "
                "is unaffected.",
                dist,
                prefix,
            )
            _warned_missing_dist = True
        return False

    router = app.router

    # Hashed static assets — long-cache/immutable is set by the browser
    # honoring the SPA build's content hashes; aiohttp's add_static serves
    # the files as-is (no per-request header injection needed here since
    # asset filenames already carry content hashes).
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        router.add_static(
            f"{prefix}/assets/",
            path=assets_dir,
            name="admin_ui_assets",
            show_index=False,
            follow_symlinks=False,
        )

    async def _spa_fallback(request: web.Request) -> web.Response:
        return _index_response(index_html)

    # Catch-all SPA fallback, anchored at the prefix so it never shadows
    # /api/* routes registered elsewhere on the app.
    router.add_get(f"{prefix}{{tail:.*}}", _spa_fallback, name="admin_ui_index")

    _register_auth_exclusion(app, f"{prefix}*")

    return True
